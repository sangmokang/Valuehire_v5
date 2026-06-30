"""humansearch 브라우징·로그인 라이브 프리플라이트 (fail-closed 게이트).

단일 출처 스펙: docs/sot/27-humansearch-browsing-preflight.json
사장님 지시(2026-06-30): 검색이 '살아있는 상태'임이 증거로 확인되지 않으면 순회(수집/채점)
코드를 아예 실행하지 않는다. 봇처럼 같은 동작을 반복하지 않는다 — 1회 점검 실패 = 즉시 STOP.

왜 필요한가: humansearch_cdp_run 에 라이브 점검 게이트가 없어, 검색 세션 만료/세션충돌/
raw+확장 동시 attach 로 결과가 0건 렌더돼도 '0명'을 조용히 뱉고 같은 네비게이션을 반복했다.
이 모듈은 그 모든 실패를 사전에 잡아 '실행 거부(PreflightError)'로 전환한다.

이 파일은 *판정 로직*만 담아 기계 검증(verify) 대상으로 고정한다. 브라우저 I/O 는
호출자(assert_live_or_abort)가 tab.eval(build_probe_js()) 로 수집한 probe 를 넘긴다.
"""
from __future__ import annotations

import re
from typing import Any

# 로그인/인증 리다이렉트 신호 (url 부분일치, 소문자 비교).
_LOGIN_REDIRECT_MARKERS = (
    "/authwall",
    "/checkpoint",
    "/uas/login",
    "/login",
    "enterprise-authentication/sessions",
)

# 세션 충돌(다른 기기 동시 로그인) — url 신호.
_SESSION_CONFLICT_URL = "enterprise-authentication/sessions"

# 결과 수 텍스트가 '진짜 결과'를 가리키는지: 숫자 + (K / results / 명 / 개).
_RESULTS_COUNT_RE = re.compile(r"\d[\d,.]*\s*(?:k\+?|results|명|개)", re.IGNORECASE)

# 결과가 렌더됐다고 인정할 최소 카드 수.
MIN_CARD_COUNT = 1


class PreflightError(RuntimeError):
    """라이브 검증 실패 — 순회 코드를 실행하지 않고 즉시 STOP 시키는 fail-closed 예외."""

    def __init__(self, decision: dict[str, Any]):
        self.decision = decision
        reasons = "; ".join(decision.get("reasons", [])) or "알 수 없는 사유"
        super().__init__(f"humansearch 프리플라이트 실패 — {reasons}")


def _positive_results_count(text: str) -> bool:
    """결과 수 텍스트가 '0보다 큰 실제 결과'를 가리키면 True.

    '0 results'/'결과 0개' 같은 0건(죽은/빈 검색)은 False 로 거른다.
    'K'(천 단위)가 있으면 무조건 양수로 본다. 그 외에는 숫자를 추출해 > 0 인지 본다.
    """
    m = _RESULTS_COUNT_RE.search(text)
    if not m:
        return False
    token = m.group(0).lower()
    if "k" in token:
        return True
    digits = re.sub(r"[^\d]", "", token)
    return bool(digits) and int(digits) > 0


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _coerce_str(value: Any) -> str:
    return value if isinstance(value, str) else ("" if value is None else str(value))


def evaluate_search_preflight(probe: dict[str, Any]) -> dict[str, Any]:
    """page 상태 probe → 라이브 여부 판정(순수 함수). docs/sot/27 규칙 강제.

    fail-closed: 입력이 비거나 일부 필드가 없으면 해당 체크는 실패로 본다.
    """
    url = _coerce_str(probe.get("url")).lower()
    card_count = _coerce_int(probe.get("card_count"))
    results_text = _coerce_str(probe.get("results_text"))
    account = _coerce_str(probe.get("logged_in_account")).strip()
    multiple_signins = bool(probe.get("multiple_signins"))
    captcha = bool(probe.get("captcha"))

    no_login_redirect = not any(m in url for m in _LOGIN_REDIRECT_MARKERS)
    logged_in = bool(account) and no_login_redirect
    no_session_conflict = (not multiple_signins) and (_SESSION_CONFLICT_URL not in url)
    no_captcha = not captcha
    results_rendered = card_count >= MIN_CARD_COUNT and _positive_results_count(results_text)

    checks = {
        "logged_in": logged_in,
        "no_session_conflict": no_session_conflict,
        "no_captcha": no_captcha,
        "results_rendered": results_rendered,
        "no_login_redirect": no_login_redirect,
    }

    reasons: list[str] = []
    if not logged_in:
        reasons.append("로그인 안 됨 또는 로그인/인증 페이지로 리다이렉트 — 계정 로그인 상태가 아님")
    if not no_session_conflict:
        reasons.append("다른 기기 동시 로그인(세션 충돌) 감지 — 한쪽 세션 정리 필요")
    if not no_captcha:
        reasons.append("캡차/보안 체크포인트 감지 — 자동 우회 금지, 사람 개입 필요")
    if not results_rendered:
        reasons.append(
            f"검색 결과 미렌더(카드 {card_count}개, 결과수 '{results_text}') — 세션 만료/Loading/껍데기 상태로 판단"
        )

    ok = all(checks.values())
    return {"ok": ok, "checks": checks, "reasons": reasons, "card_count": card_count}


def build_probe_js() -> str:
    """라이브 수집 탭에서 page 상태 probe 를 만드는 JS(IIFE). tab.eval(returnByValue) 용."""
    return r"""(() => {
      const txt = document.body ? document.body.innerText : '';
      const cardSet = new Set();
      for (const a of document.querySelectorAll('a[href*="/talent/profile/"]')) {
        cardSet.add((a.href || '').split('?')[0]);
      }
      const rm = txt.match(/([\d,.]+\s*K?\+?)\s*(results|개의 결과|명)/i);
      const am = txt.match(/Expand the user menu\n([^\n]+)/);
      return {
        url: location.href,
        card_count: cardSet.size,
        results_text: rm ? rm[0] : '',
        logged_in_account: am ? am[1].trim() : '',
        multiple_signins: /multiple sign-ins|only one session|동시 로그인/i.test(txt),
        captcha: /security verification|captcha|checkpoint|체크포인트|로봇이 아닙니다/i.test(txt)
      };
    })()"""


def assert_live_or_abort(tab: Any) -> dict[str, Any]:
    """순회 시작 직전 호출하는 fail-closed 게이트.

    tab.eval(build_probe_js()) 로 page 상태를 수집해 판정하고, ok=False 면 PreflightError 를
    raise 해 수집/채점이 시작조차 못 하게 한다. 봇 재시도 루프 금지(호출자는 예외를 잡아
    즉시 STOP·원인 보고만 한다 — 같은 URL 재네비게이션 금지).
    """
    probe = tab.eval(build_probe_js())
    if not isinstance(probe, dict):
        probe = {}
    decision = evaluate_search_preflight(probe)
    if not decision["ok"]:
        raise PreflightError(decision)
    return decision
