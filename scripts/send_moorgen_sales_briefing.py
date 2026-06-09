#!/usr/bin/env python3
"""Send Moorgen Space Sales Manager multisearch candidate briefings to the
Valuehire search-list Discord channel.

- Reads VALUEHIRE_SEARCH_LIST_DISCORD_WEBHOOK_URL from .env.local (never printed).
- Every candidate card carries the public Profile URL (hard requirement).
- Internal team handoff only. No outreach to candidates.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

POSITION_ID = "moorgen-space-sales-manager-2026-06-09"
POSITION_TITLE = "모건 스페이스(Moorgen Space) — Sales Manager (선임~책임급, 경력 3~10년, 서울/정규직)"

# Candidates discovered via public LinkedIn X-ray search (2026-06-09).
# Evidence = LinkedIn search-indexed title/headline (reliable). Public profile
# bodies could NOT be opened (HTTP 999 auth wall) — so unverified items are
# flagged in why_not. No fabricated candidates.
CANDIDATES = [
    {
        "name": "Ashton Oh",
        "url": "https://kr.linkedin.com/in/ashton-oh-1a211b271",
        "score": 88,
        "summary": "Crestron Electronics 한국 Sales Manager. 하이엔드 AV·공간 자동화 제어 솔루션 B2B 영업. 타겟 출신 회사(Crestron) 직접 재직, 한국 기반, Sales Manager 타이틀로 JD와 직결.",
        "why_fit": [
            "타겟 출신 회사 #6 Crestron 직접 재직 (하이엔드 AV·자동화 제어)",
            "한국 기반 Sales Manager — 포지션 직무·근무지(서울) 일치",
            "AV·공간 자동화 B2B 영업으로 필수 자격요건(공간 자동화 B2B) 직접 부합",
        ],
        "why_not": [
            "경력 연차·인테리어/건축 네트워크 보유 여부는 공개 본문 미확인 (LinkedIn 인증벽)",
        ],
        "evidence": ["https://kr.linkedin.com/in/ashton-oh-1a211b271"],
    },
    {
        "name": "Sang-Yeong Lee (이상영)",
        "url": "https://kr.linkedin.com/in/sylee8794028/en",
        "score": 74,
        "summary": "Schneider Electric 한국 영업. 1997년부터 산업자동화/PLC 영업으로 장기 영업 경력. 타겟 출신 회사(Schneider Electric Korea) 재직.",
        "why_fit": [
            "타겟 출신 회사 #8 Schneider Electric Korea 재직",
            "20년 이상 B2B 영업 경력 — 프로젝트·솔루션 영업 경험 가능성 높음",
        ],
        "why_not": [
            "스마트홈 부문이 아닌 산업자동화/PLC 영업 중심일 수 있음 — 하이엔드 건자재·공간 자동화 적합성 확인 필요",
            "인테리어·건축 네트워크 보유 여부 미확인",
        ],
        "evidence": ["https://kr.linkedin.com/in/sylee8794028/en"],
    },
    {
        "name": "Sungyoun (Scott) Kang",
        "url": "https://kr.linkedin.com/in/sungyoun-scott-kang-1283bab1/en",
        "score": 70,
        "summary": "Schneider Electric Korea(SEK) 재직. 타겟 출신 회사 재직자로 슈나이더 스마트홈/빌딩 부문 가능성.",
        "why_fit": [
            "타겟 출신 회사 #8 Schneider Electric Korea 재직",
            "글로벌 전기·자동화 기업 한국 조직 — 솔루션 영업 인접 풀",
        ],
        "why_not": [
            "직무가 영업인지 본문 미확인 (영업/마케팅/엔지니어 구분 필요)",
            "재직 기간·스마트홈 부문 여부 미확인",
        ],
        "evidence": ["https://kr.linkedin.com/in/sungyoun-scott-kang-1283bab1/en"],
    },
    {
        "name": "Pan-Jin Kim",
        "url": "https://kr.linkedin.com/in/pan-jin-kim-00913378",
        "score": 67,
        "summary": "Schneider Electric 재직. 타겟 출신 회사 재직자 — 추가 검증 대상.",
        "why_fit": [
            "타겟 출신 회사 #8 Schneider Electric 재직",
        ],
        "why_not": [
            "직무(영업 여부)·한국 근무·스마트홈 부문 모두 본문 미확인",
        ],
        "evidence": ["https://kr.linkedin.com/in/pan-jin-kim-00913378"],
    },
    {
        "name": "정상훈 (Sanghoon Jung)",
        "url": "https://kr.linkedin.com/in/%EC%83%81%ED%9B%88-%EC%A0%95-037161177",
        "score": 66,
        "summary": "서울 기반. KNX/DALI/조명제어/AV/스마트홈 영업 검색에서 노출된 프로필 — 우대 자격요건(프로토콜·스마트홈) 도메인 신호 보유.",
        "why_fit": [
            "KNX/DALI/조명제어/AV/스마트홈 도메인 영업 신호 (우대 자격요건 부합 가능)",
            "서울 기반",
        ],
        "why_not": [
            "현재 회사·직무·경력 연차 본문 미확인 — 우선 검증 필요",
        ],
        "evidence": ["https://kr.linkedin.com/in/%EC%83%81%ED%9B%88-%EC%A0%95-037161177"],
    },
]

# Korean smart-home/AV integrator leads (companies, not individuals) for the
# next sourcing round — official dealer/integrator sales staff are prime targets.
COMPANY_LEADS = [
    "digital21 (스마트홈 전문) — https://kr.linkedin.com/company/digital21-smart-home-specialists-inc",
    "(주)스마트코어 — https://kr.linkedin.com/company/smartcoreinc",
]


def load_webhook() -> str:
    for line in Path(".env.local").read_text().splitlines():
        if line.startswith("VALUEHIRE_SEARCH_LIST_DISCORD_WEBHOOK_URL="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("webhook not configured")


def bullets(items: list[str], empty: str) -> str:
    return "\n".join(f"- {i}" for i in items) if items else f"- {empty}"


def briefing(c: dict) -> str:
    return (
        "[Multisearch 후보 브리핑]\n"
        f"포지션: {POSITION_TITLE}\n"
        f"대상 포지션 ID: {POSITION_ID}\n"
        f"후보: {c['name']}\n"
        f"Profile URL: {c['url']}\n"
        f"점수: {c['score']}/100\n"
        "후보자 요약:\n"
        f"{c['summary']}\n\n"
        "잘 맞는 이유:\n"
        f"{bullets(c['why_fit'], '적합 사유 없음')}\n\n"
        "리스크/확인 필요:\n"
        f"{bullets(c['why_not'], '뚜렷한 불일치 없음')}\n\n"
        "근거:\n"
        f"{bullets(c['evidence'], '근거 없음')}"
    )


def post(webhook: str, content: str) -> int:
    data = json.dumps({"content": content}).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Valuehire-Multisearch/1.0 (+https://valueconnect.kr)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:400]
        print(f"  HTTP {e.code} body: {body}")
        raise


def main() -> None:
    dry = "--send" not in sys.argv
    webhook = load_webhook()

    header = (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "[AI Multisearch 결과] 모건 스페이스(Moorgen Space) — Sales Manager\n"
        f"포지션 ID: {POSITION_ID}\n"
        f"롱리스트: {len(CANDIDATES)}명 (공개 LinkedIn 프로필 기반, Profile URL 포함)\n"
        "출신 타겟: Crestron / Schneider Electric Korea / KNX·DALI·AV 스마트홈 영업\n"
        "주의: LinkedIn 인증벽으로 본문 직접 검증 불가 — 미확인 항목은 각 카드 리스크에 명시\n"
        "다음 라운드 딜러/통합사 리드:\n"
        + bullets(COMPANY_LEADS, "없음")
        + "\n━━━━━━━━━━━━━━━━━━━━"
    )

    messages = [header] + [briefing(c) for c in CANDIDATES]

    if dry:
        print("=== DRY RUN (use --send to post) ===\n")
        for m in messages:
            print(m)
            print("\n----------\n")
        print(f"total messages: {len(messages)}")
        return

    for i, m in enumerate(messages):
        status = post(webhook, m)
        print(f"sent {i+1}/{len(messages)} status={status}")
        time.sleep(1.2)  # gentle pacing for Discord rate limit


if __name__ == "__main__":
    main()
