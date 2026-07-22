"""AC-N0 — 자연어 셸 라우팅 계약(SOT-32) + 가드 H-NL1~H-NL4 기계 검증.

goal: docs/prompts/discord-nl-shell-routing-goal-2026-07-22.md
정본 계약: docs/sot/32-nl-shell-routing.json (기계) + .md (사람)

검사하는 것:
  1) 계약 JSON 이 존재하고 필수 키·구조를 갖춘다 (문서만 있고 계약이 없는 위장 방지)
  2) 문서(.md)와 계약(.json)의 어휘가 일치한다 — 드리프트 0
  3) 가드가 harness-dispatch 를 통해 실제로 문을 닫는다:
     H-NL1 정본 모듈 밖 즉석 자연어 파서 자작 차단
     H-NL2 대상 미해소(URL 없음) 상태의 실행형 큐 적재 차단
     H-NL3 자연어 경로에서 포털 raw 조작·발송으로 새는 것 차단
  4) 정본 경로(정식 러너·정본 모듈 편집·해소된 URL 적재)는 반드시 통과한다
     — false positive 로 자기 작업을 막지 않는다(SOT-27 가드 계약)

주의: 훅은 fail-open 이다. 이 테스트는 2층이 '있을 때 실제로 닫히는지'만 봉인하며,
본체 방어는 해소층 코드 안의 정책(SOT-32 §4)이다.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
DISPATCH = ROOT / ".claude/hooks/harness-dispatch.py"
SOT_JSON = ROOT / "docs/sot/32-nl-shell-routing.json"
SOT_MD = ROOT / "docs/sot/32-nl-shell-routing.md"
GOAL_DOC = ROOT / "docs/prompts/discord-nl-shell-routing-goal-2026-07-22.md"
GUARD = ROOT / ".claude/hooks/guards/nl-shell-routing.py"

# 자연어 셸 작업 컨텍스트를 나타내는 env — 가드는 이 컨텍스트에서만 문을 건다.
NL_ENV = {"VH_NL_SHELL": "1"}


def _dispatch(payload: dict, *, nl: bool = True):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(ROOT))
    env.pop("VH_NL_SHELL", None)
    if nl:
        env.update(NL_ENV)
    p = subprocess.run(["python3", str(DISPATCH)], input=json.dumps(payload),
                       capture_output=True, text=True, env=env, cwd=str(ROOT))
    return p.returncode, p.stderr


def _tool(name: str, **kw) -> dict:
    return {"tool_name": name, "tool_input": kw}


class ContractShape(unittest.TestCase):
    """1) 계약 JSON 이 실재하고 구조를 갖췄는가."""

    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(SOT_JSON.read_text(encoding="utf-8"))

    def test_files_exist(self):
        for path in (SOT_JSON, SOT_MD, GOAL_DOC, GUARD):
            self.assertTrue(path.exists(), f"필수 산출물 없음: {path}")

    def test_required_top_level_keys(self):
        for key in ("grammar", "loci", "verbs", "routes",
                    "resolution_policy", "forbidden", "reuse"):
            self.assertIn(key, self.contract, f"계약 최상위 키 누락: {key}")

    def test_grammar_requires_three_elements(self):
        grammar = self.contract["grammar"]
        self.assertEqual(sorted(grammar["required_elements"]),
                         ["locus", "target", "verb"])
        # 3요소 미충족 시 추측하지 않고 거부 — CLAUDE.md 0.2
        self.assertEqual(grammar["on_incomplete"], "reject")

    def test_owner_examples_are_routable(self):
        """사장님이 드신 두 예시가 라우팅표에 실제로 앉는가."""
        routes = {(r["locus"], r["verb"]) for r in self.contract["routes"]}
        # "클릭업에서 번개장터 PM 찾아" (N2)
        self.assertIn(("clickup", "find"), routes)
        # "웹에서 공식 채용페이지에서 번개장터 PM 찾아" (N3)
        self.assertIn(("web", "find"), routes)

    def test_resolution_policy_forbids_guessing(self):
        policy = self.contract["resolution_policy"]
        # 0건이면 실행 금지 + 다른 장소로 임의 확장 금지
        self.assertFalse(policy["zero_hits"]["may_execute"])
        self.assertFalse(policy["zero_hits"]["may_widen_locus"])
        # N건이면 고르기 전까지 실행 금지
        self.assertFalse(policy["many_hits"]["may_execute"])
        # 1건이면 진행 허용
        self.assertTrue(policy["one_hit"]["may_execute"])

    def test_forbidden_covers_five_rules(self):
        ids = {f["id"] for f in self.contract["forbidden"]}
        self.assertEqual(ids, {"F-NL1", "F-NL2", "F-NL3", "F-NL4", "F-NL5"})

    def test_fail_closed_parser_is_protected(self):
        """기존 fail-closed 파서를 고치지 말라는 재사용 원칙이 계약에 있는가."""
        must_not = self.contract["reuse"]["must_not_modify"]
        self.assertIn("tools/multi_position_sourcing/fleet_args.py", must_not)

    def test_dangerous_verbs_absent_from_vocabulary(self):
        """발송·삭제·계산서는 자연어 어휘에 없어야 한다(F-NL5)."""
        blob = json.dumps(self.contract["verbs"], ensure_ascii=False)
        for word in ("발송", "보내", "삭제", "계산서"):
            self.assertNotIn(word, blob, f"위험 동사가 자연어 어휘에 있음: {word}")


class DocContractParity(unittest.TestCase):
    """2) 문서와 계약의 어휘가 어긋나지 않는가 (H-NL4 의 정적 짝)."""

    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(SOT_JSON.read_text(encoding="utf-8"))
        cls.md = SOT_MD.read_text(encoding="utf-8")

    def test_every_locus_documented(self):
        for locus in self.contract["loci"]:
            self.assertIn(locus, self.md, f"문서에 없는 장소: {locus}")

    def test_every_verb_documented(self):
        for verb in self.contract["verbs"]:
            self.assertIn(verb, self.md, f"문서에 없는 동사: {verb}")

    def test_md_points_to_json_as_source_of_truth(self):
        self.assertIn("32-nl-shell-routing.json", self.md)


class GuardBlocks(unittest.TestCase):
    """3) 막아야 하는 것이 실제로 막히는가."""

    def test_hnl1_blocks_adhoc_parser_script(self):
        """정본 모듈 밖에서 자연어 파서를 즉석 자작하면 차단 (F-NL4)."""
        rc, err = _dispatch(_tool(
            "Write",
            file_path=str(ROOT / "scripts/quick_nl_parse.py"),
            content="def parse_natural_language(msg):\n    if '클릭업에서' in msg:\n        return 'clickup'\n",
        ))
        self.assertEqual(rc, 2, f"즉석 자연어 파서 자작이 통과됨: {err}")
        self.assertIn("nl-shell-routing", err)

    def test_hnl2_blocks_enqueue_without_resolved_url(self):
        """대상 미해소(URL 없음) 상태로 실행형 큐에 적재하면 차단 (F-NL3)."""
        rc, err = _dispatch(_tool(
            "Bash",
            command="python3 -c \"from tools.multi_position_sourcing.job_queue import enqueue_job; "
                    "enqueue_job(skill='aisearch', params={'position_name': '번개장터 PM'})\"",
        ))
        self.assertEqual(rc, 2, f"미해소 큐 적재가 통과됨: {err}")

    def test_hnl3_blocks_raw_portal_automation(self):
        """자연어 경로에서 채용사이트 raw CDP 조작으로 새면 차단 (F-NL2)."""
        rc, err = _dispatch(_tool(
            "Bash",
            command="python3 -c \"import websockets; ws='ws://127.0.0.1:9222/devtools/page/1'; "
                    "print('Page.navigate', 'https://www.saramin.co.kr/zf_user/talent-search')\"",
        ))
        self.assertEqual(rc, 2, f"raw 포털 조작이 통과됨: {err}")

    def test_hnl3_blocks_send_from_nl_path(self):
        """자연어 경로에서 제안 발송에 도달하면 차단 (F-NL1)."""
        rc, err = _dispatch(_tool(
            "Bash",
            command="python3 tools/position-batch/send_inmail.py --send --candidate 123",
        ))
        self.assertEqual(rc, 2, f"자연어 경로 발송이 통과됨: {err}")


class GuardAllows(unittest.TestCase):
    """4) 정본 경로가 막히지 않는가 (false positive 금지)."""

    def test_allows_editing_canonical_module(self):
        """정본 모듈 자체를 만드는 것은 통과해야 한다."""
        rc, err = _dispatch(_tool(
            "Write",
            file_path=str(ROOT / "tools/multi_position_sourcing/nl_shell.py"),
            content="def parse(message):\n    return None\n",
        ))
        self.assertEqual(rc, 0, f"정본 모듈 편집이 차단됨: {err}")

    def test_allows_enqueue_with_resolved_url(self):
        """해소된 URL 이 붙은 적재는 통과해야 한다."""
        rc, err = _dispatch(_tool(
            "Bash",
            command="python3 -m tools.multi_position_sourcing.direct_receiver "
                    "'/fleet-run aisearch https://app.clickup.com/t/86exwz89j channels:saramin,jobkorea'",
        ))
        self.assertEqual(rc, 0, f"해소된 URL 적재가 차단됨: {err}")

    def test_allows_official_runner(self):
        """정식 러너 호출은 통과해야 한다."""
        rc, err = _dispatch(_tool("Bash", command="npm run position-batch:research"))
        self.assertEqual(rc, 0, f"정식 러너가 차단됨: {err}")

    def test_allows_reading_docs(self):
        rc, err = _dispatch(_tool("Read", file_path=str(SOT_MD)))
        self.assertEqual(rc, 0, f"문서 읽기가 차단됨: {err}")

    def test_inactive_outside_nl_context(self):
        """자연어 셸 컨텍스트가 아니면 이 가드는 아무것도 막지 않는다."""
        rc, err = _dispatch(_tool(
            "Write",
            file_path=str(ROOT / "scripts/quick_nl_parse.py"),
            content="def parse_natural_language(msg):\n    return None\n",
        ), nl=False)
        self.assertEqual(rc, 0, f"컨텍스트 밖에서 차단됨: {err}")


if __name__ == "__main__":
    unittest.main()
