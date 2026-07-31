"""테스트 공용 — 실제 파일에 결합된 프로필 저장 증거 영수증 생성기.

V1 3라운드 이후 `recorders.has_saved_profile_evidence()` 는 manifest·스크린샷이
**디스크에 실재하고** 스크린샷의 sha256 이 일치할 때만 증거로 인정한다. 그래서
테스트도 실제 파일을 만들어야 한다(가짜 경로로 통과시키는 픽스처는 게이트를
무력화하는 것과 같다).
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

#: 테스트 세션 동안 유지되는 증거 파일 보관소.
_ROOT = Path(tempfile.mkdtemp(prefix="aisearch-evidence-"))


def make_evidence(
    profile_url: str,
    *,
    position_id: str,
    site: str = "linkedin_rps",
    task: str = "aisearch",
    mode: str = "profile",
) -> dict:
    """실제 manifest/스크린샷 파일을 만들고 그 영수증을 돌려준다."""
    key = hashlib.sha256(f"{profile_url}|{position_id}|{site}".encode()).hexdigest()[:16]
    folder = _ROOT / key
    folder.mkdir(parents=True, exist_ok=True)
    shot = folder / "profile.png"
    if not shot.exists():
        shot.write_bytes(f"screenshot-of-{profile_url}".encode())
    manifest = folder / "manifest.json"
    if not manifest.exists():
        manifest.write_text(
            json.dumps({"profile_url": profile_url, "position_id": position_id}),
            encoding="utf-8",
        )
    return {
        "profile_url": profile_url,
        "site": site,
        "position_id": position_id,
        "task": task,
        "mode": mode,
        "manifest_path": str(manifest),
        "screenshot_path": str(shot),
        "screenshot_sha256": hashlib.sha256(shot.read_bytes()).hexdigest(),
    }
