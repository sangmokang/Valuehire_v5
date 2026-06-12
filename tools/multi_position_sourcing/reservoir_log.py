"""저수지 모델 — 관측가능성 로그 (단계 2, 모든 단계 공통).

5라인(Harvest→Index→Match→Calibrate→Send)의 모든 경계와 모든 fail-closed 분기에 구조화 로그
1줄(JSON)을 남긴다. "어느 머신·어느 라인·어느 세그먼트·어느 사이트에서 몇 건이 왜 빠졌나"를
로그만 보고 즉시 답할 수 있어야 한다. 실패는 조용히 넘기지 않는다(fail-closed).

이 스키마 자체가 verify 계약이다: 필드 누락·잘못된 status/line·이유 없는 실패는 RED.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

# 5라인 경계.
RESERVOIR_LINES: tuple[str, ...] = ("harvest", "index", "match", "calibrate", "send")
RESERVOIR_STATUSES: tuple[str, ...] = ("ok", "fail", "skip")
RESERVOIR_LOG_FIELDS: tuple[str, ...] = (
    "ts",
    "run_id",
    "machine",
    "segment_id",
    "site",
    "line",
    "in_count",
    "out_count",
    "dropped_count",
    "status",
    "fail_reason",
    "latency_ms",
)

_INT_FIELDS = ("in_count", "out_count", "dropped_count", "latency_ms")


class ReservoirLogContractError(ValueError):
    """관측 로그 스키마 계약 위반(필드 누락·잘못된 값·이유 없는 실패)."""


def make_reservoir_log_record(
    *,
    ts: str,
    run_id: str,
    machine: str,
    segment_id: str,
    site: str,
    line: str,
    in_count: int,
    out_count: int,
    dropped_count: int,
    status: str,
    fail_reason: str = "",
    latency_ms: int = 0,
) -> dict:
    """12필드를 모두 가진 로그 레코드(dict)를 만든다. 키워드 강제로 필드 누락을 막는다."""
    return {
        "ts": ts,
        "run_id": run_id,
        "machine": machine,
        "segment_id": segment_id,
        "site": site,
        "line": line,
        "in_count": int(in_count),
        "out_count": int(out_count),
        "dropped_count": int(dropped_count),
        "status": status,
        "fail_reason": fail_reason,
        "latency_ms": int(latency_ms),
    }


def validate_reservoir_log_record(record: Mapping[str, object]) -> None:
    """계약 검증. 위반 시 ``ReservoirLogContractError``.

    - 12필드 모두 존재
    - ``line`` ∈ RESERVOIR_LINES, ``status`` ∈ RESERVOIR_STATUSES
    - 카운트/latency 는 int
    - fail-closed: ``status=='fail'`` 이면 ``fail_reason`` 이 비어 있으면 안 된다(조용한 실패 금지).
    """
    missing = [field for field in RESERVOIR_LOG_FIELDS if field not in record]
    if missing:
        raise ReservoirLogContractError(f"로그 필드 누락: {missing}")
    if record["line"] not in RESERVOIR_LINES:
        raise ReservoirLogContractError(f"알 수 없는 line: {record['line']!r}")
    if record["status"] not in RESERVOIR_STATUSES:
        raise ReservoirLogContractError(f"알 수 없는 status: {record['status']!r}")
    for field in _INT_FIELDS:
        value = record[field]
        if not isinstance(value, int) or isinstance(value, bool):
            raise ReservoirLogContractError(f"{field} 는 int 여야 함: {value!r}")
    if record["status"] == "fail" and not str(record["fail_reason"]).strip():
        raise ReservoirLogContractError("status=fail 인데 fail_reason 이 비었습니다(fail-closed 위반)")


def append_reservoir_log(record: Mapping[str, object], *, root: Path | str, today: str) -> Path:
    """검증을 통과한 레코드를 ``logs/reservoir/<today>.jsonl`` 에 append 한다."""
    validate_reservoir_log_record(record)
    out_dir = Path(root) / "logs" / "reservoir"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{today}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path
