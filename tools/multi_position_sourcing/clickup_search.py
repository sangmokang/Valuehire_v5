"""ClickUp 포지션 검색 REST 어댑터 (#200).

nl_shell.clickup_position_searcher 가 요구하는 계약 — (list_id=, query=, parent=)
-> Sequence[Mapping] — 을 ClickUp REST 로 채운다. 새 검색 계약을 만들지 않고 기존
어댑터 모양을 그대로 구현한다(CLAUDE.md §0.2).

운영 게이트웨이(scripts/discord_direct_gateway._build_client)가
production_nl_searcher_factory 로 이 어댑터를 nl_searcher_factory 에 배선한다.
ClickUp 미설정이면 None 을 돌려 자연어를 조용히 비활성(기존 명령 경로 불변).
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Any, Callable, Mapping, Optional

_CLICKUP_API = "https://api.clickup.com/api/v2"
# ClickUp list id 는 숫자. task id 는 영숫자(예: 86exwz89j). 경로/URL 안전 문자만 허용.
_LIST_ID_RE = re.compile(r"^[0-9]+$")
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9]+$")
# Codex V2 2R: Discord 마크다운/멘션 트리거 문자를 표시 이름에서 이스케이프한다.
_MD_SPECIAL = set(r"\*_~`|>[]()#@:")


def _sanitize_name(raw: Any) -> str:
    """태스크 이름을 한 줄로 접고 마크다운/멘션 특수문자를 이스케이프(표시 안전).

    매칭은 토큰(영숫자·한글) 기준이라 특수문자 이스케이프의 영향을 받지 않는다."""
    text = " ".join(str(raw or "").split())  # 개행·연속공백 → 단일 공백(멀티라인 주입 차단)
    return "".join("\\" + ch if ch in _MD_SPECIAL else ch for ch in text)


def make_clickup_search_tasks(
    token: str, *, urlopen: Callable[..., Any] = urllib.request.urlopen,
    timeout: int = 15,
) -> Callable[..., list[dict[str, Any]]]:
    """ClickUp 리스트의 열린 태스크를 가져오는 검색 콜러블을 만든다.

    반환 콜러블 계약: ``(list_id=, query=, parent=) -> list[dict]``. ClickUp 의
    ``GET /list/{list_id}/task`` 는 이름 서버검색을 지원하지 않으므로 열린 태스크를
    받아오고, 이름 토큰 필터링은 상위(clickup_position_searcher)가 한다. archived·
    closed 는 제외해 '진행 중 포지션'만 후보가 되게 한다."""

    def search_tasks(*, list_id: str, query: str = "",
                     parent: Optional[str] = None) -> list[dict[str, Any]]:
        # Codex V2 F5: list_id 는 숫자만 — 경로 traversal(`../team/123`) 차단.
        if not _LIST_ID_RE.match(str(list_id)):
            raise ValueError("invalid ClickUp list_id")
        params = urllib.parse.urlencode({
            "archived": "false", "include_closed": "false", "subtasks": "false",
        })
        req = urllib.request.Request(
            f"{_CLICKUP_API}/list/{urllib.parse.quote(str(list_id), safe='')}/task?{params}",
            headers={"Authorization": token, "Content-Type": "application/json"},
        )
        with urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode() or "null")
        tasks = payload.get("tasks") if isinstance(payload, Mapping) else None
        if not isinstance(tasks, list):
            return []
        # Codex V2 F2/2R: id 가 영숫자인 태스크만 남기고, url 을 검증된 id 로 만든
        # 정식 링크로 *덮어쓴다* — task['url'] 을 신뢰하면 악성 태스크가 임의 URL 을
        # position_url 로 주입할 수 있다(_task_url 이 task['url'] 우선). 표시 이름도
        # 마크다운/멘션 안전하게 정규화한다.
        out: list[dict[str, Any]] = []
        for t in tasks:
            if not isinstance(t, Mapping):
                continue
            task_id = str(t.get("id") or "")
            if not _TASK_ID_RE.match(task_id):
                continue
            safe = dict(t)
            safe["url"] = f"https://app.clickup.com/t/{task_id}"
            safe["name"] = _sanitize_name(t.get("name"))
            out.append(safe)
        return out

    return search_tasks


def production_nl_searcher_factory(
    env: Mapping[str, str],
    *, urlopen: Callable[..., Any] = urllib.request.urlopen,
) -> Optional[Callable[[], Any]]:
    """운영 배선용 nl_searcher_factory — ClickUp 설정이 있으면 검색기 팩토리, 없으면 None.

    None 이면 gateway 가 자연어를 조용히 비활성(fail-safe) — 정형 명령 경로는 불변.
    비밀(토큰)은 여기서 로그·노출하지 않는다."""
    token = str(env.get("CLICKUP_API_TOKEN") or "").strip()
    list_id = str(env.get("CLICKUP_POSITIONS_LIST_ID") or "").strip()
    # Codex V2 F5: list_id 는 숫자만(오설정·주입 방지). 아니면 NL 비활성(None).
    if not token or not _LIST_ID_RE.match(list_id):
        return None
    from tools.multi_position_sourcing.nl_shell import clickup_position_searcher

    def factory() -> Any:
        base = clickup_position_searcher(
            make_clickup_search_tasks(token, urlopen=urlopen), list_id=list_id)

        def safe_searcher(locus: str, target: str) -> Any:
            # Codex V2 F1: 어댑터 예외를 그대로 올리면 resolve()가 str(exc)를 디스코드
            # 답장으로 내보낸다 — 토큰·내부 URL·스택이 새지 않도록 일반 메시지로 봉인.
            try:
                return base(locus, target)
            except Exception:  # noqa: BLE001 — 원문 삼킴이 아니라 '못 물어봤다'는 유지
                raise RuntimeError("ClickUp 포지션 조회에 실패했습니다") from None

        return safe_searcher

    return factory
