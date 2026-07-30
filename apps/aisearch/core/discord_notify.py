"""V1 5차 결함 ③ — 차단 알림 Discord notifier 어댑터.

goal: docs/engineering/aisearch-fleet-goal-2026-07-28.md AC-7 — 캡차/2FA/
체크포인트 차단 시 Discord 채널로 알림한다(화면 출력만으로는 계약 위반).

- **주입식 클라이언트**: 이 모듈은 네트워크를 직접 열지 않는다. webhook/봇
  API 로 실제 발신하는 ``send(payload)`` callable 을 주입받는다(테스트는
  페이크 send — 실 네트워크 0).
- **--live 게이트**: 실제 발신은 live=True 일 때만. 기본(live=False)은
  payload 를 ``planned`` 에 계획만 기록한다(조용한 발신 금지 — SOT 발송
  불변식과 동일 원칙). live=True 인데 send 미주입이면 fail-closed.
- payload 계약: {"channel_id": <차단 알림 채널>, "content": <사유 포함 본문>,
  "reason": <원본 사유>} — InterventionMonitor 의 Notifier 프로토콜(notify)
  을 그대로 구현한다.
"""
from __future__ import annotations

import sys
from typing import Callable, Optional

__all__ = ["DISCORD_BLOCK_CHANNEL_ID", "DiscordNotifier", "DiscordNotifyError"]

#: 차단 알림 Discord 채널 — 오너 지정(2026-07-28 V1 5차 지시).
DISCORD_BLOCK_CHANNEL_ID = "1512503041448743092"


class DiscordNotifyError(RuntimeError):
    """notifier 구성/입력 오류 — 전부 fail-closed(조용한 무시 금지)."""


class DiscordNotifier:
    """InterventionMonitor 에 주입되는 차단 알림 어댑터.

    - live=False(기본): 발신 계획(payload)만 ``planned`` 에 기록 — 발신 0.
    - live=True: 주입된 send(payload) 호출 — 보낸 payload 는 ``sent`` 에 보존.
    어느 모드든 stderr 즉시 표면화는 유지한다(기존 StderrNotifier 대체).
    """

    def __init__(
        self,
        send: Optional[Callable[[dict], object]] = None,
        *,
        channel_id: str = DISCORD_BLOCK_CHANNEL_ID,
        live: bool = False,
    ) -> None:
        if live and send is None:
            raise DiscordNotifyError(
                "live 발신에는 Discord send 클라이언트가 필요하다(fail-closed) — "
                "send 미주입 상태로 live 를 켤 수 없다"
            )
        if not isinstance(channel_id, str) or not channel_id.strip():
            raise DiscordNotifyError(f"channel_id 가 비어 있다(fail-closed): {channel_id!r}")
        self._send = send
        self._channel_id = channel_id
        self._live = live
        #: live 발신 payload 보존(원장 증거).
        self.sent: list[dict] = []
        #: live 아님 — 발신 "계획"만 기록(실 발신 0).
        self.planned: list[dict] = []

    def build_payload(self, reason: str) -> dict:
        if not isinstance(reason, str) or not reason.strip():
            raise DiscordNotifyError(f"차단 사유가 비어 있다(fail-closed): {reason!r}")
        return {
            "channel_id": self._channel_id,
            "content": f"[aisearch 차단 알림] {reason}",
            "reason": reason,
        }

    def notify(self, message: str) -> None:
        """InterventionMonitor Notifier 계약 — 차단 사유 1건을 알린다."""
        payload = self.build_payload(message)
        # 기존 stderr 표면화 유지 — Discord 경로와 무관하게 즉시 보인다.
        print(f"[aisearch][차단 알림] {message}", file=sys.stderr)
        if self._live:
            assert self._send is not None  # __init__ 에서 fail-closed 보장
            self._send(payload)
            self.sent.append(payload)
        else:
            self.planned.append(payload)
