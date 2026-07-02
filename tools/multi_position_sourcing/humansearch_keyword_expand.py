"""서치 후 검색어 확장·갭 점검 (2026-07-03 사장님 지시).

사장님이 걸어둔 검색어를 한↔영·띄어쓰기 변형으로 확장하고, JD 핵심 키워드 중
어느 것도 못 덮는 갭(missing)을 찾아 재검색 후보(research_queries)를 만든다.
기계 확장은 보수적 사전 기반 — 최종 큐레이션은 SKILL 실행 시 LLM(Claude)이
문맥으로 검증한다(오탐 확장·무의미 재검색 차단).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# 한↔영 리크루팅 도메인 사전 (보수적 — 확실한 쌍만. 확장은 LLM 큐레이션이 보정)
KO_EN_GLOSSARY: tuple[tuple[str, str], ...] = (
    ("로봇", "robot"),
    ("로보틱스", "robotics"),
    ("제어", "control"),
    ("기구학", "kinematics"),
    ("동역학", "dynamics"),
    ("머신러닝", "machine learning"),
    ("머신 러닝", "machine learning"),
    ("딥러닝", "deep learning"),
    ("강화학습", "reinforcement learning"),
    ("컴퓨터비전", "computer vision"),
    ("컴퓨터 비전", "computer vision"),
    ("임베디드", "embedded"),
    ("백엔드", "backend"),
    ("프론트엔드", "frontend"),
    ("데이터 사이언티스트", "data scientist"),
    ("데이터 엔지니어", "data engineer"),
    ("프로덕트 매니저", "product manager"),
    ("서비스 기획", "product manager"),
    ("서비스기획", "product manager"),
    ("사업개발", "business development"),
    ("영업", "sales"),
    ("세일즈", "sales"),
    ("재무", "finance"),
    ("회계", "accounting"),
    ("결산", "financial closing"),
    ("세무", "tax"),
    ("감사", "audit"),
    ("공급망", "supply chain"),
    ("품질", "quality assurance"),
    ("인사", "human resources"),
    ("채용", "recruiting"),
    ("마케팅", "marketing"),
    ("자동화", "automation"),
    ("워크플로우", "workflow"),
    ("보안", "security"),
)
EN_KO = {en: ko for ko, en in KO_EN_GLOSSARY}
KO_EN = {ko: en for ko, en in KO_EN_GLOSSARY}
# 대표 역번역 보강: product manager 는 한국어 두 표현으로
EN_KO_MULTI: dict[str, tuple[str, ...]] = {
    "product manager": ("프로덕트 매니저", "서비스기획"),
    "robot": ("로봇",),
    "control": ("제어",),
    "sales": ("영업", "세일즈"),
}

# JD 에서 핵심 키워드로 인정할 신호(영문 토큰·한글 도메인어) — 흔한 불용어 제외
_JD_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#./-]{1,}|[가-힣]{2,}")
_JD_SECTION_HINT = re.compile(r"(자격|요건|필수|주요\s*업무|우대|Requirements|Qualifications)", re.IGNORECASE)
_STOPWORDS = {
    "있으신", "있는", "경험", "경력", "이상", "우대", "능숙", "이해", "기반", "관련",
    "그리고", "또는", "하는", "위한", "대한", "함께", "모듈", "and", "or", "the",
    "with", "for", "of", "in", "to", "years", "etc",
}


@dataclass(frozen=True)
class KeywordExpansion:
    expanded: tuple[str, ...]        # 사장님 검색어의 한↔영·띄어쓰기 변형
    jd_core: tuple[str, ...]         # JD 핵심 키워드(요건 절 위주)
    missing: tuple[str, ...]         # 어떤 검색어/확장도 못 덮는 JD 핵심 키워드
    research_queries: tuple[str, ...]  # missing 기반 재검색 후보(LLM 큐레이션 대상)


def _spacing_variants(term: str) -> set[str]:
    out = set()
    if " " in term:
        out.add(term.replace(" ", ""))
    # 한글 복합어 → 띄어쓰기 변형(사전에 등재된 spaced 형이 있으면 그것을)
    for ko, _ in KO_EN_GLOSSARY:
        if " " in ko and ko.replace(" ", "") == term:
            out.add(ko)
    return out


def _translate(term: str) -> set[str]:
    low = term.lower().strip()
    out: set[str] = set()
    if low in EN_KO_MULTI:
        out.update(EN_KO_MULTI[low])
    if low in EN_KO:
        out.add(EN_KO[low])
    # 한→영: 용어가 통째로 사전에 있으면 그 번역, 아니면 포함된 단어별
    if term in KO_EN:
        out.add(KO_EN[term])
    else:
        for ko, en in KO_EN_GLOSSARY:
            if ko in term:
                out.add(en)
    return out - {term}


def expand_search_terms(owner_terms: list[str] | tuple[str, ...], jd_text: str) -> KeywordExpansion:
    owner_terms = [t.strip() for t in owner_terms if t and t.strip()]
    if not owner_terms and not jd_text.strip():
        return KeywordExpansion((), (), (), ())

    expanded: set[str] = set()
    for t in owner_terms:
        expanded |= _spacing_variants(t)
        expanded |= _translate(t)
        for v in list(_spacing_variants(t)):
            expanded |= _translate(v)

    # JD 핵심 키워드: 요건 힌트가 있는 줄 우선, 없으면 전체에서 도메인 사전·기술 토큰
    lines = [ln for ln in jd_text.splitlines() if ln.strip()]
    hinted = [ln for ln in lines if _JD_SECTION_HINT.search(ln)]
    scan_text = "\n".join(hinted) if hinted else jd_text
    core: list[str] = []
    for tok in _JD_TOKEN_RE.findall(scan_text):
        low = tok.lower()
        if low in _STOPWORDS or len(tok) < 2:
            continue
        is_domain = tok in KO_EN or low in EN_KO or any(ko in tok for ko, _ in KO_EN_GLOSSARY)
        is_tech = bool(re.search(r"[A-Za-z]", tok)) and (tok[0].isupper() or low in EN_KO or "+" in tok or "/" in tok or low.isupper() or len(tok) <= 6)
        if (is_domain or is_tech) and tok not in core:
            core.append(tok)

    # 커버리지: 사장님 검색어 + 확장이 (양방향 번역 포함) 덮는 키워드는 missing 아님
    cover = {t.lower() for t in owner_terms} | {t.lower() for t in expanded}
    cover_expanded = set(cover)
    for c in list(cover):
        if c in KO_EN:
            cover_expanded.add(KO_EN[c].lower())
        if c in EN_KO:
            cover_expanded.add(EN_KO[c].lower())
    missing = []
    for kw in core:
        low = kw.lower()
        translations = {low}
        if kw in KO_EN:
            translations.add(KO_EN[kw].lower())
        if low in EN_KO:
            translations.add(EN_KO[low].lower())
        if any(any(t in c or c in t for c in cover_expanded) for t in translations):
            continue
        missing.append(kw)

    research = tuple(dict.fromkeys(
        q for kw in missing[:8]
        for q in ([kw] + ([KO_EN[kw]] if kw in KO_EN else []) + ([EN_KO[kw.lower()]] if kw.lower() in EN_KO else []))
    ))
    return KeywordExpansion(tuple(sorted(expanded)), tuple(core), tuple(missing), research)
