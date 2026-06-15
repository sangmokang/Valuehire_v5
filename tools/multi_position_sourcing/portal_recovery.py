from __future__ import annotations

import asyncio
import base64
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from .models import Channel
from .portal_ops import DiscordWebhookNotifier, ReauthEvent, ReauthEventStore, RecoveredBy, utc_now_ops
from .portal_keychain import add_generic_password
from .portal_snapshot import OpenSslSessionEncryptor, SessionSnapshotStore
from .portal_worker import PortalSearchAttempt, ReadyCheck, _close_page_if_possible, _goto_search_surface


class PortalCredentialError(RuntimeError):
    pass


@dataclass(frozen=True)
class PortalCredentials:
    username: str
    password: str

    def __repr__(self) -> str:
        return "PortalCredentials(username=<redacted>, password=<redacted>)"


class PortalCredentialProvider(Protocol):
    def load(self, site: Channel) -> PortalCredentials:
        ...


@dataclass(frozen=True)
class MacKeychainPortalCredentialProvider:
    service: str = "valuehire.portal_credentials"

    def load(self, site: Channel) -> PortalCredentials:
        if site not in {"saramin", "jobkorea", "linkedin_rps"}:
            raise PortalCredentialError(f"automatic relogin credentials are not allowed for {site}")
        username = self._read_secret(f"{site}:username")
        password = self._read_secret(f"{site}:password")
        return PortalCredentials(username=username, password=password)

    def store(self, site: Channel, credentials: PortalCredentials) -> None:
        if site not in {"saramin", "jobkorea", "linkedin_rps"}:
            raise PortalCredentialError(f"automatic relogin credentials are not allowed for {site}")
        self._write_secret(f"{site}:username", credentials.username)
        self._write_secret(f"{site}:password", credentials.password)

    def _read_secret(self, account: str) -> str:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", self.service, "-a", account, "-w"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            raise PortalCredentialError("portal credential is missing from macOS keychain")
        try:
            return base64.b64decode(result.stdout.strip(), validate=True).decode("utf-8")
        except Exception as exc:
            raise PortalCredentialError("portal credential in macOS keychain is malformed") from exc

    def _write_secret(self, account: str, secret: str) -> None:
        encoded = base64.b64encode(secret.encode("utf-8")).decode("ascii")
        result = add_generic_password(service=self.service, account=account, password=encoded)
        if result.returncode != 0:
            raise PortalCredentialError("failed to write portal credential to macOS keychain")


AutoRelogin = Callable[[Any, Channel, PortalCredentials], Awaitable[bool]]


@dataclass(frozen=True)
class RecoveryDecision:
    recovered: bool
    recovered_by: RecoveredBy
    pause_site: bool = False
    discord_alert_sent: bool = False
    reauth_event_recorded: bool = True


