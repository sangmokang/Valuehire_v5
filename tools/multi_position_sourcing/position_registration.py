from __future__ import annotations

from typing import Callable, Optional, Protocol, Sequence

from tools.multi_position_sourcing.posting_extractor import extract_posting
from tools.multi_position_sourcing.posting_models import (
    ExistingPositionTask,
    ExtractedPosting,
    FetchResult,
    PostingRecognition,
    RegistrationOutcome,
    VisionAnalysis,
)
from tools.multi_position_sourcing.position_dedup import find_duplicate_position
from tools.multi_position_sourcing.posting_recognizer import recognize_posting
from tools.multi_position_sourcing.request_parser import (
    PositionRegistrationRequestParseResult,
)

# Type aliases for the injected runtime callables (production wires real adapters;
# tests inject fakes). These are intentionally narrow side-effect boundaries.
HttpFetch = Callable[[str], FetchResult]
RenderFetch = Callable[[str], FetchResult]
ImageDownloader = Callable[[tuple[str, ...], str], tuple[str, ...]]
VisionAnalyzer = Callable[[tuple[str, ...]], VisionAnalysis]
ClickUpSearch = Callable[[PostingRecognition], Sequence[ExistingPositionTask]]
ClickUpCreateComment = Callable[[str, str], str]


class ClickUpCreateTask(Protocol):
    """포지션 태스크 생성 어댑터 계약.

    목적지 ``list_id`` 를 선택 인자로 받는다(기본 None → 종전 2-인자 호출과 동일).
    PC-A0: 계약만 확장(순수 seam). 실제 목적지 전달·단언은 PC-A1 이 수행한다.
    list_id 를 넘기지 않는 기존 2-인자 어댑터도 그대로 호환된다(호출부가 None 또는
    빈 문자열이면 3번째 인자를 붙이지 않는다).
    """

    def __call__(
        self, title: str, body: str, list_id: str | None = None, /
    ) -> tuple[str, str]:
        ...


# 포지션 인입 기본 목적지 — 사장님 지정 FY26ClientsPosition ClickUp 리스트(단일출처·SOT5).
# 출처: docs/search-access.md:425, .claude/skills/url/SKILL.md:59
#       (https://app.clickup.com/9018789656/v/li/901814621569).
# 라이브 경로에서 clickup_list_id 로 주입해 create 목적지로 쓴다(PC-A1). 실제 ClickUp 쓰기
# 어댑터는 범위 밖(SOT5 신규 writer 금지·SOT3 발송 아님) — 소비자는 통합테스트 + PC-A3
# 디스패처(예정, seam).
FY26_CLIENTS_POSITION_LIST_ID: str = "901814621569"


def build_task_title(recognition: PostingRecognition) -> str:
    """Return the ClickUp task title ``"{company} - {role}"``.

    Falls back gracefully when a part is missing so a title is always produced.
    """
    company = (recognition.company or "").strip()
    role = (recognition.role or "").strip()
    if company and role:
        return f"{company} - {role}"
    if company:
        return company
    if role:
        return role
    return "포지션"


def build_registration_body(recognition: PostingRecognition) -> str:
    """Build a ClickUp task/comment body from a recognized posting.

    Includes the JD summary, the original source URL, and the extraction/image
    evidence paths. NEVER emits secret values (tokens are not referenced here).
    """
    lines: list[str] = []
    lines.append(f"회사: {(recognition.company or '').strip() or '(미상)'}")
    lines.append(f"포지션: {(recognition.role or '').strip() or '(미상)'}")
    lines.append(f"인식 방식: {recognition.recognition_mode}")
    lines.append(f"신뢰도: {recognition.confidence:.2f}")

    jd = (recognition.jd_text or "").strip()
    if jd:
        lines.append("")
        lines.append("JD 요약:")
        lines.append(jd)

    lines.append("")
    lines.append(f"원본 URL: {(recognition.source_url or '').strip() or '(없음)'}")

    if recognition.image_evidence_paths:
        lines.append("")
        lines.append("이미지 근거:")
        for path in recognition.image_evidence_paths:
            lines.append(f"- {path}")

    return "\n".join(lines)


