from __future__ import annotations

import importlib.util
from pathlib import Path

from tools.multi_position_sourcing.fleet_worker import build_job_prompt


REPO = Path(__file__).resolve().parents[1]
GUARD = REPO / ".claude" / "hooks" / "guards" / "login.py"
PROMPT = REPO / "docs" / "prompts" / "login-search-execution-contract.md"
SKILL = REPO / "skills" / "login" / "SKILL.md"


def _decode(value: str) -> str:
    return bytes.fromhex(value).decode("utf-8")


def _load_guard():
    spec = importlib.util.spec_from_file_location("login_guard", GUARD)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bash(command: str) -> dict[str, object]:
    return {"command": command}


def test_login_guard_blocks_unsafe_browser_session_paths() -> None:
    guard = _load_guard()
    chrome = _decode("476f6f676c65204368726f6d65")
    linkedin = _decode("6c696e6b6564696e2e636f6d2f74616c656e74")
    saramin = _decode("736172616d696e2e636f2e6b72")
    jobkorea = _decode("6a6f626b6f7265612e636f2e6b72")
    blocked = (
        f'{_decode("706b696c6c")} -f "{chrome}"',
        f'{_decode("6b696c6c")} -9 $(pgrep -f "{chrome}")',
        f"./scripts/portal_browsers.sh {_decode('73746f70')} linkedin",
        f"./scripts/portal_browsers.sh {_decode('72657374617274')} saramin",
        f"./scripts/portal_browsers.sh {_decode('7374617274')} jobkorea",
        f"node unsafe.mjs # {_decode('636f6e6e6563744f766572434450')} https://{linkedin}",
        f"python3 unsafe.py # context.new_page() https://{saramin}",
        f"node unsafe.mjs # PUT {_decode('2f6a736f6e2f6e6577')} https://{jobkorea}",
        "python3 -m tools.multi_position_sourcing.portal_login --site linkedin_rps",
        "python3 -m tools.multi_position_sourcing.portal_autologin --site saramin",
        f"node unsafe.mjs # context.close() after https://{linkedin}",
    )
    for command in blocked:
        reason = guard.check("Bash", _bash(command))
        assert reason is not None, command
        assert "session_guard" in reason


def test_login_guard_allows_exact_runner_and_read_only_inspection() -> None:
    guard = _load_guard()
    allowed = (
        (
            "PYTHONPATH=. python3 -m tools.multi_position_sourcing.session_guard "
            "human-auth --site linkedin_rps --agent Codex --target-id abc"
        ),
        (
            "PYTHONPATH=. python3 -m tools.multi_position_sourcing.session_guard "
            "keepalive --site saramin --agent Claude "
            "--safe-target-json /tmp/audited.json"
        ),
        "./scripts/portal_browsers.sh status",
        "./scripts/portal_browsers.sh cdp jobkorea",
        "rg -n 'browser lifecycle patterns' docs tools",
        "git status --short",
    )
    for command in allowed:
        assert guard.check("Bash", _bash(command)) is None, command


def test_login_guard_handles_codex_command_arrays() -> None:
    guard = _load_guard()
    reason = guard.check(
        "local_shell",
        {
            "command": [
                _decode("706b696c6c"),
                "-f",
                _decode("476f6f676c65204368726f6d65"),
            ]
        },
    )
    assert reason is not None
    assert "session_guard" in reason


def test_execution_prompt_makes_login_a_code_enforced_search_barrier() -> None:
    text = PROMPT.read_text(encoding="utf-8")
    required = (
        "LOGIN_BARRIER",
        "aisearch",
        "humansearch",
        "url",
        "session_guard human-auth",
        "AUTHENTICATED",
        "HUMAN_ACTIVE",
        "HUMAN_AUTH",
        "AUTH_CONFLICT",
        "managed_browser_missing",
        "exact target",
        "새 창 0개",
        "새 탭 0개",
        "고정 좌표",
        "비밀번호",
        "브라우저 보존: 창/탭/프로필 종료 0건, CDP 연결만 해제",
    )
    for marker in required:
        assert marker in text

    assert text.index("LOGIN_BARRIER") < text.index("SEARCH_EXECUTION")
    assert "탐지 우회" in text
    assert "반복 제출" in text


def test_login_skill_points_to_the_prompt_and_hook() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "docs/prompts/login-search-execution-contract.md" in text
    assert ".claude/hooks/guards/login.py" in text


def test_fleet_search_prompts_require_login_barrier_before_execution() -> None:
    for skill in ("aisearch", "humansearch", "url"):
        prompt = build_job_prompt(
            {
                "id": 205,
                "skill": skill,
                "machine": "macmini",
                "position_url": "https://app.clickup.com/t/example",
                "requested_by": "814353841088757800:owner",
                "role": "owner",
                "params": {},
            }
        )
        assert "docs/prompts/login-search-execution-contract.md" in prompt
        assert "LOGIN_BARRIER=PASS" in prompt
        assert prompt.index("LOGIN_BARRIER=PASS") < prompt.index(
            f"{skill} 스킬의 검색·URL 작업"
        )
