from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.multi_position_sourcing.browser_evidence import (
    BrowserEvidenceError,
    capture_owned_browser_evidence,
)
from tools.multi_position_sourcing.session_guard import (
    AuthObservation,
    BrowserTargetRef,
    run_capture_evidence_episode,
)


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
PROFILE_URL = "https://www.linkedin.com/talent/profile/AAA?project=1752949252"


class _Tab:
    def __init__(self, *, url: str = PROFILE_URL, text: str = "Candidate\nRobotics engineer") -> None:
        self.target_id = "target-exact"
        self.url = url
        self.text = text
        self.send_calls: list[str] = []
        self.eval_calls = 0
        self.change_url_after_screenshot = ""
        self.disconnected = 0

    def eval(self, script: str):
        self.eval_calls += 1
        if script == "location.href":
            return self.url
        if "document.body" in script:
            return self.text
        return None

    def send(self, method: str, _params=None):
        self.send_calls.append(method)
        if method == "Page.captureScreenshot":
            if self.change_url_after_screenshot:
                self.url = self.change_url_after_screenshot
            return {"data": base64.b64encode(PNG_1X1).decode("ascii")}
        raise AssertionError(method)

    def disconnect(self) -> bool:
        self.disconnected += 1
        return True


def _auth(tab: _Tab, _site: str) -> AuthObservation:
    return AuthObservation(
        authenticated=True,
        challenge=False,
        auth_conflict=False,
        url=tab.url,
        proof_names=("recruiter_menu",),
    )


class _Archive:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def save(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(row_id=73)


def test_owned_capture_saves_private_screen_text_manifest_and_profile_receipt(tmp_path: Path) -> None:
    tab = _Tab()
    archive = _Archive()
    guards: list[str] = []

    receipt = capture_owned_browser_evidence(
        tab,
        site="linkedin_rps",
        task="humansearch",
        mode="profile",
        expected_target_id="target-exact",
        profile_url="https://www.linkedin.com/talent/profile/AAA",
        mutation_guard=lambda: guards.append("guard"),
        auth_probe=_auth,
        root_dir=tmp_path,
        archive_store=archive,
        position_id="position-1",
        candidate_index=4,
    )

    assert receipt.status == "saved"
    assert receipt.archive_row_id == 73
    assert len(guards) >= 3
    assert tab.send_calls == ["Page.captureScreenshot"]
    assert len(archive.calls) == 1
    assert archive.calls[0]["profile_url"] == "https://www.linkedin.com/talent/profile/AAA"
    assert archive.calls[0]["resume_text"] == tab.text
    for value in (receipt.screenshot_path, receipt.text_path, receipt.manifest_path):
        path = Path(value)
        assert path.is_file()
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700
    manifest = json.loads(Path(receipt.manifest_path).read_text(encoding="utf-8"))
    assert manifest["status"] == "saved"
    assert manifest["screenshot_sha256"] == receipt.screenshot_sha256
    assert manifest["visible_text_sha256"] == receipt.visible_text_sha256
    assert tab.text not in Path(receipt.manifest_path).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "observation",
    [
        AuthObservation(False, False, PROFILE_URL),
        AuthObservation(False, True, PROFILE_URL),
        AuthObservation(False, False, PROFILE_URL, auth_conflict=True),
    ],
)
def test_auth_loss_challenge_or_conflict_blocks_before_screenshot_and_files(
    tmp_path: Path, observation: AuthObservation
) -> None:
    tab = _Tab()
    with pytest.raises(BrowserEvidenceError, match="authenticated"):
        capture_owned_browser_evidence(
            tab,
            site="linkedin_rps",
            task="login",
            mode="evidence",
            expected_target_id="target-exact",
            mutation_guard=lambda: None,
            auth_probe=lambda _tab, _site: observation,
            root_dir=tmp_path,
        )
    assert tab.send_calls == []
    assert list(tmp_path.rglob("*")) == []


def test_page_identity_change_after_screenshot_is_not_persisted(tmp_path: Path) -> None:
    tab = _Tab()
    tab.change_url_after_screenshot = "https://www.linkedin.com/checkpoint/challenge"
    with pytest.raises(BrowserEvidenceError, match="changed"):
        capture_owned_browser_evidence(
            tab,
            site="linkedin_rps",
            task="ai-search",
            mode="profile",
            expected_target_id="target-exact",
            profile_url="https://www.linkedin.com/talent/profile/AAA",
            mutation_guard=lambda: None,
            auth_probe=_auth,
            root_dir=tmp_path,
            archive_store=_Archive(),
            position_id="position-1",
            candidate_index=1,
        )
    assert tab.send_calls == ["Page.captureScreenshot"]
    assert list(tmp_path.rglob("*")) == []


def test_capture_episode_reuses_exact_target_lease_and_disconnects_only(tmp_path: Path) -> None:
    trace: list[str] = []
    idle_values = iter((70.0, 71.0, 72.0, 73.0))

    class Lease:
        def acquire(self):
            trace.append("lease.acquire")

        def assert_owned(self):
            trace.append("lease.assert_owned")

        def release(self):
            trace.append("lease.release")

    tab = _Tab()
    ref = BrowserTargetRef(
        site="linkedin_rps",
        endpoint="http://127.0.0.1:9224",
        target_id="target-exact",
        websocket_url="ws://127.0.0.1:9224/devtools/page/target-exact",
        initial_url=PROFILE_URL,
        profile_path="/private/linkedin-profile",
        browser_pid=4242,
    )

    def capture(*_args, **kwargs):
        kwargs["mutation_guard"]()
        trace.append("capture")
        return SimpleNamespace(status="saved", manifest_path=str(tmp_path / "manifest.json"))

    result = run_capture_evidence_episode(
        "linkedin_rps",
        task="url",
        mode="evidence",
        agent="Codex",
        target_id="target-exact",
        owner_snapshot=lambda: SimpleNamespace(
            detection_status="ok",
            owner_activity_detected=False,
            idle_seconds=next(idle_values),
            portal_site_active=True,
        ),
        mutation_sleep=lambda _seconds: None,
        wait_sleep=lambda _seconds: None,
        _lease_factory=lambda _site: Lease(),
        _target_resolver=lambda *_args, **_kwargs: ref,
        _tab_attacher=lambda *_args, **_kwargs: tab,
        _auth_reader=_auth,
        _capture=capture,
        _root_dir=tmp_path,
    )

    assert result["status"] == "saved"
    assert result["site"] == "linkedin_rps"
    assert "capture" in trace
    assert tab.disconnected == 1
    assert trace[-1] == "lease.release"

