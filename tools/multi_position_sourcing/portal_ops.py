from __future__ import annotations

import json
import random
import re
import urllib.error
import urllib.request
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Protocol
from urllib.parse import quote

from .models import Channel
from .portal_snapshot import SupabaseRestConfig

RecoveredBy = Literal["snapshot_reinject", "auto_relogin", "human", "unrecovered"]
ReauthWeeklyKey = tuple[Channel, str, str, RecoveredBy]
PROTECTED_REAUTH_SITES = frozenset({"saramin", "jobkorea", "linkedin_rps"})
RECOVERED_BY_VALUES = frozenset({"snapshot_reinject", "auto_relogin", "human", "unrecovered"})
ALLOWED_REAUTH_CAUSES = frozenset(
    {
        "profile_corrupt",
        "cookie_rotated",
        "forced_logout",
        "login_redirect",
        "login_marker_missing",
        "login_marker_lost",
        "unknown",
    }
)
HTTP_REAUTH_CAUSE_RE = re.compile(r"^http_(401|403)$")


@dataclass(frozen=True)
class ReauthEvent:
    id: str
    site: Channel
    worker_id: str
    cause: str
    recovered_by: RecoveredBy
    occurred_at: str


def is_allowed_reauth_cause(cause: str) -> bool:
    return cause in ALLOWED_REAUTH_CAUSES or bool(HTTP_REAUTH_CAUSE_RE.fullmatch(cause))


def validate_reauth_event_policy(site: Channel, cause: str, recovered_by: RecoveredBy) -> None:
    # SOT invariant (docs/search-access.md): LinkedIn RPS auto-logs in like the other
    # portals, so linkedin_rps/auto_relogin reauth events are valid and recordable.
    if not is_allowed_reauth_cause(cause):
        raise ValueError("unsupported reauth event cause")


class InMemoryReauthEventStore:
    def __init__(self) -> None:
        self.events: list[ReauthEvent] = []

    def record(
        self,
        *,
        site: Channel,
        worker_id: str,
        cause: str,
        recovered_by: RecoveredBy,
        occurred_at: str | None = None,
    ) -> ReauthEvent:
        validate_reauth_event_policy(site, cause, recovered_by)
        event = ReauthEvent(
            id=str(uuid.uuid4()),
            site=site,
            worker_id=worker_id,
            cause=cause,
            recovered_by=recovered_by,
            occurred_at=occurred_at or utc_now_ops(),
        )
        self.events.append(event)
        return event

    def weekly_counts(self, *, week_start: str) -> dict[ReauthWeeklyKey, int]:
        start = parse_utc(week_start)
        end = start + timedelta(days=7)
        counts: Counter[ReauthWeeklyKey] = Counter()
        for event in self.events:
            occurred_at = parse_utc(event.occurred_at)
            if start <= occurred_at < end:
                counts[(event.site, event.worker_id, event.cause, event.recovered_by)] += 1
        return dict(counts)


class ReauthEventStore(Protocol):
    def record(
        self,
        *,
        site: Channel,
        worker_id: str,
        cause: str,
        recovered_by: RecoveredBy,
        occurred_at: str | None = None,
    ) -> ReauthEvent:
        ...


class SupabaseReauthEventStore:
    def __init__(self, config: SupabaseRestConfig, *, urlopen: Any = urllib.request.urlopen) -> None:
        self.config = config
        self.urlopen = urlopen

    def record(
        self,
        *,
        site: Channel,
        worker_id: str,
        cause: str,
        recovered_by: RecoveredBy,
        occurred_at: str | None = None,
    ) -> ReauthEvent:
        validate_reauth_event_policy(site, cause, recovered_by)
        event = ReauthEvent(
            id=str(uuid.uuid4()),
            site=site,
            worker_id=worker_id,
            cause=cause,
            recovered_by=recovered_by,
            occurred_at=occurred_at or utc_now_ops(),
        )
        payload = {
            "id": event.id,
            "site": event.site,
            "worker_id": event.worker_id,
            "cause": event.cause,
            "recovered_by": event.recovered_by,
            "occurred_at": event.occurred_at,
        }
        rows = self._request_json(
            "POST",
            f"{self.config.rest_url}/reauth_events",
            payload,
            prefer="return=representation",
        )
        if rows and isinstance(rows[0], dict):
            returned = _reauth_event_from_row(rows[0])
            if returned is not None:
                return returned
        return event

    def weekly_counts(self, *, week_start: str) -> dict[ReauthWeeklyKey, int]:
        start = parse_utc(week_start)
        try:
            rows = self._request_json(
                "POST",
                f"{self.config.rest_url}/rpc/reauth_weekly_counts",
                {"week_start_arg": start.isoformat()},
            )
            return _weekly_counts_from_aggregate_rows(rows)
        except RuntimeError as exc:
            if "failed with status 404" not in str(exc):
                raise
            # Keep old deployments observable while the aggregate RPC migration
            # is being applied. The preferred path is the RPC above.
            return self._weekly_counts_via_reauth_events_table(start)

    def _weekly_counts_via_reauth_events_table(self, start: datetime) -> dict[ReauthWeeklyKey, int]:
        end = start + timedelta(days=7)
        params = (
            "select=site,worker_id,cause,recovered_by"
            f"&occurred_at=gte.{quote(start.isoformat(), safe='')}"
            f"&occurred_at=lt.{quote(end.isoformat(), safe='')}"
        )
        rows = self._request_json("GET", f"{self.config.rest_url}/reauth_events?{params}", None)
        return _weekly_counts_from_event_rows(rows)

    def _request_json(
        self,
        method: str,
        url: str,
        payload: dict[str, object] | None,
        *,
        prefer: str = "",
    ) -> list[object]:
        headers = self.config.headers()
        if prefer:
            headers["Prefer"] = prefer
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with self.urlopen(request, timeout=self.config.timeout_seconds) as response:
                status = int(getattr(response, "status", 0) or 0)
                raw = response.read()
        except urllib.error.HTTPError as exc:
            exc.close()
            raise RuntimeError(f"Supabase reauth_events {method} failed with status {exc.code}") from exc
        except Exception as exc:
            raise RuntimeError(f"Supabase reauth_events {method} request failed") from exc
        if status < 200 or status >= 300:
            raise RuntimeError(f"Supabase reauth_events {method} failed with status {status}")
        if not raw:
            return []
        decoded = json.loads(raw.decode("utf-8"))
        if isinstance(decoded, list):
            return decoded
        if isinstance(decoded, dict):
            return [decoded]
        return []


