"""apps/aisearch 오케스트레이터 — 8개 모듈(AC1~AC9)을 하나의 실행 경로로 배선.

V1 적대검증 BLOCKER("고아 모듈/배선 부재") + V1 2차 적대검증 결함 10건 해소.
진입점은 ``run_search_pipeline(jd, deps, previous=...)`` 하나이며, 실행 흐름은
goal 문서(docs/engineering/aisearch-fleet-goal-2026-07-28.md) 파이프라인 그대로다:

1. AC1 ``boolean_builder.build_search_plan`` — RPS 검색 플랜(서울 소재 대학 우선
   → 소진/cap 시 다음 변형) + AC2 ``portal_search.build_portal_search_descriptors``
   — 사람인/잡코리아 디스크립터. JD 제외어(not_keywords)는 RPS Boolean NOT 절과
   포털 post_filter_exclude 로 전달·반영된다(2차 결함 2).
2. D6 "3사 동시 착수": 채널별 파이프라인(LinkedIn 플랜 / 사람인 / 잡코리아)을
   라운드로빈으로 인터리브 실행한다 — 한 채널의 종료가 다른 채널의 시작
   조건이 아니다(2차 결함 5).
3. 각 변형마다 AC8 ``banner.build_dispatch_snippet`` 표시 → AC3
   ``pagination_store.paginate_and_store`` 순회·전량 저장 → 배너 해제.
   해제 실패는 삼키지 않고 ``PipelineReport.banner_errors`` 로 보고하며,
   해제 실패가 있으면 전체 상태는 completed 가 될 수 없다(2차 결함 3).
   D3: 20페이지 cap(switch_boolean_variant)도 플랜의 다음 변형 전환 사유다
   (2차 결함 4).
4. AC7 ``InterventionMonitor`` — 매 리스트 페이지·매 상세 조회·등록·기록·초안
   전마다 점검한다. BLOCKED 면 그 즉시 아무 후속 호출 없이 중단(2차 결함 1).
   드라이버 이벤트는 ``intervention.feed_driver_events`` 어댑터로 모니터에
   공급된다(2차 결함 10, deps.poll_driver_events 주입 시).
5. 검색 호출 payload 는 드라이버가 즉시 실행 가능하도록 Boolean 문자열·대학
   필터·필수요건(RPS), 채널 URL·입력 단계(사람인/잡코리아)를 그대로 싣는다
   (2차 결함 9).
6. 수집 후보는 AC4 ``score_gate.register_if_eligible``(강제 게이트) 경유로만
   등록 — 60점 미만은 등록 함수가 아예 호출되지 않는다. 등록 통과 후보는
   AC5 ``DualRecorder`` 기록 + AC9 초안 생성(발송 경로 없음). 기록 status 가
   recorded/dry_run 이 아니면 초안을 만들지 않고 전체 상태를 partial 로
   보고한다(2차 결함 8). 후보별 기록 결과는 ``record_states`` 에 보존되며,
   재실행 시 ``previous`` 로 넘기면 미완 단계(pending_steps)만 이어서
   완결한다(2차 결함 7).
7. 표에 없는 예외(드라이버 예외·저장 실패 등)는 명시적 중단 + 상태 보고
   (E8 catch-all — 임의 추정 금지).

이 모듈 자체는 네트워크/브라우저 코드를 갖지 않는다 — 드라이버·저장소·클라이언트
전부 주입식이며, 재사용 모듈 함수는 import 로 그대로 참조한다(복제 금지).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

from apps.aisearch.core import recorders
from apps.aisearch.core.banner import build_dispatch_snippet
from apps.aisearch.core.boolean_builder import (
    ADVANCE_REASON_CAP_REACHED,
    ADVANCE_REASON_EXHAUSTED,
    DEFAULT_LOCATION,
    SearchPlan,
    build_search_plan,
)
from apps.aisearch.core.draft_builder import build_candidate_draft
from apps.aisearch.core.intervention import (
    InterventionMonitor,
    MonitorState,
    feed_driver_events,
)
from apps.aisearch.core.pagination_store import (
    NEXT_EXHAUSTED,
    NEXT_SWITCH_BOOLEAN_VARIANT,
    PageStore,
    PaginationResult,
    paginate_and_store,
)
from apps.aisearch.core.portal_search import build_portal_search_descriptors
from apps.aisearch.core.recorders import Candidate, DualRecorder, RecordResult
from apps.aisearch.core.score_gate import BelowThresholdError, register_if_eligible

__all__ = [
    "LINKEDIN_CHANNEL",
    "STATUS_ABORTED",
    "STATUS_BLOCKED",
    "STATUS_COMPLETED",
    "STATUS_PARTIAL",
    "STATUS_WAITING_RESUME",
    "BrowserDriverPort",
    "PipelineDeps",
    "PipelineReport",
    "VariantRun",
    "run_search_pipeline",
]

LINKEDIN_CHANNEL = "linkedin_rps"

STATUS_COMPLETED = "completed"
STATUS_PARTIAL = "partial"  # 일부 실패(배너 해제·기록) — completed 로 위장 금지
STATUS_BLOCKED = "blocked"  # AC7 차단 신호 — human_reset 전까지 진행 금지
STATUS_WAITING_RESUME = "waiting_resume"  # 사람 개입 — 30초 무입력 후 재실행
STATUS_ABORTED = "aborted"  # E8 — 표에 없는 예외, 명시적 중단 + 상태 보고

#: 초안 생성이 허용되는 기록 status (2차 결함 8 — 이 외에는 초안 금지).
_RECORD_OK_STATUSES = frozenset({recorders.STATUS_RECORDED, recorders.STATUS_DRY_RUN})


class BrowserDriverPort(Protocol):
    """주입식 브라우저 드라이버 포트 — 배너 dispatch JS 스니펫만 전달받는다."""

    def run_js(self, snippet: str) -> None: ...


class _PipelineBlocked(Exception):
    """AC7 BLOCKED — 파이프라인 즉시 중단(내부 제어 신호)."""


class _PipelineWaiting(Exception):
    """AC7 사람 개입 일시정지 — 재개까지 대기 시그널(내부 제어 신호)."""


@dataclass
class PipelineDeps:
    """전부 주입식 의존성 — 이 모듈은 실제 네트워크/브라우저를 만들지 않는다."""

    driver: BrowserDriverPort
    store: PageStore
    monitor: InterventionMonitor
    recorder: DualRecorder
    #: fetch_list_page(channel, page, search_payload) -> AC3 리스트 페이지 dict.
    #: search_payload 는 즉시 실행 가능한 검색 명세(2차 결함 9) — LinkedIn 은
    #: Boolean·대학필터·필수요건, 포털은 URL·입력 단계(steps)를 그대로 담는다.
    fetch_list_page: Callable[[str, int, dict], dict]
    #: fetch_detail_page(channel, ref) -> AC3 상세 페이지 dict
    fetch_detail_page: Callable[[str, str], dict]
    #: extract_candidates(channel) -> [{"score_payload", "record", "draft_inputs"}]
    extract_candidates: Callable[[str], list[dict]]
    machine: str
    #: 드라이버 관측 이벤트(사람 입력/캡차 등)를 돌려주는 폴러(2차 결함 10).
    #: 반환 이벤트는 intervention.feed_driver_events 규격 그대로 모니터에 공급된다.
    poll_driver_events: Optional[Callable[[], list[dict]]] = None


@dataclass
class VariantRun:
    channel: str
    task: str
    pagination: Optional[PaginationResult] = None


@dataclass
class PipelineReport:
    status: str
    variants: list[VariantRun] = field(default_factory=list)
    registered: list[RecordResult] = field(default_factory=list)
    below_threshold: list[dict[str, Any]] = field(default_factory=list)
    drafts: list[dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    #: 2차 결함 3 — 배너 해제 실행 예외 보고(삼키지 않는다).
    banner_errors: list[dict[str, str]] = field(default_factory=list)
    #: 2차 결함 7 — 후보별(프로필 URL 키) 기록 결과 보존. partial 이면
    #: pending_steps 가 남아 있고, 재실행 시 previous 로 넘겨 이어서 완결한다.
    record_states: dict[str, RecordResult] = field(default_factory=dict)
    #: 2차 결함 8 — recorded/dry_run 이 아닌 기록 결과(초안 금지 + completed 금지).
    record_failures: list[dict[str, Any]] = field(default_factory=list)


def _check_monitor(deps: PipelineDeps) -> None:
    """AC7 — 매 단계(페이지·상세·등록·기록·초안) 진입 전 상태 점검.

    2차 결함 10: 주입된 드라이버 이벤트 폴러가 있으면 먼저 드레인해
    feed_driver_events 로 모니터에 공급한 뒤 판정한다.
    RUNNING 이 아니면 진행 금지 — BLOCKED 는 즉시 중단.
    """
    if deps.poll_driver_events is not None:
        feed_driver_events(deps.monitor, deps.poll_driver_events())
    state = deps.monitor.poll()
    if state is MonitorState.BLOCKED:
        raise _PipelineBlocked(
            "AC7 BLOCKED — 차단 신호(캡차/2FA 등), human_reset 전까지 진행 금지"
        )
    if state is MonitorState.PAUSED_HUMAN:
        raise _PipelineWaiting(
            "AC7 사람 개입 감지 — 30초 무입력 후 재개, 그때까지 대기"
        )


def _register_and_draft(
    jd: dict[str, Any],
    deps: PipelineDeps,
    report: PipelineReport,
    channel: str,
    previous: Optional[PipelineReport],
) -> None:
    """AC4 강제 게이트 경유 등록 → AC5 기록(재개 지원) → AC9 초안 생성."""
    position_name = jd["position_name"]
    for cand in deps.extract_candidates(channel):
        _check_monitor(deps)  # 2차 결함 1 — 등록 전 차단 확인
        profile_url = cand["record"]["profile_url"]

        # 2차 결함 7 — 이전 실행 결과가 있으면 미완 단계만 이어서 수행한다.
        prev_state: Optional[RecordResult] = None
        if previous is not None:
            prev_state = previous.record_states.get(profile_url)
            if prev_state is not None and prev_state.status in _RECORD_OK_STATUSES:
                # 이미 완결된 후보 — 재기록(중복 발신) 금지, 상태만 이월한다.
                report.record_states[profile_url] = prev_state
                continue
            if prev_state is not None and not prev_state.pending_steps:
                prev_state = None  # 재개할 미완 단계가 없으면 처음부터 다시

        def _register(
            gated: dict[str, object],
            _cand: dict = cand,
            _resume: Optional[RecordResult] = prev_state,
        ) -> RecordResult:
            # AC4 게이트를 통과한 결과만 이 함수에 도달한다 — 60점 미만은
            # register_if_eligible 이 BelowThresholdError 로 여기 진입 자체를 막는다.
            _check_monitor(deps)  # 2차 결함 1 — 기록(외부 쓰기) 전 차단 확인
            candidate = Candidate(score=int(gated["score"]), **_cand["record"])
            return deps.recorder.record(
                position_name=position_name,
                candidate=candidate,
                resume_from=_resume,
            )

        try:
            record_result = register_if_eligible(cand["score_payload"], _register)
        except BelowThresholdError as e:
            report.below_threshold.append(
                {"channel": channel, "score": e.score, "threshold": e.threshold}
            )
            continue
        report.record_states[profile_url] = record_result

        # 2차 결함 8 — recorded/dry_run 이 아니면 초안 금지 + 실패로 집계.
        if record_result.status not in _RECORD_OK_STATUSES:
            if record_result.status != recorders.STATUS_SKIPPED:
                report.record_failures.append(
                    {
                        "channel": channel,
                        "profile_url": profile_url,
                        "status": record_result.status,
                        "error": record_result.error,
                    }
                )
            continue
        report.registered.append(record_result)
        _check_monitor(deps)  # 2차 결함 1 — 초안 생성 전 차단 확인
        # AC9 — 전달 초안만 생성(발송 경로 없음, is_draft_only=True)
        report.drafts.append(build_candidate_draft(**cand["draft_inputs"]))


def _run_variant(
    jd: dict[str, Any],
    deps: PipelineDeps,
    report: PipelineReport,
    channel: str,
    task: str,
    search_payload: dict[str, Any],
    previous: Optional[PipelineReport],
) -> PaginationResult:
    """검색 변형 1개 실행: 배너 ON → AC3 순회·저장 → 배너 OFF → 후보 처리."""
    variant = VariantRun(channel=channel, task=task)
    report.variants.append(variant)

    _check_monitor(deps)  # 변형 시작 전 점검
    # AC8 — "조작 시작" 빨간 띠 표시 신호를 드라이버 포트로 전달
    deps.driver.run_js(build_dispatch_snippet(True, task))
    try:

        def guarded_list(page: int) -> dict:
            _check_monitor(deps)  # AC7 — 매 리스트 페이지 요청 전 상태 확인
            return deps.fetch_list_page(channel, page, search_payload)

        def guarded_detail(ref: str) -> dict:
            _check_monitor(deps)  # 2차 결함 1 — 매 상세 조회 전 차단 확인
            return deps.fetch_detail_page(channel, ref)

        variant.pagination = paginate_and_store(
            guarded_list,
            guarded_detail,
            deps.store,
            channel=channel,
            position_ref=jd["position_name"],
            machine=deps.machine,
        )
    finally:
        # 배너 해제 신호는 중단 경로에서도 반드시 시도한다. 2차 결함 3:
        # 해제 실패는 본 오류(차단/예외)를 가리지 않되 조용히 삼키지도 않는다 —
        # banner_errors 로 보고하고, 전체 상태 completed 를 막는다.
        try:
            deps.driver.run_js(build_dispatch_snippet(False))
        except Exception as release_error:  # noqa: BLE001 — 본 오류에 종속, 보고만
            report.banner_errors.append(
                {"channel": channel, "task": task, "error": str(release_error)}
            )

    _check_monitor(deps)  # 2차 결함 1 — 후보 처리(등록 경로) 진입 전 차단 확인
    _register_and_draft(jd, deps, report, channel, previous)
    return variant.pagination


class _LinkedInRunner:
    """LinkedIn RPS 채널 러너 — 플랜 단계를 소진/cap 사유로만 전진시킨다."""

    channel = LINKEDIN_CHANNEL

    def __init__(self, plan: SearchPlan) -> None:
        self._plan = plan

    def next_unit(self) -> Optional[tuple[str, dict[str, Any]]]:
        if self._plan.is_exhausted():
            return None
        stage = self._plan.current_stage()
        # 2차 결함 9 — 드라이버가 즉시 실행 가능한 RPS 검색 payload.
        payload: dict[str, Any] = {
            "channel": LINKEDIN_CHANNEL,
            "stage": stage.name,
            "keywords": stage.keywords,
            "location": stage.location,
            "required_filters": stage.required_filters,
            "universities": stage.universities,
        }
        return f"{LINKEDIN_CHANNEL}:{stage.name}", payload

    def feed(self, pagination: PaginationResult) -> None:
        # 2차 결함 4 — D3: cap 도달(switch_boolean_variant)도 소진과 마찬가지로
        # 플랜의 다음 불린 변형으로 계속 실행한다.
        if pagination.next_action == NEXT_EXHAUSTED:
            self._plan.advance(ADVANCE_REASON_EXHAUSTED)
        elif pagination.next_action == NEXT_SWITCH_BOOLEAN_VARIANT:
            self._plan.advance(ADVANCE_REASON_CAP_REACHED)


class _DescriptorRunner:
    """사람인/잡코리아 채널 러너 — AC2 디스크립터 1건을 1변형으로 실행한다."""

    def __init__(self, descriptor: dict[str, Any]) -> None:
        self._descriptor = descriptor
        self.channel = descriptor["channel"]
        self._done = False

    def next_unit(self) -> Optional[tuple[str, dict[str, Any]]]:
        if self._done:
            return None
        d = self._descriptor
        # 2차 결함 9 — URL·로그인 URL·입력 단계(steps)를 그대로 싣는다.
        payload: dict[str, Any] = {
            "channel": d["channel"],
            "url": d["url"],
            "steps": d["steps"],
            "dedup_key": d["dedup_key"],
            "post_filter_exclude": d["post_filter_exclude"],
        }
        if "login_url" in d:
            payload["login_url"] = d["login_url"]
        return f"{d['channel']}:{d['dedup_key']}", payload

    def feed(self, pagination: PaginationResult) -> None:
        self._done = True


def run_search_pipeline(
    jd: dict[str, Any],
    deps: PipelineDeps,
    *,
    previous: Optional[PipelineReport] = None,
) -> PipelineReport:
    """단일 진입점 — AC1~AC9 전 모듈을 실제 호출한다(배선 경로).

    previous: 직전 실행의 PipelineReport — 후보별 기록이 partial 로 남았으면
    미완 단계만 이어서 완결한다(2차 결함 7).

    반환 status:
    - "completed": 전 변형 완료 + 실패 0
    - "partial": 변형은 돌았으나 배너 해제 실패 또는 기록 미완결이 있음
    - "blocked": AC7 차단 신호 — 즉시 중단(진행 금지)
    - "waiting_resume": 사람 개입 — 재개까지 대기 시그널
    - "aborted": E8 — 표에 없는 예외, 명시적 중단 + error 에 상태 보고
    """
    report = PipelineReport(status=STATUS_ABORTED)
    try:
        position_name = jd.get("position_name")
        if not isinstance(position_name, str) or not position_name.strip():
            raise ValueError(
                "position_name 이 비어 있다 — 파이프라인 진입 fail-closed"
            )

        # 1) AC1 — RPS 검색 플랜(서울 소재 대학 우선 → 소진/cap 시 다음 변형).
        # 2차 결함 2 — JD 제외어(not_keywords)는 build_rps_boolean 이 NOT 절로 반영.
        plan = build_search_plan(jd, location=jd.get("location", DEFAULT_LOCATION))
        # 1) AC2 — 사람인/잡코리아 디스크립터(제외어는 post_filter_exclude 로 전달).
        descriptors = build_portal_search_descriptors(
            or_keywords=jd.get("or_keywords"),
            and_keywords=jd.get("and_keywords"),
            exclude_keywords=jd.get("not_keywords"),
            career_min=jd.get("career_min"),
            career_max=jd.get("career_max"),
        )

        # 2) D6 "3사 동시 착수"(2차 결함 5) — 채널별 러너를 라운드로빈으로
        # 인터리브 실행한다. 한 채널의 종료는 다른 채널의 시작 조건이 아니다.
        runners: list[Any] = [_LinkedInRunner(plan)] + [
            _DescriptorRunner(d) for d in descriptors
        ]
        active = list(runners)
        while active:
            for runner in list(active):
                unit = runner.next_unit()
                if unit is None:
                    active.remove(runner)
                    continue
                task, payload = unit
                pagination = _run_variant(
                    jd, deps, report, runner.channel, task, payload, previous
                )
                runner.feed(pagination)

        # 2차 결함 3·8 — 배너 해제 실패나 기록 미완결이 있으면 completed 금지.
        has_pending_records = any(
            state.pending_steps for state in report.record_states.values()
        )
        if report.banner_errors or report.record_failures or has_pending_records:
            report.status = STATUS_PARTIAL
        else:
            report.status = STATUS_COMPLETED
    except _PipelineBlocked as e:
        report.status = STATUS_BLOCKED
        report.error = str(e)
    except _PipelineWaiting as e:
        report.status = STATUS_WAITING_RESUME
        report.error = str(e)
    except Exception as e:  # noqa: BLE001 — E8 catch-all: 명시적 중단 + 상태 보고
        report.status = STATUS_ABORTED
        report.error = f"{type(e).__name__}: {e}"
    return report