def _skipped(reason: str, *, dry_run: bool, recognition: Optional[PostingRecognition] = None) -> RegistrationOutcome:
    """Build a fail-closed skipped outcome (no external posting, no secrets)."""
    return RegistrationOutcome(
        status="skipped",
        is_new_task=False,
        reason=reason,
        recognition_mode=recognition.recognition_mode if recognition else "none",
        confidence=recognition.confidence if recognition else 0.0,
        external_posting_sent=False,
        secret_emitted=False,
        dry_run=dry_run,
    )


_JD_HEADINGS: tuple[str, ...] = (
    "회사소개",
    "주요업무",
    "담당업무",
    "자격요건",
    "우대사항",
    "복지",
    "혜택",
    "채용",
    "포지션",
)


def _company_role_from_pasted_jd(text: str) -> tuple[str, str]:
    """Best-effort company/role from a pasted JD body using stdlib line heuristics.

    - company: the first content line directly under a "회사소개" heading.
    - role: the first non-heading, non-bullet content line (typically the title).
    This is intentionally conservative; when nothing usable is found it returns
    empty strings and the handler falls back to fail-closed recognition.
    """
    lines = [ln.strip() for ln in (text or "").splitlines()]
    lines = [ln for ln in lines if ln]

    def _is_heading(line: str) -> bool:
        compact = line.replace(" ", "")
        return any(compact == h or compact.startswith(h) for h in _JD_HEADINGS) and len(compact) <= 12

    company = ""
    role = ""

    for index, line in enumerate(lines):
        compact = line.replace(" ", "")
        if compact.startswith("회사소개") and index + 1 < len(lines):
            nxt = lines[index + 1]
            if not _is_heading(nxt) and not nxt.startswith("-"):
                # Trim a trailing Korean topic marker like "는/은/이/가" + remainder.
                company = nxt.split("는")[0].split("은")[0].split("(")[0].strip()
            break

    for line in lines:
        if _is_heading(line) or line.startswith("-") or line.startswith("·"):
            continue
        role = line
        break

    return company, role


def _build_extracted(
    parse_result: PositionRegistrationRequestParseResult,
    *,
    http_fetch: Optional[HttpFetch],
    render_fetch: Optional[RenderFetch],
    image_downloader: Optional[ImageDownloader],
    artifacts_dir: str,
) -> ExtractedPosting:
    """Produce an ExtractedPosting from the parse result.

    - URL inputs (wanted_url/clickup_url) -> fetch+parse via extract_posting.
    - pasted_jd -> build directly from parse_result.text (no network).
    Fail-closed ExtractedPosting otherwise.
    """
    url = (parse_result.url or "").strip()
    if url:
        if http_fetch is None:
            return ExtractedPosting(
                source_url=url,
                ok=False,
                reason="no http_fetch adapter provided",
            )
        return extract_posting(
            url,
            http_fetch=http_fetch,
            render_fetch=render_fetch,
            image_downloader=image_downloader,
            artifacts_dir=artifacts_dir,
        )

    if parse_result.input_kind == "pasted_jd":
        jd_text = (parse_result.text or "").strip()
        company, role = _company_role_from_pasted_jd(jd_text)
        return ExtractedPosting(
            source_url="",
            ok=bool(jd_text),
            company=company,
            role=role,
            jd_text=jd_text,
            fetch_method="none",
            reason="" if jd_text else "empty pasted JD",
        )

    # plain_position or anything without a URL or JD body: insufficient input.
    return ExtractedPosting(
        source_url="",
        ok=False,
        reason="insufficient input: no URL or JD body to extract",
    )


