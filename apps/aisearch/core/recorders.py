"""AC-5/AC-6 — ClickUp + Discord + admin.valuehire.cc 3중 기록 모듈.

goal: docs/engineering/aisearch-fleet-goal-2026-07-28.md §4 AC-5, §5
계약: docs/sot/25-ai-search-execution-process.json clickup_registration_contract 재사용.
AC-6(admin.valuehire.cc 등록)는 별도 goal
(docs/engineering/aisearch-register-api-goal-2026-07-31.md, valuehire_v4
POST /api/aisearch/register)의 클라이언트측 배선이다 — D12 확정(전용 API, 오너
2026-07-31 결정) 후 이 모듈에 추가됐다.

L3 외부 쓰기 규율:
- 클라이언트는 전부 주입식(Protocol) — 이 모듈에는 HTTP 호출 코드가 없다.
- 라이브 발신은 코드 기본값 OFF(live=False). live=True 는 owner_signoff=True 와
  함께일 때만 허용되며, 아니면 LiveGateError 로 fail-closed.
- dry-run 에서는 외부 쓰기 0건 — 라이브와 동일 모양의 payload 를 계획으로만 남긴다.
  단 중복확인(read)은 SOT25 write_gate 상 등록 전 필수 회수 단계라 dry-run 에서도 수행한다.

상태 계약(V1 결함1 수정):
- RecordResult.status ∈ {"dry_run", "recorded", "partial", "failed", "skipped"}.
- dry-run 결과는 절대 "recorded" 로 표시되지 않는다 — 성공적 dry-run 은 "dry_run".
- "partial" = 일부 외부 쓰기 성공 후 중단 — pending_steps 에 미완 단계가 남으며,
  record(..., resume_from=이전결과) 로 미완 단계만 이어서 수행해 완결한다(결함2).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Protocol

# SOT25 clickup_registration_contract / goal 문서 D10·D11 고정값
CLICKUP_LIST_ID = "901818680208"  # FY26AI_Search
DISCORD_RESULT_CHANNEL_ID = "1470955309089554554"  # 서치 결과 전용
DISCORD_MEMBER_CHANNEL_ID = "1512503041448743092"  # 진행상황/에러 (멤버 채널)

SCORE_THRESHOLD = 60  # 60점 이상 후보 확정 시에만 기록

# SOT25 candidate_subtask_required_fields — 원문 그대로 5필드.
# 2026-07-31 전수 리뷰 H1: 예전에는 saved_profile_evidence 가 빠진 4필드였다.
# SOT25 는 profile_save_evidence_required=true 이므로, 프로필 저장 증거가 없는
# 후보는 subtask 를 만들지 않는다(fail-closed).
REQUIRED_FIELDS = (
    "profile_url",
    "score",
    "why_fit",
    "profile_summary",
    "saved_profile_evidence",
)

#: 증거 부재 표기 — humansearch_register.py:345 와 동일 문자열 계약.
EVIDENCE_MISSING = "missing"


def saved_profile_evidence_text(evidence: Any) -> str:
    """프로필 저장 증거를 사람이 읽는 한 줄 영수증으로 만든다.

    계약은 tools/multi_position_sourcing/humansearch_register.py:345
    ``_saved_profile_evidence_text`` 와 **동형**이다(중복 계약 금지 — 같은 뜻,
    같은 모양). manifest 경로와 스크린샷 해시가 **둘 다** 있어야 영수증으로
    인정하고, 하나라도 없으면 "missing" 을 돌려준다. 이 값이 그대로 subtask
    필드로 들어가며, "missing"·빈 문자열은 등록 게이트에서 거부된다.
    """
    if isinstance(evidence, Mapping):
        manifest = str(evidence.get("manifest_path") or "").strip()
        digest = str(evidence.get("screenshot_sha256") or "").strip()
        if manifest and digest:
            return f"manifest: {manifest} | screenshot_sha256: {digest}"
    return EVIDENCE_MISSING


def unknown_name_placeholder(profile_url: str) -> str:
    """이름 미확보 후보의 **후보별로 다른** 정직한 표기(2026-07-31 리뷰 F12).

    예전에는 전부 "이름 미확인" 한 문자열이었다. v4 dedup 이 jd_id 안에서
    이름 기반 canonicalIdentityKey 로 동일인을 합치므로, 같은 포지션의 이름
    미확보 후보가 전부 한 건으로 병합될 수 있었다. profile_url 파생 접미사를
    붙여 후보별로 갈라 놓되, URL 자체를 이름인 척 흘려보내지는 않는다.
    """
    digest = hashlib.sha256(profile_url.strip().encode("utf-8")).hexdigest()
    return f"이름 미확인-{digest[:8]}"

# 결함5: dry-run 에서 부모 Task 가 아직 없을 때 subtask 계획이 참조하는 placeholder.
# None 이 아니라 "생성 예정 부모" 라는 의미를 명시한다. live 경로에서는 절대 쓰이지
# 않으며, live 는 생성된 실제 Task ID 만 사용한다(_run_step 에서 강제).
PARENT_PLACEHOLDER = "<parent-to-be-created>"

# 기록 단계(순서 고정). 부분 실패 시 이 이름들이 pending_steps 로 반환된다.
STEP_CLICKUP_PARENT = "clickup_parent"
STEP_CLICKUP_SUBTASK = "clickup_subtask"
STEP_ADMIN_REGISTER = "admin_register"  # AC-6 — admin.valuehire.cc(v4) 등록
STEP_DISCORD_RESULT = "discord_result"
STEP_DISCORD_MEMBER = "discord_member"
# V1 독립검증 결함6 — admin 등록을 ClickUp보다 먼저 시도한다. 이전 순서(ClickUp
# 먼저)에서는 admin 클라이언트 미구성/실패를 ClickUp에 이미 쓴 뒤에야 발견해,
# ClickUp에는 있는데 admin엔 없는 반쪽 상태가 롤백 없이 남았다. admin을 먼저
# 두면 그 misconfiguration/실패가 다른 어떤 외부 쓰기보다도 먼저 표면화된다.
ALL_STEPS = (
    STEP_ADMIN_REGISTER,
    STEP_CLICKUP_PARENT,
    STEP_CLICKUP_SUBTASK,
    STEP_DISCORD_RESULT,
    STEP_DISCORD_MEMBER,
)

STATUS_DRY_RUN = "dry_run"
STATUS_RECORDED = "recorded"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"


class LiveGateError(RuntimeError):
    """live=True 인데 오너 사인오프가 없을 때 — fail-closed."""


def subtask_idempotency_key(profile_url: str) -> str:
    """결함3: profile_url 기반 결정론적 외부 멱등키.

    중복확인(read)→생성(write)은 로컬에서 원자적으로 묶을 수 없다(TOCTOU).
    그래서 생성 요청 자체에 이 키를 실어 보내는 계약으로 바꾼다 — 같은
    profile_url 은 언제 몇 번 재시도해도 같은 키가 나오므로, 중복 생성의
    원자적 차단은 이 키를 받은 원격(ClickUp 어댑터/서버)이 보장한다.
    원문 URL 은 노출하지 않고 sha256 파생값만 쓴다.
    """
    digest = hashlib.sha256(profile_url.strip().encode("utf-8")).hexdigest()
    return f"vh-ac5-{digest[:32]}"


class ClickUpClient(Protocol):
    """주입식 ClickUp 인터페이스. 실제 HTTP 어댑터는 별도 파일, 기본 미사용.

    create_candidate_subtask 의 fields 에는 idempotency_key 가 포함된다 —
    어댑터는 이 키를 원격 생성 요청에 실어 중복 생성을 원자적으로 막아야 한다.
    """

    def find_parent_task(self, list_id: str, position_name: str) -> Optional[str]: ...

    def subtask_exists_with_profile_url(self, list_id: str, profile_url: str) -> bool: ...

    def create_parent_task(self, list_id: str, position_name: str) -> str: ...

    def create_candidate_subtask(
        self, list_id: str, parent_task_id: str, fields: dict[str, Any]
    ) -> str: ...


class DiscordClient(Protocol):
    """주입식 Discord 인터페이스."""

    def post_message(self, channel_id: str, content: str) -> str: ...


class AdminApiClient(Protocol):
    """주입식 admin.valuehire.cc 인터페이스.

    실제 HTTP 어댑터는 admin_api_client.py(POST /api/aisearch/register,
    x-internal-key 인증) — 이 모듈에는 HTTP 호출 코드가 없다.
    """

    def register_candidate(self, payload: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class Candidate:
    profile_url: str
    score: int
    why_fit: str
    profile_summary: str
    saved_profile_evidence: str = ""  # SOT25 5번째 필수 필드(프로필 저장 증거 영수증)
    match_basis: str = ""  # 매칭 근거
    education: str = ""  # 학력
    career_brief: str = ""  # 경력 브리핑
    name: str = ""  # 후보자 이름(AC-6 admin 등록 필수 필드 — 미확보 시 profile_url로 대체)


@dataclass
class RecordResult:
    dry_run: bool
    status: str = STATUS_SKIPPED
    duplicate_skipped: bool = False
    error: Optional[str] = None
    parent_task_id: Optional[str] = None
    subtask_id: Optional[str] = None
    planned_actions: list[dict[str, Any]] = field(default_factory=list)
    pending_steps: list[str] = field(default_factory=list)

    @property
    def recorded(self) -> bool:
        """결함1: dry-run 은 절대 recorded 로 표시되지 않는다 — status 파생값."""
        return self.status == STATUS_RECORDED


def build_result_message(position_name: str, c: Candidate) -> str:
    """결과 채널 게시문 — {매칭점수, 프로필URL, 적합/부적합 사유, 매칭 근거, 학력, 경력 브리핑}."""
    return "\n".join(
        [
            f"[AI Search 결과] {position_name}",
            f"매칭점수: {c.score}",
            f"프로필URL: {c.profile_url}",
            f"적합/부적합 사유: {c.why_fit}",
            f"매칭 근거: {c.match_basis}",
            f"학력: {c.education}",
            f"경력 브리핑: {c.career_brief}",
        ]
    )


class DualRecorder:
    """60점 이상 확정 후보를 ClickUp + Discord + admin.valuehire.cc 세 곳에 기록한다.

    이름은 초기 설계(ClickUp+Discord 이중 기록) 그대로 유지한다 — AC-6(admin 등록)
    추가로 실제로는 3중 기록이지만, 6개 파일이 이 이름을 참조하고 있어 개명은
    이번 변경 범위 밖(별도 리팩터로 분리).

    기본은 dry-run(라이브 발신 OFF). 라이브는 live=True + owner_signoff=True 둘 다 필요.
    부분 실패 시 status="partial" + pending_steps 로 반환하며, 같은 인자에
    resume_from=이전결과 를 넘기면 미완 단계만 이어서 수행한다.

    V1 독립검증 결함9(공식 확인) — dry-run의 계약은 **"외부 쓰기 0건"**이지
    "외부 호출 0건"이 아니다. ClickUp 중복확인(subtask_exists_with_profile_url)과
    부모 Task 조회(find_parent_task)는 SOT25가 등록 전 필수 회수 단계로 못박아
    dry-run에서도 실행된다(실제 ClickUp 클라이언트를 주입하면 진짜 읽기 호출이
    나간다) — 오직 admin.register_candidate 처럼 **쓰기**만 self.live 로 게이트된다.
    "dry-run = 아무 네트워크도 안 나간다"고 가정하고 실제 클라이언트를 주입하면
    안 된다 — 진짜 네트워크 0건이 필요하면 항상 페이크/None 클라이언트를 넣는다.
    """

    def __init__(
        self,
        clickup: ClickUpClient,
        discord: DiscordClient,
        admin: Optional[AdminApiClient] = None,
        *,
        live: bool = False,
        owner_signoff: bool = False,
    ) -> None:
        if live and not owner_signoff:
            raise LiveGateError(
                "L3 외부 쓰기: live=True 는 owner_signoff=True 없이는 금지 (fail-closed)"
            )
        # 2026-07-31 리뷰 F5 — admin 은 ALL_STEPS 의 **첫 단계**다. live 인데
        # 미주입이면 첫 단계가 AttributeError 로 죽어 ClickUp 등록도 Discord
        # 보고도 한 건도 나가지 않는다(조용한 전면 실패). 그래서 실행 시점이
        # 아니라 **조립 시점에** 거부한다 — 실패를 늦게 발견할수록 손해가 크다.
        # dry-run 은 어떤 단계도 실제 호출하지 않으므로 None 을 허용한다.
        if live and admin is None:
            raise LiveGateError(
                "L3 외부 쓰기: live=True 는 admin 클라이언트 주입 없이는 금지 "
                "(admin_register 가 첫 단계 — 미주입 시 ClickUp·Discord 보고까지 "
                "전부 유실된다, fail-closed)"
            )
        self._clickup = clickup
        self._discord = discord
        self._admin = admin
        self.live = live

    # ── 내부: dry-run 이면 계획만, 라이브면 실제 클라이언트 호출 ──────────────

    def _do(self, result: RecordResult, kind: str, payload: dict[str, Any], call):
        result.planned_actions.append({"kind": kind, **payload})
        if self.live:
            return call()
        return None

    # ── 공개 API ─────────────────────────────────────────────────────────────

    def record(
        self,
        *,
        position_name: str,
        candidate: Candidate,
        channel: str = "",
        resume_from: Optional[RecordResult] = None,
    ) -> RecordResult:
        result = RecordResult(dry_run=not self.live)

        # 결함4: 점수 계약 — int(불리언 제외) + 0~100 범위. 위반이면 fail-closed.
        if (
            isinstance(candidate.score, bool)
            or not isinstance(candidate.score, int)
            or not (0 <= candidate.score <= 100)
        ):
            result.status = STATUS_FAILED
            result.error = (
                f"score 계약 위반: 정수 0~100 필요, 받은 값 {candidate.score!r}"
            )
            self._post_member(
                result,
                f"[AI Search 에러] {position_name}: {result.error} — 등록하지 않음",
            )
            return result

        # 60점 미만 = 확정 아님 — 아무 것도 하지 않는다
        if candidate.score < SCORE_THRESHOLD:
            result.status = STATUS_SKIPPED
            return result

        # SOT25 필수 5필드 검증 — 미충족이면 등록 없이 멤버 채널 에러 보고 (fail-closed)
        missing = [f for f in REQUIRED_FIELDS if not getattr(candidate, f)]
        if missing:
            result.status = STATUS_FAILED
            result.error = f"필수 필드 누락: {', '.join(missing)}"
            self._post_member(
                result,
                f"[AI Search 에러] {position_name}: {result.error} — 등록하지 않음",
            )
            return result

        # V1 독립검증 결함8 — truthy 체크만으로는 "javascript:void(0)" 같은 가짜
        # URL이나 공백뿐인 텍스트를 걸러내지 못해, ClickUp까지 쓴 뒤에야 admin
        # 원격 API(400)에서 뒤늦게 걸러졌다. 여기서 형식까지 먼저 검증한다 —
        # ClickUp을 포함한 모든 외부 쓰기보다 먼저(위 순서 변경과 함께 결함6도 보강).
        if not re.match(r"^https?://", candidate.profile_url.strip(), re.IGNORECASE):
            result.status = STATUS_FAILED
            result.error = f"profile_url 형식 위반(http/https 아님): {candidate.profile_url!r}"
            self._post_member(
                result,
                f"[AI Search 에러] {position_name}: {result.error} — 등록하지 않음",
            )
            return result
        # H1 게이트 — SOT25 profile_save_evidence_required. 저장 증거가 "missing"
        # 이거나 공백뿐이면 어떤 외부 쓰기(admin/ClickUp/Discord)보다도 먼저 거부한다:
        # "프로필 저장 증거 확인 후에만 subtask 생성"이 계약이다.
        evidence = candidate.saved_profile_evidence.strip()
        if not evidence or evidence == EVIDENCE_MISSING:
            result.status = STATUS_FAILED
            result.error = (
                "saved_profile_evidence 없음 — 프로필 저장 증거 없이는 등록하지 "
                f"않는다(SOT25 fail-closed): {candidate.saved_profile_evidence!r}"
            )
            self._post_member(
                result,
                f"[AI Search 에러] {position_name}: {result.error} — 등록하지 않음",
            )
            return result

        blank_text_fields = [
            f for f in ("why_fit", "profile_summary") if not getattr(candidate, f).strip()
        ]
        if blank_text_fields:
            result.status = STATUS_FAILED
            result.error = f"공백뿐인 필드: {', '.join(blank_text_fields)}"
            self._post_member(
                result,
                f"[AI Search 에러] {position_name}: {result.error} — 등록하지 않음",
            )
            return result

        if resume_from is not None and resume_from.pending_steps:
            # 결함2: 재개 경로 — 이전 실행에서 이미 쓴 단계는 건너뛰고 미완 단계만
            # 수행한다. 중복확인은 재수행하지 않는다: 1차 실행이 만든 subtask 가
            # 중복으로 판정되어 Discord 게시가 영구 누락되는 결함의 원인이었다.
            steps = list(resume_from.pending_steps)
            result.parent_task_id = resume_from.parent_task_id
            result.subtask_id = resume_from.subtask_id
        else:
            # 중복확인(read) — dry-run 에서도 수행 (SOT25 등록 전 필수 회수 단계).
            # 주의: 이 확인은 원자성 보장이 아니라 조기 skip 최적화다 — 확인과 생성
            # 사이 경합의 원자적 차단은 subtask_idempotency_key 가 담당한다(결함3).
            if self._clickup.subtask_exists_with_profile_url(
                CLICKUP_LIST_ID, candidate.profile_url
            ):
                result.duplicate_skipped = True
                result.status = STATUS_SKIPPED
                self._post_member(
                    result,
                    f"[AI Search 진행] {position_name}: 중복 profile_url — 등록 skip "
                    f"({candidate.profile_url})",
                )
                return result
            steps = list(ALL_STEPS)

        # 결함2: 단계별 실행 — 실패 시 미완 단계 목록과 함께 partial/failed 반환.
        completed: list[str] = []
        for i, step in enumerate(steps):
            try:
                self._run_step(step, result, position_name, candidate, channel)
            except Exception as exc:  # noqa: BLE001 — 외부 쓰기 실패는 종류 불문 수거
                result.error = f"{step} 실패: {exc}"
                result.pending_steps = list(steps[i:])
                already_wrote = bool(completed) or resume_from is not None
                result.status = STATUS_PARTIAL if already_wrote else STATUS_FAILED
                return result
            completed.append(step)

        result.pending_steps = []
        result.status = STATUS_DRY_RUN if not self.live else STATUS_RECORDED
        return result

    # ── 단계 실행 ────────────────────────────────────────────────────────────

    def _run_step(
        self,
        step: str,
        result: RecordResult,
        position_name: str,
        candidate: Candidate,
        channel: str = "",
    ) -> None:
        if step == STEP_CLICKUP_PARENT:
            # 포지션 부모 Task — 있으면 재사용, 없으면 생성
            parent_id = self._clickup.find_parent_task(CLICKUP_LIST_ID, position_name)
            if parent_id is None:
                parent_id = self._do(
                    result,
                    "clickup_create_parent_task",
                    {"list_id": CLICKUP_LIST_ID, "name": position_name},
                    lambda: self._clickup.create_parent_task(
                        CLICKUP_LIST_ID, position_name
                    ),
                )
            result.parent_task_id = parent_id

        elif step == STEP_CLICKUP_SUBTASK:
            # 후보 Subtask — SOT25 필수 5필드 + 멱등키(결함3)
            fields = {
                "profile_url": candidate.profile_url,
                "score": candidate.score,
                "why_fit": candidate.why_fit,
                "profile_summary": candidate.profile_summary,
                # H1 — SOT25 5번째 필수 필드. 여기 도달했다는 것은 위 게이트에서
                # 증거 존재가 이미 확인됐다는 뜻이다(증거 없으면 진입 불가).
                "saved_profile_evidence": candidate.saved_profile_evidence,
                "idempotency_key": subtask_idempotency_key(candidate.profile_url),
            }
            if self.live:
                # 결함5: live 경로는 생성된 실제 부모 Task ID 만 사용 — 없으면 중단
                if result.parent_task_id is None:
                    raise RuntimeError(
                        "live 경로에서 부모 Task ID 미확보 — subtask 생성 불가"
                    )
                parent_ref = result.parent_task_id
            else:
                # 결함5: dry-run 계획은 None 대신 placeholder 로 '생성 예정 부모' 명시
                parent_ref = (
                    result.parent_task_id
                    if result.parent_task_id is not None
                    else PARENT_PLACEHOLDER
                )
            result.subtask_id = self._do(
                result,
                "clickup_create_candidate_subtask",
                {
                    "list_id": CLICKUP_LIST_ID,
                    "parent_task_id": parent_ref,
                    "fields": fields,
                },
                lambda: self._clickup.create_candidate_subtask(
                    CLICKUP_LIST_ID, result.parent_task_id, fields
                ),
            )

        elif step == STEP_ADMIN_REGISTER:
            # AC-6 — admin.valuehire.cc(v4) POST /api/aisearch/register 등록.
            # 그 API 계약(docs/engineering/aisearch-register-api-goal-2026-07-31.md):
            # name 필수(v4는 빈 name 을 400 거부) — V1 독립검증 결함7: 예전에는
            # 이름 없으면 profile_url 문자열을 그대로 이름란에 흘려보냈다(프로덕션
            # 데이터 오염). URL을 이름인 척 보내지 않고 정직한 플레이스홀더를 쓴다.
            # jd_id — v4 쪽 dedup(같은 jd_id 안에서 canonicalIdentityKey 비교)이
            # 이 값을 기준으로 삼는다. aisearch의 JD 계약에는 v4 UUID가 없으므로,
            # 같은 포지션이면 항상 같은 값이 나오는 position_name 을 그대로
            # jd_id 로 쓴다(ClickUp 부모 Task 조회도 이미 position_name 을
            # 자연키로 쓰고 있어 일관됨). 예전에는 jd_id 자체가 누락돼 v4 dedup이
            # 항상 스킵되고 URL 변형만 달라도 중복 등록됐다.
            payload = {
                "name": candidate.name or unknown_name_placeholder(candidate.profile_url),
                "profile_url": candidate.profile_url,
                "match_score": candidate.score,
                "why_fit": candidate.why_fit,
                "profile_summary": candidate.profile_summary,
                "channel": channel or "unknown",
                "jd_id": position_name,
                "jd_title": position_name,
            }
            self._do(
                result,
                "admin_register_candidate",
                payload,
                lambda: self._admin.register_candidate(payload),
            )

        elif step == STEP_DISCORD_RESULT:
            body = build_result_message(position_name, candidate)
            self._do(
                result,
                "discord_result_post",
                {"channel_id": DISCORD_RESULT_CHANNEL_ID, "content": body},
                lambda: self._discord.post_message(DISCORD_RESULT_CHANNEL_ID, body),
            )

        elif step == STEP_DISCORD_MEMBER:
            self._post_member(
                result,
                f"[AI Search 진행] {position_name}: 후보 1건 등록 완료 "
                f"(점수 {candidate.score}, ClickUp {CLICKUP_LIST_ID})",
            )

        else:  # pragma: no cover — 계약 밖 단계명은 프로그래밍 오류
            raise ValueError(f"알 수 없는 기록 단계: {step}")

    def _post_member(self, result: RecordResult, content: str) -> None:
        self._do(
            result,
            "discord_member_post",
            {"channel_id": DISCORD_MEMBER_CHANNEL_ID, "content": content},
            lambda: self._discord.post_message(DISCORD_MEMBER_CHANNEL_ID, content),
        )
