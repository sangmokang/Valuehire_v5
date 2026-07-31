"""AC-6 — admin.valuehire.cc 연동 클라이언트 (D12 확정: 신규 API, 2026-07-31).

서버 계약(정본): valuehire_v4 app/api/aisearch/register/route.ts (커밋 db7429c2, PR#744)
- POST /api/aisearch/register, 인증 x-internal-key 헤더
- 필수: name, profile_url(https?://), match_score(0~100, 60 미만 거부), why_fit, channel
- 선택: profile_summary, jd_id, jd_title, skills[str]
- 응답: {ok: bool, error?: str}, 400/401/500

클라이언트 규율: fail-fast(서버에 보내기 전에 계약 위반 거부), dry-run 기본(전송 0),
키 하드코딩 금지(호출자 주입), 표 밖 필드 명시적 거부(E12 catch-all).
"""
import pytest

from apps.aisearch.core.admin_api import (
    AdminApiContractError,
    AdminApiRecorder,
    AdminApiResponseError,
    RegisterOutcome,
    build_register_request,
    parse_register_response,
)

BASE = "https://admin.valuehire.cc"
KEY = "test-internal-key-16plus"


def candidate(**over):
    base = {
        "name": "홍길동",
        "profile_url": "https://www.saramin.co.kr/profile/123",
        "match_score": 72,
        "why_fit": "B2B SaaS 세일즈 7년, 서울 소재 대학.",
        "channel": "saramin",
    }
    base.update(over)
    return base


class TestBuildRegisterRequest:
    def test_valid_candidate_builds_exact_contract(self):
        req = build_register_request(candidate(), base_url=BASE, internal_key=KEY)
        assert req["method"] == "POST"
        assert req["url"] == BASE + "/api/aisearch/register"
        assert req["headers"]["x-internal-key"] == KEY
        assert req["headers"]["content-type"] == "application/json"
        body = req["json"]
        assert body["name"] == "홍길동"
        assert body["profile_url"].startswith("https://")
        assert body["match_score"] == 72
        assert body["why_fit"] and body["channel"] == "saramin"

    def test_optional_fields_pass_through(self):
        req = build_register_request(
            candidate(profile_summary="요약", jd_id="jd-1", jd_title="세일즈 매니저",
                      skills=["b2b", "saas"]),
            base_url=BASE, internal_key=KEY)
        body = req["json"]
        assert body["profile_summary"] == "요약"
        assert body["jd_id"] == "jd-1"
        assert body["jd_title"] == "세일즈 매니저"
        assert body["skills"] == ["b2b", "saas"]

    @pytest.mark.parametrize("field", ["name", "profile_url", "why_fit", "channel"])
    def test_missing_required_field_fails_fast(self, field):
        cand = candidate()
        del cand[field]
        with pytest.raises(AdminApiContractError):
            build_register_request(cand, base_url=BASE, internal_key=KEY)

    def test_non_https_profile_url_rejected(self):
        with pytest.raises(AdminApiContractError):
            build_register_request(candidate(profile_url="ftp://x"), base_url=BASE,
                                   internal_key=KEY)

    @pytest.mark.parametrize("score", [-1, 101, "80", None, float("nan")])
    def test_invalid_score_rejected(self, score):
        with pytest.raises(AdminApiContractError):
            build_register_request(candidate(match_score=score), base_url=BASE,
                                   internal_key=KEY)

    def test_score_59_refused_client_side_60_allowed(self):
        with pytest.raises(AdminApiContractError):
            build_register_request(candidate(match_score=59), base_url=BASE,
                                   internal_key=KEY)
        req = build_register_request(candidate(match_score=60), base_url=BASE,
                                     internal_key=KEY)
        assert req["json"]["match_score"] == 60

    def test_unknown_field_rejected_catch_all(self):
        with pytest.raises(AdminApiContractError):
            build_register_request(candidate(evil="x"), base_url=BASE, internal_key=KEY)

    def test_missing_key_or_bad_base_url_rejected(self):
        with pytest.raises(AdminApiContractError):
            build_register_request(candidate(), base_url=BASE, internal_key="")
        with pytest.raises(AdminApiContractError):
            build_register_request(candidate(), base_url="http://insecure", internal_key=KEY)


class FakeTransport:
    def __init__(self, status=200, body=None, raw=None):
        self.calls = []
        self.status = status
        self.body = {"ok": True} if body is None else body
        self.raw = raw

    def __call__(self, request):
        self.calls.append(request)
        if self.raw is not None:
            return {"status": self.status, "text": self.raw}
        import json
        return {"status": self.status, "text": json.dumps(self.body)}


