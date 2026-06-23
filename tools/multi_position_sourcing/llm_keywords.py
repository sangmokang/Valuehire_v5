"""W4 — LLM 기반 키워드 생성기.

기존 5분류 룰(``grouping.ROLE_SIGNALS``)과 하드코딩 키워드표(``keywords.PORTAL_STANDARD_WORDS``)는
JD를 "단어 카운트"로만 보고 고정 표를 뱉는다. 이 모듈은 그 대신 **JD 원문을 LLM에 넘겨**
포지션에 가장 적합한, 사람 헤드헌터 수준의 검색 키워드를 채널별로 뽑는다.

설계 원칙
- LLM 호출은 주입형(``llm_client: Callable[[str], str]``). 테스트는 가짜 클라이언트로 결정론,
  운영은 ``claude_keyword_client``(``claude -p``)로 라이브.
- 0건 검색의 원인을 막는다: 빈/깨진 응답·빈 키워드는 **조용히 통과시키지 않고 에러**
  (``KeywordGenerationError``). "0건이면 키워드가 진짜 들어갔나부터 의심"의 출발점.
- 채널별 형식: 링크드인/공개웹은 boolean(AND/OR) X-ray 쿼리를 살리고, 사람인·잡코리아는
  인재검색 필드의 AND/OR 지원이 라이브 미검증이라 평문 키워드만 둔다(boolean_query="").
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

from .models import BOOLEAN_CHANNELS, Channel, KeywordSession, QueueItem

LLMClient = Callable[[str], str]

# 검색이 도는 기본 채널 순서.
DEFAULT_CHANNELS: tuple[Channel, ...] = ("saramin", "jobkorea", "linkedin_rps", "public_web")

# boolean(AND/OR) X-ray 쿼리를 실제로 받는 채널. 단일 출처는 models.BOOLEAN_CHANNELS
# (생성=여기, 주입=portal_queue_executor 가 같은 집합을 참조해 드리프트를 막는다).
_BOOLEAN_CHANNELS: frozenset[Channel] = BOOLEAN_CHANNELS


class KeywordGenerationError(RuntimeError):
    """LLM 키워드 생성이 신뢰할 결과를 못 냈을 때(빈 응답·파싱 실패·빈 키워드)."""


@dataclass(frozen=True)
class LLMKeywordPlan:
    channel: Channel
    keywords: tuple[str, ...]
    boolean_query: str = ""


def _build_prompt(position, channel: Channel) -> str:
    boolean_hint = (
        '이 채널은 boolean 검색을 지원한다. "boolean_query"에 ("A" OR "B") AND ("C" OR "D") '
        "형식의 X-ray 쿼리를 한 줄로 채워라. "
        "boolean_query 는 Title(직무) + Skill(변별력 있는 기술스택 2~3개) + Domain(도메인/산업)"
        "만으로 구성하라. 연차·경력년수·지역·근무지·OTW(연봉/처우)는 boolean_query 에 절대 넣지 마라"
        " — 이 조건들은 검색의 native 필터/2패스가 따로 처리하므로 boolean 에 넣으면 충돌해 0건이 난다."
        if channel in _BOOLEAN_CHANNELS
        else '이 채널은 평문 키워드 검색이다. "boolean_query"는 빈 문자열("")로 두어라.'
    )
    must = ", ".join(position.must_haves) or "(명시 없음)"
    nice = ", ".join(position.nice_to_haves) or "(명시 없음)"
    return (
        "너는 한국 IT 채용 시니어 헤드헌터다. 아래 채용공고(JD)를 이해하고, 이 포지션에 "
        "가장 적합한 후보를 찾을 검색 키워드를 발굴하라.\n"
        f"검색 채널: {channel}\n"
        f"회사: {position.company_name}\n"
        f"직무: {position.role_title}\n"
        f"필수조건: {must}\n"
        f"우대조건: {nice}\n"
        "JD 원문:\n"
        f"{position.jd_text}\n\n"
        "요구사항:\n"
        "1. 국문과 영문 키워드를 모두 발굴하라(국문/영문 표기, 띄어쓰기 변형, 흔한 축약어 포함).\n"
        "2. 바보같은 문장이나 JD를 통째로 넣지 말고, 검색 필드에 그대로 칠 수 있는 키워드 단위로 뽑아라.\n"
        f"3. {boolean_hint}\n"
        '4. 오직 JSON 한 개만 출력하라: {"keywords": ["..."], "boolean_query": "..."} '
        "(키워드는 적합도 높은 순, 설명 금지).\n"
    )


def _extract_json_object(raw: str) -> dict:
    text = (raw or "").strip()
    if not text:
        raise KeywordGenerationError("LLM 응답이 비었습니다 (0건 검색 위험).")
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise KeywordGenerationError(f"LLM 응답에서 JSON을 찾지 못했습니다: {text[:120]!r}")
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise KeywordGenerationError(f"LLM JSON 파싱 실패: {exc}") from exc
    if not isinstance(parsed, dict):
        raise KeywordGenerationError("LLM JSON 최상위가 객체가 아닙니다.")
    return parsed


def _clean_keywords(raw_keywords) -> tuple[str, ...]:
    if not isinstance(raw_keywords, list):
        raise KeywordGenerationError('"keywords"가 리스트가 아닙니다.')
    seen: set[str] = set()
    ordered: list[str] = []
    for item in raw_keywords:
        if not isinstance(item, str):
            continue
        kw = item.strip()
        if not kw or kw in seen:
            continue
        seen.add(kw)
        ordered.append(kw)
    if not ordered:
        raise KeywordGenerationError("LLM이 유효한 키워드를 하나도 내지 않았습니다 (0건 검색 위험).")
    return tuple(ordered)


def generate_keyword_plan(position, channel: Channel, *, llm_client: LLMClient) -> LLMKeywordPlan:
    """JD를 LLM에 넘겨 채널별 키워드 계획을 만든다.

    실패(빈 응답·파싱 실패·빈 키워드)는 조용히 넘기지 않고 ``KeywordGenerationError``.
    """
    prompt = _build_prompt(position, channel)
    raw = llm_client(prompt)
    parsed = _extract_json_object(raw)
    keywords = _clean_keywords(parsed.get("keywords"))
    boolean_query = ""
    if channel in _BOOLEAN_CHANNELS:
        bq = parsed.get("boolean_query")
        boolean_query = bq.strip() if isinstance(bq, str) else ""
    return LLMKeywordPlan(channel=channel, keywords=keywords, boolean_query=boolean_query)


def build_llm_keyword_sessions(
    position,
    *,
    llm_client: LLMClient,
    channels: tuple[Channel, ...] = DEFAULT_CHANNELS,
) -> tuple[KeywordSession, ...]:
    """LLM 키워드 계획을 검색 경로가 소비하는 ``KeywordSession`` 튜플로 변환한다.

    채널마다 ``generate_keyword_plan`` 을 호출해 키워드 1개당 세션 1개를 만든다(순서 보존).
    boolean 채널(링크드인/공개웹)은 AND/OR X-ray 쿼리를 세션 ``filters['boolean_query']`` 로
    실어 나른다(평문 채널은 비움). 어느 채널이라도 키워드를 못 뽑으면 ``KeywordGenerationError``
    가 그대로 전파된다 — 조용히 건너뛰어 0건 검색을 유발하지 않는다.
    """
    sessions: list[KeywordSession] = []
    for channel in channels:
        plan = generate_keyword_plan(position, channel, llm_client=llm_client)
        base_filters = {"boolean_query": plan.boolean_query} if plan.boolean_query else {}
        for keyword in plan.keywords:
            sessions.append(
                KeywordSession(
                    channel=channel,
                    standard_keyword=keyword,
                    filters=dict(base_filters),
                    reset_before_run=True,
                )
            )
    return tuple(sessions)


def build_llm_queue_items(
    position,
    *,
    llm_client: LLMClient,
    channels: tuple[Channel, ...] = DEFAULT_CHANNELS,
) -> tuple[QueueItem, ...]:
    """포지션 1건을 LLM 키워드 기반 채널별 ``QueueItem`` 으로 만든다(검색 큐 투입 단위).

    5분류/그룹핑을 거치지 않고 **포지션 원문→LLM 키워드**로 곧장 큐 아이템을 만든다.
    채널마다 그 채널 세션만 담은 ``QueueItem``(status=pending, group_id는 포지션 추적)을 만든다.
    키워드를 못 뽑는 채널은 ``KeywordGenerationError`` 가 전파된다(0건 검색 방지).
    """
    sessions = build_llm_keyword_sessions(position, llm_client=llm_client, channels=channels)
    items: list[QueueItem] = []
    for channel in channels:
        channel_sessions = tuple(s for s in sessions if s.channel == channel)
        items.append(
            QueueItem(
                group_id=f"llm-{position.position_id}",
                channel=channel,
                keyword_plan=channel_sessions,
                status="pending",
            )
        )
    return tuple(items)


def claude_keyword_client(
    *, model: str = "haiku", run_command: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run
) -> LLMClient:
    """운영용 LLM 클라이언트 — 로컬 ``claude -p`` 호출(비용 헌법: 저가 모델 기본).

    ``claude`` CLI가 없으면 호출 시점에 ``KeywordGenerationError``.
    """

    def _call(prompt: str) -> str:
        if shutil.which("claude") is None:
            raise KeywordGenerationError("claude CLI를 찾지 못했습니다.")
        result = run_command(
            ["claude", "-p", "--model", model, prompt],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise KeywordGenerationError(f"claude -p 실패(rc={result.returncode}): {(result.stderr or '')[:200]}")
        return result.stdout or ""

    return _call
