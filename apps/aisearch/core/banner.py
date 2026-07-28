"""AC-8/D9 — 자동화 빨간 띠 배너용 dispatch JS 스니펫 생성.

이 모듈은 **문자열 생성만** 한다. CDP 실행/브라우저 호출은 상위 레이어의 몫이다.

프로토콜: 페이지 컨텍스트에서 아래 CustomEvent 를 dispatch 하면
``apps/aisearch/extension/content.js`` 가 수신해 배너를 표시(active=true)
또는 제거(active=false)한다::

    window.dispatchEvent(new CustomEvent("valuehire:automation",
        {detail: {"active": true, "task": "..."}}))
"""

from __future__ import annotations

import json

EVENT_NAME = "valuehire:automation"


def build_dispatch_snippet(active: bool, task: str = "") -> str:
    """배너 표시/제거 CustomEvent dispatch 용 JS 스니펫 문자열을 만든다.

    - ``active=True`` 면 배너 표시(``task`` 문구 포함), ``False`` 면 제거.
    - payload 는 JSON 직렬화로 안전하게 이스케이프한다(따옴표·``</script>`` 등).
    - 엄격 타입 검증(fail-fast): ``active`` 는 bool 만, ``task`` 는 str 만 허용.
      조용한 변환(``"false"`` → True, ``None`` → ``"None"``) 금지.
      표시 신호(``active=True``)의 ``task`` 는 비어있지 않아야 한다.
    """
    if not isinstance(active, bool):
        raise TypeError(
            f"active 는 bool 만 허용 (받은 값: {type(active).__name__}={active!r})"
        )
    if not isinstance(task, str):
        raise TypeError(
            f"task 는 str 만 허용 (받은 값: {type(task).__name__}={task!r})"
        )
    if active and not task.strip():
        raise ValueError("active=True 표시 신호의 task 는 비어있지 않은 str 이어야 한다")

    detail = json.dumps(
        {"active": active, "task": task},
        ensure_ascii=False,
    )
    # "</script>" 가 인라인 <script> 에 들어가면 태그가 조기 종료될 수 있어
    # 슬래시를 이스케이프한다(JSON/JS 모두에서 "\/" == "/").
    detail = detail.replace("</", "<\\/")
    return (
        "window.dispatchEvent(new CustomEvent("
        + json.dumps(EVENT_NAME)
        + ", {detail: "
        + detail
        + "}));"
    )
