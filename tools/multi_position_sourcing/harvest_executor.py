"""PC-D5 — 라이브 ExecuteHarvestItem 어댑터.

상시 Harvest 이음매(``harvest_runner.run_harvest_cycle``)는 ``execute_item``
(``ExecuteHarvestItem`` = ``HarvestItem → Iterable[profile]``)을 주입받는데, 이를 만족하는
라이브 구현자가 리포에 없었다(테스트 로컬 함수만 존재). 라이브 검색기
``GuardedPortalSearchRunner``(``portal_runtime.py``)는 ``run_keyword_search(keyword) →
GuardedSearchResult`` 계약이라 드롭인이 안 됐다 — 이 어댑터가 그 이음매를 채운다.

핵심 규칙(SOT2, 봇 금지):
  - ``HarvestItem`` 은 segment_id + channel 만 갖고 keyword 가 없다. 코드베이스에 segment→keyword
    매핑이 없으므로 ``keywords_for_segment`` 를 주입받는다.
  - STOP 규율은 같은 러너를 감싸는 기존 어댑터 ``portal_queue_executor.execute_queue_item`` 선례와
    일치한다: ``searched`` 만 다음 키워드로 진행하고, 그 외 모든 status(not_ready·pacing_blocked·
    error·selector_missing) 또는 pause_site 는 **즉시 halt**한다. 챌린지(세션락·authwall·재인증)·
    일일 상한·DOM 오류를 만나면 남은 키워드를 계속 두드리지 않는다(기계적 반복 금지).
  - STOP 해도 그 전에 이미 찾은 카드는 버리지 않는다(harvest 는 발견 즉시 저장=차감0). STOP 사유는
    ``stops`` 에 기록해 드라이버(PC-D2b/PC-K6)가 사이트 양보/중단을 판단하게 한다.
  - 이 어댑터는 브라우저/네트워크 수명주기를 소유하지 않는다. ``runner_for_channel`` 이 채널별
    러너를 지연 생성한다(``portal_queue_executor.make_execute_item`` 참조 패턴).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .harvest_runner import HarvestItem
from .models import Channel, SegmentId
from .portal_runtime import GuardedPortalSearchRunner, GuardedSearchResult


def _stop_reason(result: GuardedSearchResult) -> str:
    """비-``searched`` 결과의 STOP 사유 문자열(관측·디버깅용). pause_site 를 최우선 표기."""
    if result.pause_site:
        return f"pause_site:{result.reason or result.reauth_cause or result.status}"
    if result.reauth_cause:
        return f"{result.status}:{result.reauth_cause}"
    return f"{result.status}:{result.reason}" if result.reason else result.status


@dataclass(frozen=True)
class HarvestStopSignal:
    """한 HarvestItem 이 STOP 된 사건(드라이버가 사이트 양보/중단 판단에 소비)."""

    channel: Channel
    segment_id: SegmentId
    reason: str


class HarvestSearchExecutor:
    """``GuardedPortalSearchRunner`` 를 harvest 계약(``ExecuteHarvestItem``)으로 감싼다.

    ``executor(item)`` (코루틴) 은 ``HarvestItem`` 을 받아 segment 키워드들을 라이브 검색하고
    발견 프로필(``candidate_cards``)들의 튜플을 돌려준다. 비-``searched`` 상태(챌린지·상한·오류)나
    ``pause_site`` 를 만나면 즉시 멈추고(남은 키워드 안 두드림) 사유를 ``stops`` 에 남긴다 — 그때까지
    모은 카드는 보존한다. ``ExecuteHarvestItem`` 계약을 만족하므로
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
            # searched 일 때만 카드를 모으고 다음 키워드로 진행한다(선례 portal_queue_executor 와
            # 동일 — searched 는 pause_site 를 세우지 않는다). 그 외는 아래에서 즉시 STOP.
            if result.status == "searched":
                self._searches_today += 1
                collected.extend(result.candidate_cards)
                continue
            # 그 외 모든 상태(챌린지·상한·오류) 또는 pause_site → 즉시 STOP.
            # 봇처럼 남은 키워드를 두드리지 않는다(SOT2). 이미 찾은 카드는 보존.
            collected.extend(result.candidate_cards)
            self.stops.append(
                HarvestStopSignal(
                    channel=item.channel,
                    segment_id=item.segment_id,
                    reason=_stop_reason(result),
                )
            )
            break
        return tuple(collected)
