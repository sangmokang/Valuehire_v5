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
import urllib.parse
from pathlib import Path
from typing import Any, Mapping, Sequence

from .access import DiscordAuthorizedUser, load_authorized_discord_users
from .discord_routing import (
    DiscordInvocation,
    load_discord_access_config,
)
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
    "fleet-run": frozenset({"skill", "url", "machine", "channels", "idempotency", "followup", "agent"}),
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
    """호스트명 기준으로만 판정한다(2026-07-14, Codex Rescue 적대검증에서 발견한 결함 수정).

    이전엔 URL 문자열 전체에서 마커가 *어디든* 나오면 True였다 — 그래서
    ``https://app.clickup.com/t/abc?source=jobkorea.co.kr``(쿼리 문자열에 마커가 우연히
    들어간 포지션 링크)나 ``https://linkedin.com.evil.example/...``(도메인 뒤에 마커
    문자열을 붙인 유사 도메인)까지 검색결과 URL로 오판했다. 호스트명이 마커와 정확히
    같거나 그 서브도메인일 때만 True로 좁힌다.
    """
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return any(host == marker or host.endswith("." + marker) for marker in _SEARCH_HOST_MARKERS)


def _default_skill_for_urls(urls: Sequence[str]) -> str:
    """URL 모양만으로 fleet-run 기본 skill을 고른다(2026-07-14 사장님 요청).

    채용포털 검색결과 리스트(사람인/잡코리아/링크드인 검색결과, ``_is_search_url``)가
    하나라도 섞여 있으면 humansearch(사람이 미리 준비한 결과를 순회·채점하는 스킬)를,
    없으면 기존 기본값 aisearch를 쓴다. ``options.setdefault`` 뒤에서만 호출되므로
    호출자가 ``skill:``을 명시했으면 이 함수는 아예 참조되지 않는다 — 명시 지정이
    항상 이 추론보다 우선한다. natural_fleet_command_text(자연어 경로)와
    parse_hermes_fleet_args(직접 명령 경로) 양쪽이 이 함수 하나만 참조해, 판정이
    갈라지거나 한쪽만 배선되는 일이 없게 한다(단일 출처).
    """
    return "humansearch" if any(_is_search_url(u) for u in urls) else _FLEET_RUN_DEFAULT_SKILL


