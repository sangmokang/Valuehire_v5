from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal

from .models import CandidateResultCard, Channel
from .portal_ops import (
    DEFAULT_PACING_POLICIES,
    DiscordWebhookNotifier,
    ReauthEvent,
    ReauthEventStore,
    SitePacingPolicy,
    utc_now_ops,
)
from .portal_recovery import AutoRelogin, PortalCredentialProvider, RecoveryDecision, recover_after_reauth
from .portal_snapshot import (
    OpenSslSessionEncryptor,
    SessionSnapshotStore,
    SnapshotKind,
    SnapshotValidator,
    capture_validated_snapshot,
)
from .portal_worker import PortalSearchAttempt, ReadyCheck

RuntimeSearchStatus = Literal["searched", "not_ready", "selector_missing", "error", "pacing_blocked"]
SleepFn = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class GuardedSearchResult:
    site: Channel
    worker_id: str
    keyword: str
    status: RuntimeSearchStatus
    reason: str
    attempt: PortalSearchAttempt | None = None
    reauth_cause: str = ""
    recovery_decision: RecoveryDecision | None = None
    snapshot_captured: bool = False
    snapshot_kind: SnapshotKind | None = None
    retried_after_recovery: bool = False
    pause_site: bool = False
    skipped_due_to_cap: bool = False
    pacing_delay_seconds: float = 0.0
    candidate_cards: tuple[CandidateResultCard, ...] = ()


