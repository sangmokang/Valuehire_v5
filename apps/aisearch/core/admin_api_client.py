"""AC-6 — admin.valuehire.cc(valuehire_v4) 등록 **정본** 클라이언트.

goal: docs/engineering/aisearch-review-fix-goal-2026-07-31.md (AC-1b/M5/F2/F3)
이전 goal: docs/engineering/aisearch-register-api-goal-2026-07-31.md
서버 계약 정본: valuehire_v4 app/api/aisearch/register/route.ts (PR#744)
- POST {base_url}/api/aisearch/register — x-internal-key 인증
- 필수: name, profile_url(https?://), match_score(0~100, 60 미만 서버 거부), why_fit, channel
- 선택: profile_summary, jd_id, jd_title, skills[str]
- 신규 201 {deduped:false} / 동일인 갱신 200 {deduped:true}

**AC-1b**: 이 파일이 유일한 admin 클라이언트다. PR#250 의 admin_api.py 는
제거됐고, 거기서만 있던 보호장치(전송 전 계약검증·JS trim 정합·키 16자/무여백·
https 강제·키 redact·201/200 deduped 계약·비-dict 200 거부·dry-run 기본)를
전부 이 파일로 이식했다. 두 클라이언트가 동시에 존재하면 AC-1b 실패다.

L3 규율:
- 전송 전에 서버가 거부할 payload 는 여기서 거부한다(fail-fast).
- 표 밖 필드는 명시적 거부(catch-all) — 조용한 통과 금지.
- dry-run 이 기본. live=True 없이는 전송 0건(SOT28 fail-closed 관례).
- 비밀키는 결과·로그 어디에도 원문으로 남기지 않는다(redact).

설정은 환경변수로 받을 수 있다(비밀값 하드코딩 금지):
- ADMIN_API_BASE_URL (https:// 필수 — http 는 x-internal-key 평문 전송이라 거부)
- ADMIN_API_INTERNAL_KEY (valuehire_v4 INTERNAL_API_KEY 와 동일 값, 16자 이상)
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping

REGISTER_PATH = "/api/aisearch/register"
MIN_MATCH_SCORE = 60  # 서버 MIN_MATCH_SCORE 와 동일 (route.ts)
MIN_INTERNAL_KEY_LENGTH = 16  # 서버 internalApiKey.ts:17

_REQUIRED_FIELDS = ("name", "profile_url", "match_score", "why_fit", "channel")
_OPTIONAL_FIELDS = ("profile_summary", "jd_id", "jd_title", "skills")
_ALLOWED_FIELDS = frozenset(_REQUIRED_FIELDS + _OPTIONAL_FIELDS)


class AdminApiConfigError(RuntimeError):
    """base_url/internal_key 미설정 또는 형식 위반 — fail-closed."""


class AdminApiContractError(ValueError):
    """전송 전 계약 위반 — 서버에 도달하기 전에 거부한다."""


class AdminApiResponseError(RuntimeError):
    """서버가 등록을 거부했거나 응답이 계약과 다르다."""


class AdminApiRegisterError(RuntimeError):
    """네트워크/전송 계층 실패 — 호출자(DualRecorder)가 partial/failed 로 집계."""


# 서버(route.ts)는 JS String.trim() — ECMAScript 공백 집합은 U+FEFF(BOM)를 포함하고
# U+0085(NEL)를 포함하지 않는다. Python str.strip() 기본과 다르므로 명시 집합으로 맞춘다.
_JS_WHITESPACE = (
    "\t\n\v\f\r           "
    "       　﻿"
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


def _validate_credentials(base_url: Any, internal_key: Any) -> None:
    """전송 안전(F3) — 키 형식과 스킴을 전송 전에 확정한다.

    http:// 는 x-internal-key 가 평문으로 나가므로 절대 허용하지 않는다.
    """
    if (
        not isinstance(internal_key, str)
        or len(internal_key) < MIN_INTERNAL_KEY_LENGTH
        or _js_trim(internal_key) != internal_key
    ):
        raise AdminApiContractError(
            f"internal_key must be >={MIN_INTERNAL_KEY_LENGTH} chars, no surrounding "
            "whitespace (주입 필수 — 하드코딩 금지)"
        )
    if not isinstance(base_url, str) or not base_url.startswith("https://"):
        raise AdminApiContractError(
            "base_url must be https:// — http 는 내부키 평문 전송이라 금지"
        )


def build_register_request(
    candidate: Mapping[str, Any],
    *,
    base_url: str,
    internal_key: str,
) -> dict[str, Any]:
    _validate_credentials(base_url, internal_key)

    unknown = set(candidate) - _ALLOWED_FIELDS
    if unknown:
        raise AdminApiContractError(
            f"unknown fields rejected (catch-all): {sorted(unknown)}"
        )

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
    """모양을 가정하지 않고 안전하게 글자로 만든다 — 어떤 입력에도 예외를 던지지 않는다."""
    try:
        text = repr(value)
        return text if len(text) <= limit else text[:limit] + "…"
    except Exception:
        pass
    try:
        return f"<unrepresentable {type(value).__name__}>"
    except Exception:
        return "<unrepresentable>"


def _describe_shape(value: Any) -> str:
    """서버가 준 원문의 '모양'만 알린다 — 개인정보가 로그·원장으로 흐르지 않게."""
    try:
        name = type(value).__name__
    except Exception:
        return "<unknown>"
    try:
        return f"{name}(len={len(value)})"
    except Exception:
        return name


@dataclass(frozen=True)
class RegisterOutcome:
    """dry-run 과 live 가 공유하는 단일 결과 타입."""

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
    try:
        status = response.get("status")
        text = response.get("text")
    except Exception as exc:
        raise AdminApiResponseError(
            f"transport mapping could not be read: {_describe_shape(response)}"
        ) from exc
    if (
        isinstance(status, bool)
        or not isinstance(status, int)
        or not 100 <= status <= 599
    ):
        raise AdminApiResponseError(
            f"transport status must be an HTTP status int (100..599): "
            f"{_describe_shape(status)}"
        )
    if not isinstance(text, str):
        raise AdminApiResponseError(f"transport text must be a str: {_describe(text)}")
    return status, text


def parse_register_response(response: Any) -> RegisterOutcome:
    """서버 응답을 전송 없이 단독 검사 — build_register_request 와 대칭인 순수 함수.

    M5/F2 — 200 이라는 이유만으로 성공으로 인정하지 않는다: 본문이 dict 여야 하고
    ok=True 여야 하며, 저장된 레코드 id 가 있어야 하고, status 와 deduped 가 서버
    계약대로 일치해야 한다. 하나라도 어긋나면 원장에 "등록됨"으로 남기지 않는다.
    """
    status, text = _read_envelope(response)
    try:
        payload = json.loads(text)
    except (ValueError, RecursionError) as exc:
        raise AdminApiResponseError(
            f"unparseable response (status={status}): {_describe_shape(text)}"
        ) from exc
    if not isinstance(payload, dict):
        # M5 — 비-dict JSON 200 은 AttributeError 가 아니라 계약 오류다.
        raise AdminApiResponseError(
            f"response must be a JSON object (status={status}): "
            f"{_describe_shape(payload)}"
        )
    # 여기서부터만 payload.get() 이 안전하다 — 모양이 확정된 뒤다.
    if status not in (200, 201) or payload.get("ok") is not True:
        # F2 — 200 + {"ok": false} 를 성공으로 세지 않는다.
        raise AdminApiResponseError(
            f"register rejected (status={status}): "
            f"{_describe(payload.get('error', 'unknown'))}"
        )
    deduped = payload.get("deduped")
    if not isinstance(deduped, bool):
        raise AdminApiResponseError(
            f"deduped must be a bool (status={status}): {_describe(deduped)}"
        )
    # 서버는 성공 시 반드시 저장된 레코드를 돌려준다(route.ts:123 갱신, :151 신규).
    # id 가 없으면 실제 저장 증거가 없는 것 — 거짓 성공은 원장을 거짓으로 만든다.
    record = payload.get("candidate")
    record_id = record.get("id") if isinstance(record, dict) else None
    if not isinstance(record_id, str) or not _js_trim(record_id):
        raise AdminApiResponseError(
            f"server reported success without an identified candidate record "
            f"(status={status}): {_describe_shape(record)}"
        )
    # 신규 201 {deduped:false}, 동일인 갱신 200 {deduped:true}. 어긋나면 중간
    # 프록시·목이 거짓말한 것이므로 fail-closed.
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


def _redacted(request: Mapping[str, Any]) -> dict[str, Any]:
    """키 가리기 — dry-run·live 양쪽 결과 모두에 적용(원장·로그로 흘러간다)."""
    return {
        **request,
        "headers": {**request["headers"], "x-internal-key": "***redacted***"},
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
        if not isinstance(live, bool):
            raise AdminApiContractError("live must be a strict bool (truthy 오용 금지)")
        self._base_url = base_url
        self._internal_key = internal_key
        self._transport = transport
        self._live = live

    @property
    def live(self) -> bool:
        return self._live

    def register(self, candidate: Mapping[str, Any]) -> RegisterOutcome:
        request = build_register_request(
            candidate, base_url=self._base_url, internal_key=self._internal_key
        )
        redacted = _redacted(request)
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


def _requests_transport(timeout_seconds: float):
    """실제 HTTP 전송 — 이 모듈에서 네트워크를 만드는 유일한 지점."""

    def _send(request: Mapping[str, Any]) -> Mapping[str, Any]:
        # 지연 import — 단위 테스트가 이 모듈을 import 하는 시점에 requests 가
        # 없어도 실패하지 않는다(session_guard.py 의 지연 import 관례와 동형).
        import requests

        try:
            response = requests.post(
                request["url"],
                json=request["json"],
                headers=request["headers"],
                timeout=timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001 — 네트워크 실패는 종류 불문 전송 오류
            raise AdminApiRegisterError(
                f"admin.valuehire.cc 전송 실패: {type(exc).__name__}"
            ) from exc
        status = getattr(response, "status_code", None)
        text = getattr(response, "text", None)
        if not isinstance(text, str):
            # text 를 제공하지 않는 응답 객체는 json() 으로 되살린다.
            try:
                text = json.dumps(response.json())
            except Exception as exc:  # noqa: BLE001
                raise AdminApiRegisterError(
                    f"admin.valuehire.cc 응답 본문을 읽지 못했다: {status!r}"
                ) from exc
        return {"status": status, "text": text}

    return _send


class HttpAdminApiClient:
    """recorders.AdminApiClient 포트의 실제 HTTP 구현(정본).

    register_candidate(payload) 는 전송 전 계약검증 → (live 일 때만) 전송 →
    응답 엄격 판정을 모두 거친다. 실패는 전부 명시적 예외다.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        internal_key: str | None = None,
        timeout_seconds: float = 15.0,
        live: bool = False,
        transport: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    ) -> None:
        if not isinstance(live, bool):
            raise AdminApiContractError("live must be a strict bool (truthy 오용 금지)")
        raw_base = (
            base_url if base_url is not None else os.environ.get("ADMIN_API_BASE_URL", "")
        )
        raw_key = (
            internal_key
            if internal_key is not None
            else os.environ.get("ADMIN_API_INTERNAL_KEY", "")
        )
        # F3 — 인자로 준 값에도 동일하게 여백을 제거한다(env 만 strip 하던 결함).
        resolved_base_url = raw_base.strip() if isinstance(raw_base, str) else raw_base
        resolved_key = raw_key.strip() if isinstance(raw_key, str) else raw_key
        if not resolved_base_url or not resolved_key:
            raise AdminApiConfigError(
                "ADMIN_API_BASE_URL/ADMIN_API_INTERNAL_KEY 미설정 — admin 등록 fail-closed"
            )
        resolved_base_url = resolved_base_url.rstrip("/")
        try:
            _validate_credentials(resolved_base_url, resolved_key)
        except AdminApiContractError as exc:
            # 구성 오류는 구성 오류로 보고한다(호출 시점이 아니라 조립 시점에 실패).
            raise AdminApiConfigError(str(exc)) from exc
        self._recorder = AdminApiRecorder(
            base_url=resolved_base_url,
            internal_key=resolved_key,
            transport=transport or _requests_transport(timeout_seconds),
            live=live,
        )
        self._base_url = resolved_base_url

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def live(self) -> bool:
        return self._recorder.live

    def register_candidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        outcome = self._recorder.register(payload)
        if not outcome.sent:
            # dry-run — 전송 0건. 계획(키 가림)만 돌려준다.
            return {
                "ok": False,
                "sent": False,
                "dry_run": True,
                "request": outcome.request,
            }
        return dict(outcome.payload or {})
