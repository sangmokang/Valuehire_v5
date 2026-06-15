#!/usr/bin/env python3
"""Score LinkedIn cards for the Moorgen Space Sales Manager position.

Sales-adjusted rubric (not the AI-engineer default). Public-evidence only.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

CARDS = json.load(open("artifacts/moorgen_linkedin_cards.json"))

KOREA = ("South Korea", "대한민국", "Seoul", "서울", ", Korea")
TARGET_COMPANIES = [
    "Crestron", "Lutron", "Control4", "Control 4", "Savant", "JUNG", "Jung ",
    "Legrand", "Somfy", "Schneider", "Signify", "Philips Lighting",
    "Bang & Olufsen", "Bang &", "KNX", "Vega Global", "AVI-SPL", "Snom",
    "Lutron", "Loxone", "Bticino",
]
SMARTHOME = ("Smart Home", "smart home", "스마트홈", "Home Automation", "home automation",
             "AV ", " AV", "KNX", "DALI", "Lighting Control", "lighting control",
             "조명", "홈오토메이션", "Crestron", "Lutron", "Integrated", "IoT")
SALES = ("Sales", "sales", "영업", "Business Development", "BD ", "Account",
         "Account Executive", "Account Manager", "Commercial", "GTM", "Channel",
         "Partner", "Distribution", "총판", "대리점")
SENIOR = ("Manager", "Director", "Lead", "Head", "Chief", "VP", "본부장", "팀장", "이사", "상무", "부장", "차장")
EXCLUDE_ROLE = ("Engineer", "Technician", "Developer", "Programmer", "Installer",
                "Architect", "Designer", "Intern", "Student", "엔지니어", "개발")


def field_lines(row: str) -> dict:
    lines = [l.strip() for l in row.split("\n") if l.strip()]
    headline = ""
    location = ""
    current = ""
    for l in lines[1:]:  # skip name
        if not headline and ("·" not in l or "degree" not in l) and "degree connection" not in l and l not in ("2nd", "3rd", "1st"):
            if not re.match(r"^·\s*\d", l) and "degree" not in l:
                headline = l
                break
    for l in lines:
        if any(k in l for k in KOREA) and ("," in l or "Korea" in l):
            location = l
            break
    for l in lines:
        if re.search(r" at .+·.+(Present|\d{4})", l) or "Present" in l:
            current = l
            break
    return {"headline": headline, "location": location, "current": current}


def score(card: dict) -> dict:
    row = card.get("row_text", "")
    f = field_lines(row)
    s = 0
    reasons = []
    risks = []

    is_korea = any(k in row for k in KOREA)
    if is_korea:
        s += 20; reasons.append("한국(서울/대한민국) 기반")
    else:
        risks.append("한국 기반 아님 — 서울 근무 포지션과 불일치")

    hit_co = [c for c in TARGET_COMPANIES if c in row]
    if hit_co:
        s += 25; reasons.append("타겟/인접사 신호: " + ", ".join(sorted(set(hit_co))[:4]))
    else:
        risks.append("명시 타겟사 신호 없음(본문 추가확인)")

    if any(k in row for k in SALES):
        s += 25; reasons.append("영업/BD/Account 직무 신호")
    else:
        risks.append("영업 직무 신호 약함 — 직무 확인 필요")

    if any(k in row for k in SMARTHOME):
        s += 15; reasons.append("스마트홈/AV/조명제어/KNX 도메인")

    if "Open to work" in row or "Open to Work" in row:
        s += 10; reasons.append("Open to work")

    if any(k in (f["headline"] + f["current"]) for k in SENIOR):
        s += 5; reasons.append("선임~책임/매니저급 시니어리티")

    # engineer/technician-only penalty (role is sales, not technical)
    head = f["headline"]
    if any(k in head for k in EXCLUDE_ROLE) and not any(k in head for k in SALES):
        s -= 12; risks.append("엔지니어/기술직 중심 헤드라인 — 영업 적합성 낮을 수 있음")

    return {
        "name": card.get("name", "").strip(),
        "profile_url": card.get("profile_url", ""),
        "headline": f["headline"],
        "location": f["location"],
        "current": f["current"],
        "score": s,
        "reasons": reasons,
        "risks": risks,
        "keyword": card.get("keyword", ""),
        "is_korea": is_korea,
    }


scored = [score(c) for c in CARDS]
# Korea-based first (role is Seoul), then score
scored.sort(key=lambda x: (x["is_korea"], x["score"]), reverse=True)

Path("artifacts/moorgen_scored.json").write_text(json.dumps(scored, ensure_ascii=False, indent=2))

korea = [c for c in scored if c["is_korea"]]
print(f"total={len(scored)} korea={len(korea)}")
print("\n=== TOP 25 (Korea-based, by score) ===")
for i, c in enumerate(korea[:25], 1):
    print(f"{i:2}. [{c['score']:>3}] {c['name']}  | {c['headline'][:70]}")
    print(f"     {c['location'][:60]}  | {c['profile_url']}")
