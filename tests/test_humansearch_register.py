"""Harness Gate 4 — PC-C1a1: register dict → CapturedProfile 재구성 어댑터 (RED 먼저).

목적: 러너/results.json 의 dict 를 하드제외 판정용 CapturedProfile 로 되살린다.
  - 가용 필드(education·employment_history[EmploymentTenure]·visible_text·summary) 복원.
  - fail-closed: 하드제외를 신뢰성 있게 판정할 수 없는 결손 dict 는 None(→ 호출자가 '제외'로 처리).
  - 무손실 아님(ocr_text 등 원본 dict 에 없을 수 있음) — 가용 필드만 복원(2차검증 V2 재정의).
  - SOT: fail-open 금지 · models.CapturedProfile 재사용(제2 프로필 타입 금지).

각 단언은 "일부러 깨면 RED, 실제면 GREEN".
"""
from __future__ import annotations

import pytest

from tools.multi_position_sourcing.humansearch import hard_exclude_reason
from tools.multi_position_sourcing.humansearch_register import (
    FY26_AI_SEARCH_LIST_ID,
    FY26_AI_SEARCH_LIST_URL,
    PROFILE_SAVE_EVIDENCE_FIELDS,
    _candidate_task_description,
    build_discord_payload,
    build_discord_payloads,
    build_message,
    clickup_registration_eligible,
    discord_briefing_eligible,
    eligible,
    has_required_candidate_output_fields,
    has_saved_profile_evidence,
    post_discord,
    reconstruct_captured_profile,
    register_clickup_fy26_ai_search,
)
from tools.multi_position_sourcing.models import CapturedProfile, EmploymentTenure


def _runner_dict(**over) -> dict:
    """humansearch_cdp_run.py 가 실제로 내보내는 results 항목 형상."""
    d = {
        "idx": 1,
        "name": "홍길동",
        "url": "https://www.saramin.co.kr/profile/1",
        "otw": False,
        "headline": "Backend Engineer",
        "education": "부산대학교 학사",
        "score": 82,
        "breakdown": {"education": 24, "role_fit": 40, "profile_logic": 10, "job_stability": 8},
        "why_fit": ["must-have 직결: python"],
        "why_not": [],
        "screenshot": "/x/1.png",
        "summary": "백엔드 8년",
        "career_summary": "A사 Backend Engineer · 백엔드 8년",
        "current_or_past_companies": ["A사"],
        "visible_text": "python backend engineer, 안정적 경력",
        "skills": ["python", "backend"],
        "employment_history": [
            {"company": "A", "start_month": "2018-01", "end_month": "2024-06"},
        ],
    }
    d.update(over)
    return d


def test_discord_briefing_includes_full_url_summary_and_why_fit() -> None:
    result = _runner_dict(
        name="핵심 후보",
        url="https://www.linkedin.com/talent/profile/fully-qualified-candidate",
        profile_summary="B2B SaaS 영업 8년, 엔터프라이즈 딜 클로징과 팀 리딩 경험",
        career_summary="B2B SaaS 영업 8년, 엔터프라이즈 딜 클로징과 팀 리딩 경험",
        why_fit=["대형 고객 딜 발굴·클로징 경험이 JD와 직접 맞음", "플레잉 리드 경험 보유"],
    )
    message = build_message([result])
    assert result["url"] in message
    assert "경력 요약" in message
    assert result["profile_summary"] in message
    assert "적합 사유" in message
    assert result["why_fit"][0] in message

    payload = build_discord_payload([result])
    assert len(payload["embeds"]) == 1
    embed = payload["embeds"][0]
    assert embed["url"] == result["url"]
    assert result["url"] in embed["description"]
    assert result["profile_summary"] in embed["description"]
    assert result["why_fit"][0] in embed["description"]


def test_discord_briefing_eligibility_rejects_missing_contract_fields() -> None:
    valid = _runner_dict(url="https://www.linkedin.com/talent/profile/valid")
    no_summary = _runner_dict(
        url="https://www.linkedin.com/talent/profile/no-summary",
        summary="",
        headline="",
        career_summary="",
    )
    no_why_fit = _runner_dict(
        url="https://www.linkedin.com/talent/profile/no-fit",
        why_fit=[],
    )
    assert discord_briefing_eligible(
        [valid, no_summary, no_why_fit], "linkedin_rps"
    ) == [valid]


