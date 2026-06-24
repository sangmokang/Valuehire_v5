"""브라우저 선택 SOT 로더 + 검문소.

"어떤 일에 어떤 브라우저를 쓰는가"는 ``browser_policy.json`` 한 장이 유일한 정답이다.
SKILL 자연어에 흩뿌리지 않는다(중복·충돌 차단). 이 모듈은 그 규칙을 **결정론적으로**
읽고, 작업 시작 직전 붙은 브라우저가 규칙과 맞는지 **fail-closed** 로 검문한다.

설계 원칙(SOT 불변식 1·2·5):
- 추측 금지: 규칙에 없는 작업명은 멈춘다(추측해서 엉뚱한 브라우저로 가지 않는다).
- fail-closed: 붙은 브라우저가 규칙과 다르면 진행하지 않고 예외를 던진다.
- 네트워크 없음: 순수 함수. 실제 attach 여부는 호출부가 connected_endpoint 로 넘긴다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# SOT 규칙 파일은 이 모듈과 같은 디렉토리에 둔다(코드와 규칙을 함께 배포).
DEFAULT_BROWSER_POLICY_PATH: Path = Path(__file__).with_name("browser_policy.json")

# 포털 CDP 주소 env 오버라이드. 사장님이 포트를 바꾸면(.env.local) 검문소가 그걸 따라간다.
CHROME_CDP_ENDPOINT_ENV = "VALUEHIRE_PORTAL_CHROME_CDP_ENDPOINT"

BrowserPolicy = dict[str, Any]


class BrowserPolicyViolation(RuntimeError):
    """규칙 위반(미지의 작업명·브라우저 불일치 등). 진행하지 않는다."""


def load_browser_policy(path: Path | str | None = None) -> BrowserPolicy:
    """규칙 파일을 읽어 dict 로 돌려준다. 파일 부재/깨짐은 fail-closed."""
    policy_path = Path(path) if path is not None else DEFAULT_BROWSER_POLICY_PATH
    try:
        raw = policy_path.read_text(encoding="utf-8")
    except OSError as exc:  # 파일이 없거나 못 읽음 → 추측 금지, 멈춘다.
        raise BrowserPolicyViolation(f"브라우저 규칙 파일을 읽지 못했다: {policy_path}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BrowserPolicyViolation(f"브라우저 규칙 파일이 깨졌다: {policy_path}") from exc
    if not isinstance(data, dict):
        raise BrowserPolicyViolation("브라우저 규칙은 객체(dict)여야 한다")
    return data


def resolve_browser_target(action: str, *, policy: BrowserPolicy | None = None) -> dict[str, Any]:
    """작업명에 맞는 브라우저 타깃을 규칙에서 읽어 돌려준다.

    규칙에 없는 작업명은 추측하지 않고 :class:`BrowserPolicyViolation` 을 던진다.
    """
    policy = policy if policy is not None else load_browser_policy()
    target = policy.get(action)
    if not isinstance(target, dict):
        known = sorted(k for k in policy if not k.startswith("_"))
        raise BrowserPolicyViolation(
            f"규칙에 없는 작업명: {action!r}. 정의된 작업: {known}"
        )
    return target


def assert_browser_ready(
    action: str,
    *,
    connected_endpoint: str,
    explicit_endpoint: str | None = None,
    policy: BrowserPolicy | None = None,
) -> None:
    """검문소: 지금 붙은 브라우저가 규칙과 맞는지 확인. 다르면 멈춘다(fail-closed).

    connected_endpoint 는 호출부가 실제로 attach 한 CDP 주소.
    규칙의 cdp_endpoint 와 다르면 :class:.

    우선순위: explicit_endpoint > env(http 로 시작하는 값만) > policy SOT.
    """
    target = resolve_browser_target(action, policy=policy)
    expected = target.get("cdp_endpoint")
    if expected is None:
        # CDP 주소를 안 쓰는 작업(예: MCP 크롬)은 endpoint 검문 대상이 아니다.
        return
    # 명시값이 최우선 (resolver 가 이미 계산한 값을 그대로 넘기면 env 충돌 없음).
    if explicit_endpoint and explicit_endpoint.strip().startswith("http"):
        expected = explicit_endpoint.strip()
    else:
        # env 오버라이드가 SOT 보다 우선. 단 공백/비URL 은 무시하고 policy 로 폴백.
        env_endpoint = os.environ.get(CHROME_CDP_ENDPOINT_ENV)
        if env_endpoint:
            env_endpoint = env_endpoint.strip()
            if env_endpoint.startswith("http"):
                expected = env_endpoint
    if connected_endpoint != expected:
        raise BrowserPolicyViolation(
            f"브라우저 불일치({action}): 규칙={expected} ↔ 실제={connected_endpoint}. "
            "엉뚱한 크롬이라 진행을 멈춘다."
        )


def policy_cdp_endpoint(policy: BrowserPolicy | None = None) -> str | None:
    """포털 자동작업의 CDP 주소(규칙 SOT). 배선용 헬퍼."""
    try:
        return resolve_browser_target("portal_automation", policy=policy).get("cdp_endpoint")
    except BrowserPolicyViolation:
        return None
