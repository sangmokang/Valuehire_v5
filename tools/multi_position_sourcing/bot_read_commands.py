"""bot_read_commands.py — 조회형 명령 → 봇 API 호출 스펙 매퍼 (AC-6, 2026-07-22).

goal §6.2: 읽기 명령은 AC-1.5 의 봇 API 층(/api/bot/*) 위에서만 동작한다. 이 모듈은
명령+인자를 HTTP 요청 스펙(ReadRequest)으로 바꾸는 순수 함수다 — 실제 네트워크 호출은
호출부가 봇 토큰으로 수행한다(여기서는 부작용 0).

안전:
- 읽기 전용(method 항상 GET). 쓰기 명령은 이 매퍼가 다루지 않는다(None).
- 인자는 엄격 검증(job id 양의 정수, week ISO). 잘못되면 None(추측·정규화 금지, fail-closed).
- E23: /interviews·/cases 는 살아있는 unified_candidate_history_view 를 쓰는 candidates
  라우트로 사상(고장난 candidate-timeline 대체).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping, Optional

READ_COMMANDS: frozenset[str] = frozenset({
    "kpi", "interviews", "cases", "priority", "job", "jobs",
})

_JOB_ID_RE = re.compile(r"^[1-9][0-9]{0,17}$")   # 양의 정수(선행 0·부호·공백 불가)
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_DISCORD_LIMIT = 2000


@dataclass(frozen=True)
class ReadRequest:
    method: str
    path: str
    params: dict[str, str] = field(default_factory=dict)


def map_read_command(command: str, args: Mapping[str, str]) -> Optional[ReadRequest]:
    """읽기 명령 1건을 ReadRequest 로. 알 수 없는 명령/무효 인자는 None."""
    cmd = (command or "").strip().lower()
    args = args or {}
    if cmd == "kpi":
        params: dict[str, str] = {}
        week = str(args.get("week", "")).strip()
        if week:
            if not _ISO_DATE_RE.match(week):
                return None
            params["week"] = week
        return ReadRequest("GET", "/api/bot/kpi", params)
    if cmd == "interviews":
        return ReadRequest("GET", "/api/bot/candidates", {"view": "interviews"})
    if cmd == "cases":
        return ReadRequest("GET", "/api/bot/candidates", {"view": "cases"})
    if cmd == "priority":
        return ReadRequest("GET", "/api/bot/positions", {})
    if cmd == "jobs":
        return ReadRequest("GET", "/api/bot/jobs", {})
    if cmd == "job":
        job_id = str(args.get("id", "")).strip()
        if not _JOB_ID_RE.match(job_id):
            return None
        return ReadRequest("GET", f"/api/bot/jobs/{job_id}", {})
    return None


def truncate_for_discord(text: str, *, link: str, limit: int = _DISCORD_LIMIT) -> tuple[str, bool]:
    """E10 결정 ㉮ — 2000자 초과 시 앞부분만 남기고 웹 링크를 붙인다.

    반환: (표시 텍스트(<=limit), 잘렸는지 여부). 링크 꼬리표 길이를 확보한 뒤 자른다.
    """
    body = text or ""
    if len(body) <= limit:
        return body, False
    tail = f"\n… 전체 보기: {link}"
    keep = max(0, limit - len(tail))
    return (body[:keep] + tail)[:limit], True
