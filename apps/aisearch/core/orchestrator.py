"""apps/aisearch 오케스트레이터 — 8개 모듈(AC1~AC9)을 하나의 실행 경로로 배선.

V1 적대검증 BLOCKER("고아 모듈/배선 부재") 해소. 진입점은
``run_search_pipeline(jd, deps)`` 하나이며, 실행 순서는 goal 문서
(docs/engineering/aisearch-fleet-goal-2026-07-28.md)의 파이프라인 그대로다:

1. AC1 ``boolean_builder.build_search_plan`` — RPS 검색 플랜(서울 소재 대학 우선
   → 소진 시 확장) + AC2 ``portal_search.build_portal_search_descriptors`` —
   사람인/잡코리아 디스크립터.
2. 각 검색 변형마다 AC8 ``banner.build_dispatch_snippet`` 을 브라우저 드라이버
   포트(주입식 Protocol)에 전달해 "조작 시작" 표시 → AC3
   ``pagination_store.paginate_and_store`` 로 순회·전량 저장 → 배너 해제 신호.
3. 매 페이지 사이 AC7 ``InterventionMonitor.poll()`` 점검 — BLOCKED 면 즉시
   중단(진행 금지), 사람 개입(PAUSED_HUMAN)이면 재개 대기 시그널 반환.
4. 수집 후보는 AC4 ``score_gate.register_if_eligible``(강제 게이트) 경유로만
   등록 — 60점 미만은 등록 함수가 아예 호출되지 않는다.
5. 등록 통과 후보는 AC5 ``DualRecorder``(기본 dry-run) 기록 + AC9
   ``draft_builder.build_candidate_draft`` 전달 초안 생성(발송 경로 없음).
6. 표에 없는 예외(드라이버 예외·저장 실패 등)는 명시적 중단 + 상태 보고
   (E8 catch-all — 임의 추정 금지).

이 모듈 자체는 네트워크/브라우저 코드를 갖지 않는다 — 드라이버·저장소·클라이언트
전부 주입식이며, 재사용 모듈 함수는 import 로 그대로 참조한다(복제 금지).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

from apps.aisearch.core.banner import build_dispatch_snippet
from apps.aisearch.core.boolean_builder import (
    ADVANCE_REASON_EXHAUSTED,
    DEFAULT_LOCATION,
    build_search_plan,
)
from apps.aisearch.core.draft_builder import build_candidate_draft
from apps.aisearch.core.intervention import InterventionMonitor, MonitorState
from apps.aisearch.core.pagination_store import (
    NEXT_EXHAUSTED,
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
    "STATUS_WAITING_RESUME",
    "BrowserDriverPort",
    "PipelineDeps",
    "PipelineReport",
    "VariantRun",
    "run_search_pipeline",
]

LINKEDIN_CHANNEL = "linkedin_rps"

STATUS_COMPLETED = "completed"
STATUS_BLOCKED = "blocked"  # AC7 차단 신호 — human_reset 전까지 진행 금지
STATUS_WAITING_RESUME = "waiting_resume"  # 사람 개입 — 30초 무입력 후 재실행
STATUS_ABORTED = "aborted"  # E8 — 표에 없는 예외, 명시적 중단 + 상태 보고


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
    #: fetch_list_page(channel, page) -> AC3 리스트 페이지 dict
    fetch_list_page: Callable[[str, int], dict]
    #: fetch_detail_page(channel, ref) -> AC3 상세 페이지 dict
    fetch_detail_page: Callable[[str, str], dict]
    #: extract_candidates(channel) -> [{"score_payload", "record", "draft_inputs"}]
    extract_candidates: Callable[[str], list[dict]]
    machine: str


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


def _check_monitor(monitor: InterventionMonitor) -> None:
    """AC7 — 매 페이지/변형 진입 전 상태 점검. RUNNING 이 아니면 진행 금지."""
    state = monitor.poll()
    if state is MonitorState.BLOCKED:
        raise _PipelineBlocked(
            "AC7 BLOCKED — 차단 신호(캡차/2FA 등), human_reset 전까지 진행 금지"
        )
    if state is MonitorState.PAUSED_HUMAN:
        raise _PipelineWaiting(
            "AC7 사람 개입 감지 — 30초 무입력 후 재개, 그때까지 대기"
        )


def _register_and_draft(
    jd: dict[str, Any], deps: PipelineDeps, report: PipelineReport, channel: str
) -> None:
    """AC4 강제 게이트 경유 등록 → AC5 dry-run 기록 → AC9 초안 생성."""
    position_name = jd["position_name"]
    for cand in deps.extract_candidates(channel):

        def _register(gated: dict[str, object], _cand: dict = cand) -> RecordResult:
            # AC4 게이트를 통과한 결과만 이 함수에 도달한다 — 60점 미만은
            # register_if_eligible 이 BelowThresholdError 로 여기 진입 자체를 막는다.
            candidate = Candidate(score=int(gated["score"]), **_cand["record"])
            return deps.recorder.record(
                position_name=position_name, candidate=candidate
            )

        try:
            record_result = register_if_eligible(cand["score_payload"], _register)
        except BelowThresholdError as e:
            report.below_threshold.append(
                {"channel": channel, "score": e.score, "threshold": e.threshold}
            )
            continue
        report.registered.append(record_result)
        # AC9 — 전달 초안만 생성(발송 경로 없음, is_draft_only=True)
        report.drafts.append(build_candidate_draft(**cand["draft_inputs"]))


def _run_variant(
    jd: dict[str, Any],
    deps: PipelineDeps,
    report: PipelineReport,
    channel: str,
    task: str,
) -> PaginationResult:
    """검색 변형 1개 실행: 배너 ON → AC3 순회·저장 → 배너 OFF → 후보 처리."""
    variant = VariantRun(channel=channel, task=task)
    report.variants.append(variant)

    _check_monitor(deps.monitor)  # 변형 시작 전 점검
    # AC8 — "조작 시작" 빨간 띠 표시 신호를 드라이버 포트로 전달
    deps.driver.run_js(build_dispatch_snippet(True, task))
    try:

        def guarded_list(page: int) -> dict:
            _check_monitor(deps.monitor)  # AC7 — 매 페이지 사이 상태 확인
            return deps.fetch_list_page(channel, page)

        variant.pagination = paginate_and_store(
            guarded_list,
            lambda ref: deps.fetch_detail_page(channel, ref),
            deps.store,
            channel=channel,
            position_ref=jd["position_name"],
            machine=deps.machine,
        )
    finally:
        # 배너 해제 신호는 중단 경로에서도 반드시 시도한다. 해제 실패가
        # 본 오류(차단/예외)를 가리면 안 되므로 2차 예외는 삼킨다.
        try:
            deps.driver.run_js(build_dispatch_snippet(False))
        except Exception:  # noqa: BLE001 — 해제 실패는 본 오류에 종속
            pass

    _register_and_draft(jd, deps, report, channel)
    return variant.pagination


def run_search_pipeline(jd: dict[str, Any], deps: PipelineDeps) -> PipelineReport:
    """단일 진입점 — AC1~AC9 전 모듈을 순서대로 실제 호출한다(배선 경로).

    반환 status:
    - "completed": 전 변형 완료
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

        # 1) AC1 — RPS 검색 플랜(서울 소재 대학 우선 → 확장)
        plan = build_search_plan(jd, location=jd.get("location", DEFAULT_LOCATION))
        # 1) AC2 — 사람인/잡코리아 디스크립터
        descriptors = build_portal_search_descriptors(
            or_keywords=jd.get("or_keywords"),
            and_keywords=jd.get("and_keywords"),
            career_min=jd.get("career_min"),
            career_max=jd.get("career_max"),
        )

        # 2~5) LinkedIn RPS: 현재 단계 실행 → 소진(exhausted)일 때만 다음 단계.
        # 20페이지 cap(switch_boolean_variant)은 "준비된 다음 불린 변형" 이 없는
        # 현 플랜에서는 RPS 종료 신호다(임의로 확장 단계로 승격하지 않는다 —
        # 확장 전환은 boolean_builder 가 exhausted 사유만 허용).
        while not plan.is_exhausted():
            stage = plan.current_stage()
            pagination = _run_variant(
                jd, deps, report, LINKEDIN_CHANNEL, f"{LINKEDIN_CHANNEL}:{stage.name}"
            )
            if pagination.next_action == NEXT_EXHAUSTED:
                if plan.advance(ADVANCE_REASON_EXHAUSTED) is None:
                    break
            else:
                break

        # 2~5) 사람인 → 잡코리아 (AC2 디스크립터 순서 그대로)
        for descriptor in descriptors:
            _run_variant(
                jd,
                deps,
                report,
                descriptor["channel"],
                f"{descriptor['channel']}:{descriptor['dedup_key']}",
            )

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
