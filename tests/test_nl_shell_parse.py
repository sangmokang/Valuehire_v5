"""AC-N1 — 자연어 셸 문법 해석기 nl_shell.parse().

goal: docs/prompts/discord-nl-shell-routing-goal-2026-07-22.md
계약: docs/sot/32-nl-shell-routing.json (어휘·문법·라우팅표의 단일 출처)

인수 기준:
  `클릭업에서 번개장터 PM 찾아` → (clickup, "번개장터 PM", find)
  3요소(장소·대상·동사) 미충족 입력은 None — 추측하지 않는다(CLAUDE.md §0.2).
  추가: 자연어 처리 경로가 하위 프로세스 env 에 VH_NL_SHELL=1 을 주입한다
        (fleet_worker.py 의 VH_BUSY_TASK 주입과 동일 패턴 — 가드 활성 스위치).

정직 표기: parse 는 해석만 한다. 대상을 실제 URL 로 바꾸는 해소(resolve)와
큐 적재는 AC-N2·AC-N4 소관이며 여기서 검증하지 않는다.
"""

from __future__ import annotations

import json
import pathlib
import unittest

from tools.multi_position_sourcing import nl_shell

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTRACT = json.loads(
    (ROOT / "docs/sot/32-nl-shell-routing.json").read_text(encoding="utf-8"))


class OwnerExamples(unittest.TestCase):
    """사장님이 직접 드신 두 문장이 반드시 해석돼야 한다."""

    def test_clickup_find(self):
        cmd = nl_shell.parse("클릭업에서 번개장터 PM 찾아")
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd.locus, "clickup")
        self.assertEqual(cmd.verb, "find")
        self.assertEqual(cmd.target, "번개장터 PM")

    def test_web_official_careers_find(self):
        cmd = nl_shell.parse("웹에서 공식 채용페이지에서 번개장터 PM 찾아")
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd.locus, "web")
        self.assertEqual(cmd.verb, "find")
        # '공식 채용페이지' 는 장소 수식어이므로 대상에서 걷어낸다
        self.assertEqual(cmd.target, "번개장터 PM")

    def test_clickup_search_routes_to_aisearch(self):
        cmd = nl_shell.parse("클릭업에서 번개장터 PM 서치해")
        self.assertEqual((cmd.locus, cmd.verb), ("clickup", "search"))
        self.assertEqual(cmd.route["queue_skill"], "aisearch")


class LocusWithoutParticle(unittest.TestCase):
    """V1 적대검증(2026-07-22)에서 발견 — 계약에 있는 queue 경로가 도달 불가였다.

    조사('에서')를 강제하면 `큐에서 보여줘` 같은 어색한 한국어만 통과한다.
    실제로 쓰는 말은 `작업목록 보여줘` 이므로, **문장 맨 앞** 에 한해 조사 없이도
    장소로 인정한다. 문장 중간의 같은 낱말은 대상 이름의 일부일 수 있으므로
    계속 장소로 보지 않는다(오탐 방지).
    """

    def test_queue_route_is_reachable(self):
        for raw in ("큐 보여줘", "작업목록 보여줘", "jobs 보여줘"):
            cmd = nl_shell.parse(raw)
            self.assertIsNotNone(cmd, f"queue 경로 도달 실패: {raw!r}")
            self.assertEqual(cmd.locus, "queue")
            self.assertEqual(cmd.verb, "find")

    def test_midsentence_word_is_not_a_locus(self):
        """'번개장터 잡 찾아' 의 '잡'은 장소가 아니라 대상의 일부다."""
        self.assertIsNone(nl_shell.parse("번개장터 잡 찾아"))

    def test_particle_form_still_works(self):
        cmd = nl_shell.parse("클릭업에서 번개장터 PM 찾아")
        self.assertEqual(cmd.locus, "clickup")


class GrammarRejects(unittest.TestCase):
    """3요소가 안 잡히면 추측하지 않고 거부한다."""

    def test_verb_missing(self):
        self.assertIsNone(nl_shell.parse("클릭업에서 번개장터 PM"))

    def test_target_missing(self):
        self.assertIsNone(nl_shell.parse("클릭업에서 찾아"))

    def test_empty_and_noise(self):
        for raw in ("", "   ", "ㅇㅇ", "고마워요"):
            self.assertIsNone(nl_shell.parse(raw), f"거부 실패: {raw!r}")

    def test_unknown_locus_is_not_guessed(self):
        """계약에 없는 장소는 임의로 매핑하지 않는다."""
        self.assertIsNone(nl_shell.parse("노션에서 번개장터 PM 찾아"))

    def test_no_route_for_locus_verb_pair(self):
        """어휘는 맞지만 라우팅표에 없는 조합은 거부한다(web × search 는 미정의)."""
        self.assertIsNone(nl_shell.parse("웹에서 번개장터 PM 서치해"))


