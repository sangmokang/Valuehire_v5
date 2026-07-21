"""AC-3 — 2층 훅(H1~H4) 기계 검증 (goal: discord-single-bot-console §9).

harness-dispatch.py(PreToolUse)와 stop-evidence-gate.py(Stop)를 실제 서브프로세스로
호출해, fleet 잡 컨텍스트(env VH_BUSY_TASK)에서:
- H1 guards/discord-bot-send.py       : 발송성 도구·명령 차단 (G3 2층)
- H2 guards/discord-bot-login-gate.py : 로그인 영수증 없이 검색 스킬 차단 (G4 2층)
- H3 guards/discord-bot-skill-whitelist.py : 허용 밖 스킬 차단 (G2 2층)
- H4 stop-evidence-gate.py            : 증거 없는 완료 보고 1턴 저지
각각 "막혀야 하는 요청이 막히고, 정상 요청은 통과"를 검사한다.

주의: 훅은 fail-open(디스패처가 가드 로드 실패 시 통과) — 1층 코드 게이트가 본체이고
이 테스트는 2층이 '있을 때 실제로 문이 닫히는지'를 봉인한다.
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
DISPATCH = ROOT / ".claude/hooks/harness-dispatch.py"
STOP_GATE = ROOT / ".claude/hooks/stop-evidence-gate.py"
FLEET_ENV = {"VH_BUSY_TASK": "fleet #7 (humansearch)", "VH_BUSY_AGENT": "claude"}


def _dispatch(payload: dict, *, fleet: bool = True, project_dir: pathlib.Path | None = None):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project_dir or ROOT))
    env.pop("VH_BUSY_TASK", None)
    if fleet:
        env.update(FLEET_ENV)
    p = subprocess.run(["python3", str(DISPATCH)], input=json.dumps(payload),
                       capture_output=True, text=True, env=env, cwd=str(ROOT))
    return p.returncode, p.stderr


def _tool(name: str, **kw) -> dict:
    return {"tool_name": name, "tool_input": kw}


def _write_receipt(root: pathlib.Path, *, ready=True, age_seconds=60) -> None:
    gen = (datetime.datetime.now(datetime.timezone.utc)
           - datetime.timedelta(seconds=age_seconds)).isoformat()
    payload = {
        "kind": "portal_session_preflight", "generated_at": gen, "ready": ready,
        "portal_sessions": [{"channel": c, "ready": ready}
                            for c in ("saramin", "jobkorea", "linkedin_rps")],
    }
    (root / "artifacts").mkdir(parents=True, exist_ok=True)
    (root / "artifacts/portal_session_status_latest.json").write_text(
        json.dumps(payload), encoding="utf-8")


class SkillWhitelistHookTests(unittest.TestCase):
    def test_blocks_non_whitelisted_skill_in_fleet_job(self) -> None:
        code, err = _dispatch(_tool("Skill", skill="jdbuilder"))
        self.assertEqual(code, 2)
        self.assertIn("discord-bot-skill-whitelist", err)

    def test_allows_whitelisted_and_outside_fleet_context(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            _write_receipt(tmp)
            code, _ = _dispatch(_tool("Skill", skill="humansearch"), project_dir=tmp)
            self.assertEqual(code, 0)
        code, _ = _dispatch(_tool("Skill", skill="jdbuilder"), fleet=False)
        self.assertEqual(code, 0)


class LoginGateHookTests(unittest.TestCase):
    def test_blocks_search_skill_without_receipt(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            code, err = _dispatch(_tool("Skill", skill="humansearch"),
                                  project_dir=pathlib.Path(td))
            self.assertEqual(code, 2)
            self.assertIn("discord-bot-login-gate", err)

    def test_blocks_search_skill_with_stale_receipt(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            _write_receipt(tmp, age_seconds=86400 + 120)
            code, err = _dispatch(_tool("Skill", skill="aisearch"), project_dir=tmp)
            self.assertEqual(code, 2)
            self.assertIn("discord-bot-login-gate", err)

    def test_passes_with_fresh_ready_receipt(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            _write_receipt(tmp)
            code, _ = _dispatch(_tool("Skill", skill="aisearch"), project_dir=tmp)
            self.assertEqual(code, 0)

    def test_non_search_skill_not_gated(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            code, _ = _dispatch(_tool("Skill", skill="login"),
                                project_dir=pathlib.Path(td))
            self.assertEqual(code, 0)


class SendHookTests(unittest.TestCase):
    def test_blocks_sendish_bash_in_fleet_job(self) -> None:
        for cmd in ("python3 tools/x.py --send", "echo hi | sendmail a@b.c",
                    "python3 -c 'import smtplib'"):
            code, err = _dispatch(_tool("Bash", command=cmd))
            self.assertEqual(code, 2, cmd)
            self.assertIn("discord-bot-send", err)

    def test_blocks_sendish_tool_names(self) -> None:
        code, err = _dispatch(_tool("mcp__future_gmail__send_message", to="x"))
        self.assertEqual(code, 2)
        self.assertIn("discord-bot-send", err)

    def test_allows_normal_bash_and_outside_context(self) -> None:
        code, _ = _dispatch(_tool("Bash", command="git status"))
        self.assertEqual(code, 0)
        code, _ = _dispatch(_tool("Bash", command="python3 tools/x.py --send"), fleet=False)
        self.assertEqual(code, 0)

    def test_draft_creation_not_blocked(self) -> None:
        code, _ = _dispatch(_tool("mcp__claude_ai_Gmail__create_draft", to="x"))
        self.assertEqual(code, 0)


class StopEvidenceFleetTests(unittest.TestCase):
    def _stop(self, last_text: str, *, fleet: bool = True) -> int:
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": last_text}]},
            }) + "\n")
            transcript = f.name
        try:
            env = dict(os.environ)
            env.pop("VH_BUSY_TASK", None)
            # strict 마커 분기와 격리 — git 밖 임시 cwd + CLAUDE_PROJECT_DIR 제거로
            # find_marker 가 None 이 되게 해 H4 분기만 검사한다.
            env.pop("CLAUDE_PROJECT_DIR", None)
            if fleet:
                env.update(FLEET_ENV)
            import tempfile
            with tempfile.TemporaryDirectory() as workdir:
                p = subprocess.run(
                    ["python3", str(STOP_GATE)],
                    input=json.dumps({"transcript_path": transcript, "cwd": workdir}),
                    capture_output=True, text=True, env=env, cwd=workdir)
            return p.returncode
        finally:
            os.unlink(transcript)

    def test_done_claim_without_evidence_blocked(self) -> None:
        self.assertEqual(self._stop("서치 완료했습니다."), 99)

    def test_done_claim_with_evidence_passes(self) -> None:
        self.assertEqual(self._stop("서치 완료 — 후보 12건 저장, 잡 #7 done."), 0)

    def test_outside_fleet_context_not_gated(self) -> None:
        self.assertEqual(self._stop("서치 완료했습니다.", fleet=False), 0)

    def test_paused_report_passes(self) -> None:
        self.assertEqual(self._stop("캡차로 중단 — paused_for_human 처리했습니다."), 0)


if __name__ == "__main__":
    unittest.main()
