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

    # 전수 돌연변이 조사에서 발견: 아래 선택 항목 검사들은 테스트가 하나도 없어서
    # 통째로 지워도 80개가 전부 통과했다(검사하는 척만 하던 구간).
    @pytest.mark.parametrize("value", [123, None, [], {}, True])
    def test_non_str_profile_summary_rejected(self, value):
        with pytest.raises(AdminApiContractError, match="profile_summary"):
            build_register_request(candidate(profile_summary=value), base_url=BASE,
                                   internal_key=KEY)

    @pytest.mark.parametrize("field", ["jd_id", "jd_title"])
    @pytest.mark.parametrize("value", ["", 123, None, [], True])
    def test_empty_or_non_str_jd_fields_rejected(self, field, value):
        with pytest.raises(AdminApiContractError, match=field):
            build_register_request(candidate(**{field: value}), base_url=BASE,
                                   internal_key=KEY)

    @pytest.mark.parametrize("value", ["b2b", 123, None, ["b2b", 7], [None], {"a": 1}])
    def test_skills_must_be_a_list_of_str(self, value):
        with pytest.raises(AdminApiContractError, match="skills"):
            build_register_request(candidate(skills=value), base_url=BASE,
                                   internal_key=KEY)

    def test_nan_score_is_rejected_by_its_own_guard(self):
        # NaN 은 범위 검사에도 걸리지만, 어느 검사가 잡았는지 고정해 둔다.
        with pytest.raises(AdminApiContractError, match="NaN"):
            build_register_request(candidate(match_score=float("nan")), base_url=BASE,
                                   internal_key=KEY)

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
        self.body = {"ok": True, "candidate": {"id": "8f14e45f-ceea-467a-9f6b-2c3d4e5a6b71"}, "deduped": False} if body is None else body
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
        t = FakeTransport(status=201, body={"ok": True, "candidate": {"id": "8f14e45f-ceea-467a-9f6b-2c3d4e5a6b71"}, "deduped": False})
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
        t = FakeTransport(status=200, body={"ok": True, "candidate": {"id": "8f14e45f-ceea-467a-9f6b-2c3d4e5a6b71"}, "deduped": True})
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
        message = str(e.value)
        # 원문 대신 모양만 — 서버 error 문구에는 후보 개인정보가 실려 올 수 있다.
        assert str(status) in message
        assert body["error"] not in message

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
            transport=FakeTransport(status=201, body={"ok": True, "candidate": {"id": "8f14e45f-ceea-467a-9f6b-2c3d4e5a6b71"}, "deduped": False}),
        ).register(candidate())
        assert isinstance(dry, RegisterOutcome) and isinstance(live, RegisterOutcome)
        assert vars(dry).keys() == vars(live).keys()

    def test_live_outcome_never_leaks_key(self):
        # dry-run 만 가리고 live 는 안 가리면 로그·원장에 키가 샌다.
        rec = AdminApiRecorder(
            base_url=BASE, internal_key=KEY, live=True,
            transport=FakeTransport(status=201, body={"ok": True, "candidate": {"id": "8f14e45f-ceea-467a-9f6b-2c3d4e5a6b71"}, "deduped": False}),
        )
        assert KEY not in repr(rec.register(candidate()))


