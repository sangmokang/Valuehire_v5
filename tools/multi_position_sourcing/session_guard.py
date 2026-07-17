"""세션가드 코어 — 로그인 세션 상시 유지의 판정·스냅샷 순수 모듈 (SOT-28 §3a·§4·§5).

직전 세션의 session_guard/vault/cdp_util/launch_chrome 아이디어(쿠키 스냅샷 롤링,
2단계 판정, LinkedIn 단일기기·자동로그인 금지)를 **새 scripts/ 트리 없이** v5 기존
인프라 위에 재작성한 것(2026-07-17 /st 지시 5). 역할 분담:

- 브라우저 접속: ``raw_cdp``(단일 탭 attach, 종료=WebSocket 해제만) 재사용 — 재발명 금지.
- 사람 점유 감지: ``owner_activity.detect_owner_activity_snapshot`` 재사용.
  **keepalive 직전마다 호출이 필수**이며, 감지 실패는 fail-closed(사용 중 간주).
- 자격증명 저장: ``portal_keychain``(키체인) 재사용 — 이 모듈은 비밀번호를 다루지 않는다.

이 파일은 순수 판정(결정론 테스트 가능)과 스냅샷 파일 관리만 담고, 실제 keepalive
루프·재로그인 실행은 기존 러너(portal_login·fleet_worker)가 이 계약을 소비한다.

⚠️ CDP 쿠키 조회(``fetch_cookies_via_cdp``)는 **실크롬 왕복 검증 전 = 미검증** 상태다.
실크롬에서 왕복(쿠키 조회 → 스냅샷 → 재조회 일치) 증거를 남기기 전까지 "검증됨"이라
표기하지 않는다(/st 지시 5). 실패 시 None 을 돌려 2단계 판정이 probe 로 폴백한다.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Literal

Site = Literal["saramin", "jobkorea", "linkedin_rps"]
CookieEvidence = Literal["present", "absent", "unknown"]
KeepaliveAction = Literal[
    "skip_not_due", "skip_owner_active", "cookie_only_ok",
    "probe_readonly", "reauth", "human_wait",
]

# SOT-28 §4: 사람인·잡코리아 서버세션(JSESSIONID·ASP.NET_SessionId)은 20~30분 유휴
# 만료 → 주기는 15분 이하. LinkedIn li_at 는 장수명 → 30분 읽기 전용이면 충분.
KEEPALIVE_INTERVAL_SECONDS: dict[Site, int] = {
    "saramin": 900,
    "jobkorea": 900,
    "linkedin_rps": 1800,
}

# 읽기 전용 probe 표면. 잡코리아는 대문자 /Corp/Person/Find (소문자 경로는 리다이렉트
# 손실 이력 — 2026-07-17 /st 지시 5). 유료 차감·저장·발송 표면 금지(SOT-28 §4).
PROBE_URLS: dict[Site, str] = {
    "saramin": "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
    "jobkorea": "https://www.jobkorea.co.kr/Corp/Person/Find",
    "linkedin_rps": "https://www.linkedin.com/talent/home",
}

# 1단계(쿠키) 판정에 쓰는 세션 쿠키 이름.
SESSION_COOKIE_NAMES: dict[Site, tuple[str, ...]] = {
    "saramin": ("JSESSIONID",),
    "jobkorea": ("ASP.NET_SessionId",),
    "linkedin_rps": ("li_at",),
}

DEFAULT_SNAPSHOT_ROOT = Path.home() / ".valuehire" / "session_snapshots"


def keepalive_due(site: Site, *, last_at: float | None, now: float) -> bool:
    """마지막 keepalive 이후 주기가 지났는가. 첫 회차(last_at=None)는 항상 due."""
    if last_at is None:
        return True
    return (now - last_at) >= KEEPALIVE_INTERVAL_SECONDS[site]


def classify_cookie_evidence(site: Site, cookies: list[dict[str, Any]] | None) -> CookieEvidence:
    """1단계 판정: 세션 쿠키 존재 여부. cookies=None(조회 실패/미검증)은 unknown."""
    if cookies is None:
        return "unknown"
    names = {str(c.get("name") or "") for c in cookies}
    return "present" if any(n in names for n in SESSION_COOKIE_NAMES[site]) else "absent"


def decide_keepalive(
    site: Site, *, due: bool, owner_active: bool, cookie_evidence: CookieEvidence,
) -> KeepaliveAction:
    """keepalive 1회차의 행동 결정 (순수함수 — 판정 우선순위가 곧 SOT-28 계약).

    1) 사람 점유 최우선: owner_active 면 due 여도 건너뛴다(§4 — 사장님을 앞지르지 않는다).
    2) due 아니면 아무것도 안 한다(분 단위 과잉 클릭 금지).
    3) 쿠키 present → 페이지 열지 않음(침습 최소).
    4) unknown → 읽기 전용 probe 1회로 2단계 판정.
    5) absent → 사람인·잡코리아는 자동 재로그인(§3), LinkedIn 은 human_wait
       (자동 폼 로그인 금지 + 계정당 단일 기기, §3a·§5).
    """
    if owner_active:
        return "skip_owner_active"
    if not due:
        return "skip_not_due"
    if cookie_evidence == "present":
        return "cookie_only_ok"
    if cookie_evidence == "unknown":
        return "probe_readonly"
    if site == "linkedin_rps":
        return "human_wait"
    return "reauth"


def save_cookie_snapshot(
    site: Site, cookies: list[dict[str, Any]], *,
    root: Path = DEFAULT_SNAPSHOT_ROOT, keep: int = 5, now: float | None = None,
) -> Path:
    """쿠키 스냅샷 롤링 저장 — 세션 사고 시 마지막 정상 상태를 복구 근거로 남긴다.

    비밀값이므로: 파일 0600, 디렉터리 0700, 내용·경로를 로그/대화에 출력하지 않는다.
    site 별 최신 ``keep`` 개만 유지(오래된 것 삭제).
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    stamp = f"{(time.time() if now is None else now):.3f}".replace(".", "")
    path = root / f"{site}-{stamp}.json"
    payload = {"site": site, "saved_at": now if now is not None else time.time(), "cookies": cookies}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    snapshots = sorted(root.glob(f"{site}-*.json"), key=lambda p: p.name)
    for old in snapshots[:-keep]:
        old.unlink(missing_ok=True)
    return path