def test_discord_payload_splits_all_passers_without_omission() -> None:
    candidates = [
        _runner_dict(
            name=f"후보{i}",
            score=90,
            url=f"https://www.linkedin.com/talent/profile/core-{i}",
            profile_summary=f"후보{i} 경력 요약",
            why_fit=[f"후보{i} 적합 사유"],
        )
        for i in range(12)
    ]
    payloads = build_discord_payloads(candidates)
    assert [len(payload["embeds"]) for payload in payloads] == [10, 2]
    urls = [embed["url"] for payload in payloads for embed in payload["embeds"]]
    assert urls == [candidate["url"] for candidate in candidates]
    assert all("ClickUp" not in payload["content"] for payload in payloads)


def test_discord_payload_keeps_70_to_84_point_passers() -> None:
    candidates = [
        _runner_dict(
            name=f"후보{score}",
            score=score,
            url=f"https://www.linkedin.com/talent/profile/score-{score}",
        )
        for score in (90, 84, 80)
    ]
    payloads = build_discord_payloads(candidates)
    assert len(payloads) == 1
    assert [embed["url"] for embed in payloads[0]["embeds"]] == [
        candidate["url"] for candidate in candidates
    ]


def test_discord_payload_rejects_embed_url_over_platform_limit() -> None:
    candidate = _runner_dict(
        url="https://www.linkedin.com/talent/profile/" + "x" * 2100,
    )
    with pytest.raises(ValueError, match="URL"):
        build_discord_payloads([candidate])


def test_post_discord_validates_embed_description_before_loading_webhook(monkeypatch) -> None:
    from tools.multi_position_sourcing import humansearch_register as register

    monkeypatch.setattr(
        register,
        "_load_env",
        lambda _key: (_ for _ in ()).throw(AssertionError("loaded webhook before validation")),
    )
    payload = {
        "content": "header",
        "embeds": [
            {
                "title": "candidate",
                "url": "https://www.linkedin.com/talent/profile/x",
                "description": "x" * 4097,
            }
        ],
    }
    with pytest.raises(ValueError, match="description"):
        post_discord(payload)


# ── 가용 필드 복원 ───────────────────────────────────────────────
def test_reconstruct_restores_available_fields() -> None:
    p = reconstruct_captured_profile(_runner_dict(), "saramin")
    assert isinstance(p, CapturedProfile)
    assert p.profile_url == "https://www.saramin.co.kr/profile/1"
    assert p.source_channel == "saramin"
    assert p.visible_text == "python backend engineer, 안정적 경력"
    assert p.summary == "백엔드 8년"
    assert p.education == "부산대학교 학사"
    assert p.skills == ("python", "backend")
    assert p.current_or_past_companies == ("A사",)


def test_reconstruct_employment_history_becomes_tenure_tuples() -> None:
    hist = [
        {"company": "A", "start_month": "2021-01", "end_month": "2021-06"},
        {"company": "B", "start_month": "2021-07", "end_month": "2022-01"},
    ]
    p = reconstruct_captured_profile(_runner_dict(employment_history=hist), "jobkorea")
    assert p is not None
    assert isinstance(p.employment_history, tuple)
    assert all(isinstance(t, EmploymentTenure) for t in p.employment_history)
    assert p.employment_history[0] == EmploymentTenure("A", "2021-01", "2021-06")
    assert p.employment_history[1] == EmploymentTenure("B", "2021-07", "2022-01")


def test_reconstruct_channel_sets_source_channel() -> None:
    assert reconstruct_captured_profile(_runner_dict(), "linkedin_rps").source_channel == "linkedin_rps"


# ── fail-closed: 결손 dict 는 None (호출자가 '제외') ───────────────
def test_reconstruct_missing_url_is_fail_closed() -> None:
    d = _runner_dict()
    del d["url"]
    assert reconstruct_captured_profile(d, "saramin") is None


