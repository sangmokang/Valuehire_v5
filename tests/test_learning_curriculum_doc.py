"""LLM 하니스·루프 엔지니어링 강의 문서 계약 검사.

goal: docs/engineering/llm-harness-curriculum-goal-2026-07-16.md

강의 문서(docs/learning/llm-harness-loop-engineering.html)는 "살아있는 문서"다 —
본문이 인용한 코드 경로(data-ref 속성)가 실존하지 않으면 RED가 되어 갱신을 강제한다.

인수 기준(기계 단언):
  1. 문서 파일이 존재하고 HTML 파싱이 성공한다.
  2. 모든 <code class="ref" data-ref="..."> 인용 경로가 레포에 실존한다.
  3. 내부 앵커(href="#x")마다 대응 id 가 존재한다 (끊긴 앵커 0).
  4. 인용(data-ref)이 최소 20개 — 문서를 비워서 통과하는 우회 차단.
  5. 여닫는 태그 균형 — 비-void 요소의 깨진 태그 0.
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "learning" / "llm-harness-loop-engineering.html"

# HTML void 요소 — 닫는 태그가 없는 것이 정상
_VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


class _DocAudit(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.refs: list[str] = []
        self.anchors: list[str] = []
        self.ids: set[str] = set()
        self.stack: list[str] = []
        self.balance_errors: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attr = dict(attrs)
        if "data-ref" in attr and attr["data-ref"]:
            self.refs.append(attr["data-ref"])
        href = attr.get("href", "")
        if href.startswith("#"):
            self.anchors.append(href[1:])
        if attr.get("id"):
            self.ids.add(attr["id"])
        if tag not in _VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID:
            return
        if not self.stack:
            self.balance_errors.append(f"여는 태그 없이 닫힘: </{tag}>")
            return
        if self.stack[-1] == tag:
            self.stack.pop()
            return
        # 중간에 안 닫힌 태그가 있으면 균형 오류로 기록
        if tag in self.stack:
            while self.stack and self.stack[-1] != tag:
                self.balance_errors.append(f"안 닫힌 태그: <{self.stack.pop()}>")
            self.stack.pop()
        else:
            self.balance_errors.append(f"짝 없는 닫는 태그: </{tag}>")


@pytest.fixture(scope="module")
def audit() -> _DocAudit:
    assert DOC.is_file(), f"강의 문서 부재: {DOC.relative_to(REPO)}"
    parser = _DocAudit()
    parser.feed(DOC.read_text(encoding="utf-8"))
    parser.close()
    return parser


def test_curriculum_doc_exists_and_parses(audit: _DocAudit) -> None:
    assert audit is not None


def test_all_cited_code_paths_exist(audit: _DocAudit) -> None:
    missing = sorted({r for r in audit.refs if not (REPO / r).exists()})
    assert not missing, (
        "강의 문서가 인용한 경로가 실존하지 않음 — 코드가 이동/삭제됐으면 문서를 갱신할 것: "
        + ", ".join(missing)
    )


def test_citation_floor(audit: _DocAudit) -> None:
    # 인용을 비워서 검사를 통과하는 우회 차단 (초판 기준 20개 이상 인용)
    assert len(audit.refs) >= 20, f"data-ref 인용이 {len(audit.refs)}개 — 최소 20개"


def test_internal_anchors_resolve(audit: _DocAudit) -> None:
    broken = sorted({a for a in audit.anchors if a not in audit.ids})
    assert not broken, f"끊긴 내부 앵커: {broken}"


def test_tag_balance(audit: _DocAudit) -> None:
    leftovers = [t for t in audit.stack if t != "html"]
    errors = audit.balance_errors + [f"문서 끝까지 안 닫힘: <{t}>" for t in leftovers]
    assert not errors, "깨진 태그: " + "; ".join(errors[:10])
