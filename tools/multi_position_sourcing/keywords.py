from __future__ import annotations

from .models import Channel, KeywordSession, PositionGroup, RoleFamily

PORTAL_STANDARD_WORDS: dict[RoleFamily, dict[Channel, tuple[str, ...]]] = {
    "backend": {
        "saramin": ("백엔드 개발자", "Java Spring 개발자", "Node.js 개발자", "플랫폼 개발자", "인프라 개발자"),
        "jobkorea": ("백엔드 개발자", "Java Spring", "Node.js", "플랫폼 엔지니어", "인프라 엔지니어"),
        "linkedin_rps": ("Backend Engineer", "Java Spring Engineer", "Node.js Engineer", "Platform Engineer", "Infrastructure Engineer"),
        "public_web": ("site:linkedin.com/in Backend Engineer Korea", "site:linkedin.com/in Java Spring Engineer Korea", "site:linkedin.com/in Node.js Engineer Korea"),
    },
    "frontend": {
        "saramin": ("프론트엔드 개발자", "React 개발자", "웹 프론트엔드"),
        "jobkorea": ("프론트엔드 개발자", "React", "웹 개발자"),
        "linkedin_rps": ("Frontend Engineer", "React Engineer", "Web Frontend Engineer"),
        "public_web": ("site:linkedin.com/in Frontend Engineer Korea", "site:linkedin.com/in React Engineer Korea", "site:linkedin.com/in Web Frontend Engineer Korea"),
    },
    "ai_ml": {
        "saramin": ("AI 엔지니어", "머신러닝 엔지니어", "ML 엔지니어"),
        "jobkorea": ("AI 엔지니어", "머신러닝", "ML Engineer"),
        "linkedin_rps": ("AI Engineer", "Machine Learning Engineer", "LLM Engineer", "MLOps Engineer"),
        "public_web": ("site:linkedin.com/in AI Engineer Korea", "site:linkedin.com/in Machine Learning Engineer Korea", "site:linkedin.com/in LLM Engineer Korea"),
    },
    "product_po": {
        "saramin": ("Product Owner", "Product Manager", "서비스기획", "플랫폼기획"),
        "jobkorea": ("Product Owner", "Product Manager", "서비스기획자", "플랫폼기획자"),
        "linkedin_rps": ("Product Owner", "Product Manager", "Platform Product Manager", "AI Product Manager"),
        "public_web": ("site:linkedin.com/in Product Owner Korea", "site:linkedin.com/in Product Manager Korea", "site:linkedin.com/in AI Product Manager Korea"),
    },
    "growth": {
        "saramin": ("그로스 마케터", "퍼포먼스 마케터", "CRM 마케터"),
        "jobkorea": ("그로스 마케터", "퍼포먼스 마케팅", "CRM 마케팅"),
        "linkedin_rps": ("Growth Lead", "Growth Marketing Manager", "Performance Marketing Manager", "CRM Manager"),
        "public_web": ("site:linkedin.com/in Growth Lead Korea", "site:linkedin.com/in CMO Korea startup", "site:linkedin.com/in Performance Marketing Korea CRM"),
    },
    "sales": {
        "saramin": ("B2B 영업", "SaaS 영업", "세일즈 매니저"),
        "jobkorea": ("B2B 영업", "SaaS 세일즈", "Account Executive"),
        "linkedin_rps": ("B2B Sales Manager", "SaaS Account Executive", "Enterprise Sales Manager"),
        "public_web": ("site:linkedin.com/in B2B Sales Manager Korea", "site:linkedin.com/in SaaS Account Executive Korea", "site:linkedin.com/in Enterprise Sales Korea"),
    },
    "operations": {
        "saramin": ("콘텐츠 운영", "정산 담당자", "파트너 운영"),
        "jobkorea": ("콘텐츠 운영", "정산", "파트너 운영"),
        "linkedin_rps": ("Content Operations", "Settlement Operations", "Partner Operations"),
        "public_web": ("site:linkedin.com/in Content Operations Korea", "site:linkedin.com/in Partner Operations Korea", "site:linkedin.com/in Operations Manager Korea"),
    },
    "unknown": {"saramin": ("직무",), "jobkorea": ("직무",), "linkedin_rps": ("Role",), "public_web": ("site:linkedin.com/in Korea",)},
}

NICHE_SCREENING_TERMS: dict[RoleFamily, tuple[str, ...]] = {
    "backend": ("llm product", "subculture", "settlement", "consumer scale"),
    "product_po": ("ontology", "ai agent", "subculture", "미연시", "서브컬쳐"),
    "growth": ("short-form", "commerce", "referral", "subscription"),
    "ai_ml": ("adtech", "recsys", "search ranking", "llm optimization"),
    "sales": ("hrtech", "martech", "security saas"),
    "frontend": ("editor", "canvas", "web performance"),
    "operations": ("rights", "billing", "anti-piracy"),
    "unknown": (),
}


def portal_keywords_for_family(
    family: RoleFamily,
    seniority: tuple[int, int],
) -> tuple[dict[Channel, tuple[str, ...]], dict[Channel, dict[str, object]]]:
    keywords = PORTAL_STANDARD_WORDS.get(family, PORTAL_STANDARD_WORDS["unknown"])
    filters: dict[Channel, dict[str, object]] = {
        "saramin": {
            "career_years": {"min": max(0, seniority[0] - 1), "max": seniority[1] + 1},
            "education": "4년제 졸업",
            "clear_existing_chips": True,
        },
        "jobkorea": {
            "career_years": {"min": max(0, seniority[0] - 1), "max": seniority[1] + 1},
            "education": "대학교 졸업",
            "clear_existing_chips": True,
        },
        "linkedin_rps": {
            "profile_url_must_match": "/talent/profile/",
            "allow_inmail_send": False,
            "export_requires_gate": "RPS_EXPORT_ALLOW_WRITE",
        },
        "public_web": {
            "source_type": "public_search_only",
            "allowed_profile_url_patterns": ("linkedin.com/in/", "about", "company", "press", "interview"),
            "no_private_message": True,
            "no_scrape_login_wall": True,
        },
    }
    return dict(keywords), filters


def build_keyword_plan(group: PositionGroup) -> tuple[KeywordSession, ...]:
    sessions: list[KeywordSession] = []
    for channel in ("saramin", "jobkorea", "linkedin_rps", "public_web"):
        for keyword in group.portal_keywords_by_channel[channel]:
            sessions.append(
                KeywordSession(
                    channel=channel,
                    standard_keyword=keyword,
                    variants=(),
                    filters=group.filters_by_channel[channel],
                    reset_before_run=True,
                    llm_screening_keywords=NICHE_SCREENING_TERMS.get(group.role_family, ()),
                )
            )
    return tuple(sessions)


def keyword_plan_for_channel(group: PositionGroup, channel: Channel) -> tuple[KeywordSession, ...]:
    return tuple(session for session in group.keyword_plan if session.channel == channel)