class DangerousVerbsBlocked(unittest.TestCase):
    """F-NL5 — 발송·삭제·계산서는 자연어로 발동할 수 없다."""

    def test_send_delete_invoice(self):
        for raw in (
            "클릭업에서 번개장터 PM 발송해",
            "클릭업에서 번개장터 PM 삭제해",
            "클릭업에서 번개장터 PM 계산서 발행해",
        ):
            self.assertIsNone(nl_shell.parse(raw), f"위험 동사가 통과됨: {raw!r}")

    def test_dangerous_word_blocks_even_with_valid_verb(self):
        """뮤턴트 생존으로 발견(V1 2026-07-22) — 위 케이스들은 '발송해'가 동사 어휘에
        없어서 걸러졌을 뿐, F-NL5 차단이 실제로 도는지는 증명하지 못했다(허수 테스트).

        문장 **끝은 정상 동사**인데 안에 위험 낱말이 섞인 형태라야 차단을 증명한다.
        설계 판단: 이런 문장은 통째로 거부한다 — 대상 이름에 '발송'이 들어간 정상
        요청을 못 받는 손해보다, 자연어가 발송 경로로 새는 위험이 크다(fail-safe).
        """
        for raw in (
            "클릭업에서 번개장터 PM 발송 목록 찾아",
            "클릭업에서 삭제 예정 포지션 찾아",
            "클릭업에서 계산서 담당자 찾아",
        ):
            self.assertIsNone(nl_shell.parse(raw), f"위험 낱말이 통과됨: {raw!r}")


class ContractDriven(unittest.TestCase):
    """어휘를 코드에 하드코딩하지 않고 계약에서 읽는가 (H-NL4 드리프트 0)."""

    def test_vocabulary_comes_from_contract(self):
        self.assertEqual(set(nl_shell.LOCI), set(CONTRACT["loci"]))
        self.assertEqual(set(nl_shell.VERBS), set(CONTRACT["verbs"]))

    def test_every_locus_alias_parses(self):
        """계약에 적힌 별칭이 전부 실제로 해석돼야 한다 — 문서만 늘리는 위장 방지."""
        for locus, aliases in CONTRACT["loci"].items():
            if not any(r["locus"] == locus and r["verb"] == "find"
                       for r in CONTRACT["routes"]):
                continue
            for alias in aliases:
                cmd = nl_shell.parse(f"{alias}에서 번개장터 PM 찾아")
                self.assertIsNotNone(cmd, f"별칭 해석 실패: {locus}/{alias}")
                self.assertEqual(cmd.locus, locus, f"별칭 오매핑: {alias}")

    def test_every_verb_alias_parses(self):
        for verb, spec in CONTRACT["verbs"].items():
            for alias in spec["aliases"]:
                cmd = nl_shell.parse(f"클릭업에서 번개장터 PM {alias}")
                if cmd is None:
                    # 라우팅표에 (clickup, verb) 조합이 없으면 거부가 정상
                    self.assertFalse(
                        any(r["locus"] == "clickup" and r["verb"] == verb
                            for r in CONTRACT["routes"]),
                        f"동사 별칭 해석 실패: {verb}/{alias}")
                    continue
                self.assertEqual(cmd.verb, verb, f"동사 오매핑: {alias}")

    def test_route_carries_risk_and_confirmation(self):
        """쓰기형(register)은 확인 필요 플래그를 달고 나온다."""
        cmd = nl_shell.parse("클릭업에서 번개장터 PM 찾아")
        self.assertEqual(cmd.risk, "read")
        self.assertFalse(cmd.requires_confirmation)


class GuardActivationWiring(unittest.TestCase):
    """가드(guards/nl-shell-routing.py)를 실제로 켜는 스위치가 있는가.

    AC-N0 V1 적대검증에서 '가드는 VH_NL_SHELL 을 아무도 안 켜서 잠들어 있다'가
    확인됐다(SOT-32 §7.1). 이 배선이 그 구멍을 닫는다.
    """

    def test_badge_env_sets_switch(self):
        env = nl_shell.badge_env()
        self.assertEqual(env["VH_NL_SHELL"], "1")

    def test_badge_env_merges_without_mutating_base(self):
        base = {"PATH": "/usr/bin"}
        env = nl_shell.badge_env(base)
        self.assertEqual(env["PATH"], "/usr/bin")
        self.assertEqual(env["VH_NL_SHELL"], "1")
        self.assertNotIn("VH_NL_SHELL", base)  # 원본 오염 금지


if __name__ == "__main__":
    unittest.main()