def test_reconstruct_empty_url_is_fail_closed() -> None:
    assert reconstruct_captured_profile(_runner_dict(url=""), "saramin") is None
    assert reconstruct_captured_profile(_runner_dict(url="   "), "saramin") is None


def test_reconstruct_no_text_fields_is_fail_closed() -> None:
    """프리랜서 마커를 볼 텍스트원(본문·요약·헤드라인)이 전혀 없으면 판정불가 → fail-closed(제외)."""
    d = _runner_dict()
    del d["visible_text"]
    del d["summary"]
    d.pop("headline", None)
    assert reconstruct_captured_profile(d, "saramin") is None


def test_reconstruct_none_text_values_is_fail_closed() -> None:
    """텍스트 필드가 None/빈값뿐이면 no-text → fail-closed (키 존재만으로 통과 금지)."""
    d = _runner_dict(visible_text=chr(0x200B), summary=chr(0xFEFF), headline=chr(0x200D), name="")
    assert reconstruct_captured_profile(d, "saramin") is None


def test_reconstructed_profile_detects_freelancer_in_headline_only() -> None:
    """프리랜서 표기가 headline 에만 있어도 매처가 봐야 한다 — 자기 적대검증(fail-open 차단)."""
    d = _runner_dict(visible_text="", summary="", headline="프리랜서 개발자", name="")
    p = reconstruct_captured_profile(d, "saramin")
    assert hard_exclude_reason(p, "saramin") == "freelancer"


def test_reconstruct_non_dict_is_fail_closed() -> None:
    for bad in (None, [], "x", 3):
        assert reconstruct_captured_profile(bad, "saramin") is None


# ── 하드제외 신호 보존 (C1a 체이닝 근거): 재구성 프로필이 매처에서 그대로 걸림 ──
def test_reconstructed_profile_detects_freelancer() -> None:
    p = reconstruct_captured_profile(_runner_dict(visible_text="프리랜서 개발자", summary=""), "saramin")
    assert hard_exclude_reason(p, "saramin") == "freelancer"


def test_reconstructed_profile_detects_low_tier_school_on_portal() -> None:
    p = reconstruct_captured_profile(
        _runner_dict(education="OO전문대학 졸업", visible_text="backend", summary=""), "saramin"
    )
    assert hard_exclude_reason(p, "saramin") == "low_tier_school"


def test_reconstructed_profile_detects_frequent_job_change() -> None:
    hist = [
        {"company": "A", "start_month": "2021-01", "end_month": "2021-06"},
        {"company": "B", "start_month": "2021-07", "end_month": "2022-01"},
    ]
    p = reconstruct_captured_profile(
        _runner_dict(visible_text="backend", summary="", education="", employment_history=hist),
        "jobkorea",
    )
    assert hard_exclude_reason(p, "jobkorea") == "frequent_job_change"


def test_reconstructed_clean_profile_passes() -> None:
    """정상 후보(지방 국공립·안정 경력)는 재구성 후에도 제외 사유 없음(과잉제외 방지)."""
    assert hard_exclude_reason(reconstruct_captured_profile(_runner_dict(), "saramin"), "saramin") is None


# ── 게이트4b step2(Codex 2차 적대검증) 발견 회귀 ──────────────────
def test_reconstruct_name_marker_does_not_overexclude() -> None:
    """name 은 신원 필드 — 마커 스캔 대상 아님. 이름에 우연히 2글자 마커 부분문자열('외주' 등)이
    있어도 본문이 정상이면 제외하지 않는다 — Codex 재검증 과잉제외(김외주→freelancer) 차단.
    프리랜서 신호는 본문(visible_text·summary·headline)에서 잡는다."""
    d = _runner_dict(name="김외주", visible_text="backend engineer 안정적", summary="부산대 8년", headline="")
    assert hard_exclude_reason(reconstruct_captured_profile(d, "saramin"), "saramin") is None


def test_reconstruct_invisible_only_text_is_fail_closed() -> None:
    """제로폭(U+200B) 등 보이지 않는 문자뿐이면 판정 불가 → fail-closed — Codex fail-open."""
    d = _runner_dict(visible_text=chr(0x200B), summary=chr(0xFEFF), headline=chr(0x200D), name="")
    assert reconstruct_captured_profile(d, "saramin") is None


