"""AC-6 — admin.valuehire.cc 후보 등록 API 클라이언트 (D12 확정: 신규 API, 2026-07-31).

서버 계약 정본: valuehire_v4 app/api/aisearch/register/route.ts (커밋 db7429c2, PR#744)
- POST {base_url}/api/aisearch/register
- 인증: x-internal-key 헤더 (키는 호출자가 주입 — 하드코딩 금지)
- 필수: name, profile_url(https?://), match_score(0~100, 60 미만 서버 거부), why_fit, channel
- 선택: profile_summary, jd_id, jd_title, skills[str]

클라이언트 규율: 서버가 거부할 payload 는 전송 전에 거부(fail-fast), 표 밖 필드 명시적
거부(goal §6 E12 catch-all), dry-run 기본(live=True 없이는 전송 0 — SOT28 fail-closed 관례).
"""
from __future__ import annotations

import json
import math
from typing import Any, Callable, Mapping

REGISTER_PATH = "/api/aisearch/register"
MIN_MATCH_SCORE = 60  # 서버 MIN_MATCH_SCORE 와 동일 (route.ts)

_REQUIRED_FIELDS = ("name", "profile_url", "match_score", "why_fit", "channel")
_OPTIONAL_FIELDS = ("profile_summary", "jd_id", "jd_title", "skills")
_ALLOWED_FIELDS = frozenset(_REQUIRED_FIELDS + _OPTIONAL_FIELDS)


class AdminApiContractError(ValueError):
    """전송 전 계약 위반 — 서버에 도달하기 전에 거부한다."""


class AdminApiResponseError(RuntimeError):
    """서버가 등록을 거부했거나 응답이 계약과 다르다."""


def _require_text(candidate: Mapping[str, Any], field: str) -> str:
    value = candidate.get(field)
    if not isinstance(value, str) or not value.strip():
        raise AdminApiContractError(f"{field} is required (non-empty str)")
    return value.strip()


def _validate_score(value: Any) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AdminApiContractError("match_score must be a number")
    if isinstance(value, float) and math.isnan(value):
        raise AdminApiContractError("match_score must not be NaN")
    if not 0 <= value <= 100:
        raise AdminApiContractError("match_score must be within 0..100")
    if value < MIN_MATCH_SCORE:
        raise AdminApiContractError(
            f"match_score {value} < {MIN_MATCH_SCORE} — 서버가 거부하므로 전송하지 않는다"
        )
    return value


def build_register_request(
    candidate: Mapping[str, Any],
    *,
    base_url: str,
    internal_key: str,
) -> dict[str, Any]:
    if not isinstance(internal_key, str) or not internal_key.strip():
        raise AdminApiContractError("internal_key is required (주입 필수 — 하드코딩 금지)")
    if not isinstance(base_url, str) or not base_url.startswith("https://"):
        raise AdminApiContractError("base_url must be https://")

    unknown = set(candidate) - _ALLOWED_FIELDS
    if unknown:
        raise AdminApiContractError(f"unknown fields rejected (E12 catch-all): {sorted(unknown)}")

    body: dict[str, Any] = {
        "name": _require_text(candidate, "name"),
        "profile_url": _require_text(candidate, "profile_url"),
        "match_score": _validate_score(candidate.get("match_score")),
        "why_fit": _require_text(candidate, "why_fit"),
        "channel": _require_text(candidate, "channel"),
    }
    if not body["profile_url"].lower().startswith(("http://", "https://")):
        raise AdminApiContractError("profile_url must be http(s)")

    if "profile_summary" in candidate:
        value = candidate["profile_summary"]
        if not isinstance(value, str):
            raise AdminApiContractError("profile_summary must be str")
        body["profile_summary"] = value
    for field in ("jd_id", "jd_title"):
        if field in candidate:
            value = candidate[field]
            if not isinstance(value, str) or not value:
                raise AdminApiContractError(f"{field} must be non-empty str")
            body[field] = value
    if "skills" in candidate:
        skills = candidate["skills"]
        if not isinstance(skills, list) or any(not isinstance(s, str) for s in skills):
            raise AdminApiContractError("skills must be list[str]")
        body["skills"] = skills

    return {
        "method": "POST",
        "url": base_url.rstrip("/") + REGISTER_PATH,
        "headers": {"x-internal-key": internal_key, "content-type": "application/json"},
        "json": body,
    }


class AdminApiRecorder:
    """admin.valuehire.cc 등록 기록기. 기본 dry-run — live=True 없이는 전송 0."""

    def __init__(
        self,
        *,
        base_url: str,
        internal_key: str,
        transport: Callable[[Mapping[str, Any]], Mapping[str, Any]],
        live: bool = False,
    ) -> None:
        self._base_url = base_url
        self._internal_key = internal_key
        self._transport = transport
        self._live = bool(live)

    def register(self, candidate: Mapping[str, Any]) -> dict[str, Any]:
        request = build_register_request(
            candidate, base_url=self._base_url, internal_key=self._internal_key
        )
        if not self._live:
            return {"status": "dry_run", "recorded": False, "request": request}

        response = self._transport(request)
        status = response.get("status")
        try:
            payload = json.loads(response.get("text", ""))
        except (TypeError, ValueError) as exc:
            raise AdminApiResponseError(
                f"non-JSON response (status={status})"
            ) from exc
        if status != 200 or payload.get("ok") is not True:
            raise AdminApiResponseError(
                f"register rejected (status={status}): {payload.get('error', 'unknown')}"
            )
        return {"status": "recorded", "recorded": True, "response": payload}
