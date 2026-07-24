"""전역 기본 엔진·모델 (디스코드 /model 의 상태 계층).

사장님 /st: "Codex·Claude 및 모델을 /model 로 선택". 적용 범위 = 전역 기본값
1세트(§0.16 합리적 기본). job 명령이 agent:/model: 를 명시하지 않으면 이 기본값을
쓴다(명시하면 그 job 만 예외 — fleet_args 단위1).

- **조회(get_default)**: 파일이 없거나 손상이면 빌트인 기본으로 fail-safe 폴백
  (조회가 시스템을 멈추면 안 된다).
- **쓰기(set_default)**: engine·model 을 fail-closed 검증(agent 와 동일 규칙:
  engine 은 codex|claude, model 은 형식 게이트). 무효면 EngineModelError.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

__all__ = ["EngineModelError", "get_default", "set_default", "ENGINES"]


class EngineModelError(ValueError):
    """엔진/모델 값이 유효하지 않을 때(fail-closed 쓰기)."""


ENGINES: tuple[str, ...] = ("codex", "claude")
# fleet_args.py 의 model 형식 게이트와 동일: 1~64자, 영숫자 시작, . _ - 허용.
_MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
# SOT-29 §1: 실행기 기본은 codex. 엔진별 빌트인 기본 모델.
_DEFAULT_ENGINE = "codex"
_BUILTIN_MODEL: dict[str, str] = {"codex": "gpt-5.5", "claude": "claude-sonnet-5"}


def _builtin() -> dict[str, str]:
    return {"engine": _DEFAULT_ENGINE, "model": _BUILTIN_MODEL[_DEFAULT_ENGINE]}


def _validate(engine: str, model: str) -> None:
    if engine not in ENGINES:
        raise EngineModelError(f"engine 은 {ENGINES} 만 허용합니다")
    if not isinstance(model, str) or not _MODEL_RE.fullmatch(model):
        raise EngineModelError("model 형식 오류(1~64자, 영숫자로 시작, . _ - 허용)")


def get_default(path: str | Path) -> dict[str, str]:
    """전역 기본 {engine, model}. 파일 부재·손상·무효는 빌트인으로 폴백(fail-safe)."""
    p = Path(path)
    if not p.exists():
        return _builtin()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        engine = data["engine"]
        model = data["model"]
        _validate(engine, model)
    except (json.JSONDecodeError, KeyError, TypeError, OSError, EngineModelError):
        return _builtin()
    return {"engine": engine, "model": model}


def set_default(path: str | Path, *, engine: str, model: str) -> dict[str, str]:
    """전역 기본을 갱신. 무효 engine/model 은 fail-closed 거부."""
    _validate(engine, model)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"engine": engine, "model": model}, ensure_ascii=False),
        encoding="utf-8",
    )
    return {"engine": engine, "model": model}