def test_reconstruct_invalid_url_is_fail_closed() -> None:
    """무효 URL(스킴 없음·제로폭·내부공백)은 재구성 단계에서 fail-closed — Codex fail-open."""
    for bad in ("not-a-url", chr(0x200B), "https://x.com/a b", "javascript:void(0)"):
        assert reconstruct_captured_profile(_runner_dict(url=bad), "saramin") is None


def test_reconstruct_skills_non_list_does_not_crash() -> None:
    """skills 가 int/str 같은 비리스트여도 예외 없이 안전 복원(()) — Codex exception."""
    for bad in (123, "python", None, {"a": 1}):
        p = reconstruct_captured_profile(_runner_dict(skills=bad), "saramin")
        assert p is not None
        assert p.skills == ()


def test_reconstruct_positional_employment_history_detects_frequent() -> None:
    """employment_history 가 위치형 리스트/튜플로 와도 잦은이직을 놓치지 않음 — Codex fail-open."""
    hist = [["A", "2021-01", "2021-06"], ["B", "2021-07", "2022-01"]]
    p = reconstruct_captured_profile(
        _runner_dict(visible_text="backend", summary="", education="", employment_history=hist),
        "jobkorea",
    )
    assert hard_exclude_reason(p, "jobkorea") == "frequent_job_change"


# ── PC-C1a: 등록 경계 eligible() 에 하드제외 게이트 배선 (RED 먼저) ──────────────
# 현행 eligible() 은 score>=70 · 유효URL 만 보고 hard_exclude_reason 을 미호출 → 프리랜서·잦은이직·
# 전문대가 등록 브리핑으로 샌다. PC-C1a1 재구성 + PC-C0 매처로 채점 전 하드제외를 등록 경계에 강제한다.
_FREQ_HIST = [
    {"company": "A", "start_month": "2021-01", "end_month": "2021-06"},
    {"company": "B", "start_month": "2021-07", "end_month": "2022-01"},
]


def test_eligible_excludes_freelancer() -> None:
    r = _runner_dict(score=85, visible_text="프리랜서 개발자", summary="")
    assert eligible([r], "saramin") == []


def test_eligible_excludes_frequent_job_change() -> None:
    r = _runner_dict(score=85, visible_text="backend", summary="", education="", employment_history=_FREQ_HIST)
    assert eligible([r], "jobkorea") == []


def test_eligible_excludes_low_tier_school_on_portal() -> None:
    r = _runner_dict(score=85, education="OO전문대학 졸업", visible_text="backend", summary="")
    assert eligible([r], "saramin") == []


def test_eligible_keeps_clean_passer() -> None:
    r = _runner_dict(score=85, visible_text="backend engineer", summary="부산대 8년 안정적")
    assert eligible([r], "saramin") == [r]


def test_eligible_low_tier_school_kept_on_linkedin() -> None:
    """링크드인은 학교 하드제외 미적용(portal 채널만) — 회귀 보호."""
    r = _runner_dict(
        score=85, education="OO전문대학", visible_text="robotics", summary="x",
        url="https://www.linkedin.com/in/x",
    )
    assert eligible([r], "linkedin_rps") == [r]


def test_eligible_fail_closed_on_unreconstructable_dict() -> None:
    """재구성 불가(본문 전무) 후보는 등록 경계에서 fail-closed(제외)."""
    r = _runner_dict(score=85)
    del r["visible_text"]
    del r["summary"]
    r.pop("headline", None)
    assert eligible([r], "saramin") == []


def test_eligible_still_filters_low_score_and_bad_url() -> None:
    """기존 계약 유지(회귀): 점수 미달·URL 무효는 여전히 제외."""
    low = _runner_dict(score=60, visible_text="backend", summary="ok")
    bad = _runner_dict(score=90, url="javascript:void(0)", visible_text="backend", summary="ok")
    assert eligible([low, bad], "saramin") == []


