"""AC-6 — admin.valuehire.cc(valuehire_v4) 등록 HTTP 어댑터.

goal: docs/engineering/aisearch-register-api-goal-2026-07-31.md
대상 API: valuehire_v4 POST /api/aisearch/register(x-internal-key 인증,
PR #744 병합됨 — 2026-07-30).

이 모듈만 실제 네트워크(requests)를 만든다. recorders.py는 AdminApiClient
Protocol(주입식)만 알고, 이 클래스의 존재를 모른다 — 단위 테스트는 이 클래스를
거치지 않고 fake client 로 recorders.py 를 검증한다(fail-closed 원칙 유지).

설정은 환경변수로만 받는다(비밀값 하드코딩 금지):
- ADMIN_API_BASE_URL (예: https://admin.valuehire.cc)
- ADMIN_API_INTERNAL_KEY (valuehire_v4 INTERNAL_API_KEY 와 동일한 값)
"""

from __future__ import annotations

import os
from typing import Any


class AdminApiConfigError(RuntimeError):
    """ADMIN_API_BASE_URL/ADMIN_API_INTERNAL_KEY 미설정 — fail-closed."""


class AdminApiRegisterError(RuntimeError):
    """비-2xx 응답 또는 네트워크 오류 — 호출자(DualRecorder)가 partial/failed 로 집계."""


class HttpAdminApiClient:
    """실제 HTTP 호출로 POST /api/aisearch/register 를 수행하는 어댑터."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        internal_key: str | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        resolved_base_url = base_url or os.environ.get("ADMIN_API_BASE_URL", "").strip()
        resolved_key = internal_key or os.environ.get("ADMIN_API_INTERNAL_KEY", "").strip()
        if not resolved_base_url or not resolved_key:
            raise AdminApiConfigError(
                "ADMIN_API_BASE_URL/ADMIN_API_INTERNAL_KEY 미설정 — admin 등록 fail-closed"
            )
        self._base_url = resolved_base_url.rstrip("/")
        self._internal_key = resolved_key
        self._timeout_seconds = timeout_seconds

    def register_candidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        # 지연 import — 이 모듈이 import 되는 시점(단위 테스트 등)에 requests 가
        # 없어도 실패하지 않는다(session_guard.py 의 지연 import 관례와 동형).
        import requests

        response = requests.post(
            f"{self._base_url}/api/aisearch/register",
            json=payload,
            headers={"x-internal-key": self._internal_key},
            timeout=self._timeout_seconds,
        )
        try:
            body = response.json()
        except ValueError as exc:
            raise AdminApiRegisterError(
                f"admin.valuehire.cc 응답 JSON 파싱 실패: {response.status_code}"
            ) from exc
        if response.status_code >= 300:
            error = body.get("error") if isinstance(body, dict) else None
            raise AdminApiRegisterError(
                f"admin.valuehire.cc 등록 실패: {response.status_code} {error or body!r}"
            )
        return body
