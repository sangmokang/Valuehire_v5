"""fleet-* 명령 인자 파서 — 단일 출처 (AC-1, 2026-07-22 hermes_fleet_bridge 에서 이사).

배경(goal: docs/prompts/discord-single-bot-console-goal-2026-07-22.md §10 D5):
``direct_receiver``(단일 봇 경로)가 헤르메스 이름이 붙은 모듈(hermes_fleet_bridge)을
import 하고 있어, 헤르메스 폐기(AC-8) 때 봇이 같이 죽는 배선이었다. 파싱 계약을
이 중립 모듈로 옮기고, hermes_fleet_bridge 는 AC-8 전까지 여기서 re-export 만 한다
(옛 이름 ``parse_hermes_fleet_args``/``HermesFleetBridgeError`` 와 동일 객체 — 드리프트 0).

파싱 규칙 자체는 이사 전과 동일(행동 변경 0) — 모르는 명령/필드는 조용히 무시하지
않고 거부(fail-closed), fleet-run 만 맨 토큰(URL/스킬/머신) 자동 인식.
"""

from __future__ import annotations

import base64
import binascii
import re
import shlex
import urllib.parse
from typing import Any

from .fleet_dispatch import FLEET_COMMANDS
from .job_queue import FLEET_MACHINES, FLEET_SKILLS

FLEET_ARG_COMMANDS: tuple[str, ...] = FLEET_COMMANDS

# fleet-run 전용 완화 규칙(2026-07-13 사장님 요청) — "/fleet-run <url>" 만 줘도 동작하게.
_FLEET_RUN_DEFAULT_SKILL = "aisearch"

_MACHINE_ALIASES: dict[str, str] = {
    "win": "winpc",
    "windows": "winpc",
    "윈도우": "winpc",
    "윈도우pc": "winpc",
    "맥미니": "macmini",
    "mini": "macmini",
    "맥북": "macbook",
}
_SEARCH_HOST_MARKERS: tuple[str, ...] = (
    "linkedin.com", "saramin.co.kr", "jobkorea.co.kr",
)

_ALLOWED_FIELDS: dict[str, frozenset[str]] = {
    "fleet-run": frozenset({
        "skill", "url", "machine", "channels", "idempotency", "followup", "agent", "filters64",
    }),
    "fleet-status": frozenset(),
    "fleet-resume": frozenset({"job"}),
    "fleet-cancel": frozenset({"job"}),
}


class FleetArgsError(ValueError):
    """입력이 계약을 벗어남(fail-closed) — 명령/필드/신원 검증 실패."""


# m3 — raw_args 길이 상한(문자). filters64(6,000자)+URL 등 정상 입력을 넉넉히 덮되
# 비정상적으로 긴 입력은 거부한다(Codex V2 지적).
_MAX_RAW_ARGS_LEN = 8000

# M3 — "명시적으로 빈 값" vs "필드 부재"를 구분하는 센티넬. options.pop 이 이 값을
# 돌려주면 필드가 아예 없었던 것이고, "" 를 돌려주면 사용자가 빈 값을 명시한 것이다.
_MISSING = object()


def _classify_bare_fleet_run_token(token: str) -> tuple[str, str] | None:
    """fleet-run 전용: ``key:value`` 가 아닌 맨 토큰이 url/skill/machine 중 뭔지 판정.

    모호하면(아무 것에도 확실히 안 맞으면) None — 추측하지 않고 호출부가 거부하게 한다.
    URL 은 소문자 스킴(``http://``/``https://``)만 인정.
    """
    if token.startswith("http://") or token.startswith("https://"):
        return ("url", token)
    if token in FLEET_SKILLS:
        return ("skill", token)
    if token in FLEET_MACHINES:
        return ("machine", token)
    if token.lower() in _MACHINE_ALIASES:
        return ("machine", _MACHINE_ALIASES[token.lower()])
    return None


def _set_option_once(options: dict[str, str], field: str, value: str, command: str) -> None:
    if field in options:
        # 같은 필드 중복 지정은 조용한 덮어쓰기가 아니라 명시 거부(fail-closed).
        raise FleetArgsError(f"필드 중복 지정: {field!r}")
    options[field] = value


def _is_search_url(url: str) -> bool:
    """호스트명 기준으로만 판정(2026-07-14 Codex Rescue 결함 수정 그대로 이사)."""
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return any(host == marker or host.endswith("." + marker) for marker in _SEARCH_HOST_MARKERS)


def _default_skill_for_urls(urls: Any) -> str:
    """URL 모양만으로 fleet-run 기본 skill 결정 — 검색결과 URL 이 섞이면 humansearch."""
    return "humansearch" if any(_is_search_url(u) for u in urls) else _FLEET_RUN_DEFAULT_SKILL


