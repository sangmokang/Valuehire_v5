"""session_guard human-auth 성공 → 로그인 영수증 파일 기록 배선 (#639).

장벽이 통과 가능해지는 유일한 정식 경로: human-auth 가 AUTHENTICATED + 증거 저장을
확인했을 때만 login_barrier 영수증이 생긴다. 모델/호출자 문자열로는 못 만든다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from tools.multi_position_sourcing import session_guard

SHA = hashlib.sha256(b"x").hexdigest()


def _episode(tmp_path: Path) -> dict:
    paths = {}
    for k in ("screenshot_path", "text_path", "manifest_path"):
        p = tmp_path / f"{k}.bin"
        p.write_bytes(b"x")
        paths[k] = str(p)
    return {
        "status": "authenticated",
        "capture_status": "saved",
        "site": "saramin",
        "already_authenticated": True,
        "auth_url": "https://www.saramin.co.kr/",
        "proof_names": ["gnb_profile_badge"],
        "evidence": {
            "target_id": "T1",
            "capture_status": "saved",
            "screenshot_sha256": SHA,
            "visible_text_sha256": SHA,
            **paths,
        },
    }


def test_human_auth_success_writes_login_receipt(tmp_path, monkeypatch, capsys):
    rdir = tmp_path / "receipts"
    monkeypatch.setenv("VH_LOGIN_RECEIPT_DIR", str(rdir))
    monkeypatch.setenv("VALUEHIRE_MACHINE", "macmini")
    with patch.object(session_guard, "run_human_auth_episode",
                      return_value=_episode(tmp_path)):
        code = session_guard.main([
            "human-auth", "--site", "saramin", "--agent", "fleet",
        ])
    assert code == 0
    receipt_path = rdir / "saramin.json"
    assert receipt_path.is_file(), "human-auth 성공이 로그인 영수증을 남겨야 한다"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["channel"] == "saramin"
    assert receipt["state"] == "AUTHENTICATED"
    assert receipt["host"] == "macmini"
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out.get("login_receipt_path") == str(receipt_path)


def test_human_auth_failure_writes_nothing(tmp_path, monkeypatch):
    rdir = tmp_path / "receipts"
    monkeypatch.setenv("VH_LOGIN_RECEIPT_DIR", str(rdir))
    monkeypatch.setenv("VALUEHIRE_MACHINE", "macmini")
    with patch.object(session_guard, "run_human_auth_episode",
                      return_value={"status": "evidence_failed", "site": "saramin",
                                    "capture_status": "failed"}):
        code = session_guard.main([
            "human-auth", "--site", "saramin", "--agent", "fleet",
        ])
    assert code == 1
    assert not (rdir / "saramin.json").exists()