def fetch_cookies_via_cdp(tab: Any) -> list[dict[str, Any]] | None:
    """CDP 로 현재 브라우저의 쿠키를 읽는다 — ⚠️ 실크롬 왕복 검증 전(미검증).

    ``raw_cdp.CDPTab.send`` 계약만 사용한다. Storage.getCookies(브라우저 전역) 우선,
    구버전 호환으로 Network.getCookies 폴백. 어떤 실패든 None(=unknown 판정 → probe
    폴백)으로 삼켜 keepalive 를 죽이지 않는다. 반환 쿠키는 비밀값 — 로그 금지.
    """
    for method in ("Storage.getCookies", "Network.getCookies"):
        try:
            result = tab.send(method)
        except Exception:
            continue
        cookies = result.get("cookies") if isinstance(result, dict) else None
        if isinstance(cookies, list):
            return cookies
    return None


def run_keepalive_once(
    site: Site, *,
    owner_snapshot: Any,
    tab_factory: Any,
    last_at: float | None,
    now: float | None = None,
    snapshot_root: Path = DEFAULT_SNAPSHOT_ROOT,
) -> dict[str, Any]:
    """keepalive 1회차 오케스트레이션 — 판정 순서가 곧 계약.

    ① owner_activity 확인(브라우저를 건드리기 **전**) → 사용 중이면 즉시 종료.
    ② due 계산 → 아니면 종료. ③ 그때만 tab_factory() 로 CDP attach(읽기 전용) 후
    쿠키 1단계 판정, present 면 스냅샷 롤링 저장. probe/reauth/human_wait 은 실행하지
    않고 action 으로만 보고한다(실행은 기존 러너 — portal_login §3 자동 재로그인 경로).
    끝나면 tab.close() = WebSocket 해제만(raw_cdp 계약 — 탭/브라우저는 살아있다).
    """
    now = time.time() if now is None else now
    snap = owner_snapshot()
    owner_active = bool(getattr(snap, "owner_activity_detected", True))
    due = keepalive_due(site, last_at=last_at, now=now)
    base = {"site": site, "at": now, "owner_active": owner_active, "due": due}
    if owner_active or not due:
        action = decide_keepalive(site, due=due, owner_active=owner_active,
                                  cookie_evidence="unknown")
        return {**base, "action": action, "cookie_evidence": None}
    tab = tab_factory()
    try:
        cookies = fetch_cookies_via_cdp(tab)
        evidence = classify_cookie_evidence(site, cookies)
        action = decide_keepalive(site, due=True, owner_active=False, cookie_evidence=evidence)
        if evidence == "present" and cookies is not None:
            save_cookie_snapshot(site, cookies, root=snapshot_root, now=now)
        return {**base, "action": action, "cookie_evidence": evidence}
    finally:
        try:
            tab.close()  # raw_cdp: WebSocket 해제만 — 세션 탭은 보존(SOT-28 §2-7)
        except Exception:
            pass


def _default_tab_factory(site: Site) -> Any:
    from . import raw_cdp

    target = raw_cdp.find_page_by_url({
        "saramin": "saramin.co.kr", "jobkorea": "jobkorea.co.kr",
        "linkedin_rps": "linkedin.com",
    }[site]) or (raw_cdp.list_pages()[0] if raw_cdp.list_pages() else None)
    if target is None:
        raise RuntimeError("no CDP page target — portal_browsers.sh 로 기동/로그인 상태 확인")
    return raw_cdp.attach(target, badge=False)


def main(argv: list[str] | None = None) -> int:
    """CLI: `python -m tools.multi_position_sourcing.session_guard --site saramin`.

    결과 JSON 1줄(stdout). 쿠키 값은 절대 출력하지 않는다(evidence 분류만).
    """
    import argparse

    parser = argparse.ArgumentParser(description="session keepalive one round (read-only)")
    parser.add_argument("--site", required=True, choices=sorted(KEEPALIVE_INTERVAL_SECONDS))
    parser.add_argument("--last-at", type=float, default=None)
    args = parser.parse_args(argv)
    site: Site = args.site

    from .owner_activity import detect_owner_activity_snapshot

    result = run_keepalive_once(
        site,
        owner_snapshot=detect_owner_activity_snapshot,
        tab_factory=lambda: _default_tab_factory(site),
        last_at=args.last_at,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
