"""그룹 세션 배치 — 이슈 #104 (2026-07-15 사장님 지시).

disearch 로그인 세션 1회를 포지션 1개로 끝내지 않는다:
- 실제 진행 중 포지션 리스트(docs/sot/24-position-jd-sot.json)를 grouping.group_positions()
  에 적용해, 같은 로그인 세션에서 이어 검색할 유사 포지션·미소진 필터 변형을 계산한다.
- fleet_dispatch 가 humansearch 잡 params.group_session 으로 싣고(배선 1),
  fleet_worker 가 큐 idle 일 때 변형을 1건씩 자동 enqueue 한다(배선 2 — 심야 지속).

원칙: 전부 fail-soft — 그룹핑 실패가 원 잡의 enqueue/실행을 절대 막지 않는다.
변형 잡은 group_session 을 상속하지 않는다(1단계 체인 — _enqueue_followup 과 동일 원칙).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .grouping import group_positions
from .job_queue import new_job_payload
from .models import Position

REPO = Path(__file__).resolve().parents[2]
SOT24_PATH = REPO / "docs" / "sot" / "24-position-jd-sot.json"

# 심야 무한 enqueue 방지 캡 — 그룹당 자동 변형은 최대 6건(사람인·잡코리아 표준어 잔여분).
MAX_PENDING_VARIANTS = 6

# humansearch 가 실제로 모는 포털만 변형 대상(링크드인 좌석·public_web 은 별도 스킬 경로).
_VARIANT_CHANNELS: tuple[str, ...] = ("saramin", "jobkorea")

_NUM_RE = re.compile(r"(\d+)")

__all__ = [
    "MAX_PENDING_VARIANTS", "SOT24_PATH", "group_session_params",
    "load_active_positions", "variant_job_payload",
]


def _joined(value: Any) -> str:
    """SOT24 필드(str | list)를 jd_text 조각으로 접는다."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        return " ".join(str(v).strip() for v in value if str(v).strip())
    return ""


def _seniority_from_experience(text: str) -> tuple[int, int]:
    """"경력 5년 이상"/"3~7년" → (min, max). 숫자 없으면 (0, 99) — 잘못 컷하지 않는다."""
    nums = [int(n) for n in _NUM_RE.findall(text or "")]
    if not nums:
        return (0, 99)
    if len(nums) == 1:
        return (nums[0], nums[0] + 5)
    return (min(nums[:2]), max(nums[:2]))


def _position_from_sot24(entry: Mapping[str, Any]) -> Position | None:
    """SOT24 positions[] 항목 1건 → Position. id/URL/JD 텍스트 없으면 None(그룹핑 불가)."""
    position_id = str(entry.get("clickup_task_id") or entry.get("opening_id") or "").strip()
    source_url = str(entry.get("clickup_url") or entry.get("official_url") or "").strip()
    jd_text = " ".join(filter(None, (
        _joined(entry.get("summary")),
        _joined(entry.get("responsibilities")),
        _joined(entry.get("must_have")),
        _joined(entry.get("nice_to_have")),
        _joined(entry.get("search_signals")),
        _joined(entry.get("product_context")),
    ))).strip()
    if not position_id or not source_url.startswith("https://") or not jd_text:
        return None
    seniority = _seniority_from_experience(str(entry.get("experience") or ""))
    must = entry.get("must_have")
    nice = entry.get("nice_to_have")
    return Position(
        position_id=position_id,
        company_name=str(entry.get("company") or "").strip(),
        role_title=str(entry.get("title") or "").strip(),
        jd_text=jd_text,
        seniority_min=seniority[0],
        seniority_max=seniority[1],
        must_haves=tuple(str(m) for m in must) if isinstance(must, (list, tuple)) else (),
        nice_to_haves=tuple(str(n) for n in nice) if isinstance(nice, (list, tuple)) else (),
        source_url=source_url,
    )