def parse_hermes_fleet_args(command: str, raw_args: str) -> dict[str, Any]:
    """``key:value key2:value2`` 형태를 허용. 모르는 명령/필드는 조용히 무시하지 않고 거부.

    fleet-run 만 예외로, ``key:value`` 가 아닌 맨 토큰도 URL/스킬/머신으로 자동 인식한다
    (2026-07-13 사장님 요청 — "그냥 /fleet-run 하고 링크만 주면 서치하도록"). skill 생략 시
    기본값은 ``_default_skill_for_urls``가 정한다 — 검색결과 URL이 섞여 있으면
    humansearch, 포지션 URL만 있으면 기존처럼 aisearch(2026-07-14 사장님 요청 — "채용포털
    url 도 search list 를 주면 humansearch 가 발동되도록"). machine 생략은
    하위(build_fleet_job_payload)의 기존 fleet 기본값과 account binding 정책에 맡긴다.
    url 은 필수 — fleet-run 인데 끝까지 url 이 안 잡히면 명확히 거부한다.
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
        options.setdefault("skill", _default_skill_for_urls(bare_urls))
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
        # 이슈 A(2026-07-15): url→aisearch 순차 핸드오프 — 후속 스킬도 화이트리스트만
        followup = options.pop("followup", "")
        if followup:
            if followup not in FLEET_SKILLS:
                raise HermesFleetBridgeError(f"followup 은 {FLEET_SKILLS} 만 허용합니다")
            params["followup_skill"] = followup
        # 이슈 B(2026-07-15): 실행 엔진 선택 — claude|codex 만(fail-closed)
        agent = options.pop("agent", "")
        if agent:
            if agent not in ("claude", "codex"):
                raise HermesFleetBridgeError("agent 는 claude|codex 만 허용합니다")
            params["agent"] = agent
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
_EXPLICIT_SKILL_IN_TEXT_RE = re.compile(r"skill:(aisearch|humansearch)")
# 뒤에 \b 를 안 붙인다: Python 정규식의 \b 는 유니코드 인식이라 "aisearch로"처럼 한글
# 조사가 바로 붙으면(h·로 둘 다 \w) 경계로 안 잡혀 매치가 깨진다 — 실측 재현됨.


def _explicit_skill_from_natural_text(low: str) -> str | None:
    """자연어 문장 안에 명시적으로 적힌 skill을 찾는다(2026-07-14, Codex Rescue 발견 결함 수정).

    이전엔 자연어 경로가 URL 모양만으로 skill을 정해서, 사용자가 문장 안에
    ``skill:aisearch`` 라고 명시하거나 그냥 "aisearch"/"humansearch" 단어를 직접 썼어도
    검색결과 URL 유무에 따라 그 지정을 조용히 덮어썼다(직접 명령 경로는 명시 지정을
    존중하는데 자연어 경로만 안 그래서 두 진입점 판정이 갈라짐). ``skill:xxx`` 형태를
    최우선으로, 그다음 "aisearch"/"humansearch" 단어가 문장에 단독으로(둘 다는 아니고)
    있으면 그것도 명시 지정으로 본다. ``words``(단어 集合) 대신 ``low`` 부분 문자열로
    찾는다 — "aisearch로"처럼 한글 조사가 바로 붙으면 단어 추출 정규식이 "aisearch로"를
    한 토큰으로 묶어버려 "aisearch"가 集合에 안 남는다(실측 재현됨; _NATURAL_TRIGGERS가
    이미 같은 이유로 부분 문자열 검사를 쓰는 것과 동일한 이유). "url"은 자연어에서 흔한
    일반 단어라 오탐 위험이 커서 명시 지정 대상에서 뺀다.
    """
    match = _EXPLICIT_SKILL_IN_TEXT_RE.search(low)
    if match:
        return match.group(1)
    has_aisearch = "aisearch" in low
    has_humansearch = "humansearch" in low
    if has_aisearch and not has_humansearch:
        return "aisearch"
    if has_humansearch and not has_aisearch:
        return "humansearch"
    return None


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
    # 이슈 A(2026-07-15): "링크드인/linkedin" + 포지션 URL(검색결과 URL 아님) 1개 →
    # url 스킬로 RPS 라이브서치를 먼저 준비하고 aisearch 를 후속 발사(1단계 체이닝).
    # 단어 검사는 URL 을 걷어낸 본문에서만 — linkedin.com 링크 자체는 트리거가 아니다.
    # 명시 skill 지정이 있으면 규칙 미적용(기존 "명시 우선" 원칙).
    explicit_skill = _explicit_skill_from_natural_text(low)
    position_urls = [url for url in urls if not _is_search_url(url)]
    low_no_urls = _URL_IN_TEXT_RE.sub(" ", raw).lower()
    linkedin_handoff = (
        explicit_skill is None
        and len(position_urls) == 1
        and len(position_urls) == len(urls)
        and ("링크드인" in low_no_urls or "linkedin" in low_no_urls)
    )
    if not linkedin_handoff and len(clickup_urls) != 1:
        return None
    known_url = bool(clickup_urls)
    if (not known_url and not any(trigger in low for trigger in _NATURAL_TRIGGERS)
            and not followup and not linkedin_handoff):
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

    skill = explicit_skill or (
        "url" if linkedin_handoff else _default_skill_for_urls(urls))
    parts = ["/fleet-run", skill, *urls, f"channels:{','.join(channels)}"]
    if linkedin_handoff:
        parts.append("followup:aisearch")
    # 이슈 B(2026-07-15): 본문(URL 제외)에 "codex" 단어가 있으면 codex 엔진 선택.
    # URL 안 문자열은 트리거 아님(low_no_urls). V1 반증 수용: 라틴 토큰 속
    # 부분문자열("precodexpost")은 오탐 — 양옆이 영숫자가 아닐 때만 단어로 인정
    # ("codex로" 같은 한글 조사는 계속 허용). 미지정 시 기존 claude 그대로.
    if re.search(r"(?<![a-z0-9])codex(?![a-z0-9])", low_no_urls):
        parts.append("agent:codex")
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
    invocation_context: Mapping[str, Any] | None = None,
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
        context = invocation_context or {}
        has_context = invocation_context is not None
        is_dm = context.get("is_dm") is True if has_context else True
        channel_id = str(context.get("channel_id", "") or "").strip()
        if not channel_id:
            channel_id = "hermes-dm" if is_dm else "hermes-unknown-channel"
        guild_id = str(context.get("guild_id", "") or "").strip()
        role_ids = tuple(
            str(role_id).strip()
            for role_id in (context.get("role_ids", ()) or ())
            if str(role_id).strip()
        )
        invocation = DiscordInvocation(
            user_id=str(gateway_user_id).strip(),
            channel_id=channel_id,
            command_name=command,
            is_dm=is_dm,
            invocation_kind="hermes-plugin",
            guild_id=guild_id,
            member_role_ids=role_ids,
            options=options,
        )
        config = load_discord_access_config()
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
