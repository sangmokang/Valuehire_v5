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


def _describe_shape(value: Any) -> str:
    """서버가 준 값의 '모양'만 알린다 — 내용은 절대 넣지 않는다.

    응답 본문에는 후보 개인정보(이름·연락처)와 내부키가 들어 있을 수 있고, 오류 메시지는
    로그·원장으로 흘러간다. 진단에 필요한 건 내용이 아니라 타입과 크기다. repr() 로 값을
    통째로 문장에 싣던 이전 방식(_describe)은 그 자체가 유출 경로였으므로 제거했다.

    오류 메시지를 만들다가 다시 터지는 사고를 구조적으로 불가능하게 해야 하므로, 이
    함수는 어떤 입력에도 절대 예외를 던지지 않는다. 적대적 str 하위형이 __len__·__str__
    을 덮어써도 안전하도록 타입 이름은 언바운드 str.encode 로 평범한 str 로 씻어낸다.
    """
    try:
        raw = type(value).__name__
        name = str.encode(raw, "utf-8", "replace").decode("utf-8", "replace")[:60]
    except Exception:
        return "<unknown>"
    try:
        size = len(value)
    except Exception:
        return name
    try:
        return f"{name}(len={size})"
    except Exception:
        return name


@dataclass(frozen=True)
class RegisterOutcome:
    """dry-run 과 live 가 공유하는 단일 결과 타입 — 호출자가 한 코드로 다룬다."""

    sent: bool
    recorded: bool
    deduped: bool | None
    status: int | None
    request: Mapping[str, Any]
    # 서버 응답 전체를 들고 있으면 후보 개인정보(이름·연락처)와 서버가 덧붙인 임의 필드가
    # 결과에 눌러앉아 로그·원장으로 샌다. 호출자가 실제로 필요한 건 '저장됐다는 영수증'
    # 뿐이므로 저장된 행을 가리키는 id 만 남긴다.
    candidate_id: str | None


def _read_envelope(response: Any) -> tuple[int, str]:
    """전송 계층이 준 봉투를 먼저 검사한다 — 꺼내 쓰기 전에 모양을 확정한다."""
    if not isinstance(response, Mapping):
        raise AdminApiResponseError(
            f"transport must return a mapping: {_describe_shape(response)}"
        )
    # Mapping 을 자처해도 .get() 이 터질 수 있다(Codex 2차 적대검증 발견) — 읽기 자체를
    # 보호해 약속한 계약 오류만 나가게 한다.
    try:
        status = response.get("status")
        text = response.get("text")
    except Exception as exc:
        raise AdminApiResponseError(
            f"transport mapping could not be read: {_describe_shape(response)}"
        ) from exc
    # 범위를 먼저 좁힌다 — 자릿수가 극단적인 정수는 오류 문장으로 바꾸는 것만으로도
    # ValueError 가 난다(2차 적대검증 발견). HTTP 상태값은 100~599 뿐이다.
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
        raise AdminApiResponseError(
            f"transport text must be a str: {_describe_shape(text)}"
        )
    return status, text


def parse_register_response(response: Any) -> RegisterOutcome:
    """서버 응답을 전송 없이 단독 검사 — build_register_request 와 대칭인 순수 함수.

    엄격함의 방향은 요청과 반대다: 요청은 표 밖 필드를 거부(E12)하지만, 응답은 서버가
    칸을 늘려도 우리 쪽이 멈추면 안 되므로 의존하는 필드만 검사하고 나머지는 관용한다.
    """
    status, text = _read_envelope(response)
    try:
        payload = json.loads(text)
    except (ValueError, RecursionError) as exc:
        # 중첩이 깊은 본문의 RecursionError 까지만 함께 흡수한다. 더 넓히면 우리 쪽
        # 내부 결함까지 '서버 응답 오류'로 둔갑시킨다(2차 적대검증 지적).
        raise AdminApiResponseError(
            f"unparseable response (status={status}): {_describe_shape(text)}"
        ) from exc
    if not isinstance(payload, dict):
        raise AdminApiResponseError(
            f"response must be a JSON object (status={status}): "
            f"{_describe_shape(payload)}"
        )
    # 여기서부터만 payload.get() 이 안전하다 — 모양이 확정된 뒤다.
    if status not in (200, 201) or payload.get("ok") is not True:
        # 서버 error 문구에는 후보 이름·연락처가 실려 올 수 있다 — 모양만 남긴다.
        raise AdminApiResponseError(
            f"register rejected (status={status}): "
            f"error={_describe_shape(payload.get('error'))}"
        )
    deduped = payload.get("deduped")
    if not isinstance(deduped, bool):
        raise AdminApiResponseError(
            f"deduped must be a bool (status={status}): {_describe_shape(deduped)}"
        )
    # 서버는 성공 시 반드시 저장된 레코드를 돌려준다(route.ts:123 갱신, :151 신규).
    # 없으면 실제로 저장된 증거가 없는 것이므로 등록 성공으로 인정하지 않는다 —
    # 거짓 성공은 원장을 거짓으로 만든다(Codex 2차 적대검증 발견).
    # 사전이기만 해선 부족하다 — 저장된 행을 가리키는 id 가 있어야 실제 저장 증거다
    # (id 는 uuid primary key, 20260507000000_pipeline.sql:3). 2차 적대검증 지적.
    record = payload.get("candidate")
    record_id = record.get("id") if isinstance(record, dict) else None
    if not isinstance(record_id, str) or not _js_trim(record_id):
        raise AdminApiResponseError(
            f"server reported success without an identified candidate record "
            f"(status={status}): {_describe_shape(record)}"
        )
    # 서버 route.ts — 신규 등록 201 {deduped:false}, 동일인 갱신 200 {deduped:true}.
    # 어긋나면 중간 프록시·목이 거짓말한 것이므로 fail-closed.
    if (status == 200) is not deduped:
        raise AdminApiResponseError(
            f"status/deduped disagree with server contract (status={status}, "
            f"deduped={deduped})"
        )
    # 서버가 칸을 늘려도 우리 쪽은 멈추지 않되(관용), 늘어난 칸을 결과에 보관하지도
    # 않는다 — 관용과 보관은 별개다.
    return RegisterOutcome(
        sent=True,
        recorded=True,
        deduped=deduped,
        status=status,
        request={},
        candidate_id=_js_trim(record_id),
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
                candidate_id=None,
            )

        outcome = parse_register_response(self._transport(request))
        return replace(outcome, request=redacted)
