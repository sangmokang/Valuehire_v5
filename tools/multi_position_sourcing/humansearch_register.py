"""humansearch 결과 묶음 등록 — Discord #ai_search 1메시지 + ClickUp 댓글 1개.

⛔ URL 무결: is_valid_profile_url 통과 + score>=70 후보만(eligible_matches_for_send 동일 기준).
⛔ 알람 폭탄 금지: Discord 는 합격자 전원을 *한 메시지*로, ClickUp 은 *댓글 1개*로 묶는다.
발송(제안/메일)이 아니라 '후보 브리핑' 등록이다(SOT3 안전).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.multi_position_sourcing.humansearch import PASS_THRESHOLD, is_valid_profile_url
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
    if not isinstance(url, str) or not url.strip():
        return None  # 신원(URL) 결손 → fail-closed
    visible_text = str(result.get("visible_text", "") or "")
    summary = str(result.get("summary", "") or "")
    headline = str(result.get("headline", "") or "")
    # 프리랜서 마커를 볼 텍스트원(본문·요약·헤드라인)이 하나도 없으면 판정 불가 → fail-closed(제외).
    if not (visible_text + summary + headline).strip():
        return None
    return CapturedProfile(
        profile_url=url,
        source_channel=channel,
        visible_text=visible_text,
        summary=summary,
        # headline 도 하드제외 텍스트 스캔 대상 — CapturedProfile 여분 텍스트 슬롯(ocr_text)에 실어
        # 프리랜서 표기가 headline 에만 있는 후보도 매처가 보게 한다(fail-open 차단).
        ocr_text=headline,
        captured_at=str(result.get("captured_at", "") or ""),
        education=str(result.get("education", "") or ""),
        skills=tuple(result.get("skills") or ()),
        employment_history=_reconstruct_tenures(result.get("employment_history", ())),
    )


def eligible(results: list[dict]) -> list[dict]:
    ok = [r for r in results if r["score"] >= PASS_THRESHOLD and is_valid_profile_url(r["url"])]
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
    passers = eligible(results)
    print(f"eligible passers: {len(passers)}")
    for r in passers:
        print(" ", r["score"], r["name"], r["url"])
    if "--send" in sys.argv:
        status = post_discord(build_message(passers))
        print("discord status:", status)
        # ClickUp 댓글 본문은 stdout 으로 — 호출자가 MCP 로 1개 등록
        Path("/tmp/clickup_comment_body.txt").write_text(clickup_comment_body(passers))
        print("clickup comment body -> /tmp/clickup_comment_body.txt")
