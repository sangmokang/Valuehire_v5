from __future__ import annotations

from .models import CapturedProfile, EmploymentTenure, Position, utc_now_iso


SAMPLE_POSITIONS: tuple[Position, ...] = (
    Position(
        position_id="pos-backend-wrtn",
        company_name="Wrtn Technologies",
        role_title="Backend Engineer",
        jd_text=(
            "Build large-scale AI product backend APIs with Java Spring, Kotlin, "
            "Node.js, NestJS, Redis, Kafka, cloud infra, and platform reliability."
        ),
        seniority_min=4,
        seniority_max=9,
        company_size="scaleup",
        industry_segment="ai_productivity",
        investment_stage="series_b",
        organization_analysis="AI product company with high traffic consumer and B2B workloads.",
        talent_density_notes="Prefers Korean scaleup backend engineers from high-density product teams.",
        must_haves=("backend api", "spring", "cloud", "production"),
        nice_to_haves=("llm product", "platform", "infra"),
        source_url="clickup://pos-backend-wrtn",
    ),
    Position(
        position_id="pos-backend-spoon",
        company_name="SpoonLabs",
        role_title="Platform Backend Engineer",
        jd_text=(
            "Own platform backend systems for global content service. Java Spring, "
            "Node/Nest, payment, settlement, observability, and distributed systems."
        ),
        seniority_min=5,
        seniority_max=10,
        company_size="scaleup",
        industry_segment="consumer_content",
        investment_stage="series_c",
        organization_analysis="Global content platform with backend reliability and settlement needs.",
        talent_density_notes="Good fit with engineers from consumer platforms and payment infra.",
        must_haves=("backend api", "spring", "distributed systems", "production"),
        nice_to_haves=("settlement", "content platform", "observability"),
        source_url="clickup://pos-backend-spoon",
    ),
    Position(
        position_id="pos-ai-madup",
        company_name="Madup",
        role_title="AI Engineer",
        jd_text=(
            "Develop production ML and LLM optimization for advertising. Python, PyTorch, "
            "recsys, MLOps, experiment design, model serving, and business problem solving."
        ),
        seniority_min=3,
        seniority_max=8,
        company_size="mid_market",
        industry_segment="adtech",
        investment_stage="profitable_growth",
        organization_analysis="Performance marketing/adtech company adopting LLM and ML systems.",
        talent_density_notes="Adtech, recommender, search, and marketplace ML pools are relevant.",
        must_haves=("python", "pytorch", "ml production", "business"),
        nice_to_haves=("adtech", "recsys", "llm"),
        source_url="clickup://pos-ai-madup",
    ),
    Position(
        position_id="pos-po-wrtn-ontology",
        company_name="Wrtn Technologies",
        role_title="AX Product Manager Ontology",
        jd_text=(
            "Own ontology and AI agent product planning. Product Owner, Product Manager, "
            "service planning, platform planning, data taxonomy, and cross-functional delivery."
        ),
        seniority_min=4,
        seniority_max=9,
        company_size="scaleup",
        industry_segment="ai_productivity",
        investment_stage="series_b",
        organization_analysis="Needs PO/PM who can translate AI ontology into product execution.",
        talent_density_notes="Strong fit from AI SaaS, platform, search, or knowledge product teams.",
        must_haves=("product owner", "service planning", "data", "stakeholder"),
        nice_to_haves=("ontology", "ai agent", "platform"),
        source_url="clickup://pos-po-wrtn-ontology",
    ),
    Position(
        position_id="pos-growth-uglylab",
        company_name="UglyLab",
        role_title="Growth Lead",
        jd_text=(
            "Lead consumer growth, performance marketing, CRM, retention, referral, "
            "content commerce, and funnel experimentation for a consumer app."
        ),
        seniority_min=7,
        seniority_max=14,
        company_size="startup",
        industry_segment="consumer_commerce",
        investment_stage="series_a",
        organization_analysis="Founder-adjacent growth owner for consumer commerce scaling.",
        talent_density_notes="Good pool from Kurly, Zigzag, TodayHouse, commerce and subscription apps.",
        must_haves=("growth", "performance marketing", "crm", "retention"),
        nice_to_haves=("consumer app", "commerce", "referral"),
        source_url="clickup://pos-growth-uglylab",
    ),
    Position(
        position_id="pos-sales-b2b-saas",
        company_name="ValueHire Client",
        role_title="B2B SaaS Sales Manager",
        jd_text=(
            "Own B2B SaaS enterprise sales, pipeline generation, CRM hygiene, "
            "customer discovery, negotiation, and renewal expansion."
        ),
        seniority_min=4,
        seniority_max=10,
        company_size="startup",
        industry_segment="b2b_saas",
        investment_stage="seed_to_series_a",
        organization_analysis="Needs hands-on sales owner with Korean B2B SaaS network.",
        talent_density_notes="Relevant from HRTech, MarTech, collaboration SaaS, CRM, and security SaaS.",
        must_haves=("b2b sales", "saas", "pipeline", "crm"),
        nice_to_haves=("enterprise", "renewal", "customer discovery"),
        source_url="clickup://pos-sales-b2b-saas",
    ),
)


