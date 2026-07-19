"""
guards/_template.py — 새 스킬 가드 템플릿.

새 스킬에 하네스 강제를 걸려면:
  1) 이 파일을 복사해 `guards/<skill-name>.py` 로 만든다(파일명 밑줄 시작 금지 — 밑줄은 로드 제외).
  2) NAME 을 스킬명으로 바꾸고 check() 안에 차단 규칙을 적는다.
  3) 끝. harness-dispatch.py 가 자동 발견해 모든 툴 호출에 적용한다(디스패처 수정 불필요).

계약: check(tool: str, tool_input: dict) -> str | None
  - 차단할 상황이면 '사유 문자열' 반환(모델에게 그대로 보여줌 → 정식 경로 안내를 담아라).
  - 허용이면 None 반환.
  - 정본(정식 러너/스킬) 경로는 반드시 통과시킨다(false positive 로 자기 스킬을 막지 말 것).
  - 순수 함수로 유지(부작용·외부 IO 금지). 예외를 던지면 이 가드만 skip(fail-open) 된다.

규약 전문: .claude/hooks/README.md, docs/sot/27-harness-skill-guards.md
"""
import re  # noqa: F401 (실제 가드에서 사용)

NAME = "example-skill"


def check(tool, tool_input):
    # 예시(주석): 이 스킬 전용 위험 동작을 정식 경로 밖에서 하려 하면 차단.
    #
    # if tool == "Bash":
    #     cmd = tool_input.get("command", "") or ""
    #     if re.search(r"<위험 신호>", cmd) and not re.search(r"<정식 러너 경로>", cmd):
    #         return "⛔ 차단(example-skill): 이 작업은 /<skill> 정식 경로로만 실행하세요."
    return None