# 서버 응답을 전송 없이 단독 검사 — build_register_request 와 대칭인 순수 함수.
def _envelope(status=201,
              text='{"ok": true, "candidate": {"id": "8f14e45f-ceea-467a-9f6b-2c3d4e5a6b71"}, "deduped": false}'):
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

    @pytest.mark.parametrize("envelope", [None, [], "text", 42])
    def test_non_mapping_envelope_is_caught_by_its_own_guard(self, envelope):
        # 전수 돌연변이 조사에서 발견: Mapping 검사를 지워도 뒤쪽 읽기 보호가 같은
        # 예외를 내서 통과했다 — 어느 검사가 잡았는지 고정한다.
        with pytest.raises(AdminApiResponseError, match="must return a mapping"):
            parse_register_response(envelope)

    @pytest.mark.parametrize("deduped", ['"false"', "null", "1", "[]"])
    def test_non_bool_deduped_is_caught_by_its_own_guard(self, deduped):
        # 같은 이유 — 지우면 상태↔deduped 검사가 대신 잡아서 통과했다.
        with pytest.raises(AdminApiResponseError, match="deduped must be a bool"):
            parse_register_response(_envelope(
                status=201,
                text='{"ok": true, "candidate": {"id": "8f14e45f-ceea-467a-9f6b-'
                     '2c3d4e5a6b71"}, "deduped": ' + deduped + "}"))

    def test_status_and_deduped_must_agree_with_server_contract(self):
        # route.ts — 201↔deduped:false(신규), 200↔deduped:true(갱신). 어긋나면 중간
        # 프록시·목이 거짓말한 것이므로 fail-closed.
        # 2차 적대검증 지적: 이 입력에 candidate 가 없어서 candidate 검사에 먼저 걸렸고,
        # 상태↔deduped 검사 코드를 지워도 통과하는 헛테스트였다. 정본 응답을 준 뒤
        # '걸린 이유'까지 확인한다.
        import json as _json
        for status, deduped in ((201, True), (200, False)):
            with pytest.raises(AdminApiResponseError, match="status/deduped disagree"):
                parse_register_response(_envelope(
                    status=status,
                    text=_json.dumps({"ok": True, "candidate": {"id": "8f14e45f-ceea-467a-9f6b-2c3d4e5a6b71"},
                                      "deduped": deduped})))

    def test_unknown_response_fields_are_tolerated(self):
        # 비대칭 규율: 요청은 모르는 필드를 거부(E12), 응답은 서버가 칸을 늘려도
        # 우리 쪽이 멈추면 안 되므로 관용한다.
        outcome = parse_register_response(_envelope(
            status=201,
            text='{"ok": true, "deduped": false, '
                 '"candidate": {"id": "8f14e45f-ceea-467a-9f6b-2c3d4e5a6b71", "new_column": 1}, "v2_field": 1}'))
        assert outcome.recorded is True
        assert outcome.deduped is False

    def test_describe_survives_objects_whose_repr_explodes(self):
        # 자체 적대검증에서 발견: 설명 함수가 repr() 에 의존하는 한 '메시지 만들다 터지는'
        # 결함은 사라지지 않는다. repr 이 예외를 던져도 계약 오류만 나와야 한다.
        class Boom:
            def __repr__(self):
                raise RuntimeError("repr exploded")

        with pytest.raises(AdminApiResponseError):
            parse_register_response(Boom())
        with pytest.raises(AdminApiResponseError):
            parse_register_response({"status": Boom(), "text": "{}"})
        with pytest.raises(AdminApiResponseError):
            parse_register_response({"status": 201, "text": Boom()})

    @pytest.mark.parametrize("text", [
        '[{"name": "홍길동", "phone": "010-1234-5678"}]',      # 비객체 JSON
        "<html>홍길동 010-1234-5678 gateway error</html>",      # 비 JSON 본문
        '"홍길동 010-1234-5678"',
    ])
    def test_error_message_never_echoes_server_body_content(self, text):
        # 자체 적대검증에서 발견: 진단을 위해 원문을 오류에 넣었더니 후보 개인정보가
        # 로그·원장으로 샜다. 오류는 '내용'이 아니라 '모양'만 알려야 한다.
        with pytest.raises(AdminApiResponseError) as e:
            parse_register_response(_envelope(status=502, text=text))
        message = str(e.value)
        assert "홍길동" not in message
        assert "010-1234-5678" not in message
        assert "502" in message  # 진단에 필요한 정보는 남아 있어야 한다

    @pytest.mark.parametrize("body", [
        '{"ok": true, "deduped": false}',                      # candidate 누락
        '{"ok": true, "deduped": false, "candidate": null}',
        '{"ok": true, "deduped": false, "candidate": "x"}',
        '{"ok": true, "deduped": false, "candidate": []}',
        # 2차 적대검증 지적: 사전이기만 하면 통과해 빈 레코드도 성공으로 인정됐다.
        # 서버 표의 id 는 uuid primary key(20260507000000_pipeline.sql:3) 라 항상 있다.
        '{"ok": true, "deduped": false, "candidate": {}}',
        '{"ok": true, "deduped": false, "candidate": {"id": null}}',
        '{"ok": true, "deduped": false, "candidate": {"id": ""}}',
        '{"ok": true, "deduped": false, "candidate": {"id": "   "}}',
        '{"ok": true, "deduped": false, "candidate": {"id": 7}}',
    ])
    def test_missing_candidate_record_is_not_a_successful_registration(self, body):
        # Codex 2차 적대검증 발견(high): 서버는 성공 시 반드시 candidate 레코드를 준다
        # (route.ts:123, :151). 없는데도 recorded=True 로 보고하면 원장이 거짓이 된다.
        with pytest.raises(AdminApiResponseError):
            parse_register_response(_envelope(status=201, text=body))

    def test_hostile_mapping_whose_get_explodes_is_contract_error(self):
        # Codex 2차 적대검증 발견(low): Mapping 인지만 확인하고 .get() 은 보호가 없었다.
        from collections.abc import Mapping as _Mapping

        class HostileMapping(_Mapping):
            def __getitem__(self, key):
                raise RuntimeError("get exploded")

            def __iter__(self):
                return iter(())

            def __len__(self):
                return 0

        with pytest.raises(AdminApiResponseError):
            parse_register_response(HostileMapping())

    def test_describe_shape_is_total_even_when_len_and_type_name_are_hostile(self):
        # Codex 2차 적대검증 발견(low): 설명 함수가 길이 확인·문자열화에서 터지면 '메시지
        # 만들다 죽는' 결함이 되살아난다. repr 기반 _describe 는 유출 경로라 제거했고,
        # 남은 _describe_shape 가 어떤 입력에도 예외를 던지지 않아야 한다.
        from apps.aisearch.core.admin_api import _describe_shape

        class BadLen:
            def __len__(self):
                raise RuntimeError("len exploded")

        class HostileName(str):
            def __len__(self):
                raise RuntimeError("len exploded")

            def __format__(self, spec):
                raise RuntimeError("format exploded")

        class BadMeta(type):
            @property
            def __name__(cls):
                return HostileName("hostile")

        class BadTypeName(metaclass=BadMeta):
            pass

        for value in (BadLen(), BadTypeName(), object()):
            assert isinstance(_describe_shape(value), str)

    @pytest.mark.parametrize("status", [-1, 0, 99, 600, 1000])
    def test_out_of_range_status_is_rejected_as_a_broken_envelope(self, status):
        # 3차 적대검증 지적: 범위를 0~999 로 느슨하게 해도 이 값들은 뒤쪽 '서버가 거부함'
        # 처리에 걸려 똑같이 통과했다 — 경계를 증명하지 못하는 헛테스트였다.
        # 걸린 '이유'까지 고정해 범위가 넓어지는 회귀를 잡는다.
        with pytest.raises(AdminApiResponseError, match="HTTP status int"):
            parse_register_response({"status": status, "text": "{}"})

    def test_internal_defect_is_not_disguised_as_a_response_error(self, monkeypatch):
        # 3차 적대검증 지적: json 파싱의 예외 범위를 다시 넓혀도(회귀) 검사가 못 잡았다.
        # 우리 쪽 내부 결함은 '서버 응답 오류'로 둔갑하지 않고 그대로 드러나야 한다.
        # 주의: AdminApiResponseError 는 RuntimeError 하위형이라, RuntimeError 를 던지고
        # pytest.raises(RuntimeError) 로 받으면 둔갑해도 통과하는 헛테스트가 된다
        # (돌연변이 검사로 발견). 계약 오류와 겹치지 않는 종류를 써야 한다.
        import apps.aisearch.core.admin_api as module

        class InternalDefect(Exception):
            pass

        def exploding_loads(*args, **kwargs):
            raise InternalDefect("internal defect")

        monkeypatch.setattr(module.json, "loads", exploding_loads)
        with pytest.raises(InternalDefect):
            parse_register_response(_envelope())

    def test_absurdly_large_status_int_is_contract_error_not_crash(self):
        # 2차 적대검증 지적: 자릿수가 극단적인 정수를 오류 문장에 넣다 ValueError 로 죽었다.
        # (parametrize 로 넘기면 pytest 가 이름표를 만들다 같은 이유로 죽으므로 본문에서 만든다)
        with pytest.raises(AdminApiResponseError):
            parse_register_response({"status": 10 ** 5000, "text": "{}"})

    def test_deeply_nested_json_does_not_blow_the_stack(self):
        # 자체 3차 적대검증 발견: 중첩이 깊은 응답이 오면 RecursionError 로 죽었다.
        with pytest.raises(AdminApiResponseError):
            parse_register_response(_envelope(status=201, text="[" * 200_000))

    def test_error_message_carries_shape_not_server_reason(self):
        # 개정(개인정보 차단): 서버 error 원문에는 후보 이름·연락처가 실려 올 수 있으므로
        # 문장에 넣지 않는다. 진단에 필요한 상태번호와 값의 모양만 남는다.
        with pytest.raises(AdminApiResponseError) as e:
            parse_register_response(_envelope(
                status=401, text='{"ok": false, "error": "Unauthorized"}'))
        message = str(e.value)
        assert "Unauthorized" not in message
        assert "401" in message
        assert "str(len=12)" in message  # len("Unauthorized") == 12


