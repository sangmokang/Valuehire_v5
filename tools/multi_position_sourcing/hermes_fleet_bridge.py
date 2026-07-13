"""Hermes 게이트웨이 플러그인 어댑터 — fleet-* 명령을 기존 dispatch_fleet_command 로 위임.

Hermes 의 ``PluginContext.register_command()`` 핸들러 계약은 ``fn(raw_args: str) -> str | None``
뿐이라 발신자 식별자를 안 준다(hermes_cli/plugins.py:414 확인, 구조적 한계). 그래서 이 모듈은
발신자 식별자(``gateway_user_id``)를 **명시 인자로 강제**하고, 비어 있으면 사장님으로도 팀원으로도
간주하지 않고 무조건 거부한다(fail-closed) — Hermes 쪽 배선(``pre_gateway_dispatch`` 훅으로
``event.sender_id`` 를 미리 확보)이 이 값을 채우는 책임을 진다. 이 모듈 자체는 그 배선을 하지 않는다
(플러그인 ``__init__.py`` 쪽 책임 — 재검증은 여기서 fail-closed 게이트로만).

권한·큐 로직은 재구현하지 않는다 — discord_routing.route_discord_invocation +
fleet_dispatch.dispatch_fleet_command(단일출처)를 그대로 감싼다.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any, Mapping, Sequence

from .access import DiscordAuthorizedUser, load_authorized_discord_users
from .discord_routing import DiscordAccessConfig, DiscordInvocation
from .fleet_dispatch import FLEET_COMMANDS, dispatch_fleet_command
from .job_queue import FLEET_MACHINES, FLEET_SKILLS

FLEET_PLUGIN_COMMANDS: tuple[str, ...] = FLEET_COMMANDS  # ("fleet-run","fleet-resume","fleet-status","fleet-cancel")

# fleet-run 전용 완화 규칙(2026-07-13 사장님 요청) — "/fleet-run <url>" 만 줘도 동작하게.
# 다른 명령(status/resume/cancel)은 여전히 엄격 key:value 만 받는다(대상이 애매해질 여지 없음).
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

# 레포 루트 기준 절대경로 — Hermes 게이트웨이 프로세스는 cwd 가 ~/.hermes 라
# (실측: pid 5698, lsof cwd=/Users/kangsangmo/.hermes) 상대경로 "docs/search-access.md" 는
# 그 프로세스에서 항상 못 찾는다(FileNotFoundError). 이 파일 위치에서 파생해 cwd 와 무관하게 만든다.
_DEFAULT_ACCESS_DOC = Path(__file__).resolve().parents[2] / "docs" / "search-access.md"

_ALLOWED_FIELDS: dict[str, frozenset[str]] = {
    "fleet-run": frozenset({"skill", "url", "machine", "channels", "idempotency"}),
    "fleet-status": frozenset(),
    "fleet-resume": frozenset({"job"}),
    "fleet-cancel": frozenset({"job"}),
}


class HermesFleetBridgeError(ValueError):
    """플러그인 입력이 계약을 벗어남(fail-closed) — 명령/필드/신원 검증 실패."""


def _classify_bare_fleet_run_token(token: str) -> tuple[str, str] | None:
    """fleet-run 전용: ``key:value`` 가 아닌 맨 토큰이 url/skill/machine 중 뭔지 판정.

    모호하면(아무 것에도 확실히 안 맞으면) None — 추측하지 않고 호출부가 거부하게 한다.
    URL 은 소문자 스킴(``http://``/``https://``)만 인정 — 대소문자 우회로 판정을 피해가는
    시도를 허용하지 않는다(다른 필드들도 소문자 고정값이라 일관성 유지).
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
        # 같은 필드 중복 지정(명시든 맨 토큰이든)은 "마지막 값으로 조용히 덮어쓰기"가 아니라
        # 명시 거부한다 — 뒤에 몰래 붙은 값으로 앞 값을 밀어내는 스머글링을 fail-closed 로 막는다.
        raise HermesFleetBridgeError(f"필드 중복 지정: {field!r}")
    options[field] = value


def _is_search_url(url: str) -> bool:
    low = url.lower()
    return any(marker in low for marker in _SEARCH_HOST_MARKERS)


def parse_hermes_fleet_args(command: str, raw_args: str) -> dict[str, Any]:
    """``key:value key2:value2`` 형태를 허용. 모르는 명령/필드는 조용히 무시하지 않고 거부.

    fleet-run 만 예외로, ``key:value`` 가 아닌 맨 토큰도 URL/스킬/머신으로 자동 인식한다
    (2026-07-13 사장님 요청 — "그냥 /fleet-run 하고 링크만 주면 서치하도록"). skill 생략 시
    기본값 aisearch, machine 생략은 하위(build_fleet_job_payload)의 기존 fleet 기본값과
    account binding 정책에 맡긴다. url 은 필수 — fleet-run 인데 끝까지 url 이 안 잡히면
    명확히 거부한다.
    """
    if command not in FLEET_PLUGIN_COMMANDS:
        raise HermesFleetBridgeError(f"알 수 없는 fleet 명령: {command!r}")
    allowed = _ALLOWED_FIELDS[command]
    try:
        tokens = shlex.split(raw_args or "")
    except ValueError as exc:
        # 따옴표 안 닫힘 등 shlex 파싱 실패 — 원본 ValueError 를 그대로 새지 않게 감싼다.
        raise HermesFleetBridgeError(f"입력을 파싱할 수 없음: {exc}") from exc
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
            raise HermesFleetBridgeError(f"'{command}' 에 허용 안 된 필드: {key!r}")
        raise HermesFleetBridgeError(f"형식 오류(키:값 아님): {token!r}")
    if command == "fleet-run":
        if bare_urls:
            position_urls = [url for url in bare_urls if not _is_search_url(url)]
            if len(position_urls) > 1:
                raise HermesFleetBridgeError("한 fleet job에는 포지션 URL을 하나만 지정할 수 있습니다")
            if "url" in options:
                if position_urls:
                    raise HermesFleetBridgeError("url 필드와 포지션 URL을 중복 지정할 수 없습니다")
            else:
                position_url = position_urls[0] if position_urls else bare_urls[0]
                options["url"] = position_url
            search_urls = [url for url in bare_urls if _is_search_url(url)]
            if search_urls:
                options["params"] = {"search_urls": search_urls}
        options.setdefault("skill", _FLEET_RUN_DEFAULT_SKILL)
        params = dict(options.get("params") or {})
        raw_channels = options.pop("channels", "")
        if raw_channels:
            channels = tuple(dict.fromkeys(x for x in raw_channels.split(",") if x))
            if not channels or any(x not in {"saramin", "jobkorea"} for x in channels):
                raise HermesFleetBridgeError("channels 는 saramin,jobkorea 만 허용합니다")
            params["channels"] = list(channels)
        idempotency = options.pop("idempotency", "")
        if idempotency:
            if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", idempotency):
                raise HermesFleetBridgeError("idempotency 형식 오류")
            params["idempotency_key"] = idempotency
        if raw_channels or idempotency:
            params.setdefault("execution", "live")
            params.setdefault("channels", ["saramin", "jobkorea"])
        if params:
            options["params"] = params
        if "url" not in options:
            raise HermesFleetBridgeError("fleet-run 에는 url(ClickUp 등 포지션 링크)이 필요합니다")
    return options


_URL_IN_TEXT_RE = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
_NATURAL_TRIGGERS: tuple[str, ...] = (
    "aisearch", "humansearch", "휴먼서치", "사람인", "잡코리아", "후보", "찾아", "서치",
)
_FOLLOWUP_TRIGGERS: tuple[str, ...] = ("계속해", "잡코리아도", "사람인부터", "방금 포지션")


def natural_fleet_command_text(
    text: str,
    *,
    context_url: str = "",
    context_channels: Sequence[str] = (),
    message_id: str = "",
) -> str | None:
    """일반 Discord 문장을 Hermes slash command로 좁게 변환한다.

    알려진 채용 URL 또는 명시적인 humansearch 트리거가 있고 URL이 실제로 있을 때만
    변환한다. 일반 대화나 URL 없는 ``win``은 실행하지 않는다(fail-closed).
    """
    raw = (text or "").strip()
    if not raw or raw.startswith("/"):
        return None
    urls = [match.group(0).rstrip(".,);]}") for match in _URL_IN_TEXT_RE.finditer(raw)]
    low = raw.lower()
    words = set(re.findall(r"[A-Za-z0-9가-힣_-]+", low))
    explicit_machine = next(
        (canonical for canonical in FLEET_MACHINES if canonical in words), ""
    )
    alias_machine = next(
        (canonical for alias, canonical in _MACHINE_ALIASES.items() if alias in words), ""
    )
    machine = explicit_machine or alias_machine
    followup = any(trigger in low for trigger in _FOLLOWUP_TRIGGERS) or raw.lower() in {
        "win", "windows", "윈도우", "윈도우pc", "winpc"
    }
    clickup_urls = [url for url in urls if "app.clickup.com" in url.lower()]
    if not clickup_urls and context_url and (followup or any(t in low for t in _NATURAL_TRIGGERS)):
        urls = [context_url, *urls]
        clickup_urls = [context_url]
    if not urls:
        return None
    if len(clickup_urls) != 1:
        return None
    known_url = bool(clickup_urls)
    if not known_url and not any(trigger in low for trigger in _NATURAL_TRIGGERS) and not followup:
        return None

    mentions_saramin = "사람인" in raw or any("saramin.co.kr" in url.lower() for url in urls)
    mentions_jobkorea = "잡코리아" in raw or any("jobkorea.co.kr" in url.lower() for url in urls)
    if mentions_saramin and not mentions_jobkorea:
        channels = ("saramin",)
    elif mentions_jobkorea and not mentions_saramin:
        channels = ("jobkorea",)
    elif mentions_saramin and mentions_jobkorea:
        channels = ("saramin", "jobkorea")
    elif context_channels and followup:
        channels = tuple(context_channels)
    else:
        channels = ("saramin", "jobkorea")

    parts = ["/fleet-run", "aisearch", *urls, f"channels:{','.join(channels)}"]
    if machine:
        parts.append(machine)
    if message_id:
        parts.append(f"idempotency:discord:{message_id}")
    return " ".join(parts)


def dispatch_hermes_fleet_command(
    command: str,
    raw_args: str,
    *,
    gateway_user_id: str,
    queue: Any = None,
    authorized_users: Sequence[DiscordAuthorizedUser] | None = None,
) -> dict[str, Any]:
    """Hermes 플러그인 커맨드 1건 처리. 성공/거부 모두 JSON 직렬화 가능한 dict 반환.

    ``gateway_user_id`` 가 비어 있으면 즉시 예외(HermesFleetBridgeError) — 이건 "거부"가
    아니라 "신원 자체를 못 믿는다"는 상위 신호라 결과 dict 가 아니라 예외로 구분한다.
    """
    if not gateway_user_id or not str(gateway_user_id).strip():
        raise HermesFleetBridgeError(
            "gateway identity missing — 실행자 식별자 없이는 사장님으로도 팀원으로도 "
            "간주하지 않고 무조건 거부한다(fail-closed)"
        )

    options = parse_hermes_fleet_args(command, raw_args)

    try:
        users = (
            authorized_users
            if authorized_users is not None
            else load_authorized_discord_users(str(_DEFAULT_ACCESS_DOC))
        )
        invocation = DiscordInvocation(
            user_id=str(gateway_user_id).strip(),
            channel_id="hermes-dm",
            command_name=command,
            is_dm=True,
            invocation_kind="hermes-plugin",
            options=options,
        )
        config = DiscordAccessConfig(allow_dm=True)
        result = dispatch_fleet_command(
            invocation, authorized_users=users, config=config, queue=queue
        )
    except Exception as exc:  # noqa: BLE001 — 여기서부턴 절대 새지 않는다.
        # Hermes 쪽 _handler()는 HermesFleetBridgeError만 골라 잡으므로, 예상 못 한 예외
        # (파일 I/O·Supabase 네트워크 오류 등)가 여기서 새면 조용한 무응답으로 이어진다
        # (플러그인 계약 위반). 알 수 없는 실패도 항상 dict로 명시 보고한다(fail-closed 보고).
        return {"action": "error", "reason": f"internal error: {exc}"}
    # command 는 parse_hermes_fleet_args 에서 이미 FLEET_PLUGIN_COMMANDS 검증을 통과했으므로
    # dispatch_fleet_command 가 None(미지원 명령)을 반환할 일은 없다.
    assert result is not None
    return result
