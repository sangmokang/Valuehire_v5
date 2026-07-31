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
from dataclasses import dataclass, replace
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


# 서버(route.ts)는 JS String.trim() — ECMAScript 공백 집합은 U+FEFF(BOM)를 포함하고
# U+0085(NEL)를 포함하지 않는다. Python str.strip() 기본과 다르므로 명시 집합으로 맞춘다.
_JS_WHITESPACE = (
    "\t\n\v\f\r           "
    "       　﻿"
)


def _js_trim(value: str) -> str:
    return value.strip(_JS_WHITESPACE)


def _require_text(candidate: Mapping[str, Any], field: str) -> str:
    value = candidate.get(field)
    if not isinstance(value, str) or not _js_trim(value):
        raise AdminApiContractError(f"{field} is required (non-empty str)")
    return _js_trim(value)


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
    # 서버 internalApiKey.ts:17 — 16자 미만 키는 항상 거부. 여백이 붙은 키는 정확 일치
    # 실패로 401 이 되므로 전송 전에 거부한다.
    if (
        not isinstance(internal_key, str)
        or len(internal_key) < 16
        or _js_trim(internal_key) != internal_key
    ):
        raise AdminApiContractError(
            "internal_key must be >=16 chars, no surrounding whitespace (주입 필수 — 하드코딩 금지)"
        )
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


def _describe(value: Any, limit: int = 200) -> str:
    """모양을 가정하지 않고 안전하게 글자로 만든다.

    오류 메시지를 만들다가 다시 터지는 사고(예: 방금 '사전이 아니다'라고 판정한 값을
    payload.get() 으로 꺼내 AttributeError)를 구조적으로 불가능하게 하는 함수다.
    repr() 자체가 예외를 던지는 값도 있으므로(자체 적대검증에서 발견) 그것까지 삼킨다 —
    이 함수는 어떤 입력에도 절대 예외를 던지지 않는다.
    """
    try:
        text = repr(value)
    except Exception:
        try:
            text = f"<unrepresentable {type(value).__name__}>"
        except Exception:
            text = "<unrepresentable>"
    return text if len(text) <= limit else text[:limit] + "…"


@dataclass(frozen=True)
class RegisterOutcome:
    """dry-run 과 live 가 공유하는 단일 결과 타입 — 호출자가 한 코드로 다룬다."""

    sent: bool
    recorded: bool
    deduped: bool | None
    status: int | None
    request: Mapping[str, Any]
    payload: Mapping[str, Any] | None


def _read_envelope(response: Any) -> tuple[int, str]:
    """전송 계층이 준 봉투를 먼저 검사한다 — 꺼내 쓰기 전에 모양을 확정한다."""
    if not isinstance(response, Mapping):
        raise AdminApiResponseError(
            f"transport must return a mapping: {_describe(response)}"
        )
    status = response.get("status")
    if isinstance(status, bool) or not isinstance(status, int):
        raise AdminApiResponseError(
            f"transport status must be an int: {_describe(status)}"
        )
    text = response.get("text")
    if not isinstance(text, str):
        raise AdminApiResponseError(f"transport text must be a str: {_describe(text)}")
    return status, text


def parse_register_response(response: Any) -> RegisterOutcome:
    """서버 응답을 전송 없이 단독 검사 — build_register_request 와 대칭인 순수 함수.

    엄격함의 방향은 요청과 반대다: 요청은 표 밖 필드를 거부(E12)하지만, 응답은 서버가
    칸을 늘려도 우리 쪽이 멈추면 안 되므로 의존하는 필드만 검사하고 나머지는 관용한다.
    """
    status, text = _read_envelope(response)
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise AdminApiResponseError(
            f"non-JSON response (status={status}): {_describe(text)}"
        ) from exc
    if not isinstance(payload, dict):
        raise AdminApiResponseError(
            f"response must be a JSON object (status={status}): {_describe(payload)}"
        )
    # 여기서부터만 payload.get() 이 안전하다 — 모양이 확정된 뒤다.
    if status not in (200, 201) or payload.get("ok") is not True:
        raise AdminApiResponseError(
            f"register rejected (status={status}): "
            f"{_describe(payload.get('error', 'unknown'))}"
        )
    deduped = payload.get("deduped")
    if not isinstance(deduped, bool):
        raise AdminApiResponseError(
            f"deduped must be a bool (status={status}): {_describe(deduped)}"
        )
    # 서버 route.ts — 신규 등록 201 {deduped:false}, 동일인 갱신 200 {deduped:true}.
    # 어긋나면 중간 프록시·목이 거짓말한 것이므로 fail-closed.
    if (status == 200) is not deduped:
        raise AdminApiResponseError(
            f"status/deduped disagree with server contract (status={status}, "
            f"deduped={deduped})"
        )
    return RegisterOutcome(
        sent=True,
        recorded=True,
        deduped=deduped,
        status=status,
        request={},
        payload=payload,
    )


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
        if not isinstance(live, bool):
            raise AdminApiContractError("live must be a strict bool (truthy 오용 금지)")
        self._base_url = base_url
        self._internal_key = internal_key
        self._transport = transport
        self._live = live

    def register(self, candidate: Mapping[str, Any]) -> RegisterOutcome:
        request = build_register_request(
            candidate, base_url=self._base_url, internal_key=self._internal_key
        )
        # 키 가리기는 dry-run·live 양쪽 모두에 적용한다 — 결과는 원장·로그로 흘러간다.
        redacted = {
            **request,
            "headers": {**request["headers"], "x-internal-key": "***redacted***"},
        }
        if not self._live:
            return RegisterOutcome(
                sent=False,
                recorded=False,
                deduped=None,
                status=None,
                request=redacted,
                payload=None,
            )

        outcome = parse_register_response(self._transport(request))
        return replace(outcome, request=redacted)