class TestAdminApiRecorder:
    def test_dry_run_default_sends_nothing(self):
        t = FakeTransport()
        rec = AdminApiRecorder(base_url=BASE, internal_key=KEY, transport=t)
        outcome = rec.register(candidate())
        assert outcome.sent is False
        assert outcome.recorded is False
        assert t.calls == []

    def test_live_success_201_new_insert(self):
        # 서버 route.ts:151 — 신규 등록은 201 {ok:true, deduped:false}
        t = FakeTransport(status=201, body={"ok": True, "deduped": False})
        rec = AdminApiRecorder(base_url=BASE, internal_key=KEY, transport=t, live=True)
        outcome = rec.register(candidate())
        assert outcome.sent is True
        assert outcome.recorded is True
        assert outcome.deduped is False
        assert outcome.status == 201
        assert len(t.calls) == 1
        assert t.calls[0]["url"] == BASE + "/api/aisearch/register"

    def test_live_success_200_deduped_update(self):
        # 서버 route.ts:123 — 같은 jd_id 내 동일인은 200 {ok:true, deduped:true}
        t = FakeTransport(status=200, body={"ok": True, "deduped": True})
        rec = AdminApiRecorder(base_url=BASE, internal_key=KEY, transport=t, live=True)
        outcome = rec.register(candidate())
        assert outcome.recorded is True
        assert outcome.deduped is True
        assert outcome.status == 200

    @pytest.mark.parametrize("status,body", [
        (400, {"ok": False, "error": "name is required"}),
        (401, {"ok": False, "error": "Unauthorized"}),
        (500, {"ok": False, "error": "boom"}),
    ])
    def test_live_error_status_is_explicit_failure(self, status, body):
        t = FakeTransport(status=status, body=body)
        rec = AdminApiRecorder(base_url=BASE, internal_key=KEY, transport=t, live=True)
        with pytest.raises(AdminApiResponseError) as e:
            rec.register(candidate())
        assert body["error"] in str(e.value)

    def test_live_non_json_response_is_explicit_failure(self):
        t = FakeTransport(status=200, raw="<html>gateway error</html>")
        rec = AdminApiRecorder(base_url=BASE, internal_key=KEY, transport=t, live=True)
        with pytest.raises(AdminApiResponseError):
            rec.register(candidate())

    def test_live_flag_must_be_strict_bool(self):
        # live="false" 같은 진리값 오용이 실전송을 내면 안 된다 — 엄격 bool 만 허용.
        t = FakeTransport()
        with pytest.raises(AdminApiContractError):
            AdminApiRecorder(base_url=BASE, internal_key=KEY, transport=t, live="false")
        assert t.calls == []

    def test_key_rules_match_server_min16_and_no_padding(self):
        # 서버 internalApiKey.ts:17 MIN_INTERNAL_KEY_LENGTH=16 — 16자 미만/여백 포함 키는
        # 어차피 거부되므로 전송 전에 거부한다.
        with pytest.raises(AdminApiContractError):
            build_register_request(candidate(), base_url=BASE, internal_key="short")
        with pytest.raises(AdminApiContractError):
            build_register_request(candidate(), base_url=BASE, internal_key=" " + KEY)

    def test_dry_run_result_never_leaks_key(self):
        t = FakeTransport()
        rec = AdminApiRecorder(base_url=BASE, internal_key=KEY, transport=t)
        outcome = rec.register(candidate())
        assert KEY not in repr(outcome)

    def test_trim_semantics_match_server_js_trim(self):
        # 서버는 JS String.trim() — U+FEFF(BOM)만 있는 값은 공백으로 거부하고,
        # U+0085(NEL)은 JS 공백이 아니므로 내용으로 인정한다(Python str.strip()과 다름).
        with pytest.raises(AdminApiContractError):
            build_register_request(candidate(name="\ufeff"), base_url=BASE,
                                   internal_key=KEY)
        req = build_register_request(candidate(name="\u0085김"), base_url=BASE,
                                     internal_key=KEY)
        assert "\u0085" in req["json"]["name"]

    def test_contract_violation_never_reaches_transport_even_live(self):
        t = FakeTransport()
        rec = AdminApiRecorder(base_url=BASE, internal_key=KEY, transport=t, live=True)
        with pytest.raises(AdminApiContractError):
            rec.register(candidate(match_score=42))
        assert t.calls == []

    def test_dry_run_and_live_share_one_result_shape(self):
        # 근본 결함: dry-run 은 'request', live 는 'response' 키를 뱉어 호출자가 한 코드로
        # 두 경우를 다룰 수 없었다. 같은 타입·같은 속성 집합이어야 한다.
        dry = AdminApiRecorder(base_url=BASE, internal_key=KEY,
                               transport=FakeTransport()).register(candidate())
        live = AdminApiRecorder(
            base_url=BASE, internal_key=KEY, live=True,
            transport=FakeTransport(status=201, body={"ok": True, "deduped": False}),
        ).register(candidate())
        assert isinstance(dry, RegisterOutcome) and isinstance(live, RegisterOutcome)
        assert vars(dry).keys() == vars(live).keys()

    def test_live_outcome_never_leaks_key(self):
        # dry-run 만 가리고 live 는 안 가리면 로그·원장에 키가 샌다.
        rec = AdminApiRecorder(
            base_url=BASE, internal_key=KEY, live=True,
            transport=FakeTransport(status=201, body={"ok": True, "deduped": False}),
        )
        assert KEY not in repr(rec.register(candidate()))