def _weekly_counts_from_event_rows(rows: list[object]) -> dict[ReauthWeeklyKey, int]:
    counts: Counter[ReauthWeeklyKey] = Counter()
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = _weekly_key_from_row(row)
        if key is None:
            continue
        counts[key] += 1
    return dict(counts)


def _weekly_counts_from_aggregate_rows(rows: list[object]) -> dict[ReauthWeeklyKey, int]:
    counts: dict[ReauthWeeklyKey, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = _weekly_key_from_row(row)
        if key is None:
            continue
        count = _positive_weekly_count(row.get("count"))
        if count is None:
            continue
        counts[key] = counts.get(key, 0) + count
    return counts


def _weekly_key_from_row(row: dict[str, object]) -> ReauthWeeklyKey | None:
    try:
        site = row["site"]
        worker_id = row["worker_id"]
        cause = row["cause"]
        recovered_by = row["recovered_by"]
    except KeyError:
        return None
    if not all(isinstance(value, str) for value in (site, worker_id, cause, recovered_by)):
        return None
    if (
        site not in PROTECTED_REAUTH_SITES
        or not worker_id
        or not is_allowed_reauth_cause(cause)
        or recovered_by not in RECOVERED_BY_VALUES
    ):
        return None
    # SOT invariant: linkedin_rps/auto_relogin is an allowed, recordable reauth outcome.
    return (site, worker_id, cause, recovered_by)  # type: ignore[return-value]


def _positive_weekly_count(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        count = value
    elif isinstance(value, str):
        try:
            count = int(value)
        except ValueError:
            return None
    else:
        return None
    return count if count > 0 else None


def _reauth_event_from_row(row: dict[str, object]) -> ReauthEvent | None:
    try:
        event_id = row["id"]
        site = row["site"]
        worker_id = row["worker_id"]
        cause = row["cause"]
        recovered_by = row["recovered_by"]
        occurred_at = row["occurred_at"]
    except KeyError:
        return None
    if not all(isinstance(value, str) and value for value in (event_id, site, worker_id, cause, recovered_by, occurred_at)):
        return None
    if site not in PROTECTED_REAUTH_SITES or recovered_by not in RECOVERED_BY_VALUES:
        return None
    try:
        validate_reauth_event_policy(site, cause, recovered_by)  # type: ignore[arg-type]
    except ValueError:
        return None
    return ReauthEvent(
        id=event_id,
        site=site,  # type: ignore[arg-type]
        worker_id=worker_id,
        cause=cause,
        recovered_by=recovered_by,  # type: ignore[arg-type]
        occurred_at=occurred_at,
    )


@dataclass(frozen=True)
class DiscordWebhookNotifier:
    webhook_url: str
    timeout_seconds: int = 10
    urlopen: Any = urllib.request.urlopen

    def send_reauth_alert(self, event: ReauthEvent) -> bool:
        if not self.webhook_url:
            return False
        payload = {
            "content": (
                f"[Valuehire] {event.site} session reauth required "
                f"(worker={event.worker_id}, cause={event.cause}, recovered_by={event.recovered_by})"
            )
        }
        request = urllib.request.Request(
            self.webhook_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.urlopen(request, timeout=self.timeout_seconds) as response:
            status = int(getattr(response, "status", 0) or 0)
        return 200 <= status < 300


@dataclass(frozen=True)
class SitePacingPolicy:
    site: Channel
    min_search_delay_seconds: int
    max_search_delay_seconds: int
    min_page_delay_seconds: int
    max_page_delay_seconds: int
    daily_search_cap: int

    def can_start_search(self, *, searches_today: int) -> bool:
        return searches_today < self.daily_search_cap

    def next_search_delay_seconds(self, rng: random.Random | None = None) -> float:
        return _uniform_delay(self.min_search_delay_seconds, self.max_search_delay_seconds, rng)

    def next_page_delay_seconds(self, rng: random.Random | None = None) -> float:
        return _uniform_delay(self.min_page_delay_seconds, self.max_page_delay_seconds, rng)


DEFAULT_PACING_POLICIES: dict[Channel, SitePacingPolicy] = {
    "saramin": SitePacingPolicy("saramin", 45, 140, 8, 30, 120),
    "jobkorea": SitePacingPolicy("jobkorea", 45, 140, 8, 30, 120),
    "linkedin_rps": SitePacingPolicy("linkedin_rps", 120, 420, 25, 90, 40),
    "public_web": SitePacingPolicy("public_web", 20, 90, 5, 20, 200),
}


def _uniform_delay(min_seconds: int, max_seconds: int, rng: random.Random | None = None) -> float:
    if min_seconds <= 0 or max_seconds < min_seconds:
        raise ValueError("invalid pacing delay range")
    generator = rng or random.SystemRandom()
    return generator.uniform(min_seconds, max_seconds)


def utc_now_ops() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
