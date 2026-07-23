from __future__ import annotations

import base64
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.multi_position_sourcing.browser_evidence import (
    BrowserEvidenceError,
    capture_owned_browser_evidence,
    complete_evidence_payload,
)
from tools.multi_position_sourcing import browser_evidence
from tools.multi_position_sourcing.session_guard import (
    AuthObservation,
    BrowserTargetRef,
    read_auth_observation,
    resolve_existing_target,
    run_capture_evidence_episode,
)
from tools.multi_position_sourcing import session_guard
from tools.multi_position_sourcing.profile_archive_store import ProfileArchiveStore


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
    def __init__(self, root: Path) -> None:
        self.calls: list[dict] = []
        self.store = ProfileArchiveStore(root / "profile-archives.sqlite3")
        self.path = self.store.path

    def save_with_finalizer(self, **kwargs):
        self.calls.append(kwargs)
        return self.store.save_with_finalizer(**kwargs)


class _ManifestCheckingArchive(_Archive):
    def save_with_finalizer(self, **kwargs):
        manifest_path = Path(kwargs["screenshot_path"]).with_name("manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "pending"
        return super().save_with_finalizer(**kwargs)


def test_owned_capture_saves_private_screen_text_manifest_and_profile_receipt(tmp_path: Path) -> None:
    tab = _Tab()
    archive = _Archive(tmp_path)
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
    assert isinstance(receipt.archive_row_id, int) and receipt.archive_row_id > 0
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
    assert complete_evidence_payload(receipt.public_dict()) is True


def test_profile_manifest_is_pending_until_archive_commit(tmp_path: Path) -> None:
    receipt = capture_owned_browser_evidence(
        _Tab(),
        site="linkedin_rps",
        task="humansearch",
        mode="profile",
        expected_target_id="target-exact",
        profile_url="https://www.linkedin.com/talent/profile/AAA",
        mutation_guard=lambda: None,
        auth_probe=_auth,
        root_dir=tmp_path,
        archive_store=_ManifestCheckingArchive(tmp_path),
        position_id="position-1",
        candidate_index=1,
    )

    assert receipt.status == "saved"
    assert isinstance(receipt.archive_row_id, int) and receipt.archive_row_id > 0
    manifest = json.loads(Path(receipt.manifest_path).read_text(encoding="utf-8"))
    assert manifest["status"] == "saved"
    assert manifest["archive_row_id"] == receipt.archive_row_id


def test_archive_failure_removes_screen_text_and_manifest(tmp_path: Path) -> None:
    class FailingArchive:
        def save(self, **_kwargs):
            raise RuntimeError("database unavailable")

    with pytest.raises(BrowserEvidenceError, match="persistence"):
        capture_owned_browser_evidence(
            _Tab(),
            site="linkedin_rps",
            task="humansearch",
            mode="profile",
            expected_target_id="target-exact",
            profile_url="https://www.linkedin.com/talent/profile/AAA",
            mutation_guard=lambda: None,
            auth_probe=_auth,
            root_dir=tmp_path,
            archive_store=FailingArchive(),
            position_id="position-1",
            candidate_index=1,
        )

    assert list(tmp_path.rglob("*.png")) == []
    assert list(tmp_path.rglob("*.txt")) == []
    assert list(tmp_path.rglob("*.json")) == []


def test_saved_receipt_is_rejected_after_visible_text_tampering(tmp_path: Path) -> None:
    receipt = capture_owned_browser_evidence(
        _Tab(),
        site="linkedin_rps",
        task="login",
        mode="evidence",
        expected_target_id="target-exact",
        mutation_guard=lambda: None,
        auth_probe=_auth,
        root_dir=tmp_path,
    )
    Path(receipt.text_path).write_text("tampered", encoding="utf-8")
    Path(receipt.text_path).chmod(0o600)

    assert complete_evidence_payload(receipt.public_dict()) is False


def test_receipt_cannot_substitute_arbitrary_private_local_files(tmp_path: Path) -> None:
    receipt = capture_owned_browser_evidence(
        _Tab(),
        site="linkedin_rps",
        task="login",
        mode="evidence",
        expected_target_id="target-exact",
        mutation_guard=lambda: None,
        auth_probe=_auth,
        root_dir=tmp_path,
    )
    payload = receipt.public_dict()
    replacement = Path(receipt.screenshot_path).with_name("unrelated.png")
    replacement.write_bytes(Path(receipt.screenshot_path).read_bytes())
    replacement.chmod(0o600)
    payload["screenshot_path"] = str(replacement)
    manifest = json.loads(Path(receipt.manifest_path).read_text(encoding="utf-8"))
    manifest["screenshot_path"] = str(replacement)
    Path(receipt.manifest_path).write_text(json.dumps(manifest), encoding="utf-8")
    Path(receipt.manifest_path).chmod(0o600)

    assert complete_evidence_payload(payload) is False


def test_receipt_rejects_non_utf8_visible_text_even_with_matching_hash(tmp_path: Path) -> None:
    import hashlib

    receipt = capture_owned_browser_evidence(
        _Tab(),
        site="linkedin_rps",
        task="login",
        mode="evidence",
        expected_target_id="target-exact",
        mutation_guard=lambda: None,
        auth_probe=_auth,
        root_dir=tmp_path,
    )
    payload = receipt.public_dict()
    invalid_text = b"\xff\xfe"
    Path(receipt.text_path).write_bytes(invalid_text)
    Path(receipt.text_path).chmod(0o600)
    payload["visible_text_sha256"] = hashlib.sha256(invalid_text).hexdigest()
    manifest = json.loads(Path(receipt.manifest_path).read_text(encoding="utf-8"))
    manifest["visible_text_sha256"] = payload["visible_text_sha256"]
    Path(receipt.manifest_path).write_text(json.dumps(manifest), encoding="utf-8")
    Path(receipt.manifest_path).chmod(0o600)

    assert complete_evidence_payload(payload) is False


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
            archive_store=_Archive(tmp_path),
            position_id="position-1",
            candidate_index=1,
        )
    assert tab.send_calls == ["Page.captureScreenshot"]
    assert list(tmp_path.rglob("*.png")) == []
    assert list(tmp_path.rglob("*.txt")) == []
    assert list(tmp_path.rglob("*.json")) == []


