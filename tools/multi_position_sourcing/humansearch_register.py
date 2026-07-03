"""humansearch 결과 묶음 등록 — Discord #ai_search 1메시지 + ClickUp 댓글 1개.

⛔ URL 무결: is_valid_profile_url 통과 + score>=70 후보만(eligible_matches_for_send 동일 기준).
⛔ 알람 폭탄 금지: Discord 는 합격자 전원을 *한 메시지*로, ClickUp 은 *댓글 1개*로 묶는다.
발송(제안/메일)이 아니라 '후보 브리핑' 등록이다(SOT3 안전).
"""
from __future__ import annotations

import json
import math
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.multi_position_sourcing.humansearch import (
    PASS_THRESHOLD,
    _normalize,
    hard_exclude_reason,
    is_valid_profile_url,
)
from tools.multi_position_sourcing.models import CapturedProfile, Channel, EmploymentTenure

POSITION_ID = "86ey2cdfj"
POSITION_NAME = "[뤼튼테크놀로지스 AX CIC] AX Sales Team Lead (AI Account Executive 리드)"


def _load_env(key: str) -> str | None:
    env = Path(__file__).resolve().parents[2] / ".env.local"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip()
    return os.environ.get(key)


def _reconstruct_tenures(raw: object) -> tuple[EmploymentTenure, ...]:
    """employment_history(dict 리스트) → EmploymentTenure 튜플. start_month 없는 잡음 항목은 skip."""
    out: list[EmploymentTenure] = []
    for e in raw if isinstance(raw, (list, tuple)) else ():
        if isinstance(e, EmploymentTenure):
            out.append(e)
        elif isinstance(e, dict) and str(e.get("start_month") or "").strip():
            out.append(
                EmploymentTenure(
                    company=str(e.get("company", "") or ""),
                    start_month=str(e.get("start_month", "") or ""),
                    end_month=str(e.get("end_month", "") or ""),
                )
            )
        elif isinstance(e, (list, tuple)) and len(e) >= 2 and str(e[1] or "").strip():
            # 위치형 [company, start_month, end_month?] — 잦은이직 신호가 튜플/배열 형상으로 와도 놓치지 않음.
            out.append(
                EmploymentTenure(
                    company=str(e[0] or ""),
                    start_month=str(e[1] or ""),
                    end_month=str(e[2] or "") if len(e) > 2 else "",
                )
            )
    return tuple(out)


def reconstruct_captured_profile(result: object, channel: Channel) -> CapturedProfile | None:
    """register/results dict → 하드제외 판정용 CapturedProfile (판정 불가면 None=fail-closed).

    SOT(fail-open 금지): 신뢰성 있는 하드제외 판정에 필요한 필드가 결손되면 None 을 돌려,
    호출자(등록 게이트 C1a)가 '판정 불가 = 제외'로 처리하게 한다.
    무손실 아님 — ocr_text 등 원본 dict 에 없을 수 있어 *가용* 필드만 복원(2차검증 V2 재정의).
    models.CapturedProfile 재사용(제2 프로필 타입 금지, SOT5).
    """
    if not isinstance(result, dict):
        return None
    url = result.get("url") or result.get("profile_url")
    if not is_valid_profile_url(url):
        return None  # 신원(URL) 결손·무효(공백·제로폭·비http) → fail-closed
    visible_text = str(result.get("visible_text", "") or "")
    summary = str(result.get("summary", "") or "")
    headline = str(result.get("headline", "") or "")
    # 판정 가능한 '본문'(본문·요약·헤드라인)이 전무하거나 보이지 않는 문자·공백뿐이면 판정 불가 → fail-closed.
    # 매처와 동일 _normalize 재사용. name/why_fit 은 스캔하지 않는다 — name 은 신원 필드라 프리랜서 신호가
    # 없고(그 신호는 본문에 있어 스캔됨), name 스캔은 '외주' 등 2글자 마커의 부분문자열 오탐만 키운다(Codex 재검증 재현).
    if not _normalize(visible_text + summary + headline):
        return None
    skills = result.get("skills")
    return CapturedProfile(
        profile_url=url,
        source_channel=channel,
        visible_text=visible_text,
        summary=summary,
        # headline 은 프로필 설명 텍스트 — 매처가 스캔하도록 여분 슬롯(ocr_text)에 싣는다(headline-only 프리랜서 차단).
        ocr_text=headline,
        captured_at=str(result.get("captured_at", "") or ""),
        education=str(result.get("education", "") or ""),
        skills=tuple(skills) if isinstance(skills, (list, tuple)) else (),
        employment_history=_reconstruct_tenures(result.get("employment_history", ())),
    )


