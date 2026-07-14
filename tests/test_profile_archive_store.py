import pytest

from tools.multi_position_sourcing.profile_archive_store import ProfileArchiveStore


def test_opened_profile_requires_complete_local_receipt_before_advance(tmp_path):
    shot = tmp_path / "profile.png"
    shot.write_bytes(b"valid screenshot bytes")
    store = ProfileArchiveStore(tmp_path / "archive.sqlite3")
    receipt = store.save(
        profile_url="https://www.jobkorea.co.kr/Corp/Person/Read/123",
        channel="jobkorea", position_id="p1", scenario="balanced", page=3,
        candidate_index=7, screenshot_path=shot, resume_text="경력 본문",
        hard_exclude_reason="freelancer",
    )
    assert receipt.row_id > 0
    assert len(receipt.screenshot_sha256) == 64
    assert receipt.remote_status == "pending"


@pytest.mark.parametrize("url,text,has_shot", [
    ("", "본문", True),
    ("https://www.saramin.co.kr/profile/1", "", True),
    ("https://www.saramin.co.kr/profile/1", "본문", False),
])
def test_incomplete_profile_save_has_no_receipt(tmp_path, url, text, has_shot):
    shot = tmp_path / "profile.png"
    if has_shot:
        shot.write_bytes(b"x")
    store = ProfileArchiveStore(tmp_path / "archive.sqlite3")
    with pytest.raises(ValueError):
        store.save(
            profile_url=url, channel="saramin", position_id="p1", scenario="precise",
            page=1, candidate_index=1, screenshot_path=shot, resume_text=text,
        )