async def recover_after_reauth(
    *,
    context: Any,
    attempt: PortalSearchAttempt,
    encryptor: OpenSslSessionEncryptor,
    snapshot_store: SessionSnapshotStore,
    event_store: ReauthEventStore,
    credential_provider: PortalCredentialProvider | None = None,
    auto_relogin: AutoRelogin | None = None,
    discord_notifier: DiscordWebhookNotifier | None = None,
    post_recovery_ready_check: ReadyCheck | None = None,
    max_relogin_attempts: int = 3,
    relogin_backoff_base_seconds: float = 1.0,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> RecoveryDecision:
    cause = attempt.reauth_cause or "unknown"
    if await _restore_snapshot(context, attempt, encryptor, snapshot_store, post_recovery_ready_check):
        recorded, _event = _record_reauth_event(
            event_store,
            site=attempt.channel,
            worker_id=attempt.worker_id,
            cause=cause,
            recovered_by="snapshot_reinject",
        )
        return RecoveryDecision(
            recovered=True,
            recovered_by="snapshot_reinject",
            reauth_event_recorded=recorded,
        )

    # SOT invariant: all three protected portals (Saramin / Jobkorea / LinkedIn RPS) may
    # attempt automatic credential relogin from the secret store. auto_relogin_portal never
    # bypasses a captcha / 2FA / checkpoint — it returns False on detection instead.
    if attempt.channel in {"saramin", "jobkorea", "linkedin_rps"}:
        if credential_provider is not None and auto_relogin is not None:
            sleep_fn = sleep if sleep is not None else asyncio.sleep
            attempts = max(1, max_relogin_attempts)
            try:
                credentials: PortalCredentials | None = credential_provider.load(attempt.channel)
            except Exception:
                credentials = None
            if credentials is not None:
                for attempt_index in range(attempts):
                    try:
                        # A clean True/False return is a settled outcome. False means a
                        # captcha / 2FA / checkpoint was detected (auto_relogin_portal never
                        # bypasses one) — we MUST NOT retry it, hammering a security challenge
                        # is the fastest way to get the account locked. Only a raised
                        # exception (network / timeout) is treated as transient and retried.
                        if await auto_relogin(
                            context, attempt.channel, credentials
                        ) and await _context_ready_after_recovery(
                            context,
                            attempt,
                            post_recovery_ready_check,
                        ):
                            recorded, _event = _record_reauth_event(
                                event_store,
                                site=attempt.channel,
                                worker_id=attempt.worker_id,
                                cause=cause,
                                recovered_by="auto_relogin",
                            )
                            return RecoveryDecision(
                                recovered=True,
                                recovered_by="auto_relogin",
                                reauth_event_recorded=recorded,
                            )
                        break
                    except Exception:
                        if attempt_index + 1 < attempts:
                            await sleep_fn(relogin_backoff_base_seconds * (2 ** attempt_index))
                            continue
                        break

    # saramin / jobkorea: when auto-relogin cannot recover, record a silent unrecovered
    # event — the persistent-profile queue simply retries later.
    if attempt.channel in {"saramin", "jobkorea"}:
        recorded, _event = _record_reauth_event(
            event_store,
            site=attempt.channel,
            worker_id=attempt.worker_id,
            cause=cause,
            recovered_by="unrecovered",
        )
        return RecoveryDecision(
            recovered=False,
            recovered_by="unrecovered",
            reauth_event_recorded=recorded,
        )

    # LinkedIn RPS (and any other protected channel): auto-relogin is not used, so stop
    # the site and alert a human rather than hammering the login form.
    recorded, event = _record_reauth_event(
        event_store,
        site=attempt.channel,
        worker_id=attempt.worker_id,
        cause=cause,
        recovered_by="human",
    )
    alert_sent = False
    if discord_notifier is not None:
        try:
            alert_sent = discord_notifier.send_reauth_alert(
                ReauthEvent(
                    id=event.id,
                    site=event.site,
                    worker_id=event.worker_id,
                    cause=event.cause,
                    recovered_by=event.recovered_by,
                    occurred_at=event.occurred_at,
                )
            )
        except Exception:
            alert_sent = False
    return RecoveryDecision(
        recovered=False,
        recovered_by="human",
        pause_site=True,
        discord_alert_sent=alert_sent,
        reauth_event_recorded=recorded,
    )


def _record_reauth_event(
    event_store: ReauthEventStore,
    *,
    site: Channel,
    worker_id: str,
    cause: str,
    recovered_by: RecoveredBy,
) -> tuple[bool, ReauthEvent]:
    try:
        return True, event_store.record(
            site=site,
            worker_id=worker_id,
            cause=cause,
            recovered_by=recovered_by,
        )
    except Exception:
        return False, ReauthEvent(
            id="unrecorded",
            site=site,
            worker_id=worker_id,
            cause=cause,
            recovered_by=recovered_by,
            occurred_at=utc_now_ops(),
        )


async def _restore_snapshot(
    context: Any,
    attempt: PortalSearchAttempt,
    encryptor: OpenSslSessionEncryptor,
    snapshot_store: SessionSnapshotStore,
    post_recovery_ready_check: ReadyCheck | None = None,
) -> bool:
    try:
        from .portal_snapshot import restore_latest_validated_snapshot

        restored = await restore_latest_validated_snapshot(
            context=context,
            site=attempt.channel,
            worker_id=attempt.worker_id,
            encryptor=encryptor,
            store=snapshot_store,
        )
        if not restored:
            return False
        return await _context_ready_after_recovery(context, attempt, post_recovery_ready_check)
    except Exception:
        return False


async def _context_ready_after_recovery(
    context: Any,
    attempt: PortalSearchAttempt,
    ready_check: ReadyCheck | None,
) -> bool:
    if ready_check is None:
        return False

    page = await context.new_page()
    try:
        await _goto_search_surface(page, attempt.channel, "")
        return bool(await ready_check(page))
    finally:
        await _close_page_if_possible(page)
