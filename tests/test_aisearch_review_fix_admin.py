"""2026-07-31 전수 리뷰 — admin 클라이언트 단일화·안전성 (U2/U12/U15).

goal: docs/engineering/aisearch-review-fix-goal-2026-07-31.md
- AC-1b: admin_api.py(PR#250) 제거 후에도 그 개선 항목이 정본에 전부 있어야 한다.
- M5/F2/F3: 비-dict 200 / ok:false 200 / 비-https base_url 을 각각 명시적 거부.
- F4: 정본 클라이언트가 프로덕션 조립 경로에서 실제로 만들어진다(고아 금지).
- F5: live=True + admin 미주입은 생성자에서 즉시 거부(ClickUp·Discord 보고 유실 금지).

실 네트워크 0 — transport 는 전부 주입/monkeypatch.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.aisearch.core import admin_api_client as mod
from apps.aisearch.core.admin_api_client import (
    AdminApiConfigError,
    AdminApiContractError,
    AdminApiRecorder,
    AdminApiRegisterError,
    AdminApiResponseError,
    HttpAdminApiClient,
    build_register_request,
    parse_register_response,
)

VALID_KEY = "k" * 32
BASE = "https://admin.valuehire.cc"

CANDIDATE = {
    "name": "홍길동",
    "profile_url": "https://linkedin.com/in/hong",
    "match_score": 87,
    "why_fit": "세일즈 총괄 경험 8년",
    "channel": "linkedin_rps",
}


def _ok_body(*, deduped: bool = False) -> str:
    return json.dumps({"ok": True, "deduped": deduped, "candidate": {"id": "uuid-1"}})


# ── AC-1b — 클라이언트가 하나뿐이고, PR#250 개선이 전부 정본에 있다 ──────────


def test_ac1b_only_one_admin_client_module_exists():
    repo_root = Path(__file__).resolve().parents[1]
    assert not (repo_root / "apps/aisearch/core/admin_api.py").exists(), (
        "admin 클라이언트 이중화 — admin_api.py 가 남아 있으면 AC-1b 실패"
    )
    assert (repo_root / "apps/aisearch/core/admin_api_client.py").exists()


def test_ac1b_ported_symbols_present_in_canonical_client():
    # PR#250 에만 있던 계약 검증·응답 파서·dry-run 기록기가 정본에 이식됐는가.
    for name in (
        "build_register_request",
        "parse_register_response",
        "AdminApiRecorder",
        "RegisterOutcome",
        "AdminApiContractError",
        "AdminApiResponseError",
        "MIN_MATCH_SCORE",
        "REGISTER_PATH",
    ):
        assert hasattr(mod, name), f"정본에 {name} 미이식 — PR#250 개선 유실"


def test_ac1b_js_trim_matches_ecmascript_whitespace_set():
    # 서버(route.ts)는 JS String.trim() — U+FEFF 포함, U+0085 미포함.
    assert mod._js_trim("﻿  이름  ﻿") == "이름"
    assert mod._js_trim("이름") == "이름"


# ── F3 — 전송 안전(https 강제 · 키 16자 · 무여백) ──────────────────────────


def test_f3_http_base_url_rejected_before_any_send():
    with pytest.raises(AdminApiContractError):
        build_register_request(CANDIDATE, base_url="http://admin.valuehire.cc", internal_key=VALID_KEY)


def test_f3_short_or_padded_key_rejected():
    with pytest.raises(AdminApiContractError):
        build_register_request(CANDIDATE, base_url=BASE, internal_key="short")
    with pytest.raises(AdminApiContractError):
        build_register_request(CANDIDATE, base_url=BASE, internal_key=" " + VALID_KEY)


def test_f3_http_client_rejects_non_https_base_url_at_construction():
    with pytest.raises(AdminApiConfigError):
        HttpAdminApiClient(base_url="http://admin.valuehire.cc", internal_key=VALID_KEY)


def test_f3_http_client_strips_whitespace_on_explicit_base_url():
    client = HttpAdminApiClient(base_url=f"  {BASE}/  ", internal_key=VALID_KEY)
    assert client.base_url == BASE


def test_f3_unknown_field_rejected_catch_all():
    with pytest.raises(AdminApiContractError):
        build_register_request(
            {**CANDIDATE, "secret_note": "x"}, base_url=BASE, internal_key=VALID_KEY
        )


def test_f3_redacts_internal_key_in_outcome():
    rec = AdminApiRecorder(base_url=BASE, internal_key=VALID_KEY, transport=lambda r: None)
    outcome = rec.register(CANDIDATE)  # dry-run 기본 — 전송 0
    assert outcome.sent is False
    assert outcome.request["headers"]["x-internal-key"] == "***redacted***"
    assert VALID_KEY not in json.dumps(outcome.request, ensure_ascii=False)


# ── M5 / F2 — 응답 판정 ────────────────────────────────────────────────────


def test_m5_non_dict_json_200_raises_response_error_not_attribute_error():
    with pytest.raises(AdminApiResponseError):
        parse_register_response({"status": 200, "text": "[1, 2, 3]"})


def test_f2_ok_false_with_200_is_not_success():
    with pytest.raises(AdminApiResponseError):
        parse_register_response(
            {"status": 200, "text": json.dumps({"ok": False, "error": "dup"})}
        )


def test_contract_201_new_and_200_deduped():
    new = parse_register_response({"status": 201, "text": _ok_body(deduped=False)})
    assert (new.recorded, new.deduped, new.status) == (True, False, 201)
    dup = parse_register_response({"status": 200, "text": _ok_body(deduped=True)})
    assert (dup.recorded, dup.deduped, dup.status) == (True, True, 200)
    with pytest.raises(AdminApiResponseError):  # 계약 불일치(201 + deduped=true)
        parse_register_response({"status": 201, "text": _ok_body(deduped=True)})


def test_success_without_candidate_id_is_rejected():
    body = json.dumps({"ok": True, "deduped": False})
    with pytest.raises(AdminApiResponseError):
        parse_register_response({"status": 201, "text": body})


# ── HttpAdminApiClient — 실제 전송 경로(요청 모양 + 응답 엄격 판정) ─────────


class _FakeRequests:
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        self.captured: dict = {}

    def post(self, url, json=None, headers=None, timeout=None, data=None):  # noqa: A002
        self.captured = {
            "url": url,
            "json": json,
            "data": data,
            "headers": headers,
            "timeout": timeout,
        }
        fake = self

        class _Resp:
            status_code = fake.status
            text = fake.body

            def json(self_inner):
                return __import__("json").loads(fake.body)

        return _Resp()


def _install(monkeypatch, fake):
    monkeypatch.setitem(__import__("sys").modules, "requests", fake)


def test_http_client_live_sends_validated_payload(monkeypatch):
    fake = _FakeRequests(201, _ok_body())
    _install(monkeypatch, fake)
    client = HttpAdminApiClient(base_url=BASE, internal_key=VALID_KEY, live=True)

    result = client.register_candidate(dict(CANDIDATE))

    assert result["ok"] is True
    assert fake.captured["url"] == f"{BASE}/api/aisearch/register"
    assert fake.captured["headers"]["x-internal-key"] == VALID_KEY
    assert fake.captured["json"]["match_score"] == 87


def test_http_client_dry_run_default_sends_nothing(monkeypatch):
    fake = _FakeRequests(201, _ok_body())
    _install(monkeypatch, fake)
    client = HttpAdminApiClient(base_url=BASE, internal_key=VALID_KEY)  # live 기본 False

    client.register_candidate(dict(CANDIDATE))

    assert fake.captured == {}, "dry-run 인데 전송이 나갔다(SOT28 fail-closed 위반)"


def test_http_client_live_must_be_strict_bool():
    with pytest.raises(AdminApiContractError):
        HttpAdminApiClient(base_url=BASE, internal_key=VALID_KEY, live=1)


def test_http_client_raises_on_error_status(monkeypatch):
    _install(monkeypatch, _FakeRequests(400, json.dumps({"ok": False, "error": "bad"})))
    client = HttpAdminApiClient(base_url=BASE, internal_key=VALID_KEY, live=True)
    with pytest.raises((AdminApiRegisterError, AdminApiResponseError)):
        client.register_candidate(dict(CANDIDATE))


def test_http_client_raises_on_ok_false_200(monkeypatch):
    _install(monkeypatch, _FakeRequests(200, json.dumps({"ok": False})))
    client = HttpAdminApiClient(base_url=BASE, internal_key=VALID_KEY, live=True)
    with pytest.raises(AdminApiResponseError):
        client.register_candidate(dict(CANDIDATE))


def test_missing_config_fails_closed(monkeypatch):
    monkeypatch.delenv("ADMIN_API_BASE_URL", raising=False)
    monkeypatch.delenv("ADMIN_API_INTERNAL_KEY", raising=False)
    with pytest.raises(AdminApiConfigError):
        HttpAdminApiClient()


# ── F5 — live=True + admin 미주입은 생성자에서 거부 ────────────────────────


def test_f5_live_recorder_without_admin_client_is_rejected_at_construction():
    from apps.aisearch.core.recorders import DualRecorder, LiveGateError

    class _Noop:
        def __getattr__(self, item):
            return lambda *a, **k: None

    with pytest.raises(LiveGateError):
        DualRecorder(clickup=_Noop(), discord=_Noop(), live=True, owner_signoff=True)


# ── F4 — 프로덕션 조립 경로가 정본 클라이언트를 실제로 만든다 ──────────────


def test_f4_run_entrypoint_wires_real_admin_client_when_configured(monkeypatch, tmp_path):
    """배선 증명 — run.main(--browser) 조립이 HttpAdminApiClient 를 만든다."""
    from apps.aisearch import run as run_mod
    from tests.test_aisearch_run_entrypoint import JD, FakeTransport

    monkeypatch.setenv("ADMIN_API_BASE_URL", BASE)
    monkeypatch.setenv("ADMIN_API_INTERNAL_KEY", VALID_KEY)

    captured: dict = {}
    real_recorder_cls = run_mod.DualRecorder

    def spy(*args, **kwargs):
        captured["admin"] = kwargs.get("admin", args[2] if len(args) > 2 else None)
        return real_recorder_cls(*args, **kwargs)

    monkeypatch.setattr(run_mod, "DualRecorder", spy)

    jd_path = tmp_path / "jd.json"
    jd_path.write_text(json.dumps(JD, ensure_ascii=False), encoding="utf-8")
    run_mod.main(
        [
            str(jd_path),
            "--browser",
            "--ws-url",
            "ws://injected",
            "--pages-out",
            str(tmp_path / "pages.jsonl"),
        ],
        transport_factory=lambda url: FakeTransport(),
        extractors={ch: (lambda pages: []) for ch in run_mod.CHANNELS},
    )

    assert isinstance(captured.get("admin"), HttpAdminApiClient), (
        "정본 admin 클라이언트가 프로덕션 조립에서 만들어지지 않았다(고아 코드)"
    )
    assert captured["admin"].live is False  # dry-run 조립 — 전송 0
