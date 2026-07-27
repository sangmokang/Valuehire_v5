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
    """
    detail = json.dumps(
        {"active": bool(active), "task": str(task)},
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