SAMPLE_PROFILE = CapturedProfile(
    profile_url="https://www.linkedin.com/talent/profile/abc123?trk=search",
    source_channel="linkedin_rps",
    visible_text=(
        "Senior Backend Engineer in Seoul. 7 years building Java Spring and Kotlin "
        "backend APIs, Node.js/NestJS services, Kafka, Redis, AWS, observability, "
        "consumer AI products, settlement systems, and platform reliability at Korean scaleups."
    ),
    summary="Senior backend/platform engineer with Java Spring, Node/Nest, Kafka, Redis, AWS, and Korean scaleup experience.",
    captured_at=utc_now_iso(),
    screenshot_path="artifacts/profile-archiver/abc123.png",
    ocr_text="Senior Backend Engineer Java Spring Kotlin Node Nest Kafka Redis AWS",
    years_experience=7,
    education="BS Computer Science",
    current_or_past_companies=("Korean AI Scaleup", "Consumer Content Platform"),
    skills=("java", "spring", "kotlin", "node.js", "nestjs", "kafka", "redis", "aws", "platform", "backend api"),
    industries=("ai_productivity", "consumer_content"),
    location_signals=("Korea", "Seoul"),
    language_signals=("Korean", "English"),
    evidence_paths=("artifacts/profile-archiver/abc123.json", "artifacts/profile-archiver/abc123.png"),
)


# 저수지 단계 3 — 경력 이력(이직 안정성) 검증용 픽스처. 1년 미만 재직 후 이직이 3회로 감점 대상.
SAMPLE_PROFILE_JOB_HOPPER = CapturedProfile(
    profile_url="https://www.saramin.co.kr/profile/hopper-001",
    source_channel="saramin",
    visible_text=(
        "Backend engineer with Java Spring and Node.js experience across several startups."
    ),
    summary="Backend engineer, frequent short tenures across early-stage startups.",
    captured_at=utc_now_iso(),
    years_experience=4,
    education="무명대학교 컴퓨터공학",
    current_or_past_companies=("Startup A", "Startup B", "Startup C", "Startup D"),
    skills=("java", "spring", "node.js", "backend api"),
    location_signals=("Korea", "Seoul"),
    language_signals=("Korean",),
    evidence_paths=("artifacts/profile-archiver/hopper-001.json",),
    employment_history=(
        EmploymentTenure("Startup A", "2021-01", "2021-08"),  # 7개월, 퇴사
        EmploymentTenure("Startup B", "2021-09", "2022-05"),  # 8개월, 퇴사
        EmploymentTenure("Startup C", "2022-06", "2023-02"),  # 8개월, 퇴사
        EmploymentTenure("Startup D", "2023-03", ""),         # 현재 재직(미카운트)
    ),
)