def parse_fleet_args(command: str, raw_args: str) -> dict[str, Any]:
    """``key:value`` 형태 허용. 모르는 명령/필드는 조용히 무시하지 않고 거부.

    fleet-run 만 예외로 맨 토큰(URL/스킬/머신)을 자동 인식. skill 생략 시 기본값은
    ``_default_skill_for_urls``. url 은 필수 — 끝까지 안 잡히면 명확히 거부.
    (이사 전 parse_hermes_fleet_args 와 동일 행동)
    """
    if command not in FLEET_ARG_COMMANDS:
        raise FleetArgsError(f"알 수 없는 fleet 명령: {command!r}")
    # m3 봉인(Codex V2): 입력 길이 상한 — 비정상적으로 긴 인자를 큐 입구에서 거부한다
    # (URL·필터 합쳐도 8,000자면 충분. filters64 는 별도 6,000자 필드 상한이 이미 있다).
    if raw_args is not None and len(raw_args) > _MAX_RAW_ARGS_LEN:
        raise FleetArgsError(
            f"입력이 너무 깁니다({len(raw_args)}자 > {_MAX_RAW_ARGS_LEN}자 상한)")
    allowed = _ALLOWED_FIELDS[command]
    try:
        tokens = shlex.split(raw_args or "")
    except ValueError as exc:
        raise FleetArgsError(f"입력을 파싱할 수 없음: {exc}") from exc
    options: dict[str, Any] = {}
    bare_urls: list[str] = []
    for token in tokens:
        key = None
        if ":" in token:
            key, _, value = token.partition(":")
            key = key.strip()
            if key in allowed:
                _set_option_once(options, key, value.strip(), command)
                continue
        if command == "fleet-run":
            classified = _classify_bare_fleet_run_token(token)
            if classified is not None:
                field, value = classified
                if field == "url":
                    bare_urls.append(value)
                    continue
                _set_option_once(options, field, value, command)
                continue
        if key is not None:
            raise FleetArgsError(f"'{command}' 에 허용 안 된 필드: {key!r}")
        raise FleetArgsError(f"형식 오류(키:값 아님): {token!r}")
    if command == "fleet-run":
        if bare_urls:
            position_urls = [url for url in bare_urls if not _is_search_url(url)]
            if len(position_urls) > 1:
                raise FleetArgsError("한 fleet job에는 포지션 URL을 하나만 지정할 수 있습니다")
            if "url" in options:
                if position_urls:
                    raise FleetArgsError("url 필드와 포지션 URL을 중복 지정할 수 없습니다")
            else:
                position_url = position_urls[0] if position_urls else bare_urls[0]
                options["url"] = position_url
            search_urls = [url for url in bare_urls if _is_search_url(url)]
            if search_urls:
                options["params"] = {"search_urls": search_urls}
        options.setdefault("skill", _default_skill_for_urls(bare_urls))
        params = dict(options.get("params") or {})
        raw_channels = options.pop("channels", "")
        if raw_channels:
            channels = tuple(dict.fromkeys(x for x in raw_channels.split(",") if x))
            if not channels or any(x not in {"saramin", "jobkorea"} for x in channels):
                raise FleetArgsError("channels 는 saramin,jobkorea 만 허용합니다")
            params["channels"] = list(channels)
        idempotency = options.pop("idempotency", "")
        if idempotency:
            if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", idempotency):
                raise FleetArgsError("idempotency 형식 오류")
            params["idempotency_key"] = idempotency
        # 이슈 A(2026-07-15): url→aisearch 순차 핸드오프 — 후속 스킬도 화이트리스트만
        followup = options.pop("followup", "")
        if followup:
            if followup not in FLEET_SKILLS:
                raise FleetArgsError(f"followup 은 {FLEET_SKILLS} 만 허용합니다")
            params["followup_skill"] = followup
        # 이슈 B(2026-07-15): 실행 엔진 선택 — claude|codex 만(fail-closed)
        agent = options.pop("agent", _MISSING)
        if agent is not _MISSING:
            # M3 봉인(Codex V2): 명시된 agent 는 정확히 claude|codex 만. 빈 문자열('')도
            # 이상값으로 거부한다 — 조용히 '미지정(agent 없음)'으로 떨어뜨리지 않는다.
            if agent not in ("claude", "codex"):
                raise FleetArgsError("agent 는 claude|codex 만 허용합니다")
            params["agent"] = agent
        filters64 = options.pop("filters64", "")
        if filters64:
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,6000}={0,2}", filters64):
                raise FleetArgsError("filters64 형식 오류")
            try:
                raw_filter_bytes = base64.b64decode(
                    filters64, altchars=b"-_", validate=True
                )
                if base64.urlsafe_b64encode(raw_filter_bytes).decode("ascii") != filters64:
                    raise ValueError("non-canonical base64")
                decoded_filters = raw_filter_bytes.decode("utf-8")
            except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
                raise FleetArgsError("filters64 디코딩 오류") from exc
            if len(decoded_filters) > 4000 or any(
                ord(ch) < 32 and ch not in "\r\n\t" for ch in decoded_filters
            ):
                raise FleetArgsError("검색 필터는 4,000자 이내 일반 텍스트여야 합니다")
            params["search_filters_text"] = decoded_filters.strip()
        if raw_channels or idempotency:
            params.setdefault("execution", "live")
            params.setdefault("channels", ["saramin", "jobkorea"])
        if params:
            options["params"] = params
        if "url" not in options:
            if options.get("skill") == "login":
                # login 은 대상 URL 이 없는 스킬(#188) — 빈 값으로 고정(new_job_payload
                # 의 login 전용 빈 URL 허용과 짝).
                options["url"] = ""
            else:
                raise FleetArgsError("fleet-run 에는 url(ClickUp 등 포지션 링크)이 필요합니다")
    return options
