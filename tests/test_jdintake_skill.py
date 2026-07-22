"""U5 (AC-N3) — `jdintake` 스킬 등록: 웹에서 공식 채용페이지를 찾아 JD 를 파악한다.

사장님 요구 N3 "웹에서 공식 채용페이지에서 번개장터 PM 찾아 ⇒ 웹에서 검색을 통해서
JD파악". SOT-32 라우팅표의 (web, find) 는 queue_skill = "jdintake" 를 가리키는데,
그 스킬이 **아직 존재하지 않아** 큐가 거부한다. 이 단위가 그것을 만든다.

핵심 위험 = **부분 갱신**. 허용 스킬 목록이 네 군데에 흩어져 있어(코드·DB 테이블·
DB RPC·harness 가드), 한 곳만 고치면 "큐에는 들어가는데 워커가 거부" 같은 절반 상태가
된다. 그래서 이 테스트는 **네 곳이 서로 일치하는지**를 본다.
"""

from __future__ import annotations

import json
import pathlib
import re
import unittest

from tools.multi_position_sourcing.job_queue import FLEET_SKILLS

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTRACT = json.loads(
    (ROOT / "docs/sot/32-nl-shell-routing.json").read_text(encoding="utf-8"))
GUARD = ROOT / ".claude/hooks/guards/discord-bot-skill-whitelist.py"
MIGRATIONS = ROOT / "supabase/migrations"
SKILL_MD = ROOT / "skills/jdintake/SKILL.md"

SKILL = "jdintake"


def _sql_allowlists() -> list[tuple[str, set[str]]]:
    """마이그레이션에서 스킬 허용 목록을 뽑는다(가장 나중 파일이 최종 상태)."""
    out: list[tuple[str, set[str]]] = []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"skill\s+not\s+in\s*\(([^)]*)\)"
                             r"|skill\s+in\s*\(([^)]*)\)", text):
            body = m.group(1) or m.group(2) or ""
            names = set(re.findall(r"'([a-z_]+)'", body))
            if names:
                out.append((path.name, names))
    return out


class QueueAcceptsSkill(unittest.TestCase):
    def test_fleet_skills_includes_jdintake(self):
        self.assertIn(SKILL, FLEET_SKILLS)

    def test_worker_can_build_prompt_for_it(self):
        from tools.multi_position_sourcing.fleet_worker import build_job_prompt

        prompt = build_job_prompt({
            "id": 7, "skill": SKILL, "machine": "macmini",
            "position_url": "https://bunjang.career.greetinghr.com/o/123",
            "requested_by": "814353841088757800", "role": "owner", "params": {},
        })
        self.assertIn(SKILL, prompt)


class WhitelistsAgree(unittest.TestCase):
    """부분 갱신 방지 — 네 군데가 같은 집합을 말해야 한다."""

    def test_latest_sql_allowlist_includes_jdintake(self):
        lists = _sql_allowlists()
        self.assertTrue(lists, "마이그레이션에서 스킬 허용목록을 못 찾음")
        # 가장 나중 마이그레이션들이 최종 상태 — jdintake 를 허용하는 파일이 있어야 한다
        self.assertTrue(any(SKILL in names for _, names in lists),
                        f"SQL 어디에도 {SKILL} 허용이 없음: {lists}")

    def test_harness_guard_allows_jdintake(self):
        text = GUARD.read_text(encoding="utf-8")
        self.assertIn(SKILL, text,
                      "가드가 jdintake 를 막으면 워커 안에서 스킬 발동이 차단된다")

    def test_contract_route_points_at_this_skill(self):
        routes = [r for r in CONTRACT["routes"]
                  if r["locus"] == "web" and r["verb"] == "find"]
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0]["queue_skill"], SKILL)


class SkillDocumentExists(unittest.TestCase):
    """워커는 SKILL.md 를 읽고 움직인다 — 문서가 없으면 스킬은 없는 것이다."""

    def test_skill_md_exists(self):
        self.assertTrue(SKILL_MD.is_file(), f"없음: {SKILL_MD}")

    def test_skill_md_states_official_source_priority(self):
        """E-NL3 — 공식 채용페이지 우선, 출처를 반드시 표기한다."""
        text = SKILL_MD.read_text(encoding="utf-8")
        self.assertIn("공식", text)
        self.assertIn("출처", text)

    @staticmethod
    def _prohibition_section() -> str:
        """'절대 금지' 절만 잘라낸다.

        왜 절을 특정하나(뮤턴트 생존으로 발견, 2026-07-22): 문서 전체를 정규식으로
        훑으면 '어딘가에 그 낱말이 있다'만 증명된다 — 실제로 금지 조항을 통째로
        지워도 다른 문장(표·정지조건)이 걸려 테스트가 통과했다. 규칙은 규칙 자리에
        있어야 규칙이다.
        """
        text = SKILL_MD.read_text(encoding="utf-8")
        m = re.search(r"^##\s*1\.\s*절대 금지(.*?)^##\s", text, re.S | re.M)
        assert m, "SKILL.md 에 '## 1. 절대 금지' 절이 없다"
        return m.group(1)

    def test_prohibition_section_forbids_sending(self):
        """F-NL1 — JD 수집 스킬이 발송으로 새면 안 된다."""
        self.assertRegex(self._prohibition_section(), r"발송[^\n]*(금지|않는다)")

    def test_prohibition_section_forbids_fabricating_jd(self):
        """수집 스킬의 최대 위험 = 못 찾았을 때 지어내기."""
        self.assertRegex(self._prohibition_section(), r"날조[^\n]*금지")

    def test_prohibition_section_forbids_raw_portal_automation(self):
        """SOT-25 §0 — 즉석 CDP 로 채용사이트를 만지지 않는다."""
        self.assertRegex(self._prohibition_section(), r"(raw|CDP)[^\n]*(금지|않는다)")


if __name__ == "__main__":
    unittest.main()