def test_query_bearing_candidate_identity_cannot_switch_between_profiles(tmp_path: Path) -> None:
    tab = _Tab(url="https://www.jobkorea.co.kr/Corp/Person/Detail?rNo=2")
    with pytest.raises(BrowserEvidenceError, match="profile identity"):
        capture_owned_browser_evidence(
            tab,
            site="jobkorea",
            task="ai-search",
            mode="profile",
            expected_target_id="target-exact",
            profile_url="https://www.jobkorea.co.kr/Corp/Person/Detail?rNo=3",
            mutation_guard=lambda: None,
            auth_probe=lambda current, _site: AuthObservation(
                True, False, current.url, ("profile_detail",)
            ),
            root_dir=tmp_path,
            archive_store=_Archive(tmp_path),
            position_id="position-1",
            candidate_index=1,
        )
    assert tab.send_calls == []


@pytest.mark.parametrize(
    ("site", "url"),
    [
        (
            "saramin",
            "https://www.saramin.co.kr/zf_user/memcom/talent-pool/search?resume_idx=77",
        ),
        (
            "jobkorea",
            "https://www.jobkorea.co.kr/Corp/Person/Find?rNo=77",
        ),
    ],
)
def test_search_listing_query_id_is_not_accepted_as_profile(
    tmp_path: Path, site: str, url: str
) -> None:
    tab = _Tab(url=url)
    with pytest.raises(BrowserEvidenceError, match="profile identity"):
        capture_owned_browser_evidence(
            tab,
            site=site,
            task="ai-search",
            mode="profile",
            expected_target_id="target-exact",
            profile_url=url,
            mutation_guard=lambda: None,
            auth_probe=lambda current, _site: AuthObservation(
                True, False, current.url, ("profile_detail",)
            ),
            root_dir=tmp_path,
            archive_store=_Archive(tmp_path),
            position_id="position-1",
            candidate_index=1,
        )
    assert tab.send_calls == []
    assert list(tmp_path.rglob("viewport.png")) == []