def load_active_positions(path: str | Path | None = None) -> tuple[Position, ...]:
    """진행 중 포지션 리스트(SOT24) → Position 튜플. 어떤 실패도 () (fail-soft).

    그룹 세션은 부가 기능 — SOT24 가 깨졌다고 원 잡 enqueue 를 막으면 안 된다.
    """
    target = Path(path) if path is not None else SOT24_PATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        entries = data.get("positions")
        if not isinstance(entries, list):
            return ()
        positions = []
        for entry in entries:
            if isinstance(entry, Mapping):
                p = _position_from_sot24(entry)
                if p is not None:
                    positions.append(p)
        return tuple(positions)
    except Exception:  # noqa: BLE001 — 파일 없음/JSON 깨짐/권한 전부 fail-soft
        return ()


def _matches(position: Position, position_url: str) -> bool:
    """잡 URL ↔ 포지션 매칭 — 정확 일치 또는 position_id 가 URL 경로 세그먼트로 등장."""
    url = (position_url or "").strip()
    if not url:
        return False
    if url.rstrip("/") == position.source_url.rstrip("/"):
        return True
    segments = [s for s in url.split("?")[0].split("/") if s]
    return position.position_id in segments


def group_session_params(
    position_url: str, positions: Sequence[Position],
) -> dict[str, Any] | None:
    """잡 URL 이 속한 그룹의 세션 파라미터. 미매칭/그룹 미발견은 None(fail-soft).

    반환 dict 는 잡 params.group_session 으로 그대로 실린다(JSON 직렬화 가능해야 함).
    pending_variants = 채널별 표준(첫) 키워드는 원 잡이 커버한다고 보고 그 나머지.
    """
    positions = tuple(positions)
    if not positions:
        return None
    target = next((p for p in positions if _matches(p, position_url)), None)
    if target is None:
        return None
    groups = group_positions(positions)
    group = next((g for g in groups if target.position_id in g.position_ids), None)
    if group is None:
        return None
    siblings = [
        p.source_url for p in positions
        if p.position_id in group.position_ids
        and p.position_id != target.position_id and p.source_url
    ]
    variants: list[dict[str, Any]] = []
    for channel in _VARIANT_CHANNELS:
        keywords = group.portal_keywords_by_channel.get(channel, ())
        filters = dict(group.filters_by_channel.get(channel, {}))
        for keyword in keywords[1:]:
            variants.append({"channel": channel, "keyword": keyword, "filters": filters})
    return {
        "group_id": group.group_id,
        "sibling_position_urls": siblings,
        "note": (
            "같은 로그인 세션을 유지한 채 sibling_position_urls 의 유사 포지션도 이어서 "
            "검색할 것(재로그인·세션 초기화 금지). 발송 게이트(SOT28)·양보 원칙(SOT29)은 그대로."
        ),
        "pending_variants": variants[:MAX_PENDING_VARIANTS],
    }


def variant_job_payload(
    base_job: Mapping[str, Any], variant: Mapping[str, Any], *, group_id: str,
) -> dict[str, Any] | None:
    """미소진 필터 변형 1건 → 후속 humansearch 잡 페이로드. 무효는 None(fail-closed).

    - new_job_payload 재사용 — 큐 입구 검증(스킬 화이트리스트·URL·인젝션 차단)을 그대로 통과해야 함.
    - 파생 idempotency 키(group:<id>:variant:<채널>:<키워드>)로 재발사 dedup(이슈 A 선례).
    - group_session 미상속 — 변형 잡이 또 변형을 낳지 않는다(1단계 체인).
    """
    channel = str(variant.get("channel") or "").strip()
    keyword = str(variant.get("keyword") or "").strip()
    if not channel or not keyword or not group_id:
        return None
    filters = variant.get("filters")
    params: dict[str, Any] = {
        "group_id": group_id,
        "variant": {"channel": channel, "keyword": keyword,
                    "filters": dict(filters) if isinstance(filters, Mapping) else {}},
        "idempotency_key": f"group:{group_id}:variant:{channel}:{keyword}"[:160],
    }
    return new_job_payload(
        machine=base_job.get("machine"),
        skill="humansearch",
        position_url=base_job.get("position_url"),
        requested_by=base_job.get("requested_by"),
        role=base_job.get("role"),
        params=params,
        account_key="",  # 자기 스킬 기본 락(default_account_key) — 부모 락 미상속(이슈 D 동일)
    )
