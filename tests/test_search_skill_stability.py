"""Harness Gate 4a — search·multisearch 스킬의 '운영 안정성(자동 복구)' 계약.

스킬 문서가 #18/#20/#22/#24에서 추가된 로그인·검색 안정성 동작을 반영했는지,
그리고 그 주장이 가리키는 코드 심볼이 실제로 존재하는지(과장/환각 경로 방지)를
기계로 고정한다. 각 단언은 "일부러 깨면 RED, 실제 문서/코드면 GREEN".

  S1  multisearch SKILL 존재 + 안정성 마커(쉬운 한국어 핵심어) 모두 포함
  S2  search SKILL 이 SOT(보안 챌린지 우회 금지) 재확인 + 포털 안정성은 multisearch 참조
  S3  안정성 주장이 가리키는 코드 심볼이 실존 (escaped-defect 보호)
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MULTISEARCH = REPO / "skills" / "multisearch" / "SKILL.md"
SEARCH = REPO / "skills" / "search" / "SKILL.md"
AUTOLOGIN = REPO / "tools" / "multi_position_sourcing" / "portal_autologin.py"
RECOVERY = REPO / "tools" / "multi_position_sourcing" / "portal_recovery.py"
WORKER = REPO / "tools" / "multi_position_sourcing" / "portal_worker.py"

# multisearch SKILL 이 반드시 담아야 할 안정성 마커(쉬운 한국어 핵심어).
MULTISEARCH_MARKERS = (
    "운영 안정성",
    "지수 백오프",
    "검색 시간제한",
    "셀렉터 드리프트",
    "잔재 잠금",
    "보안 챌린지",
)

# 안정성 주장이 가리키는 코드 심볼 — 실존해야 한다.
CODE_SYMBOLS = (
    (RECOVERY, "async def recover_after_reauth"),
    (RECOVERY, "relogin_backoff_base_seconds"),
    (WORKER, "search_timeout_seconds"),
    (WORKER, "async def run_one_search"),
    (WORKER, "def clear_stale_singleton_locks"),
    (AUTOLOGIN, "async def login_selector_preflight"),
)


def test_s1_multisearch_skill_exists() -> None:
    assert MULTISEARCH.exists(), f"부재: {MULTISEARCH}"


def test_s1_multisearch_has_stability_markers() -> None:
    text = MULTISEARCH.read_text(encoding="utf-8")
    missing = [m for m in MULTISEARCH_MARKERS if m not in text]
    assert not missing, f"multisearch SKILL 안정성 마커 누락: {missing}"


def test_s2_search_skill_reaffirms_sot_and_points_to_multisearch() -> None:
    assert SEARCH.exists(), f"부재: {SEARCH}"
    text = SEARCH.read_text(encoding="utf-8")
    assert "보안 챌린지" in text, "search SKILL: '보안 챌린지' 우회 금지 재확인 필요"
    assert "multisearch" in text, "search SKILL: 포털 안정성은 multisearch 참조 안내 필요"


def test_s3_stability_claims_reference_real_code() -> None:
    for path, symbol in CODE_SYMBOLS:
        assert path.exists(), f"코드 부재: {path}"
        assert symbol in path.read_text(encoding="utf-8"), f"코드 심볼 부재: {symbol} in {path.name}"