def test_same_profile_recapture_updates_archive_binding_and_validates(tmp_path: Path) -> None:
    archive = _Archive(tmp_path)
    first = capture_owned_browser_evidence(
        _Tab(),
        site="linkedin_rps",
        task="ai-search",
        mode="profile",
        expected_target_id="target-exact",
        profile_url="https://www.linkedin.com/talent/profile/AAA",
        mutation_guard=lambda: None,
        auth_probe=_auth,
        root_dir=tmp_path,
        archive_store=archive,
        position_id="position-1",
        candidate_index=1,
    )
    second = capture_owned_browser_evidence(
        _Tab(),
        site="linkedin_rps",
        task="humansearch",
        mode="profile",
        expected_target_id="target-exact",
        profile_url="https://www.linkedin.com/talent/profile/AAA",
        mutation_guard=lambda: None,
        auth_probe=_auth,
        root_dir=tmp_path,
        archive_store=archive,
        position_id="position-1",
        candidate_index=2,
    )

    assert first.archive_row_id == second.archive_row_id
    assert complete_evidence_payload(second.public_dict()) is True
    with sqlite3.connect(archive.path) as db:
        row = db.execute(
            "SELECT scenario,candidate_index,screenshot_path FROM profile_archive_receipts "
            "WHERE id=?",
            (second.archive_row_id,),
        ).fetchone()
    assert row == ("humansearch", 2, second.screenshot_path)


def test_manifest_failure_rolls_back_existing_archive_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    archive = _Archive(tmp_path)
    first = capture_owned_browser_evidence(
        _Tab(),
        site="linkedin_rps",
        task="ai-search",
        mode="profile",
        expected_target_id="target-exact",
        profile_url="https://www.linkedin.com/talent/profile/AAA",
        mutation_guard=lambda: None,
        auth_probe=_auth,
        root_dir=tmp_path,
        archive_store=archive,
        position_id="position-1",
        candidate_index=1,
    )
    monkeypatch.setattr(
        browser_evidence,
        "_write_manifest_atomic",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("manifest unavailable")),
    )

    with pytest.raises(BrowserEvidenceError, match="persistence"):
        capture_owned_browser_evidence(
            _Tab(),
            site="linkedin_rps",
            task="humansearch",
            mode="profile",
            expected_target_id="target-exact",
            profile_url="https://www.linkedin.com/talent/profile/AAA",
            mutation_guard=lambda: None,
            auth_probe=_auth,
            root_dir=tmp_path,
            archive_store=archive,
            position_id="position-1",
            candidate_index=2,
        )

    with sqlite3.connect(archive.path) as db:
        row = db.execute(
            "SELECT scenario,candidate_index,screenshot_path,screenshot_sha256 "
            "FROM profile_archive_receipts WHERE id=?",
            (first.archive_row_id,),
        ).fetchone()
    assert row == (
        "ai-search",
        1,
        first.screenshot_path,
        first.screenshot_sha256,
    )
    assert Path(first.screenshot_path).is_file()