def eligible(results: list[dict], channel: Channel) -> list[dict]:
    """등록 브리핑에 내보낼 후보만 — 점수·URL 게이트 + 채점 전 하드제외(프리랜서·잦은이직·전문대).

    현행 계약(score>=PASS_THRESHOLD · 유효 URL) 유지 + PC-C1a1 재구성으로 CapturedProfile 복원 후
    PC-C0 매처(hard_exclude_reason)를 적용해 프리랜서·단기이직2회+·전문대(portal 채널)를 등록 전에 차단한다.
    재구성 불가(결손 dict)는 fail-closed(제외). 학교컷은 PORTAL_SCHOOL_CUT_CHANNELS 채널만(매처가 판단). SOT5·SOT3.
    channel 은 필수 — 기본값을 두면 잘못된 채널로 school-cut 이 조용히 우회되므로 호출자가 명시한다.
    """
    ok: list[dict] = []
    for r in results:
        if not isinstance(r, dict):
            continue  # 비dict 항목 → fail-closed skip(크래시 방지)
        score = r.get("score", 0)
        # NaN/inf 는 '<threshold' 를 통과(NaN 비교 False, inf>=t True) → 유한 수치 + 양수형(>=)으로 판정.
        if not (isinstance(score, (int, float)) and math.isfinite(score) and score >= PASS_THRESHOLD):
            continue  # 점수 미달·비수치·NaN·inf → 제외 (fail-closed)
        # register 스키마 URL 키는 'url'. 하류(build_message·clickup) 도 r['url'] 을 읽으므로 여기서 'url' 로 통일한다.
        if not is_valid_profile_url(r.get("url")):
            continue  # URL 무효/결손 → 제외
        profile = reconstruct_captured_profile(r, channel)
        if profile is None:
            continue  # 재구성 불가(결손) → fail-closed 제외
        if hard_exclude_reason(profile, channel) is not None:
            continue  # 프리랜서·잦은이직·전문대(portal) → 채점 전 하드제외
        ok.append(r)
    return sorted(ok, key=lambda r: -r["score"])


def _school(education: str) -> str:
    """학력 원문에서 학교명만 — 'Degree details' 앞부분(부분일치 잡음 제거)."""
    head = (education or "").split("Degree details")[0]
    return head.strip()[:34] or "-"


def build_message(passers: list[dict]) -> str:
    head = (
        f"📋 **AI Search 후보 브리핑 — {POSITION_NAME}**\n"
        f"채널: LinkedIn Recruiter(RPS) · 합격선 {PASS_THRESHOLD}점 · 합격 {len(passers)}명\n"
        f"(채점: 학력30·직무50·논리10·이직안정10 / 🟢=Open to work)\n"
        "──────────────"
    )
    blocks = []
    for i, r in enumerate(passers, 1):
        b = r.get("breakdown", {})
        otw = " 🟢" if r.get("otw") else ""
        note = ""
        if "berkeley college" in (r.get("education", "").lower()):
            note = " ⚠️('Berkeley College'=명문대 오탐, 학력 재판단 요)"
        blocks.append(
            f"**{i}. {r['name']} — {r['score']}/100**{otw} · {_school(r.get('education',''))}{note}\n"
            f"  학력{b.get('education','?')}/직무{b.get('role_fit','?')}/논리{b.get('profile_logic','?')}/안정{b.get('job_stability','?')}\n"
            f"  {r['url']}"
        )
    return head + "\n" + "\n".join(blocks)


def post_discord(message: str) -> int:
    url = _load_env("VALUEHIRE_SEARCH_LIST_DISCORD_WEBHOOK_URL")
    if not url:
        raise RuntimeError("VALUEHIRE_SEARCH_LIST_DISCORD_WEBHOOK_URL 없음")
    # Discord 2000자 제한 — 넘으면 잘라 1메시지 유지(알람 폭탄 금지 우선).
    payload = json.dumps({"content": message[:1990], "flags": 4}).encode()
    # Discord 는 Cloudflare 뒤 — 기본 python-urllib UA 는 403. 브라우저 UA 로 우회.
    req = urllib.request.Request(url, data=payload, method="POST", headers={
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status


def clickup_comment_body(passers: list[dict]) -> str:
    lines = [f"🔎 **AI Search 결과 — LinkedIn RPS · 합격 {len(passers)}명** (합격선 {PASS_THRESHOLD}점, 🟢=Open to work)",
             "_채점: 학력30·직무50·논리10·이직안정10_", ""]
    for i, r in enumerate(passers, 1):
        b = r.get("breakdown", {})
        otw = " 🟢" if r.get("otw") else ""
        note = " ⚠️('Berkeley College'=명문대 오탐, 학력 재판단)" if "berkeley college" in (r.get("education","").lower()) else ""
        lines.append(f"{i}. **{r['name']}** ({r['score']}/100){otw} · {_school(r.get('education',''))}{note}")
        lines.append(f"   학력{b.get('education','?')}/직무{b.get('role_fit','?')}/논리{b.get('profile_logic','?')}/안정{b.get('job_stability','?')} · [프로필 열기]({r['url']})")
    return "\n".join(lines)


if __name__ == "__main__":
    results_path = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path.home() / ".vh-search-results" / "linkedin_rps")
    results = json.loads(Path(results_path).read_text())
    passers = eligible(results, "linkedin_rps")  # 이 러너 경로는 LinkedIn RPS 포지션(학교컷 미적용 채널)
    print(f"eligible passers: {len(passers)}")
    for r in passers:
        print(" ", r["score"], r["name"], r["url"])
    if "--send" in sys.argv:
        status = post_discord(build_message(passers))
        print("discord status:", status)
        # ClickUp 댓글 본문은 stdout 으로 — 호출자가 MCP 로 1개 등록
        Path("/tmp/clickup_comment_body.txt").write_text(clickup_comment_body(passers))
        print("clickup comment body -> /tmp/clickup_comment_body.txt")
