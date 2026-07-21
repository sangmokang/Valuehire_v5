"""AC-7 — 쓰기형 명령 확인 게이트 G5 (goal: discord-single-bot-console §7 G5·§11 AC-7).

"확인 없이 실행되는 경로가 하나도 없어야 한다." 이 모듈은 그 불변식을 강제하는
순수 상태기다(부작용 0 — 실제 실행/DB 변경은 호출부가 confirm() 가 승인한 뒤에만 한다).

- create_pending(action, summary, actor, now): 변경 요약을 담은 대기 건 생성 → nonce 발급.
- confirm(store, nonce, actor, now): 아래 전부 만족해야 execute=True.
  · 존재하는 대기 건
  · 같은 actor(다른 사람 대신 확인 거부)
  · 만료 전(TTL)
  · 미사용(단일 사용 — 같은 확인 2번째는 거부)
- 만료·부재·타인·재사용 = execute=False + 사유. 감사 로그 이벤트 반환.
- fail-closed: 알 수 없는 상황 전부 미실행.
"""

from __future__ import annotations

import unittest

from tools.multi_position_sourcing.bot_confirm_gate import (
    ConfirmGateStore,
    CONFIRM_TTL_SECONDS,
    confirm,
    create_pending,
)

OWNER = "814353841088757800"
OTHER = "222222222222222222"


class CreateTests(unittest.TestCase):
    def test_create_returns_nonce_and_stores_summary(self) -> None:
        store = ConfirmGateStore()
        pending = create_pending(
            store, action="invoice", summary="계산서 3건 발행", actor=OWNER, now=1000)
        self.assertTrue(pending.nonce)
        self.assertEqual(store.get(pending.nonce).summary, "계산서 3건 발행")
        self.assertEqual(store.get(pending.nonce).actor, OWNER)

    def test_distinct_nonces(self) -> None:
        store = ConfirmGateStore()
        a = create_pending(store, action="weekly", summary="s", actor=OWNER, now=1, seed="a")
        b = create_pending(store, action="weekly", summary="s", actor=OWNER, now=2, seed="b")
        self.assertNotEqual(a.nonce, b.nonce)


class ConfirmTests(unittest.TestCase):
    def _mk(self):
        store = ConfirmGateStore()
        pending = create_pending(
            store, action="priority_set", summary="우선순위 P1→P0", actor=OWNER, now=1000)
        return store, pending

    def test_valid_confirm_executes_once(self) -> None:
        store, pending = self._mk()
        r = confirm(store, pending.nonce, actor=OWNER, now=1005)
        self.assertTrue(r.execute)
        self.assertEqual(r.action, "priority_set")

    def test_second_confirm_rejected(self) -> None:
        store, pending = self._mk()
        confirm(store, pending.nonce, actor=OWNER, now=1005)
        r2 = confirm(store, pending.nonce, actor=OWNER, now=1006)
        self.assertFalse(r2.execute)
        self.assertIn("이미", r2.reason)

    def test_other_actor_rejected(self) -> None:
        store, pending = self._mk()
        r = confirm(store, pending.nonce, actor=OTHER, now=1005)
        self.assertFalse(r.execute)
        # 대기 건은 소모되지 않는다 — 올바른 사람은 이후에도 확인 가능.
        r2 = confirm(store, pending.nonce, actor=OWNER, now=1006)
        self.assertTrue(r2.execute)

    def test_expired_rejected(self) -> None:
        store, pending = self._mk()
        r = confirm(store, pending.nonce, actor=OWNER, now=1000 + CONFIRM_TTL_SECONDS + 1)
        self.assertFalse(r.execute)
        self.assertIn("만료", r.reason)

    def test_unknown_nonce_rejected(self) -> None:
        store = ConfirmGateStore()
        r = confirm(store, "does-not-exist", actor=OWNER, now=1)
        self.assertFalse(r.execute)

    def test_empty_or_bad_nonce_rejected(self) -> None:
        store, _ = self._mk()
        for bad in ("", "   ", None):
            r = confirm(store, bad, actor=OWNER, now=1005)  # type: ignore[arg-type]
            self.assertFalse(r.execute)

    def test_confirm_emits_audit_event(self) -> None:
        store, pending = self._mk()
        r = confirm(store, pending.nonce, actor=OWNER, now=1005)
        self.assertEqual(r.audit["action"], "priority_set")
        self.assertEqual(r.audit["actor"], OWNER)
        self.assertTrue(r.audit["executed"])
        self.assertIn("at", r.audit)


class NoImplicitExecuteTests(unittest.TestCase):
    """확인이라는 명시적 단계 없이 실행으로 이어지는 경로가 없음을 봉인."""

    def test_pending_alone_does_not_execute(self) -> None:
        store = ConfirmGateStore()
        create_pending(store, action="invoice", summary="s", actor=OWNER, now=1)
        # 대기 건만으로는 어떤 실행 신호도 없다 — confirm 을 거치지 않으면 execute 없음.
        self.assertEqual(len(store._pending), 1)  # noqa: SLF001 — 테스트 한정 내부 점검
        # 만료 시각 이후 자동 실행되지 않는다(대기 건은 그냥 무효화될 뿐).
        r = confirm(store, next(iter(store._pending)), actor=OWNER,  # noqa: SLF001
                    now=1 + CONFIRM_TTL_SECONDS + 10)
        self.assertFalse(r.execute)


if __name__ == "__main__":
    unittest.main()