def test_manifest_failure_rolls_back_new_archive_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    archive = _Archive(tmp_path)
    monkeypatch.setattr(
        browser_evidence,
        "_write_manifest_atomic",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("manifest unavailable")),
    )

    with pytest.raises(BrowserEvidenceError, match="persistence"):
        capture_owned_browser_evidence(
            _Tab(),
            site="linkedin_rps",
            task="humansearch",
            mode="profile",
            expected_target_id="target-exact",
            profile_url="https://www.linkedin.com/talent/profile/AAA",
            mutation_guard=lambda: None,
            auth_probe=_auth,
            root_dir=tmp_path,
            archive_store=archive,
            position_id="position-1",
            candidate_index=1,
        )

    with sqlite3.connect(archive.path) as db:
        count = db.execute("SELECT COUNT(*) FROM profile_archive_receipts").fetchone()[0]
    assert count == 0


def test_structurally_plausible_but_missing_evidence_files_are_rejected() -> None:
    assert complete_evidence_payload({
        "status": "saved",
        "screenshot_path": "/private/forged.png",
        "text_path": "/private/forged.txt",
        "manifest_path": "/private/forged.json",
        "screenshot_sha256": "a" * 64,
        "visible_text_sha256": "b" * 64,
    }) is False


def test_capture_episode_reuses_exact_target_lease_and_disconnects_only(tmp_path: Path) -> None:
    trace: list[str] = []
    idle_value = 69.0

    def owner_snapshot():
        nonlocal idle_value
        idle_value += 1.0
        return SimpleNamespace(
            detection_status="ok",
            owner_activity_detected=False,
            idle_seconds=idle_value,
            portal_site_active=True,
        )

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

    def capture(*args, **kwargs):
        kwargs["mutation_guard"]()
        trace.append("capture")
        return capture_owned_browser_evidence(*args, **kwargs)

    result = run_capture_evidence_episode(
        "linkedin_rps",
        task="url",
        mode="evidence",
        agent="Codex",
        target_id="target-exact",
        owner_snapshot=owner_snapshot,
        mutation_sleep=lambda _seconds: None,
        wait_sleep=lambda _seconds: None,
        _lease_factory=lambda _site: Lease(),
        _target_resolver=lambda *_args, **_kwargs: ref,
        _tab_attacher=lambda *_args, **_kwargs: tab,
        _auth_reader=_auth,
        _capture=capture,
        _root_dir=tmp_path,
    )

    assert result["status"] == "saved", result
    assert result["site"] == "linkedin_rps"
    assert "capture" in trace
    assert tab.disconnected == 1
    assert trace[-1] == "lease.release"


def test_capture_episode_rejects_saved_label_without_real_evidence_files() -> None:
    trace: list[str] = []
    idle_value = 69.0

    class Lease:
        def acquire(self):
            trace.append("lease.acquire")

        def assert_owned(self):
            trace.append("lease.assert_owned")

        def release(self):
            trace.append("lease.release")

    def owner_snapshot():
        nonlocal idle_value
        idle_value += 1.0
        return SimpleNamespace(
            detection_status="ok",
            owner_activity_detected=False,
            idle_seconds=idle_value,
            portal_site_active=True,
        )

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
    result = run_capture_evidence_episode(
        "linkedin_rps",
        task="url",
        mode="evidence",
        agent="Codex",
        target_id="target-exact",
        owner_snapshot=owner_snapshot,
        mutation_sleep=lambda _seconds: None,
        wait_sleep=lambda _seconds: None,
        _lease_factory=lambda _site: Lease(),
        _target_resolver=lambda *_args, **_kwargs: ref,
        _tab_attacher=lambda *_args, **_kwargs: tab,
        _auth_reader=_auth,
        _capture=lambda *_args, **_kwargs: {
            "status": "saved",
            "capture_status": "saved",
            "task": "url",
            "mode": "evidence",
        },
    )

    assert result["status"] == "failed"
    assert result["capture_status"] == "failed"
    assert tab.disconnected == 1
    assert trace[-1] == "lease.release"


