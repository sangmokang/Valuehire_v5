from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tools.multi_position_sourcing.auth_classifier import classify_auth_observation


NOW = datetime(2026, 7, 26, 3, 0, tzinfo=timezone.utc).isoformat()


def _classify(site, url, markers, **changes):
    args = {
        "site": site,
        "target_id_before": "page-1",
        "target_id_after": "page-1",
        "url_before": url,
        "url_after": url,
        "markers": markers,
        "observed_at": NOW,
    }
    args.update(changes)
    return classify_auth_observation(**args)


@pytest.mark.parametrize(
    ("site", "url", "markers", "proofs"),
    [
        (
            "saramin",
            "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
            {
                "account_or_logout": True, "search_input": True,
                "career_min": True, "career_max": True,
                "challenge_control": False, "multiple_sign_in": False,
            },
            ["account_or_logout", "search_input", "career_min", "career_max"],
        ),
        (
            "jobkorea",
            "https://www.jobkorea.co.kr/Corp/Person/Find",
            {
                "logout": True, "company_account": True, "talent_search": True,
                "challenge_control": False, "multiple_sign_in": False,
            },
            ["logout", "company_account", "talent_search"],
        ),
        (
            "linkedin_rps",
            "https://www.linkedin.com/talent/home",
            {
                "recruiter_marker": True,
                "challenge_control": False, "multiple_sign_in": False,
            },
            ["talent_surface", "recruiter_marker"],
        ),
    ],
)
def test_site_truth_table_requires_all_fresh_markers(site, url, markers, proofs):
    result = _classify(site, url, markers)
    assert result["state"] == "AUTHENTICATED"
    assert result["proof_names"] == proofs
    assert result["block_names"] == []
    assert "body" not in repr(result).lower()


def test_linkedin_url_alone_and_partial_site_markers_never_authenticate():
    linkedin = _classify(
        "linkedin_rps",
        "https://www.linkedin.com/talent/home",
        {"recruiter_marker": False, "challenge_control": False, "multiple_sign_in": False},
    )
    assert linkedin["state"] == "AUTH_LOST"

    saramin = _classify(
        "saramin",
        "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
        {
            "account_or_logout": True, "search_input": True,
            "career_min": True, "career_max": False,
            "challenge_control": False, "multiple_sign_in": False,
        },
    )
    assert saramin["state"] == "AUTH_LOST"


def test_instructional_body_words_are_not_classifier_inputs_or_false_positives():
    result = _classify(
        "jobkorea",
        "https://www.jobkorea.co.kr/Corp/Person/Find",
        {
            "logout": False, "company_account": False, "talent_search": False,
            "challenge_control": False, "multiple_sign_in": False,
            "body_text": "로그아웃 보안문자 multiple sign-ins",
        },
    )
    assert result["state"] == "AUTH_LOST"
    assert "body_text" not in result["proof_names"]
    assert "body_text" not in result["block_names"]


@pytest.mark.parametrize(
    ("url", "markers", "state", "block"),
    [
        (
            "https://www.linkedin.com/talent/home",
            {"recruiter_marker": True, "challenge_control": True, "multiple_sign_in": False},
            "HUMAN_AUTH_REQUIRED", "challenge_control",
        ),
        (
            "https://www.linkedin.com/checkpoint/challenge",
            {"recruiter_marker": False, "challenge_control": False, "multiple_sign_in": False},
            "AUTH_LOST", "challenge_path",
        ),
        (
            "https://www.linkedin.com/enterprise-authentication/sessions",
            {"recruiter_marker": False, "challenge_control": False, "multiple_sign_in": True},
            "AUTH_CONFLICT", "multiple_sign_in",
        ),
    ],
)
def test_challenge_and_conflict_states_are_terminal(url, markers, state, block):
    result = _classify("linkedin_rps", url, markers)
    assert result["state"] == state
    assert block in result["block_names"]


def test_probe_redirect_or_target_swap_is_terminal():
    changed_url = _classify(
        "linkedin_rps",
        "https://www.linkedin.com/talent/home",
        {"recruiter_marker": True, "challenge_control": False, "multiple_sign_in": False},
        url_after="https://www.linkedin.com/authwall",
    )
    assert changed_url["state"] == "TARGET_CHANGED_DURING_PROBE"

    changed_query = _classify(
        "linkedin_rps",
        "https://www.linkedin.com/talent/home?origin=one",
        {"recruiter_marker": True, "challenge_control": False, "multiple_sign_in": False},
        url_after="https://www.linkedin.com/talent/home?origin=two",
    )
    assert changed_query["state"] == "TARGET_CHANGED_DURING_PROBE"

    changed_target = _classify(
        "linkedin_rps",
        "https://www.linkedin.com/talent/home",
        {"recruiter_marker": True, "challenge_control": False, "multiple_sign_in": False},
        target_id_after="page-2",
    )
    assert changed_target["state"] == "TARGET_CHANGED_DURING_PROBE"


def test_missing_or_non_boolean_selector_is_selector_drift():
    result = _classify(
        "saramin",
        "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
        {
            "account_or_logout": True, "search_input": True,
            "career_min": True, "challenge_control": False,
            "multiple_sign_in": False,
        },
    )
    assert result["state"] == "SELECTOR_DRIFT"
    assert result["block_names"] == ["career_max"]