def test_eligible_sorts_passers_by_score_desc() -> None:
    """정상 후보 다건은 점수 내림차순 정렬 유지(기존 계약)."""
    lo = _runner_dict(score=75, visible_text="backend", summary="부산대", url="https://x.co/a")
    hi = _runner_dict(score=95, visible_text="backend", summary="부산대", url="https://x.co/b")
    assert eligible([lo, hi], "saramin") == [hi, lo]


# ── 게이트4b step2(Codex 2차 적대검증) 발견 회귀 ──────────────────
def test_eligible_excludes_nan_score() -> None:
    """score=NaN 은 어떤 비교도 False → '<threshold' 를 통과하던 fail-open 차단(Codex)."""
    r = _runner_dict(score=float("nan"), visible_text="backend", summary="부산대")
    assert eligible([r], "saramin") == []


def test_eligible_excludes_profile_url_only_schema_drift() -> None:
    """register 스키마 URL 키는 'url' — url 없이 profile_url 만 있는 dict 는 제외(fail-closed).
    하류 build_message/clickup 이 r['url'] 을 읽으므로 통과시키면 KeyError — Codex 재검증 재현 차단."""
    r = _runner_dict(visible_text="backend", summary="부산대 8년")
    r["profile_url"] = r.pop("url")
    assert eligible([r], "saramin") == []


def test_eligible_excludes_non_finite_score() -> None:
    """score=inf/-inf/nan 비유한 값은 제외 — inf>=threshold 로 통과하던 fail-open 차단(Codex 재검증)."""
    for bad in (float("inf"), float("-inf"), float("nan")):
        r = _runner_dict(score=bad, visible_text="backend", summary="부산대")
        assert eligible([r], "saramin") == []


def test_eligible_skips_non_dict_items_without_crash() -> None:
    """results 에 비dict 항목이 섞여도 예외 없이 skip(fail-closed) — Codex exception."""
    clean = _runner_dict(visible_text="backend", summary="부산대", url="https://x.co/ok")
    assert eligible([clean, None, "bad-item", 123], "saramin") == [clean]


# ── ClickUp FY26AI_Search 등록 계약: 중복검사·칸반 Task/Subtask·프로필 저장 증거 ──
class _FakeClickUp:
    def __init__(
        self,
        *,
        parent_hits: list[dict] | None = None,
        duplicate_profile_urls: set[str] | None = None,
    ) -> None:
        self.parent_hits = parent_hits or []
        self.duplicate_profile_urls = duplicate_profile_urls or set()
        self.searches: list[tuple[str, str, str | None]] = []
        self.creates: list[tuple[str, str, str, str | None]] = []

    def search_tasks(self, *, list_id: str, query: str, parent: str | None = None) -> list[dict]:
        self.searches.append((list_id, query, parent))
        if parent is None:
            return self.parent_hits
        if query in self.duplicate_profile_urls:
            return [{"id": "SUB-EXISTING", "url": "https://app.clickup.com/t/SUB-EXISTING"}]
        return []

    def create_task(
        self,
        *,
        list_id: str,
        name: str,
        description: str,
        parent: str | None = None,
    ) -> dict:
        task_id = f"TASK-{len(self.creates) + 1}"
        self.creates.append((list_id, name, description, parent))
        return {"id": task_id, "url": f"https://app.clickup.com/t/{task_id}"}


def test_clickup_registration_eligible_requires_saved_profile_evidence() -> None:
    """ClickUp 등록은 프로필 저장 증거가 있는 후보만 통과 — 단순 URL/점수 통과와 분리."""
    saved = _runner_dict(screenshot="/tmp/profile.png")
    unsaved = _runner_dict(url="https://www.linkedin.com/in/not-saved")
    unsaved.pop("screenshot", None)
    unsaved.pop("evidence_paths", None)

    assert has_saved_profile_evidence(saved) is True
    assert has_saved_profile_evidence(unsaved) is False
    assert clickup_registration_eligible([saved, unsaved], "linkedin_rps") == [saved]