@pytest.mark.parametrize(
    ("site", "url", "account_fields", "proof"),
    [
        (
            "saramin",
            "https://www.saramin.co.kr/zf_user/member/resume-view?resume_idx=1",
            {"hasLogout": True, "hasValueConnect": False},
            "profile_detail",
        ),
        (
            "jobkorea",
            "https://www.jobkorea.co.kr/corp/person/find/resume/view?rNo=2",
            {"hasLogout": True, "hasValueConnect": True},
            "profile_detail",
        ),
    ],
)
def test_portal_profile_detail_has_positive_auth_marker(
    site: str, url: str, account_fields: dict[str, bool], proof: str
) -> None:
    class Tab:
        def eval(self, _script: str):
            return {
                "url": url,
                "hasChallenge": False,
                "hasSessionConflict": False,
                "saraminSearch": False,
                "jobkoreaSearch": False,
                "linkedinSearch": False,
                "linkedinAccount": False,
                **account_fields,
            }

    observation = read_auth_observation(Tab(), site)  # type: ignore[arg-type]
    assert observation.authenticated is True
    assert proof in observation.proof_names


def test_exact_target_resolver_accepts_jobkorea_profile_detail() -> None:
    target = {
        "id": "job-detail",
        "type": "page",
        "url": "https://www.jobkorea.co.kr/corp/person/find/resume/view?rNo=2",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9224/devtools/page/job-detail",
    }
    ref = resolve_existing_target(
        "jobkorea",
        target_id="job-detail",
        managed_endpoint_resolver=lambda _site: "http://127.0.0.1:9224",
        list_pages=lambda _endpoint: [target],
    )
    assert ref.target_id == "job-detail"


def test_session_guard_cli_dispatches_capture_evidence(monkeypatch, capsys) -> None:
    calls: list[dict] = []

    def run(site: str, **kwargs):
        calls.append({"site": site, **kwargs})
        return {"status": "saved", "capture_status": "saved", "site": site}

    monkeypatch.setattr(session_guard, "run_capture_evidence_episode", run)
    exit_code = session_guard.main([
        "capture-evidence",
        "--site", "linkedin_rps",
        "--agent", "Codex",
        "--task", "url",
        "--mode", "evidence",
        "--target-id", "target-exact",
    ])
    assert exit_code == 0
    assert calls == [{
        "site": "linkedin_rps",
        "task": "url",
        "mode": "evidence",
        "agent": "Codex",
        "target_id": "target-exact",
        "profile_url": "",
        "position_id": "",
        "candidate_index": 0,
    }]
    assert json.loads(capsys.readouterr().out)["capture_status"] == "saved"


def test_capture_episode_rejects_empty_agent_before_browser_access() -> None:
    with pytest.raises(ValueError, match="agent"):
        run_capture_evidence_episode(
            "linkedin_rps",
            task="url",
            mode="evidence",
            agent="!!!",
            target_id="target-exact",
            _lease_factory=lambda _site: pytest.fail("browser lease must not be accessed"),
        )


@pytest.mark.parametrize(
    ("task", "mode"),
    [("ai-search", "evidence"), ("humansearch", "evidence"), ("url", "profile"), ("login", "profile")],
)
def test_capture_episode_rejects_wrong_task_mode_before_browser_access(
    task: str, mode: str
) -> None:
    with pytest.raises(ValueError, match="task/mode"):
        run_capture_evidence_episode(
            "linkedin_rps",
            task=task,
            mode=mode,  # type: ignore[arg-type]
            agent="Codex",
            target_id="target-exact",
            _lease_factory=lambda _site: pytest.fail("browser lease must not be accessed"),
        )


def test_portal_login_sot_declares_official_capture_entrypoint() -> None:
    spec = json.loads(
        Path("docs/sot/26-portal-login-spec.json").read_text(encoding="utf-8")
    )
    capture = spec["production_entrypoints"]["capture_evidence"]
    assert "session_guard capture-evidence" in capture
    assert spec["browser_evidence_capture"]["success_condition"] == (
        "private screenshot + visible text + manifest + SHA-256 receipt all saved"
    )
    assert spec["browser_evidence_capture"]["browser_mutations"] == []