# 서버 응답을 전송 없이 단독 검사 — build_register_request 와 대칭인 순수 함수.
def _envelope(status=201, text='{"ok": true, "deduped": false}'):
    return {"status": status, "text": text}


class TestParseRegisterResponse:
    """근본 결함: 응답은 검사 함수 자체가 없었고, 오류 메시지를 만들 때 방금 '사전이
    아니다'라고 판정한 값을 다시 사전처럼 꺼내 써서 AttributeError 로 죽었다."""

    @pytest.mark.parametrize("text", [
        "null", "[]", '"ok"', "123", "true", "[{\"ok\": true}]",  # JSON 이지만 객체 아님
    ])
    def test_non_object_json_raises_contract_error_not_crash(self, text):
        with pytest.raises(AdminApiResponseError):
            parse_register_response(_envelope(status=500, text=text))

    @pytest.mark.parametrize("body", [
        {}, {"ok": False}, {"ok": "true"}, {"ok": 1}, {"ok": None},
        {"ok": True},                                  # deduped 누락
        {"ok": True, "deduped": "false"},              # deduped 타입 위반
        {"ok": True, "deduped": None},
    ])
    def test_object_missing_or_wrong_confirmation_is_explicit_failure(self, body):
        import json as _json
        with pytest.raises(AdminApiResponseError):
            parse_register_response(_envelope(status=201, text=_json.dumps(body)))

    @pytest.mark.parametrize("envelope", [
        None, [], "text", 42,                                  # Mapping 이 아님
        {"text": '{"ok": true}'},                              # status 누락
        {"status": "201", "text": '{"ok": true}'},             # status 가 문자열
        {"status": True, "text": '{"ok": true}'},              # bool 은 int 오용
        {"status": None, "text": '{"ok": true}'},
        {"status": 201},                                       # text 누락
        {"status": 201, "text": None},
        {"status": 201, "text": b'{"ok": true}'},              # bytes 는 계약 밖
    ])
    def test_malformed_transport_envelope_is_explicit_failure(self, envelope):
        with pytest.raises(AdminApiResponseError):
            parse_register_response(envelope)

    def test_status_and_deduped_must_agree_with_server_contract(self):
        # route.ts — 201↔deduped:false(신규), 200↔deduped:true(갱신). 어긋나면 중간
        # 프록시·목이 거짓말한 것이므로 fail-closed.
        import json as _json
        for status, deduped in ((201, True), (200, False)):
            with pytest.raises(AdminApiResponseError):
                parse_register_response(_envelope(
                    status=status,
                    text=_json.dumps({"ok": True, "deduped": deduped})))

    def test_unknown_response_fields_are_tolerated(self):
        # 비대칭 규율: 요청은 모르는 필드를 거부(E12), 응답은 서버가 칸을 늘려도
        # 우리 쪽이 멈추면 안 되므로 관용한다.
        outcome = parse_register_response(_envelope(
            status=201,
            text='{"ok": true, "deduped": false, "candidate": {"id": 7}, "v2_field": 1}'))
        assert outcome.recorded is True
        assert outcome.deduped is False

    def test_error_message_carries_server_reason(self):
        with pytest.raises(AdminApiResponseError) as e:
            parse_register_response(_envelope(
                status=401, text='{"ok": false, "error": "Unauthorized"}'))
        assert "Unauthorized" in str(e.value)
