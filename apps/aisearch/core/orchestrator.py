"""apps/aisearch 오케스트레이터 — 8개 모듈(AC1~AC9)을 하나의 실행 경로로 배선.

V1 적대검증 BLOCKER("고아 모듈/배선 부재") + V1 2차 적대검증 결함 10건 해소.
진입점은 ``run_search_pipeline(jd, deps, previous=...)`` 하나이며, 실행 흐름은
goal 문서(docs/engineering/aisearch-fleet-goal-2026-07-28.md) 파이프라인 그대로다:

1. AC1 ``boolean_builder.build_search_plan`` — RPS 검색 플랜(서울 소재 대학 우선
   → 소진/cap 시 다음 변형) + AC2 ``portal_search.build_portal_search_descriptors``
   — 사람인/잡코리아 디스크립터. JD 제외어(not_keywords)는 RPS Boolean NOT 절과
   포털 post_filter_exclude 로 전달·반영된다(2차 결함 2).
2. D6 "3사 동시 착수": 채널별 파이프라인(LinkedIn 플랜 / 사람인 / 잡코리아)을
   스레드(채널당 1, ThreadPoolExecutor)로 실제 동시 실행한다 — 한 채널의
   드라이버 호출이 블록돼도 다른 채널은 시작·진행된다(2차 결함 5 → 3차 결함 ⑩).
   공유 상태(개입 모니터·리포트·기록기)는 deps.lock 으로 보호한다.
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

import threading
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Protocol

from apps.aisearch.core import recorders
from apps.aisearch.core.banner import build_dispatch_snippet
from apps.aisearch.core.cdp_driver import DetailPageBlocked, HumanInterventionDetected
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


class _PipelineStopped(Exception):
    """M2 — 다른 채널 실패로 인한 협조적 중단(내부 제어 신호)."""


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
    #: 4차 결함 ⑩ — 채널별 독립 드라이버(각자 탭/연결) 맵. 주입되면 배너 등
    #: 채널 국한 드라이버 호출은 반드시 자기 채널 드라이버로만 나간다(혼선 0).
    #: 맵에 없는 채널은 fail-closed(조용한 공용 드라이버 격하 금지).
    drivers: Optional[Mapping[str, BrowserDriverPort]] = None
    #: 3차 결함 ⑩ — 채널 스레드 간 공유 상태(개입 모니터·리포트·기록기) 보호 락.
    #: RLock: _register_and_draft(락 보유) 내부에서 _check_monitor(락 취득)를
    #: 다시 부르는 중첩 경로가 있다.
    lock: threading.RLock = field(default_factory=threading.RLock)
    #: V1 독립검증 결함4 — 링크드인 채널 실행 전체를 감싸는 기기 간 세션 락
    #: (컨텍스트 매니저, session_lock.LinkedInSessionLock 계약). None 이면
    #: 기기 간 배제를 하지 않는다(이 프로세스 내부 threading.RLock 만으로는
    #: 다른 기기의 동시 실행을 막을 수 없다 — 알려진 한계, 주입 안 하면
    #: 명시적으로 그 한계를 그대로 가져간다).
    linkedin_session_lock: Optional[Any] = None
    #: M2 — 채널 간 협조적 중단 신호. 한 채널이 죽으면 여기에 세팅되고, 남은
    #: 채널은 새 작업 단위·새 페이지 요청을 시작하지 않는다(헛일 방지).
    stop_event: threading.Event = field(default_factory=threading.Event)


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
    #: M2(2026-07-31 리뷰) — 채널별 예외 **전량** 보고. 예전에는 첫 예외만
    #: 재발생하고 나머지 채널의 실패는 흔적 없이 사라졌다.
    channel_errors: list[dict[str, Any]] = field(default_factory=list)
    #: M3(2026-07-31 리뷰) — 재발신에도 끝내 못 보낸 차단 알림(조용한 유실 금지).
    notification_failures: list[str] = field(default_factory=list)
    #: 후보 1명당 1회만 집계하기 위한 내부 표식(profile_url). "이미 record_states 에
    #: 있다"로 판정하면, 지난 라운드에 **미완결(partial)** 이던 후보가 이번 라운드에
    #: 완결돼도 집계에서 빠진다 — 그래서 "실제로 등록·초안으로 센 후보"만 담는다.
    counted_profile_urls: set[str] = field(default_factory=set)
    #: 3차 결함 ⑦ — 제외어(not_keywords) 매칭으로 등록·초안 전에 걸러낸 후보
    #: (제외 사유 기록). 항목: channel, profile_url, matched_keyword,
    #: matched_field, reason.
    excluded: list[dict[str, Any]] = field(default_factory=list)


def _raise_if_stopped(deps: PipelineDeps) -> None:
    """M2 — 다른 채널이 이미 죽었으면 새 작업을 시작하지 않는다."""
    if deps.stop_event.is_set():
        raise _PipelineStopped("다른 채널 실패로 협조적 중단")


def _check_monitor(deps: PipelineDeps) -> None:
    """AC7 — 매 단계(페이지·상세·등록·기록·초안) 진입 전 상태 점검.

    2차 결함 10: 주입된 드라이버 이벤트 폴러가 있으면 먼저 드레인해
    feed_driver_events 로 모니터에 공급한 뒤 판정한다.
    RUNNING 이 아니면 진행 금지 — BLOCKED 는 즉시 중단.
    3차 결함 ⑩: 모니터는 채널 스레드 공유 상태 — deps.lock 으로 직렬화한다.
    """
    with deps.lock:
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


def _iter_strings(value: Any, path: str):
    """후보 payload 트리(dict/list/tuple/str)의 모든 문자열을 경로와 함께 순회."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, Mapping):
        for key, inner in value.items():
            yield from _iter_strings(inner, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, inner in enumerate(value):
            yield from _iter_strings(inner, f"{path}[{index}]")


#: 2026-07-31 전수 리뷰 H2 — 제외어를 찾을 **후보 고유** 영역.
#: - "record": 경력·학력·프로필 요약 등 후보 본인의 정보
#: - "score_payload": D1~D8 점수 근거(evidence) — 후보를 보고 쓴 글
#: draft_inputs(jd_summary·briefing_elements)는 **JD 공통 텍스트**라 제외한다.
#: 여기에 제외어가 한 번 들어가면 그 채널의 모든 후보가 함께 떨어졌다.
#: 표 밖(신규) 최상위 키는 스캔하지 않는다 — 조용한 대량 제외를 막는다.
#: 후보 고유 정보만 담긴 최상위 칸.
EXCLUSION_SCAN_ROOTS: tuple[str, ...] = ("record",)

#: score_payload 안에서는 **후보를 보고 쓴 근거(evidence)** 만 훑는다.
#: V1 3라운드 — 점수자료 전체를 훑으면 JD 에서 복사된 평가 기준 문구
#: ("인턴 경험 제외" 같은 requirement/criteria)에 걸려 정상 후보가 떨어졌다.
EXCLUSION_SCAN_SCORE_FIELD = "evidence"

#: draft_inputs 안에서도 **후보 본인** 정보인 칸은 스캔한다(V1 2라운드 지적).
#: 회사·직함은 후보 고유 정보라서, 여기 "프리랜서"가 있으면 걸러야 한다.
#: 반대로 jd_summary·briefing_elements·company_name(고객사)·position_title 은
#: JD 공통 텍스트라 스캔하지 않는다 — 한 번 걸리면 전 후보가 함께 떨어진다.
EXCLUSION_SCAN_DRAFT_FIELDS: tuple[str, ...] = (
    "candidate_name",
    "candidate_company",
    "candidate_headline",
)


#: 매칭 전 정규화에서 지우는 "보이지 않는" 문자(제로폭·워드조이너 등).
_INVISIBLE_CHARS = dict.fromkeys(
    [0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD], None
)


def _normalize_for_match(text: Any) -> str:
    """제외어 비교용 정규화 — V1 3차 지적(앞뒤 공백·전각·보이지 않는 문자).

    ``" 인턴 "`` 처럼 여백이 붙은 제외어를 놓치거나, ``프리<제로폭>랜서``·전각
    ``ＦＲＥＥＬＡＮＣＥ`` 같은 표기를 지나치지 않도록 같은 잣대로 맞춘다.
    """
    if not isinstance(text, str):
        return ""
    normalized = unicodedata.normalize("NFKC", text).translate(_INVISIBLE_CHARS)
    return normalized.casefold().strip()


def _iter_evidence_values(value: Any, path: str):
    """점수자료 트리에서 ``evidence`` 칸만 골라 낸다(후보를 보고 쓴 근거)."""
    if isinstance(value, Mapping):
        for key, inner in value.items():
            child = f"{path}.{key}"
            if key == EXCLUSION_SCAN_SCORE_FIELD:
                yield child, inner
            else:
                yield from _iter_evidence_values(inner, child)
    elif isinstance(value, (list, tuple)):
        for index, inner in enumerate(value):
            yield from _iter_evidence_values(inner, f"{path}[{index}]")


def _find_exclusion_match(
    cand: dict[str, Any], exclusions: list[str]
) -> Optional[tuple[str, str]]:
    """3차 결함 ⑦(4차 재수정 → 2026-07-31 H2 범위 한정) — 제외어 매칭.

    후보 고유 영역(EXCLUSION_SCAN_ROOTS) 안의 중첩 dict/list 문자열만 재귀
    스캔한다(casefold 부분일치). 반환: (매칭된 제외어, 매칭 필드 경로).
    """
    folded_terms = [
        (term, _normalize_for_match(term))
        for term in exclusions
        if _normalize_for_match(term)
    ]
    if not folded_terms:
        return None
    def _scan(value: Any, path: str) -> Optional[tuple[str, str]]:
        for found_path, text in _iter_strings(value, path):
            folded = _normalize_for_match(text)
            for term, folded_term in folded_terms:
                if folded_term in folded:
                    return term, found_path
        return None

    for root in EXCLUSION_SCAN_ROOTS:
        if root not in cand:
            continue
        hit = _scan(cand[root], f"candidate.{root}")
        if hit is not None:
            return hit
    score_payload = cand.get("score_payload")
    if isinstance(score_payload, Mapping):
        for path, value in _iter_evidence_values(
            score_payload, "candidate.score_payload"
        ):
            hit = _scan(value, path)
            if hit is not None:
                return hit
    draft_inputs = cand.get("draft_inputs")
    if isinstance(draft_inputs, Mapping):
        for field_name in EXCLUSION_SCAN_DRAFT_FIELDS:
            if field_name not in draft_inputs:
                continue
            hit = _scan(
                draft_inputs[field_name], f"candidate.draft_inputs.{field_name}"
            )
            if hit is not None:
                return hit
    return None


def _register_and_draft(
    jd: dict[str, Any],
    deps: PipelineDeps,
    report: PipelineReport,
    channel: str,
    previous: Optional[PipelineReport],
    exclusions: list[str],
) -> None:
    """3차 결함 ⑦ exclusion 게이트 → AC4 강제 게이트 경유 등록 →
    AC5 기록(재개 지원) → AC9 초안 생성."""
    position_name = jd["position_name"]
    for cand in deps.extract_candidates(channel):
        # M2(V1 2라운드) — 다른 채널이 죽었으면 등록(외부 쓰기)도 시작하지 않는다.
        # 예전에는 목록 요청에만 중단 확인이 있어, 실패 이후에도 admin 등록이
        # 계속 나갔다(되돌리기 어려운 외부 쓰기가 중단 신호를 무시).
        _raise_if_stopped(deps)
        _check_monitor(deps)  # 2차 결함 1 — 등록 전 차단 확인
        profile_url = cand["record"]["profile_url"]

        # 3차 결함 ⑦ — 제외어 매칭 후보는 등록·초안 어느 경로에도 진입 금지.
        # 검색 payload(NOT 절/post_filter_exclude)와 별개로 후보 단계에서
        # 최종 강제하고, 제외 사유를 기록한다(fail-closed).
        matched = _find_exclusion_match(cand, exclusions)
        if matched is not None:
            term, field_path = matched
            with deps.lock:
                already_excluded = any(
                    e.get("profile_url") == profile_url and e.get("channel") == channel
                    for e in report.excluded
                )
            if already_excluded:
                continue  # V1 3차 — 재개 시 같은 제외 기록이 두 번 쌓이던 것 방지
            with deps.lock:
                report.excluded.append(
                    {
                        "channel": channel,
                        "profile_url": profile_url,
                        "matched_keyword": term,
                        "matched_field": field_path,
                        "reason": (
                            f"JD 제외어 '{term}' 이(가) 후보 {field_path} 에서 "
                            "매칭 — 등록·초안 진입 금지(결함 ⑦ exclusion 게이트)"
                        ),
                    }
                )
            continue

        # 2차 결함 7 — 이전 실행 결과가 있으면 미완 단계만 이어서 수행한다.
        prev_state: Optional[RecordResult] = None
        if previous is not None:
            prev_state = previous.record_states.get(profile_url)
            if prev_state is not None and prev_state.status in _RECORD_OK_STATUSES:
                # 이미 완결된 후보 — 재기록(중복 발신)은 하지 않는다.
                # 2026-07-31 리뷰 F7: 예전에는 여기서 상태만 이월하고 continue 해서,
                # 재개가 한 번이라도 돌면 새 리포트의 registered 에서 빠지고 초안도
                # 만들어지지 않았다(수치 축소 + 전달 초안 영구 누락). 외부 쓰기는
                # 건너뛰되 **리포트 집계와 초안 생성은 그대로 수행**한다 —
                # build_candidate_draft 는 순수 함수라 발신이 없다.
                with deps.lock:
                    # V1 2라운드 — 같은 후보가 여러 변형/중복 추출로 두 번 오면
                    # 리포트에 두 번 세지 않는다(실제로 센 적 있는지로 판정).
                    already_counted = profile_url in report.counted_profile_urls
                    report.record_states[profile_url] = prev_state
                    if not already_counted:
                        report.registered.append(prev_state)
                if already_counted:
                    continue
                _check_monitor(deps)
                carried_draft = build_candidate_draft(**cand["draft_inputs"])
                with deps.lock:
                    report.drafts.append(carried_draft)
                    report.counted_profile_urls.add(profile_url)
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
            with deps.lock:  # 결함 ⑩ — 기록기(ClickUp/Discord)는 공유 상태
                return deps.recorder.record(
                    position_name=position_name,
                    candidate=candidate,
                    channel=channel,
                    resume_from=_resume,
                )

        try:
            record_result = register_if_eligible(cand["score_payload"], _register)
        except BelowThresholdError as e:
            with deps.lock:
                report.below_threshold.append(
                    {"channel": channel, "score": e.score, "threshold": e.threshold}
                )
            continue
        with deps.lock:
            # V1 2라운드 — 같은 후보(profile_url)는 몇 번 등장하든 리포트에
            # 한 번만 센다. 링크드인은 변형이 여럿이고 추출기가 같은 후보를
            # 두 번 넘길 수도 있어, 예전에는 등록 수·초안 수가 실제보다 부풀었다.
            first_time = profile_url not in report.counted_profile_urls
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
            if not first_time:
                continue  # 이미 센 후보 — 중복 집계·중복 초안 금지
            report.registered.append(record_result)
        _check_monitor(deps)  # 2차 결함 1 — 초안 생성 전 차단 확인
        # AC9 — 전달 초안만 생성(발송 경로 없음, is_draft_only=True)
        draft = build_candidate_draft(**cand["draft_inputs"])
        with deps.lock:
            report.drafts.append(draft)
            # V1 3차 — "센 후보" 표식은 **초안까지 마친 뒤**에 찍는다. 등록 직후에
            # 찍으면 초안 생성 전에 중단됐을 때 재개가 "이미 셌다"며 건너뛰어
            # 전달 초안이 영구 누락됐다.
            report.counted_profile_urls.add(profile_url)


def _run_variant(
    jd: dict[str, Any],
    deps: PipelineDeps,
    report: PipelineReport,
    channel: str,
    task: str,
    search_payload: dict[str, Any],
    previous: Optional[PipelineReport],
    exclusions: list[str],
) -> PaginationResult:
    """검색 변형 1개 실행: 배너 ON → AC3 순회·저장 → 배너 OFF → 후보 처리."""
    variant = VariantRun(channel=channel, task=task)
    with deps.lock:  # 결함 ⑩ — 리포트는 채널 스레드 공유 상태
        report.variants.append(variant)

    # 4차 결함 ⑩ — 채널별 드라이버 맵이 주입되면 배너 신호는 반드시 자기
    # 채널 드라이버(자기 탭/연결)로만 나간다. 없는 채널은 fail-closed.
    if deps.drivers is not None:
        driver = deps.drivers.get(channel)
        if driver is None:
            raise ValueError(
                f"채널 {channel!r} 드라이버 미배선(fail-closed) — drivers 맵 확인"
            )
    else:
        driver = deps.driver

    def _release_banner() -> None:
        """배너 해제 — 실패는 삼키지 않고 banner_errors 로 보고한다(2차 결함 3)."""
        try:
            driver.run_js(build_dispatch_snippet(False))
        except Exception as release_error:  # noqa: BLE001 — 본 오류에 종속, 보고만
            with deps.lock:
                report.banner_errors.append(
                    {"channel": channel, "task": task, "error": str(release_error)}
                )

    _check_monitor(deps)  # 변형 시작 전 점검
    # AC8 — "조작 시작" 빨간 띠 표시 신호를 드라이버 포트로 전달
    driver.run_js(build_dispatch_snippet(True, task))
    try:

        def _beat_session_lock() -> None:
            """장시간 실행이 stale 로 오인돼 락을 뺏기지 않게 살아있음을 알린다.

            자체 적대검증 발견 — 검색 한 판이 stale_seconds(기본 1시간)를 넘으면
            다른 기기가 락을 회수해 같은 계정으로 동시 접속할 수 있었다(E4 위반).
            """
            if channel != LINKEDIN_CHANNEL:
                return
            beat = getattr(deps.linkedin_session_lock, "heartbeat", None)
            if callable(beat):
                beat()

        def _handle_page_block(exc: DetailPageBlocked) -> None:
            """차단 신호를 모니터에 공급하고 BLOCKED 로 승격한다(목록·상세 공통).

            자체 적대검증 발견 — 목록 페이지 차단(M1)을 아무도 받아주지 않아
            E8 abort 로 떨어졌다. 그러면 상태가 blocked 가 아니고, 무엇보다
            차단 알림이 사장님께 나가지 않는다. 상세와 **같은 계약**으로 다룬다.
            """
            with deps.lock:
                feed_driver_events(deps.monitor, exc.events)
                deps.monitor.poll()

        def guarded_list(page: int) -> dict:
            _raise_if_stopped(deps)  # M2 — 협조적 중단 확인
            _check_monitor(deps)  # AC7 — 매 리스트 페이지 요청 전 상태 확인
            _beat_session_lock()
            try:
                return deps.fetch_list_page(channel, page, search_payload)
            except HumanInterventionDetected as exc:
                with deps.lock:
                    feed_driver_events(deps.monitor, exc.events)
                    deps.monitor.poll()
                raise _PipelineWaiting(
                    "AC7 사람 개입 감지(드라이버) — 자동 조작 즉시 중단, 무입력 후 재개"
                ) from exc
            except DetailPageBlocked as exc:
                _handle_page_block(exc)
                raise _PipelineBlocked(
                    "AC7 BLOCKED — 목록 페이지 차단 신호(캡차/2FA 등), "
                    "human_reset 전까지 진행 금지"
                ) from exc

        def guarded_detail(ref: str) -> dict:
            _raise_if_stopped(deps)  # M2(V1 2라운드) — 상세 조회에도 중단 확인
            _check_monitor(deps)  # 2차 결함 1 — 매 상세 조회 전 차단 확인
            _beat_session_lock()
            try:
                return deps.fetch_detail_page(channel, ref)
            except HumanInterventionDetected as exc:
                with deps.lock:
                    feed_driver_events(deps.monitor, exc.events)
                    deps.monitor.poll()
                raise _PipelineWaiting(
                    "AC7 사람 개입 감지(드라이버) — 자동 조작 즉시 중단, 무입력 후 재개"
                ) from exc
            except DetailPageBlocked as exc:
                # V1 독립검증 결함1 — 상세페이지 자체의 차단신호는 목록 페이지
                # 기준 _check_monitor 이전 검사로는 못 잡는다. 드라이버가 감지해
                # 올려보낸 이벤트를 여기서 모니터에 공급하고 즉시 BLOCKED 처리한다.
                _handle_page_block(exc)
                raise _PipelineBlocked(
                    "AC7 BLOCKED — 상세페이지 차단 신호(캡차/2FA 등), "
                    "human_reset 전까지 진행 금지"
                ) from exc

        variant.pagination = paginate_and_store(
            guarded_list,
            guarded_detail,
            deps.store,
            channel=channel,
            position_ref=jd["position_name"],
            machine=deps.machine,
            # 3차 결함 ⑥ — 목록/상세 "저장 직전"에도 개입 모니터를 재확인한다.
            # 응답 수신 도중 캡차가 들어오면 그 페이지는 저장 0건으로 중단된다.
            before_store=lambda: _check_monitor(deps),
        )
    except (_PipelineBlocked, _PipelineWaiting):
        # V1 3라운드 — 사장님이 크롬을 만졌거나 캡차가 떴는데도 정리 구문이
        # 브라우저에 JS 를 하나 더 보냈다(SOT 불변식 2: 개입 중 자동 조작 0).
        # 배너는 그대로 두고 왜 안 지웠는지만 보고한다 — 화면 정리보다
        # "개입 중에는 손대지 않는다"가 우선이다(사람이 재개하면 해제된다).
        with deps.lock:
            report.banner_errors.append(
                {
                    "channel": channel,
                    "task": task,
                    "error": "개입/차단 감지로 배너 해제 보류(브라우저 무접촉 유지)",
                }
            )
        raise
    except BaseException:
        _release_banner()
        raise
    else:
        _release_banner()

    _raise_if_stopped(deps)  # M2 — 후보 처리 진입 전 협조적 중단 확인
    _check_monitor(deps)  # 2차 결함 1 — 후보 처리(등록 경로) 진입 전 차단 확인
    _register_and_draft(jd, deps, report, channel, previous, exclusions)
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
    # M2 — 협조적 중단 신호는 **이번 실행** 한정이다. 재개 실행(previous=...)이
    # 지난 실행의 신호를 물려받아 즉시 멈추면 자동 재개가 성립하지 않는다.
    deps.stop_event.clear()
    if previous is not None:
        # V1 2차 독립검증 결함 — previous 를 record_states 조회(개별 후보
        # 재개)에만 쓰고, report 자체는 매 호출마다 빈 채로 새로 만들어서
        # 이전 실행에서 이미 등록/제외/초안된 후보가 재시도 결과에서
        # 통째로 사라졌다(재개 루프가 report 를 매번 덮어씀). 여기서 이어받되,
        # 대상은 되돌릴 수 없는(한번 확정되면 안 변하는) 결과만 한정한다.
        # record_failures/banner_errors/below_threshold 는 "이번 라운드에
        # 아직 안 풀린 문제"를 뜻하는 append-only 로그라 그대로 이어받으면,
        # 이번 라운드에 실제로 해결된 뒤에도 지난 라운드의 stale 항목이 남아
        # 영원히 completed 로 못 올라간다(V1 재검증에서 잡은 회귀) — 그래서
        # 이번 라운드에 남아있는 문제만 반영하도록 새로 채운다(reset).
        report.registered = list(previous.registered)
        report.drafts = list(previous.drafts)
        report.excluded = list(previous.excluded)
        report.record_states = dict(previous.record_states)
        report.counted_profile_urls = set(previous.counted_profile_urls)
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

        # 3차 결함 ⑦ — 제외어는 검색 payload 반영과 별개로 후보 단계에서
        # 최종 강제한다(exclusion 게이트). 형식은 위 디스크립터 빌더가 이미
        # fail-closed 로 검증했다(list[str] 강제).
        exclusions: list[str] = list(jd.get("not_keywords") or [])

        # 2) D6 "3사 동시 착수"(2차 결함 5 → 3차 결함 ⑩ 수정) — 채널별
        # 파이프라인을 스레드(채널당 1)로 "실제 동시" 실행한다. 한 채널의
        # 드라이버 호출이 블록돼도 다른 채널은 시작·진행된다. 공유 상태
        # (개입 모니터·리포트·기록기)는 deps.lock 으로 보호한다.
        runners: list[Any] = [_LinkedInRunner(plan)] + [
            _DescriptorRunner(d) for d in descriptors
        ]

        def _run_units(runner: Any) -> None:
            while True:
                _raise_if_stopped(deps)  # M2 — 새 변형 착수 전 협조적 중단 확인
                unit = runner.next_unit()
                if unit is None:
                    return
                task, payload = unit
                pagination = _run_variant(
                    jd, deps, report, runner.channel, task, payload,
                    previous, exclusions,
                )
                runner.feed(pagination)

        def _run_channel(runner: Any) -> None:
            # V1 독립검증 결함4 — 링크드인 채널 실행 전체를 기기 간 세션 락으로
            # 감싼다. 다른 기기(또는 이 기기의 다른 프로세스)가 이미 보유 중이면
            # LinkedInSessionLockError 로 즉시 실패(E4: 계정당 동시 1기기).
            try:
                if (
                    runner.channel != LINKEDIN_CHANNEL
                    or deps.linkedin_session_lock is None
                ):
                    _run_units(runner)
                    return
                with deps.linkedin_session_lock:
                    _run_units(runner)
            except BaseException:
                # M2 — 한 채널이 죽으면 남은 채널에 협조적 중단을 알린다.
                # (사람 개입/차단도 같은 신호를 쓴다 — 어차피 전 채널이 멈춰야 한다.)
                deps.stop_event.set()
                raise

        with ThreadPoolExecutor(
            max_workers=len(runners), thread_name_prefix="aisearch-channel"
        ) as pool:
            futures = {
                pool.submit(_run_channel, runner): runner.channel for runner in runners
            }
        channel_errors: list[BaseException] = []
        for future, channel in futures.items():
            exc = future.exception()
            if exc is None:
                continue
            channel_errors.append(exc)
            # M2 — "전체 보고": 원인 오류든 그로 인한 협조적 중단이든 채널마다
            # 무슨 일이 있었는지 전부 남긴다(예전에는 첫 예외만 남고 사라졌다).
            report.channel_errors.append(
                {
                    "channel": channel,
                    "type": type(exc).__name__,
                    "error": str(exc) or type(exc).__name__,
                    "cooperative_stop": isinstance(exc, _PipelineStopped),
                }
            )
        if channel_errors:
            # 상태 우선순위: BLOCKED(차단) > WAITING(개입) > 그 외(E8 abort)
            # > _PipelineStopped(파생 신호는 마지막).
            for kind in (_PipelineBlocked, _PipelineWaiting):
                for exc in channel_errors:
                    if isinstance(exc, kind):
                        raise exc
            real = [e for e in channel_errors if not isinstance(e, _PipelineStopped)]
            raise (real or channel_errors)[0]

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
    finally:
        # M3(2026-07-31 리뷰) — 종료 전에 밀린 차단 알림을 다시 보낸다.
        # 끝내 실패한 것은 리포트에 남겨 사람이 알 수 있게 한다(조용한 유실 금지).
        flush = getattr(deps.monitor, "flush_pending_notifications", None)
        if callable(flush):
            try:
                report.notification_failures = list(flush())
            except Exception as flush_error:  # noqa: BLE001 — 알림 실패가 결과를 덮지 않는다
                report.notification_failures = [f"flush 실패: {flush_error}"]
    return report
