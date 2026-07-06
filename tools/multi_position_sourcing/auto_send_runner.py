"""SOT28 자동발송 실행기 — 게이트 단일 관문(evaluate_send)을 거쳐서만 발송 클릭.

사용법:
  .venv/bin/python -m tools.multi_position_sourcing.auto_send_runner \
      --request-json request.json [--live] [--ledger PATH] [--policy PATH]

- request.json = SendRequest 필드 그대로(candidate_key, candidate_name, channel,
  position_id, body, score, hard_exclude_flags, precheck_passed).
- 기본은 dry-run: 게이트 판정 + 발송 단계 계획만 출력, 브라우저 무접촉.
- --live: 게이트 allowed 일 때만 채널 디버그 크롬(사람인9223/잡코리아9224/링크드인9225)의
  현재 열린 제안/컴포저 화면에 본문을 주입하고 발송 버튼을 클릭, 원장(live) 기록.
- 발송 흐름 전제: 제안 모달/컴포저는 상류(소싱 스킬)가 열어둔 상태에서 마지막
  주입+클릭만 담당한다(포털 점유·양보는 상류 R4 가드가 담당).

exit code: 0=성공(dry-run 계획 출력 또는 라이브 발송 완료), 3=게이트 차단, 2=실행 실패.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from .auto_send import (
    AutoSendPolicyError,
    SendLedger,
    SendRequest,
    evaluate_send,
    load_policy,
    plan_send_steps,
)
from .selectors import DEFAULT_SELECTOR_MAP

DEFAULT_LEDGER_PATH = Path(
    os.environ.get(
        "VALUEHIRE_SEND_LEDGER",
        str(Path.home() / ".cache" / "valuehire-auto-send" / "ledger.jsonl"),
    )
)


def _load_request(path: Path) -> SendRequest:
    data = json.loads(path.read_text(encoding="utf-8"))
    return SendRequest(
        candidate_key=data["candidate_key"],
        candidate_name=data["candidate_name"],
        channel=data["channel"],
        position_id=data["position_id"],
        body=data["body"],
        score=data.get("score"),
        score_breakdown=data.get("score_breakdown"),
        hard_exclude_flags=tuple(data.get("hard_exclude_flags", ())),
        precheck_passed=bool(data.get("precheck_passed", False)),
    )


def _selector_js_candidates(site: str, purpose: str) -> list[str]:
    return [c.selector for c in DEFAULT_SELECTOR_MAP[site][purpose]]


def _execute_live(request: SendRequest, policy: dict) -> dict:
    """열린 제안/컴포저 화면에 본문 주입 + 발송 클릭 (raw CDP, 채널 전용 포트)."""
    from . import raw_cdp

    cdp_http = policy["channels"][request.channel].get("cdp_http")
    if cdp_http:
        os.environ["CDP_HTTP"] = cdp_http

    pages = [p for p in raw_cdp.list_pages() if p.get("type") == "page"]
    if not pages:
        raise RuntimeError(f"no_open_page: {request.channel} 디버그 크롬에 열린 탭 없음")
    tab = raw_cdp.attach(pages[0])
    executed: list[dict] = []
    try:
        tab.send("Page.bringToFront")
        for step in plan_send_steps(request.channel):
            candidates = _selector_js_candidates(step.site, step.selector_purpose)
            value = getattr(request, step.value_field) if step.value_field else None
            result = tab.eval(_STEP_JS % {
                "candidates": json.dumps(candidates, ensure_ascii=False),
                "action": json.dumps(step.action),
                "value": json.dumps(value, ensure_ascii=False),
            })
            executed.append({"step": step.selector_purpose, "result": result})
            if not (isinstance(result, dict) and result.get("ok")):
                raise RuntimeError(f"step_failed: {step.selector_purpose} — {result}")
            time.sleep(1.2)  # 사람 속도(SOT 불변식 2 — 봇처럼 굴지 않는다)
        return {"executed": executed}
    finally:
        tab.close()


# :has-text 는 CSS 표준이 아니므로 라벨 후보는 텍스트 스캔으로 처리한다.
_STEP_JS = """
(() => {
  const candidates = %(candidates)s;
  const action = %(action)s;
  const value = %(value)s;
  const byLabel = (sel) => {
    const m = sel.match(/^([a-z]+):has-text\\("(.+)"\\)$/);
    if (!m) return null;
    return [...document.querySelectorAll(m[1])].find(
      (el) => el.textContent && el.textContent.trim().includes(m[2]) && !el.disabled
    ) || null;
  };
  let el = null, used = null;
  for (const sel of candidates) {
    el = byLabel(sel) || (sel.includes(':has-text') ? null : document.querySelector(sel));
    if (el) { used = sel; break; }
  }
  if (!el) return { ok: false, error: 'selector_not_found', tried: candidates };
  if (action === 'fill') {
    el.focus();
    document.execCommand('selectAll', false, null);
    document.execCommand('insertText', false, value);
    return { ok: true, used, filled: (el.value || el.textContent || '').length };
  }
  el.scrollIntoView({ block: 'center' });
  el.click();
  return { ok: true, used, clicked: true };
})()
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SOT28 자동발송 실행기 (기본 dry-run)")
    parser.add_argument("--request-json", required=True)
    parser.add_argument("--live", action="store_true", help="게이트 통과 시 실제 발송 클릭")
    parser.add_argument("--policy", default=None)
    parser.add_argument("--ledger", default=None)
    args = parser.parse_args(argv)

    try:
        policy = load_policy(args.policy)
        request = _load_request(Path(args.request_json))
    except (AutoSendPolicyError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2

    ledger = SendLedger(Path(args.ledger) if args.ledger else DEFAULT_LEDGER_PATH)
    decision = evaluate_send(request, policy, ledger)
    if not decision.allowed:
        print(json.dumps(
            {"ok": False, "blocked": True, "reasons": list(decision.reasons)},
            ensure_ascii=False,
        ))
        return 3

    steps = [
        {"action": s.action, "selector": s.selector_purpose} for s in plan_send_steps(request.channel)
    ]
    if not args.live:
        ledger.append(
            candidate_key=request.candidate_key, channel=request.channel,
            position_id=request.position_id, body=request.body, mode="dry_run",
        )
        print(json.dumps(
            {"ok": True, "mode": "dry_run", "allowed": True, "planned_steps": steps},
            ensure_ascii=False,
        ))
        return 0

    try:
        outcome = _execute_live(request, policy)
    except Exception as exc:  # 실행 실패는 원장에 남기지 않는다(발송 미확정)
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    ledger.append(
        candidate_key=request.candidate_key, channel=request.channel,
        position_id=request.position_id, body=request.body, mode="live",
    )
    print(json.dumps(
        {"ok": True, "mode": "live", "sent": True, "steps": outcome["executed"]},
        ensure_ascii=False,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