def test_clickup_registration_eligible_requires_output_contract_fields() -> None:
    """Subtask 후보는 profile_url·score·why_fit·profile_summary 계약을 만족해야 한다."""
    base = _runner_dict(
        url="https://www.linkedin.com/talent/profile/abc",
        score=91,
        why_fit=["직무 직결"],
        summary="프로필 요약",
        screenshot="/tmp/profile.png",
    )
    no_why_fit = dict(base, url="https://www.linkedin.com/talent/profile/no-why", why_fit=[])
    no_summary = dict(base, url="https://www.linkedin.com/talent/profile/no-summary", summary="")

    assert has_required_candidate_output_fields(base) is True
    assert has_required_candidate_output_fields(no_why_fit) is False
    assert has_required_candidate_output_fields(no_summary) is False
    assert clickup_registration_eligible([base, no_why_fit, no_summary], "linkedin_rps") == [base]


def test_clickup_fy26_registration_checks_duplicates_before_creating_tasks() -> None:
    """부모 Task 와 후보 profile_url Subtask 를 먼저 검색한 뒤 FY26AI_Search 리스트에만 생성."""
    fake = _FakeClickUp()
    candidate = _runner_dict(
        name="홍길동",
        url="https://www.linkedin.com/talent/profile/abc",
        score=91,
        screenshot="/tmp/profile.png",
    )

    plan = register_clickup_fy26_ai_search(
        position_name="Acme Backend",
        position_id="86abc",
        passers=[candidate],
        channel="linkedin_rps",
        clickup_search_tasks=fake.search_tasks,
        clickup_create_task=fake.create_task,
        dry_run=False,
    )

    assert plan.list_id == FY26_AI_SEARCH_LIST_ID
    assert plan.list_url == FY26_AI_SEARCH_LIST_URL
    assert fake.searches[0] == (FY26_AI_SEARCH_LIST_ID, "Acme Backend", None)
    assert (FY26_AI_SEARCH_LIST_ID, candidate["url"], plan.parent_task_id) in fake.searches
    assert len(fake.creates) == 2
    assert fake.creates[0][0] == FY26_AI_SEARCH_LIST_ID
    assert fake.creates[0][3] is None
    assert fake.creates[1][0] == FY26_AI_SEARCH_LIST_ID
    assert fake.creates[1][3] == plan.parent_task_id
    assert candidate["url"] in fake.creates[1][1]
    assert candidate["url"] in fake.creates[1][2]


def test_clickup_candidate_subtask_description_explains_fit_in_detail() -> None:
    """Subtask 본문은 URL+점수만이 아니라 왜 맞는지 판단 근거를 상세히 보여줘야 한다."""
    candidate = _runner_dict(
        name="홍길동",
        url="https://www.linkedin.com/talent/profile/detail",
        score=91,
        headline="AI Product Builder",
        education="KAIST 석사",
        summary="AI SaaS 제품기획과 B2B GTM을 함께 수행",
        profile_summary="AI SaaS 7년, B2B 고객검증과 제품 출시 경험",
        skills=["AI SaaS", "B2B", "MVP"],
        breakdown={"education": 28, "role_fit": 45, "profile_logic": 9, "job_stability": 9},
        why_fit=["JD 필수요건인 AI 서비스 기획과 B2B 고객검증 경험이 직접 맞음", "초기 제품 출시 경험이 MVP 검증 업무와 맞음"],
        why_not=["대기업 프로세스 경험은 상대적으로 약함"],
        screenshot="/tmp/profile.png",
    )

    body = _candidate_task_description(candidate, position_id="86abc", channel="linkedin_rps")

    assert "프로필 요약:" in body
    assert "왜 이 포지션에 잘 맞는지:" in body
    assert "점수 근거:" in body
    assert "학력 28 / 직무 45 / 논리 9 / 안정 9" in body
    assert "프로필에서 확인한 신호:" in body
    assert "기술/키워드: AI SaaS, B2B, MVP" in body
    assert "리스크/확인 필요:" in body
    assert "등록 판단:" in body
    assert "JD 필수요건인 AI 서비스 기획과 B2B 고객검증 경험이 직접 맞음" in body