class GuardedPortalSearchRunner:
    """Compose search, pacing, snapshot capture, and reauth recovery without heartbeats."""

    def __init__(
        self,
        *,
        worker: Any,
        encryptor: OpenSslSessionEncryptor,
        snapshot_store: SessionSnapshotStore,
        event_store: ReauthEventStore,
        snapshot_validator: SnapshotValidator,
        ready_check: ReadyCheck | None = None,
        credential_provider: PortalCredentialProvider | None = None,
        auto_relogin: AutoRelogin | None = None,
        discord_notifier: DiscordWebhookNotifier | None = None,
        pacing_policies: Mapping[Channel, SitePacingPolicy] | None = None,
        rng: random.Random | None = None,
        sleep: SleepFn | None = asyncio.sleep,
    ) -> None:
        self.worker = worker
        self.encryptor = encryptor
        self.snapshot_store = snapshot_store
        self.event_store = event_store
        self.snapshot_validator = snapshot_validator
        self.ready_check = ready_check
        self.credential_provider = credential_provider
        self.auto_relogin = auto_relogin
        self.discord_notifier = discord_notifier
        self.pacing_policies = pacing_policies or DEFAULT_PACING_POLICIES
        self.rng = rng
        self.sleep = sleep

    async def run_keyword_search(
        self,
        keyword: str,
        *,
        searches_today: int,
        reauth_cause_override: str = "",
    ) -> GuardedSearchResult:
        site = self.worker.config.channel
        worker_id = self.worker.config.worker_id
        pacing_delay_seconds = await self._apply_pacing(site, searches_today)
        if pacing_delay_seconds < 0:
            return GuardedSearchResult(
                site=site,
                worker_id=worker_id,
                keyword=keyword,
                status="pacing_blocked",
                reason="daily protected-portal search cap reached",
                skipped_due_to_cap=True,
            )

        attempt = await self.worker.run_one_search(keyword, ready_check=self.ready_check)
        if attempt.status == "searched":
            return await self._result_after_success(
                attempt,
                pacing_delay_seconds=pacing_delay_seconds,
            )
        if attempt.status != "not_ready" or not attempt.reauth_cause:
            return _result_from_attempt(attempt, pacing_delay_seconds=pacing_delay_seconds)
        if reauth_cause_override:
            attempt = replace(attempt, reauth_cause=reauth_cause_override)

        try:
            decision = await recover_after_reauth(
                context=self.worker.context,
                attempt=attempt,
                encryptor=self.encryptor,
                snapshot_store=self.snapshot_store,
                event_store=self.event_store,
                credential_provider=self.credential_provider,
                auto_relogin=self.auto_relogin,
                discord_notifier=self.discord_notifier,
                post_recovery_ready_check=self.ready_check,
            )
        except Exception as exc:
            decision = self._decision_after_recovery_exception(attempt)
            return GuardedSearchResult(
                site=attempt.channel,
                worker_id=attempt.worker_id,
                keyword=attempt.keyword,
                status="error",
                reason=f"reauth recovery failed: {type(exc).__name__}",
                attempt=attempt,
                reauth_cause=attempt.reauth_cause,
                recovery_decision=decision,
                pause_site=decision.pause_site,
                pacing_delay_seconds=pacing_delay_seconds,
            )

        if not decision.recovered:
            return _result_from_attempt(
                attempt,
                recovery_decision=decision,
                pause_site=decision.pause_site,
                pacing_delay_seconds=pacing_delay_seconds,
            )

        retried = await self.worker.run_one_search(keyword, ready_check=self.ready_check)
        if retried.status == "searched":
            return await self._result_after_success(
                retried,
                recovery_decision=decision,
                retried_after_recovery=True,
                reauth_cause=attempt.reauth_cause,
                pacing_delay_seconds=pacing_delay_seconds,
            )
        return _result_from_attempt(
            retried,
            recovery_decision=decision,
            retried_after_recovery=True,
            reauth_cause=attempt.reauth_cause,
            pacing_delay_seconds=pacing_delay_seconds,
        )

    async def _apply_pacing(self, site: Channel, searches_today: int) -> float:
        policy = self.pacing_policies.get(site)
        if policy is None:
            return 0.0
        if not policy.can_start_search(searches_today=searches_today):
            return -1.0
        delay_seconds = policy.next_search_delay_seconds(self.rng)
        if self.sleep is not None:
            await self.sleep(delay_seconds)
        return delay_seconds

    def _decision_after_recovery_exception(self, attempt: PortalSearchAttempt) -> RecoveryDecision:
        recovered_by = "human" if attempt.channel == "linkedin_rps" else "unrecovered"
        event = ReauthEvent(
            id="unrecorded",
            site=attempt.channel,
            worker_id=attempt.worker_id,
            cause=attempt.reauth_cause or "unknown",
            recovered_by=recovered_by,
            occurred_at=utc_now_ops(),
        )
        recorded = False
        try:
            event = self.event_store.record(
                site=attempt.channel,
                worker_id=attempt.worker_id,
                cause=attempt.reauth_cause or "unknown",
                recovered_by=recovered_by,
            )
            recorded = True
        except Exception:
            recorded = False

        alert_sent = False
        if attempt.channel == "linkedin_rps" and self.discord_notifier is not None:
            try:
                alert_sent = self.discord_notifier.send_reauth_alert(event)
            except Exception:
                alert_sent = False
        return RecoveryDecision(
            recovered=False,
            recovered_by=recovered_by,
            pause_site=attempt.channel == "linkedin_rps",
            discord_alert_sent=alert_sent,
            reauth_event_recorded=recorded,
        )

    async def _result_after_success(
        self,
        attempt: PortalSearchAttempt,
        *,
        recovery_decision: RecoveryDecision | None = None,
        retried_after_recovery: bool = False,
        reauth_cause: str = "",
        pacing_delay_seconds: float,
    ) -> GuardedSearchResult:
        try:
            snapshot = await capture_validated_snapshot(
                context=self.worker.context,
                site=attempt.channel,
                worker_id=attempt.worker_id,
                encryptor=self.encryptor,
                store=self.snapshot_store,
                validator=self.snapshot_validator,
            )
        except Exception as exc:
            return GuardedSearchResult(
                site=attempt.channel,
                worker_id=attempt.worker_id,
                keyword=attempt.keyword,
                status="error",
                reason=f"snapshot capture failed: {type(exc).__name__}",
                attempt=attempt,
                reauth_cause=reauth_cause,
                recovery_decision=recovery_decision,
                retried_after_recovery=retried_after_recovery,
                pacing_delay_seconds=pacing_delay_seconds,
                candidate_cards=attempt.candidate_cards,
            )

        return GuardedSearchResult(
            site=attempt.channel,
            worker_id=attempt.worker_id,
            keyword=attempt.keyword,
            status="searched",
            reason=attempt.reason,
            attempt=attempt,
            reauth_cause=reauth_cause,
            recovery_decision=recovery_decision,
            snapshot_captured=snapshot is not None,
            snapshot_kind=None if snapshot is None else snapshot.kind,
            retried_after_recovery=retried_after_recovery,
            pacing_delay_seconds=pacing_delay_seconds,
            candidate_cards=attempt.candidate_cards,
        )


def _result_from_attempt(
    attempt: PortalSearchAttempt,
    *,
    recovery_decision: RecoveryDecision | None = None,
    retried_after_recovery: bool = False,
    pause_site: bool = False,
    reauth_cause: str | None = None,
    pacing_delay_seconds: float,
) -> GuardedSearchResult:
    return GuardedSearchResult(
        site=attempt.channel,
        worker_id=attempt.worker_id,
        keyword=attempt.keyword,
        status=attempt.status,
        reason=attempt.reason,
        attempt=attempt,
        reauth_cause=attempt.reauth_cause if reauth_cause is None else reauth_cause,
        recovery_decision=recovery_decision,
        retried_after_recovery=retried_after_recovery,
        pause_site=pause_site,
        pacing_delay_seconds=pacing_delay_seconds,
        candidate_cards=attempt.candidate_cards,
    )