def run_position_registration(
    parse_result: PositionRegistrationRequestParseResult,
    *,
    http_fetch: Optional[HttpFetch] = None,
    render_fetch: Optional[RenderFetch] = None,
    image_downloader: Optional[ImageDownloader] = None,
    vision_analyzer: Optional[VisionAnalyzer] = None,
    clickup_search: Optional[ClickUpSearch] = None,
    clickup_create_task: Optional[ClickUpCreateTask] = None,
    clickup_create_comment: Optional[ClickUpCreateComment] = None,
    clickup_list_id: Optional[str] = None,
    artifacts_dir: str = "artifacts/position_registration",
    confidence_threshold: float = 0.55,
    dry_run: bool = True,
) -> RegistrationOutcome:
    """Wire extract -> recognize -> dedup -> register for Valuehire position intake.

    Fail-closed at every gate. There is NO code path that posts to an external
    portal or sends outreach/email; every outcome reports external_posting_sent
    and secret_emitted as False.
    """
    # Gate 0: only act on routed registration requests.
    if not parse_result.should_route_to_registration:
        return _skipped("not a position registration request", dry_run=dry_run)

    # Build the ExtractedPosting (fetch+parse for URLs, direct for pasted JD).
    extracted = _build_extracted(
        parse_result,
        http_fetch=http_fetch,
        render_fetch=render_fetch,
        image_downloader=image_downloader,
        artifacts_dir=artifacts_dir,
    )

    # Gate 1: extraction must succeed.
    if not extracted.ok:
        return _skipped(extracted.reason or "원문 확인 요청", dry_run=dry_run)

    # Recognize whether this is a job posting (text -> vision -> none).
    recognition = recognize_posting(
        extracted,
        vision_analyzer=vision_analyzer,
        confidence_threshold=confidence_threshold,
    )

    # Gate 2: must be a posting with sufficient confidence.
    if not recognition.is_job_posting or recognition.confidence < confidence_threshold:
        return _skipped("원문 확인 요청", dry_run=dry_run, recognition=recognition)

    # Duplicate detection against existing ClickUp tasks.
    existing: Sequence[ExistingPositionTask] = ()
    if clickup_search is not None:
        existing = clickup_search(recognition)
    duplicate = find_duplicate_position(recognition, existing)

    body = build_registration_body(recognition)

    if duplicate is not None:
        # Link a comment to the existing task instead of creating a new one.
        comment_id = ""
        if not dry_run and clickup_create_comment is not None:
            comment_id = clickup_create_comment(duplicate.task_id, body)
        return RegistrationOutcome(
            status="linked",
            is_new_task=False,
            reason="duplicate position; linked evidence comment"
            if not dry_run
            else "duplicate position; comment planned (dry-run)",
            task_id=duplicate.task_id,
            task_url=duplicate.task_url,
            comment_id=comment_id,
            recognition_mode=recognition.recognition_mode,
            confidence=recognition.confidence,
            external_posting_sent=False,
            secret_emitted=False,
            dry_run=dry_run,
        )

    # No duplicate: create a new task (or plan it in dry-run).
    title = build_task_title(recognition)
    task_id = ""
    task_url = ""
    if not dry_run and clickup_create_task is not None:
        # 목적지 list_id 가 실제로 주어지면 어댑터까지 전달(PC-A1 단언 seam). None 또는
        # 빈 문자열은 '목적지 없음'으로 보고 종전 2-인자 호출 그대로 — 빈 문자열을 3번째
        # 인자로 흘려 기존 2-인자 어댑터를 깨는 footgun 을 막는다(codex V1 caveat). SOT5 계약 확장.
        if clickup_list_id:
            task_id, task_url = clickup_create_task(title, body, clickup_list_id)
        else:
            task_id, task_url = clickup_create_task(title, body)
    return RegistrationOutcome(
        status="created",
        is_new_task=True,
        reason="new position task created"
        if not dry_run
        else "new position task planned (dry-run)",
        task_id=task_id,
        task_url=task_url,
        recognition_mode=recognition.recognition_mode,
        confidence=recognition.confidence,
        external_posting_sent=False,
        secret_emitted=False,
        dry_run=dry_run,
    )
