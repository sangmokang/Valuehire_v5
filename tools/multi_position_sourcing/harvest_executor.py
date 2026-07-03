"""PC-D5 — 라이브 ExecuteHarvestItem 어댑터.

상시 Harvest 이음매(``harvest_runner.run_harvest_cycle``)는 ``execute_item``
(``ExecuteHarvestItem`` = ``HarvestItem → Iterable[profile]``)을 주입받는데, 이를 만족하는
라이브 구현자가 리포에 없었다(테스트 로컬 함수만 존재). 라이브 검색기
``GuardedPortalSearchRunner``(``portal_runtime.py``)는 ``run_keyword_search(keyword) →
GuardedSearchResult`` 계약이라 드롭인이 안 됐다 — 이 어댑터가 그 이음매를 채운다.

핵심 규칙(SOT2, 봇 금지):
  - ``HarvestItem`` 은 segment_id + channel 만 갖고 keyword 가 없다. 코드베이스에 segment→keyword
    매핑이 없으므로 ``keywords_for_segment`` 를 주입받는다.
  - 챌린지(세션락·authwall·재인증·사이트중단)를 감지하면 그 아이템은 **즉시 STOP** — 빈 반환 +
    사유를 ``stops`` 에 기록한다. 챌린지 후 다음 키워드를 계속 두드리지 않는다(기계적 반복 금지).
  - 이 어댑터는 브라우저/네트워크 수명주기를 소유하지 않는다. ``runner_for_channel`` 이 채널별
    러너를 지연 생성한다(``portal_queue_executor.make_execute_item`` 참조 패턴).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .harvest_runner import HarvestItem
from .models import Channel, SegmentId
from .portal_runtime import GuardedPortalSearchRunner, GuardedSearchResult

# not_ready/error 는 그 자체론 STOP 이 아니다 — reauth_cause(재인증/세션락/로그인 리다이렉트)가
# 함께 있거나 pause_site(사이트 중단)일 때만 챌린지로 판정한다.
_REAUTH_STATUSES = frozenset({"not_ready", "error"})


def _stop_reason(result: GuardedSearchResult) -> str:
    """이 검색 결과가 '챌린지라 STOP' 이면 사유 문자열을, 아니면 빈 문자열을 돌려준다."""
    if result.pause_site:
        return f"pause_site:{result.reason or result.reauth_cause or result.status}"
    if result.status in _REAUTH_STATUSES and result.reauth_cause:
        return f"{result.status}:{result.reauth_cause}"
    if result.status == "error":
        return f"error:{result.reason}"
    return ""


@dataclass(frozen=True)
class HarvestStopSignal:
    """한 HarvestItem 이 챌린지로 STOP 된 사건(드라이버가 사이트 양보/중단 판단에 소비)."""

    channel: Channel
    segment_id: SegmentId
    reason: str


class HarvestSearchExecutor:
    """``GuardedPortalSearchRunner`` 를 harvest 계약(``ExecuteHarvestItem``)으로 감싼다.

    ``executor(item)`` (코루틴) 은 ``HarvestItem`` 을 받아 segment 키워드들을 라이브 검색하고
    발견 프로필(``candidate_cards``)들의 튜플을 돌려준다. 챌린지 감지 시 그 아이템은 빈 튜플을
    돌려주고 사유를 ``stops`` 에 남긴다. ``ExecuteHarvestItem`` 계약을 만족하므로
    ``run_harvest_cycle(execute_item=executor, ...)`` 에 그대로 꽂힌다.
    """

    def __init__(
        self,
        *,
        runner_for_channel: Callable[[Channel], GuardedPortalSearchRunner],
        keywords_for_segment: Callable[[SegmentId], Sequence[str]],
        searches_today: int = 0,
    ) -> None:
        self._runner_for_channel = runner_for_channel
        self._keywords_for_segment = keywords_for_segment
        self._searches_today = searches_today
        self.stops: list[HarvestStopSignal] = []

    async def __call__(self, item: HarvestItem) -> tuple[object, ...]:
        keywords = tuple(self._keywords_for_segment(item.segment_id))
        if not keywords:
            return ()

        runner = self._runner_for_channel(item.channel)
        collected: list[object] = []
        for keyword in keywords:
            result = await runner.run_keyword_search(
                keyword, searches_today=self._searches_today
            )
            reason = _stop_reason(result)
            if reason:
                # 챌린지/재인증/사이트중단 → 봇처럼 계속 두드리지 않는다. 즉시 STOP.
                self.stops.append(
                    HarvestStopSignal(
                        channel=item.channel, segment_id=item.segment_id, reason=reason
                    )
                )
                return ()
            if result.status == "searched":
                self._searches_today += 1
                collected.extend(result.candidate_cards)
        return tuple(collected)
