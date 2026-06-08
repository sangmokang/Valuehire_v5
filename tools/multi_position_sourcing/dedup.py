from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse, urlunparse


@dataclass(frozen=True)
class SeenProfile:
    canonical_url: str
    captured_at: str


def canonical_profile_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    path = re.sub(r"/+", "/", parsed.path).rstrip("/")

    if "linkedin.com" in host:
        match = re.search(r"/(?:talent/profile|in)/([^/?#]+)", path, re.IGNORECASE)
        if match:
            prefix = "/talent/profile" if "/talent/profile/" in path.lower() else "/in"
            return f"https://www.linkedin.com{prefix}/{match.group(1).lower()}"

    if "saramin.co.kr" in host:
        qs = parse_qs(parsed.query)
        profile_id = qs.get("rec_idx") or qs.get("person_id") or qs.get("resume_idx")
        if profile_id:
            return f"https://www.saramin.co.kr/profile/{profile_id[0]}"

    if "jobkorea.co.kr" in host:
        qs = parse_qs(parsed.query)
        profile_id = qs.get("M_ID") or qs.get("ResumeNo") or qs.get("resumeNo")
        if profile_id:
            return f"https://www.jobkorea.co.kr/profile/{profile_id[0]}"

    return urlunparse(("https", host, path, "", "", ""))


def _parse_iso(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def seen_within_ttl(
    url: str,
    seen_profiles: tuple[SeenProfile, ...] | list[SeenProfile],
    now_iso: str,
    ttl_hours: int,
) -> bool:
    canonical = canonical_profile_url(url)
    now = _parse_iso(now_iso)
    for seen in seen_profiles:
        if seen.canonical_url == canonical:
            age_hours = (now - _parse_iso(seen.captured_at)).total_seconds() / 3600
            return age_hours <= ttl_hours
    return False