def test_clickup_fy26_registration_skips_duplicate_candidate_subtask() -> None:
    """같은 부모 아래 이미 profile_url 이 있으면 후보 Subtask 를 새로 만들지 않는다."""
    candidate = _runner_dict(
        name="홍길동",
        url="https://www.linkedin.com/talent/profile/dup",
        score=88,
        screenshot="/tmp/profile.png",
    )
    fake = _FakeClickUp(duplicate_profile_urls={candidate["url"]})

    plan = register_clickup_fy26_ai_search(
        position_name="Acme Backend",
        position_id="86abc",
        passers=[candidate],
        channel="linkedin_rps",
        clickup_search_tasks=fake.search_tasks,
        clickup_create_task=fake.create_task,
        dry_run=False,
    )

    assert len(fake.creates) == 1  # parent only
    assert plan.candidates[0].action == "skipped_duplicate"
    assert plan.candidates[0].profile_url == candidate["url"]


def test_clickup_fy26_registration_requires_duplicate_checker() -> None:
    """중복검사 어댑터가 없으면 dry-run 이어도 등록 계획을 만들지 않는다."""
    with pytest.raises(RuntimeError, match="duplicate_check_required"):
        register_clickup_fy26_ai_search(
            position_name="Acme Backend",
            position_id="86abc",
            passers=[_runner_dict(screenshot="/tmp/profile.png")],
            channel="linkedin_rps",
            clickup_search_tasks=None,
            clickup_create_task=None,
            dry_run=True,
        )


def test_clickup_fy26_registration_dry_run_never_creates_tasks() -> None:
    """dry-run 은 중복검사만 하고 create_task 를 호출하지 않는다."""
    fake = _FakeClickUp()
    candidate = _runner_dict(
        url="https://www.linkedin.com/talent/profile/dry",
        score=82,
        screenshot="/tmp/profile.png",
    )

    plan = register_clickup_fy26_ai_search(
        position_name="Acme Backend",
        position_id="86abc",
        passers=[candidate],
        channel="linkedin_rps",
        clickup_search_tasks=fake.search_tasks,
        clickup_create_task=fake.create_task,
        dry_run=True,
    )

    assert fake.creates == []
    assert plan.parent_action == "planned_create"
    assert plan.candidates[0].action == "planned_create"


def test_clickup_fy26_registration_live_requires_create_adapter() -> None:
    """live 모드에서 create 어댑터가 없으면 created 라고 주장하지 않고 fail-closed."""
    fake = _FakeClickUp()
    with pytest.raises(RuntimeError, match="clickup_create_task_required"):
        register_clickup_fy26_ai_search(
            position_name="Acme Backend",
            position_id="86abc",
            passers=[_runner_dict(screenshot="/tmp/profile.png")],
            channel="linkedin_rps",
            clickup_search_tasks=fake.search_tasks,
            clickup_create_task=None,
            dry_run=False,
        )


def test_clickup_fy26_registration_live_requires_parent_task_id() -> None:
    """부모 Task id 를 받지 못하면 후보를 top-level task 로 만들지 않는다."""
    fake = _FakeClickUp()

    def bad_create_task(**_kwargs) -> dict:
        return {"id": "", "url": "https://app.clickup.com/t/EMPTY"}

    with pytest.raises(RuntimeError, match="parent_task_id_required"):
        register_clickup_fy26_ai_search(
            position_name="Acme Backend",
            position_id="86abc",
            passers=[_runner_dict(screenshot="/tmp/profile.png")],
            channel="linkedin_rps",
            clickup_search_tasks=fake.search_tasks,
            clickup_create_task=bad_create_task,
            dry_run=False,
        )


def test_profile_save_evidence_fields_include_db_and_supabase_ids() -> None:
    """DB/Supabase 저장 id 도 SOT 의 프로필 저장 증거 필드로 인정된다."""
    assert "sourcing_result_id" in PROFILE_SAVE_EVIDENCE_FIELDS
    assert "db_row_id" in PROFILE_SAVE_EVIDENCE_FIELDS
    assert has_saved_profile_evidence(_runner_dict(screenshot="", sourcing_result_id="src-1")) is True
    assert has_saved_profile_evidence(_runner_dict(screenshot="", db_row_id="row-1")) is True