# ── 후속 결함(PR#254 이후): 응답에서 온 값이 오류 문장·결과에 그대로 실려
#    개인정보(이름·연락처)와 내부키가 로그·원장으로 새는 경로가 남아 있었다.
#    오류는 '내용'이 아니라 '모양'만, 결과는 '안전한 영수증'만 남겨야 한다.
_PII_NAME = "홍길동"
_PII_PHONE = "010-1234-5678"
_PII_TEXT = f"{_PII_NAME} {_PII_PHONE}"


class TestResponseNeverLeaksPrivateData:
    def _assert_no_pii(self, probe: str) -> None:
        assert _PII_NAME not in probe
        assert _PII_PHONE not in probe

    def test_server_error_field_is_not_echoed_into_the_message(self):
        # 재현 1 — status=400, error 에 후보 이름·연락처가 담겨 오는 경우.
        import json as _json

        with pytest.raises(AdminApiResponseError) as e:
            parse_register_response(_envelope(
                status=400,
                text=_json.dumps({"ok": False, "error": _PII_TEXT})))
        message = str(e.value)
        self._assert_no_pii(message)
        assert "400" in message  # 진단에 필요한 모양 정보는 남는다

    def test_non_bool_deduped_value_is_not_echoed_into_the_message(self):
        # 재현 2 — 성공 모양이지만 deduped 자리에 개인정보 문자열이 온 경우.
        import json as _json

        with pytest.raises(AdminApiResponseError, match="deduped must be a bool") as e:
            parse_register_response(_envelope(
                status=201,
                text=_json.dumps({
                    "ok": True,
                    "candidate": {"id": "8f14e45f-ceea-467a-9f6b-2c3d4e5a6b71"},
                    "deduped": _PII_TEXT,
                })))
        self._assert_no_pii(str(e.value))

    def test_non_mapping_envelope_content_is_not_echoed_into_the_message(self):
        # 재현 3 — 전송 계층이 사전이 아닌 껍데기를 돌려준 경우.
        with pytest.raises(AdminApiResponseError, match="must return a mapping") as e:
            parse_register_response([_PII_TEXT])
        self._assert_no_pii(str(e.value))

    def test_bytes_text_content_is_not_echoed_into_the_message(self):
        # 재현 4 — text 가 개인정보를 담은 bytes 로 온 경우.
        with pytest.raises(AdminApiResponseError, match="text must be a str") as e:
            parse_register_response({"status": 201, "text": _PII_TEXT.encode("utf-8")})
        self._assert_no_pii(str(e.value))

    def test_success_outcome_keeps_only_a_safe_receipt(self):
        # 재현 5 — 정상 201 응답에 후보 개인정보와 내부키가 실려 와도 결과에 남으면 안 된다.
        # 요청 쪽 값과 구분되도록 서버 응답에는 다른 이름·연락처를 쓴다.
        import json as _json

        server_name, server_phone = "김서버", "010-9999-8888"
        cid = "8f14e45f-ceea-467a-9f6b-2c3d4e5a6b71"
        text = _json.dumps({
            "ok": True,
            "deduped": False,
            "candidate": {"id": cid, "name": server_name, "phone": server_phone},
            "debug_key": KEY,
        })

        outcome = parse_register_response(_envelope(status=201, text=text))
        probe = repr(outcome) + repr(vars(outcome))
        assert server_name not in probe
        assert server_phone not in probe
        assert KEY not in probe
        # 안전한 영수증은 그대로 남아 있어야 한다 — 지워버리는 것으로 통과하면 안 된다.
        assert outcome.recorded is True
        assert outcome.deduped is False
        assert outcome.status == 201
        assert outcome.candidate_id == cid

    def test_live_success_outcome_keeps_only_a_safe_receipt(self):
        # 같은 누출을 실제 호출 경로(AdminApiRecorder.live)에서도 막는지 고정한다.
        server_name, server_phone = "김서버", "010-9999-8888"
        cid = "8f14e45f-ceea-467a-9f6b-2c3d4e5a6b71"
        rec = AdminApiRecorder(
            base_url=BASE, internal_key=KEY, live=True,
            transport=FakeTransport(status=201, body={
                "ok": True,
                "deduped": False,
                "candidate": {"id": cid, "name": server_name, "phone": server_phone},
                "debug_key": KEY,
            }),
        )
        outcome = rec.register(candidate())
        probe = repr(outcome) + repr(vars(outcome))
        assert server_name not in probe
        assert server_phone not in probe
        assert KEY not in probe
        assert outcome.candidate_id == cid
