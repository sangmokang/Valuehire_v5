"""SOT-28 §12 현상6 — "로그인됐는데 꺼짐" 정조준 (TODO-2).

portal_worker.stop() 이 linkedin_rps 외 채널(사람인·잡코리아)에서
`context.close()` 를 호출해 로그인 세션이 담긴 탭/창을 닫아 버렸다
(portal_worker.py:656-670, 2026-07-17 SOT-28 매트릭스 ⛔ 판정).
훅(guards/login.py)은 러너 '내부' 의 close 를 원리적으로 못 막으므로
유일한 방어는 이 코드 수정이다.

인수 기준(기계 단언):
- saramin/jobkorea 채널에서 start() → stop() 후 context.close() 호출 0회.
- linkedin_rps 는 원래도 close 하지 않았음을 회귀로 봉인.
- stop() 의 나머지 정리(프로필 lock 해제, _started/_context 리셋)는 그대로.
- 단, 세션을 보존한 채 같은 프로필 재-launch 는 실제 playwright 가 거부하므로
  "재기동 가능"이 아니라 "lock 재획득 가능 + 재-launch 미지원(CDP 재부착이 정답,
  TODO-2b)"이 정직한 계약이다 (V1 적대검증 반례 C2).
"""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.multi_position_sourcing.portal_worker import PortalWorker, PortalWorkerConfig


class FakeContext:
    def __init__(self) -> None:
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


class FakeChromium:
    """실제 playwright 의미론 모사(V1 반례 2 봉인): 같은 user-data-dir 에 살아있는
    (close 안 된) persistent context 가 있으면 재-launch 는 "profile already in use" 로
    거부된다 — 세션 보존과 같은 프로필 재기동은 양립 불가(후속 TODO-2b: CDP 재부착)."""

    def __init__(self, context: FakeContext) -> None:
        self._context = context
        self.launch_calls = 0

    async def launch_persistent_context(self, *_args, **_kwargs) -> FakeContext:
        self.launch_calls += 1
        if self.launch_calls > 1 and self._context.close_calls == 0:
            raise RuntimeError("browser is already in use for user data dir")
        return self._context

    async def connect_over_cdp(self, _endpoint: str) -> object:
        class _FakeBrowser:
            contexts = ()

            async def new_context(self_inner) -> FakeContext:
                return self._context

        return _FakeBrowser()


class FakePlaywright:
    def __init__(self, context: FakeContext) -> None:
        self.chromium = FakeChromium(context)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class PortalWorkerSessionPreserveTests(unittest.TestCase):
    def _worker(self, channel: str, root: str) -> tuple[PortalWorker, FakeContext]:
        context = FakeContext()
        config = PortalWorkerConfig(
            channel=channel,
            profile_root=Path(root),
            # linkedin_rps 는 start() 에서 browser_policy 검문소(규칙=9222)와 대조한다.
            # playwright 는 가짜라 실제 연결은 일어나지 않는다.
            chrome_cdp_endpoint="http://127.0.0.1:9222",
        )
        return PortalWorker(config, playwright=FakePlaywright(context)), context

    def test_stop_preserves_saramin_session_context(self) -> None:
        with TemporaryDirectory(prefix="pwsp_") as root:
            worker, context = self._worker("saramin", root)

            async def flow() -> None:
                await worker.start()
                await worker.stop()

            _run(flow())
            self.assertEqual(
                context.close_calls, 0,
                "stop() 이 사람인 로그인 세션 탭(context)을 닫았다 — SOT-28 §4 세션 상시 유지 위반",
            )

    def test_stop_preserves_jobkorea_session_context(self) -> None:
        with TemporaryDirectory(prefix="pwsp_") as root:
            worker, context = self._worker("jobkorea", root)

            async def flow() -> None:
                await worker.start()
                await worker.stop()

            _run(flow())
            self.assertEqual(context.close_calls, 0)

    def test_stop_releases_lock_but_same_profile_relaunch_is_unsupported(self) -> None:
        # V1 적대검증(2026-07-17) 반례 2 봉인: 세션을 보존한 채 같은 프로필로
        # launch_persistent_context 재호출은 실제 playwright 가 거부한다.
        # 현재 계약 = stop() 후 프로필 lock 재획득은 가능하되, 살아있는 브라우저에
        # 대한 재접속은 재-launch 가 아니라 CDP 재부착(후속 TODO-2b)이어야 한다.
        # 프로덕션 호출자는 stop() 후 같은 스코프에서 start() 를 다시 부르지 않는다
        # (V1 CALL_SITE_ANALYSIS: stop 은 __aexit__ 로만 호출됨).
        from tools.multi_position_sourcing.portal_worker import ProfileLock

        with TemporaryDirectory(prefix="pwsp_") as root:
            worker, context = self._worker("saramin", root)

            async def flow() -> str:
                await worker.start()
                await worker.stop()
                # lock 은 반납되어 재획득 가능해야 한다.
                relock = ProfileLock(worker.config)
                relock.acquire()
                relock.release()
                try:
                    await worker.start()
                except RuntimeError as exc:
                    await worker.stop()
                    return str(exc)
                return ""

            message = _run(flow())
            self.assertEqual(context.close_calls, 0)
            self.assertIn("already in use", message,
                          "같은 프로필 재-launch 는 미지원임을 테스트가 정직하게 모델링해야 한다")

    def test_linkedin_rps_stop_never_closes_context_regression(self) -> None:
        with TemporaryDirectory(prefix="pwsp_") as root:
            worker, context = self._worker("linkedin_rps", root)

            async def flow() -> None:
                await worker.start()
                await worker.stop()

            _run(flow())
            self.assertEqual(context.close_calls, 0)


if __name__ == "__main__":
    unittest.main()
