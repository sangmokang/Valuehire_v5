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
from pathlib import Path
from typing import Any, Mapping, Sequence

from .access import DiscordAuthorizedUser, load_authorized_discord_users
from .discord_routing import (
    DiscordInvocation,
    load_discord_access_config,
)
from .fleet_args import (  # AC-1 이사(2026-07-22) — 파싱 단일출처는 fleet_args, 여기는 호환 re-export
    FLEET_ARG_COMMANDS,
    FleetArgsError,
    _ALLOWED_FIELDS,
    _FLEET_RUN_DEFAULT_SKILL,
    _MACHINE_ALIASES,
    _SEARCH_HOST_MARKERS,
    _classify_bare_fleet_run_token,
    _default_skill_for_urls,
    _is_search_url,
    _set_option_once,
    parse_fleet_args,
)
from .fleet_dispatch import FLEET_COMMANDS, dispatch_fleet_command
from .job_queue import FLEET_MACHINES, FLEET_SKILLS

FLEET_PLUGIN_COMMANDS: tuple[str, ...] = FLEET_ARG_COMMANDS  # ("fleet-run","fleet-resume","fleet-status","fleet-cancel")

# 옛 이름 호환(AC-8 헤르메스 폐기 때 이 모듈째 삭제) — 같은 객체를 가리켜 드리프트 0.
HermesFleetBridgeError = FleetArgsError
parse_hermes_fleet_args = parse_fleet_args

# 레포 루트 기준 절대경로 — Hermes 게이트웨이 프로세스는 cwd 가 ~/.hermes 라
# (실측: pid 5698, lsof cwd=/Users/kangsangmo/.hermes) 상대경로 "docs/search-access.md" 는
# 그 프로세스에서 항상 못 찾는다(FileNotFoundError). 이 파일 위치에서 파생해 cwd 와 무관하게 만든다.
_DEFAULT_ACCESS_DOC = Path(__file__).resolve().parents[2] / "docs" / "search-access.md"


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
