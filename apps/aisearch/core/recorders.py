"""AC-5 — ClickUp + Discord 이중 기록 모듈.

goal: docs/engineering/aisearch-fleet-goal-2026-07-28.md §4 AC-5, §5
계약: docs/sot/25-ai-search-execution-process.json clickup_registration_contract 재사용.

L3 외부 쓰기 규율:
- 클라이언트는 전부 주입식(Protocol) — 이 모듈에는 HTTP 호출 코드가 없다.
- 라이브 발신은 코드 기본값 OFF(live=False). live=True 는 owner_signoff=True 와
  함께일 때만 허용되며, 아니면 LiveGateError 로 fail-closed.
- dry-run 에서는 외부 쓰기 0건 — 라이브와 동일 모양의 payload 를 계획으로만 남긴다.
  단 중복확인(read)은 SOT25 write_gate 상 등록 전 필수 회수 단계라 dry-run 에서도 수행한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

# SOT25 clickup_registration_contract / goal 문서 D10·D11 고정값
CLICKUP_LIST_ID = "901818680208"  # FY26AI_Search
DISCORD_RESULT_CHANNEL_ID = "1470955309089554554"  # 서치 결과 전용
DISCORD_MEMBER_CHANNEL_ID = "1512503041448743092"  # 진행상황/에러 (멤버 채널)

SCORE_THRESHOLD = 60  # 60점 이상 후보 확정 시에만 기록

# SOT25 candidate_subtask_required_fields 중 이 모듈 책임 4필드
REQUIRED_FIELDS = ("profile_url", "score", "why_fit", "profile_summary")


class LiveGateError(RuntimeError):
    """live=True 인데 오너 사인오프가 없을 때 — fail-closed."""


class ClickUpClient(Protocol):
    """주입식 ClickUp 인터페이스. 실제 HTTP 어댑터는 별도 파일, 기본 미사용."""

    def find_parent_task(self, list_id: str, position_name: str) -> Optional[str]: ...

    def subtask_exists_with_profile_url(self, list_id: str, profile_url: str) -> bool: ...

    def create_parent_task(self, list_id: str, position_name: str) -> str: ...

    def create_candidate_subtask(
        self, list_id: str, parent_task_id: str, fields: dict[str, Any]
    ) -> str: ...


class DiscordClient(Protocol):
    """주입식 Discord 인터페이스."""

    def post_message(self, channel_id: str, content: str) -> str: ...


@dataclass(frozen=True)
class Candidate:
    profile_url: str
    score: int
    why_fit: str
    profile_summary: str
    match_basis: str = ""  # 매칭 근거
    education: str = ""  # 학력
    career_brief: str = ""  # 경력 브리핑


@dataclass
class RecordResult:
    dry_run: bool
    recorded: bool = False
    duplicate_skipped: bool = False
    error: Optional[str] = None
    parent_task_id: Optional[str] = None
    subtask_id: Optional[str] = None
    planned_actions: list[dict[str, Any]] = field(default_factory=list)


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
    """60점 이상 확정 후보를 ClickUp + Discord 두 곳에 기록한다.

    기본은 dry-run(라이브 발신 OFF). 라이브는 live=True + owner_signoff=True 둘 다 필요.
    """

    def __init__(
        self,
        clickup: ClickUpClient,
        discord: DiscordClient,
        *,
        live: bool = False,
        owner_signoff: bool = False,
    ) -> None:
        if live and not owner_signoff:
            raise LiveGateError(
                "L3 외부 쓰기: live=True 는 owner_signoff=True 없이는 금지 (fail-closed)"
            )
        self._clickup = clickup
        self._discord = discord
        self.live = live

    # ── 내부: dry-run 이면 계획만, 라이브면 실제 클라이언트 호출 ──────────────

    def _do(self, result: RecordResult, kind: str, payload: dict[str, Any], call):
        result.planned_actions.append({"kind": kind, **payload})
        if self.live:
            return call()
        return None

    # ── 공개 API ─────────────────────────────────────────────────────────────

    def record(self, *, position_name: str, candidate: Candidate) -> RecordResult:
        result = RecordResult(dry_run=not self.live)

        # 60점 미만 = 확정 아님 — 아무 것도 하지 않는다
        if candidate.score < SCORE_THRESHOLD:
            return result

        # 필수 4필드 검증 — 미충족이면 등록 없이 멤버 채널 에러 보고 (fail-closed)
        missing = [f for f in REQUIRED_FIELDS if not getattr(candidate, f)]
        if missing:
            result.error = f"필수 필드 누락: {', '.join(missing)}"
            self._post_member(
                result,
                f"[AI Search 에러] {position_name}: {result.error} — 등록하지 않음",
            )
            return result

        # 중복확인(read) — dry-run 에서도 수행 (SOT25 등록 전 필수 회수 단계)
        if self._clickup.subtask_exists_with_profile_url(
            CLICKUP_LIST_ID, candidate.profile_url
        ):
            result.duplicate_skipped = True
            self._post_member(
                result,
                f"[AI Search 진행] {position_name}: 중복 profile_url — 등록 skip "
                f"({candidate.profile_url})",
            )
            return result

        # 포지션 부모 Task — 있으면 재사용, 없으면 생성
        parent_id = self._clickup.find_parent_task(CLICKUP_LIST_ID, position_name)
        if parent_id is None:
            parent_id = self._do(
                result,
                "clickup_create_parent_task",
                {"list_id": CLICKUP_LIST_ID, "name": position_name},
                lambda: self._clickup.create_parent_task(CLICKUP_LIST_ID, position_name),
            )
        result.parent_task_id = parent_id

        # 후보 Subtask — 필수 4필드
        fields = {
            "profile_url": candidate.profile_url,
            "score": candidate.score,
            "why_fit": candidate.why_fit,
            "profile_summary": candidate.profile_summary,
        }
        result.subtask_id = self._do(
            result,
            "clickup_create_candidate_subtask",
            {"list_id": CLICKUP_LIST_ID, "parent_task_id": parent_id, "fields": fields},
            lambda: self._clickup.create_candidate_subtask(
                CLICKUP_LIST_ID, parent_id, fields
            ),
        )

        # Discord 결과 채널 게시
        body = build_result_message(position_name, candidate)
        self._do(
            result,
            "discord_result_post",
            {"channel_id": DISCORD_RESULT_CHANNEL_ID, "content": body},
            lambda: self._discord.post_message(DISCORD_RESULT_CHANNEL_ID, body),
        )

        # Discord 멤버 채널 진행상황 요약
        self._post_member(
            result,
            f"[AI Search 진행] {position_name}: 후보 1건 등록 완료 "
            f"(점수 {candidate.score}, ClickUp {CLICKUP_LIST_ID})",
        )

        result.recorded = True
        return result

    def _post_member(self, result: RecordResult, content: str) -> None:
        self._do(
            result,
            "discord_member_post",
            {"channel_id": DISCORD_MEMBER_CHANNEL_ID, "content": content},
            lambda: self._discord.post_message(DISCORD_MEMBER_CHANNEL_ID, content),
        )
