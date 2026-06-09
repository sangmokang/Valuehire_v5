from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Literal, Protocol

from .models import Channel
from .portal_keychain import add_generic_password
from .portal_worker import _close_page_if_possible, _goto_search_surface

SnapshotKind = Literal["current", "last_known_good"]
SnapshotValidator = Callable[[Mapping[str, object]], bool | Awaitable[bool]]

PAYLOAD_VERSION = b"VHSS1"
TAG_BYTES = 32
PORTAL_STORAGE_DOMAINS: dict[Channel, tuple[str, ...]] = {
    "saramin": ("saramin.co.kr",),
    "jobkorea": ("jobkorea.co.kr",),
    "linkedin_rps": ("linkedin.com",),
}


class SessionEncryptionError(RuntimeError):
    pass


class SnapshotValidationError(RuntimeError):
    pass


class SupabaseSessionStoreError(RuntimeError):
    pass


class SessionKeyProvider(Protocol):
    def get_key(self) -> bytes:
        ...


@dataclass(frozen=True)
class StaticSessionKeyProvider:
    key: bytes

    def get_key(self) -> bytes:
        return self.key


@dataclass(frozen=True)
class MacKeychainSessionKeyProvider:
    service: str = "valuehire.session_state"
    account: str = "session_state_v2"
    create_if_missing: bool = True

    def get_key(self) -> bytes:
        found = subprocess.run(
            ["security", "find-generic-password", "-s", self.service, "-a", self.account, "-w"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if found.returncode == 0:
            return _decode_keychain_key(found.stdout.strip())
        if not self.create_if_missing:
            raise SessionEncryptionError("macOS keychain session key is missing")

        key = secrets.token_bytes(32)
        encoded = base64.b64encode(key).decode("ascii")
        created = add_generic_password(service=self.service, account=self.account, password=encoded)
        if created.returncode != 0:
            raise SessionEncryptionError("failed to create macOS keychain session key")
        return key


def _decode_keychain_key(value: bytes) -> bytes:
    try:
        key = base64.b64decode(value, validate=True)
    except Exception as exc:
        raise SessionEncryptionError("macOS keychain session key is malformed") from exc
    if len(key) < 32:
        raise SessionEncryptionError("macOS keychain session key is too short")
    return key


def _derive_key(master_key: bytes, purpose: bytes) -> bytes:
    if len(master_key) < 32:
        raise SessionEncryptionError("session encryption key is too short")
    return hmac.new(master_key, purpose, hashlib.sha256).digest()


def _run_openssl_enc(
    *,
    openssl_bin: str,
    passphrase: bytes,
    data: bytes,
    decrypt: bool,
) -> bytes:
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, passphrase + b"\n")
        os.close(write_fd)
        write_fd = -1
        command = [
            openssl_bin,
            "enc",
            "-aes-256-ctr",
            "-pbkdf2",
            "-md",
            "sha256",
            "-pass",
            f"fd:{read_fd}",
        ]
        if decrypt:
            command.append("-d")
        else:
            command.append("-salt")
        result = subprocess.run(
            command,
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=(read_fd,),
            check=False,
        )
    finally:
        if write_fd >= 0:
            os.close(write_fd)
        os.close(read_fd)
    if result.returncode != 0:
        raise SessionEncryptionError("OpenSSL session encryption operation failed")
    return result.stdout


@dataclass(frozen=True)
class OpenSslSessionEncryptor:
    key_provider: SessionKeyProvider
    openssl_bin: str = "openssl"

    def encrypt(self, plaintext: bytes) -> bytes:
        master_key = self.key_provider.get_key()
        enc_key = _derive_key(master_key, b"valuehire-session-state-encryption")
        mac_key = _derive_key(master_key, b"valuehire-session-state-authentication")
        ciphertext = _run_openssl_enc(
            openssl_bin=self.openssl_bin,
            passphrase=base64.b64encode(enc_key),
            data=plaintext,
            decrypt=False,
        )
        tag = hmac.new(mac_key, PAYLOAD_VERSION + ciphertext, hashlib.sha256).digest()
        return PAYLOAD_VERSION + tag + ciphertext

    def decrypt(self, payload: bytes) -> bytes:
        if not payload.startswith(PAYLOAD_VERSION) or len(payload) <= len(PAYLOAD_VERSION) + TAG_BYTES:
            raise SessionEncryptionError("encrypted session payload is malformed")
        master_key = self.key_provider.get_key()
        enc_key = _derive_key(master_key, b"valuehire-session-state-encryption")
        mac_key = _derive_key(master_key, b"valuehire-session-state-authentication")
        tag_start = len(PAYLOAD_VERSION)
        expected_tag = payload[tag_start : tag_start + TAG_BYTES]
        ciphertext = payload[tag_start + TAG_BYTES :]
        actual_tag = hmac.new(mac_key, PAYLOAD_VERSION + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(expected_tag, actual_tag):
            raise SessionEncryptionError("encrypted session payload authentication failed")
        return _run_openssl_enc(
            openssl_bin=self.openssl_bin,
            passphrase=base64.b64encode(enc_key),
            data=ciphertext,
            decrypt=True,
        )


@dataclass(frozen=True)
class EncryptedSessionSnapshot:
    site: Channel
    worker_id: str
    storage_state_enc: bytes
    is_validated: bool
    kind: SnapshotKind
    captured_at: str
    updated_at: str


def validate_encrypted_session_payload(storage_state_enc: bytes) -> None:
    if (
        not storage_state_enc.startswith(PAYLOAD_VERSION)
        or len(storage_state_enc) <= len(PAYLOAD_VERSION) + TAG_BYTES
    ):
        raise SessionEncryptionError("encrypted session payload is malformed")


class InMemorySessionSnapshotStore:
    """Testable current/last_known_good store matching the Supabase uniqueness contract."""

    def __init__(self) -> None:
        self._records: dict[tuple[Channel, str, SnapshotKind], EncryptedSessionSnapshot] = {}

    def save_validated_current(
        self,
        *,
        site: Channel,
        worker_id: str,
        storage_state_enc: bytes,
        captured_at: str,
    ) -> EncryptedSessionSnapshot:
        validate_encrypted_session_payload(storage_state_enc)
        current_key: tuple[Channel, str, SnapshotKind] = (site, worker_id, "current")
        previous = self._records.get(current_key)
        if previous is not None and previous.is_validated:
            self._records[(site, worker_id, "last_known_good")] = replace(
                previous,
                kind="last_known_good",
                updated_at=captured_at,
            )
        record = EncryptedSessionSnapshot(
            site=site,
            worker_id=worker_id,
            storage_state_enc=storage_state_enc,
            is_validated=True,
            kind="current",
            captured_at=captured_at,
            updated_at=captured_at,
        )
        self._records[current_key] = record
        return record

    def latest_validated(self, *, site: Channel, worker_id: str) -> EncryptedSessionSnapshot | None:
        snapshots = self.validated_snapshots(site=site, worker_id=worker_id)
        return snapshots[0] if snapshots else None

    def validated_snapshots(self, *, site: Channel, worker_id: str) -> tuple[EncryptedSessionSnapshot, ...]:
        records: list[EncryptedSessionSnapshot] = []
        for kind in ("current", "last_known_good"):
            record = self._records.get((site, worker_id, kind))
            if record is not None and record.is_validated:
                records.append(record)
        return tuple(records)

    def get(self, *, site: Channel, worker_id: str, kind: SnapshotKind) -> EncryptedSessionSnapshot | None:
        return self._records.get((site, worker_id, kind))


class SessionSnapshotStore(Protocol):
    def save_validated_current(
        self,
        *,
        site: Channel,
        worker_id: str,
        storage_state_enc: bytes,
        captured_at: str,
    ) -> EncryptedSessionSnapshot:
        ...

    def latest_validated(self, *, site: Channel, worker_id: str) -> EncryptedSessionSnapshot | None:
        ...

    def validated_snapshots(self, *, site: Channel, worker_id: str) -> tuple[EncryptedSessionSnapshot, ...]:
        ...


@dataclass(frozen=True)
class SupabaseRestConfig:
    url: str
    service_role_key: str
    timeout_seconds: int = 10

    @property
    def rest_url(self) -> str:
        return self.url.rstrip("/") + "/rest/v1"

    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.service_role_key}",
            "apikey": self.service_role_key,
            "Content-Type": "application/json",
        }


class SupabaseSessionSnapshotStore:
    """Supabase-backed snapshot store using RPC wrappers to keep bytea handling explicit."""

    def __init__(self, config: SupabaseRestConfig, *, urlopen: Any = urllib.request.urlopen) -> None:
        self.config = config
        self.urlopen = urlopen

    def save_validated_current(
        self,
        *,
        site: Channel,
        worker_id: str,
        storage_state_enc: bytes,
        captured_at: str,
    ) -> EncryptedSessionSnapshot:
        validate_encrypted_session_payload(storage_state_enc)
        payload = {
            "site_arg": site,
            "worker_id_arg": worker_id,
            "storage_state_b64_arg": base64.b64encode(storage_state_enc).decode("ascii"),
            "captured_at_arg": captured_at,
        }
        rows = self._rpc("save_validated_session_snapshot", payload)
        if not rows:
            raise SupabaseSessionStoreError("Supabase session snapshot save returned no row")
        return _snapshot_from_supabase_row(rows[0])

    def latest_validated(self, *, site: Channel, worker_id: str) -> EncryptedSessionSnapshot | None:
        snapshots = self.validated_snapshots(site=site, worker_id=worker_id)
        return snapshots[0] if snapshots else None

    def validated_snapshots(self, *, site: Channel, worker_id: str) -> tuple[EncryptedSessionSnapshot, ...]:
        rows = self._rpc(
            "validated_session_snapshots",
            {"site_arg": site, "worker_id_arg": worker_id},
        )
        if not rows:
            return ()
        records: list[EncryptedSessionSnapshot] = []
        for row in rows:
            try:
                records.append(_snapshot_from_supabase_row(row))
            except Exception:
                continue
        return tuple(records)

    def _rpc(self, name: str, payload: Mapping[str, object]) -> list[dict[str, object]]:
        url = f"{self.config.rest_url}/rpc/{name}"
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers=self.config.headers(),
            method="POST",
        )
        try:
            with self.urlopen(request, timeout=self.config.timeout_seconds) as response:
                status = int(getattr(response, "status", 0) or 0)
                raw = response.read()
        except urllib.error.HTTPError as exc:
            exc.close()
            raise SupabaseSessionStoreError(f"Supabase RPC {name} failed with status {exc.code}") from exc
        except Exception as exc:
            raise SupabaseSessionStoreError(f"Supabase RPC {name} request failed") from exc
        if status < 200 or status >= 300:
            raise SupabaseSessionStoreError(f"Supabase RPC {name} failed with status {status}")
        decoded = json.loads(raw.decode("utf-8") or "[]")
        if isinstance(decoded, dict):
            return [decoded]
        if not isinstance(decoded, list):
            raise SupabaseSessionStoreError(f"Supabase RPC {name} returned malformed JSON")
        return [row for row in decoded if isinstance(row, dict)]


def _snapshot_from_supabase_row(row: Mapping[str, object]) -> EncryptedSessionSnapshot:
    storage_state_b64 = _required_supabase_row_string(row, "storage_state_b64")
    try:
        storage_state_enc = base64.b64decode(storage_state_b64, validate=True)
    except Exception as exc:
        raise SupabaseSessionStoreError("Supabase snapshot row has malformed encrypted payload") from exc
    validate_encrypted_session_payload(storage_state_enc)
    site = _required_supabase_row_string(row, "site")
    kind = _required_supabase_row_string(row, "kind")
    worker_id = _required_supabase_row_string(row, "worker_id")
    captured_at = _required_supabase_row_string(row, "captured_at")
    updated_at = _required_supabase_row_string(row, "updated_at")
    if site not in {"saramin", "jobkorea", "linkedin_rps"}:
        raise SupabaseSessionStoreError("Supabase snapshot row has unsupported site")
    if kind not in {"current", "last_known_good"}:
        raise SupabaseSessionStoreError("Supabase snapshot row has unsupported kind")
    if row.get("is_validated") is not True:
        raise SupabaseSessionStoreError("Supabase snapshot row is not validated")
    return EncryptedSessionSnapshot(
        site=site,  # type: ignore[arg-type]
        worker_id=worker_id,
        storage_state_enc=storage_state_enc,
        is_validated=True,
        kind=kind,  # type: ignore[arg-type]
        captured_at=captured_at,
        updated_at=updated_at,
    )


def _required_supabase_row_string(row: Mapping[str, object], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise SupabaseSessionStoreError(f"Supabase snapshot row has malformed {field}")
    return value


def encode_storage_state(state: Mapping[str, object]) -> bytes:
    return json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def decode_storage_state(payload: bytes) -> dict[str, object]:
    decoded = json.loads(payload.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise SnapshotValidationError("storage state payload is not an object")
    return decoded


def storage_state_for_site(state: Mapping[str, object], site: Channel) -> dict[str, object]:
    allowed_domains = PORTAL_STORAGE_DOMAINS.get(site)
    if not allowed_domains:
        return {"cookies": [], "origins": []}
    return {
        "cookies": [
            normalized_cookie
            for cookie in state.get("cookies", ())
            if isinstance(cookie, Mapping)
            for normalized_cookie in [_cookie_for_site(cookie, allowed_domains)]
            if normalized_cookie is not None
        ],
        "origins": [
            {"origin": origin, "localStorage": local_storage}
            for origin_state in state.get("origins", ())
            if isinstance(origin_state, Mapping)
            for origin, local_storage in [_origin_storage_for_site(origin_state, allowed_domains)]
            if origin and local_storage
        ],
    }


def _cookie_for_site(cookie: Mapping[str, object], allowed_domains: tuple[str, ...]) -> dict[str, object] | None:
    domain = str(cookie.get("domain") or "").strip()
    host = domain.lower().lstrip(".")
    url = str(cookie.get("url") or "").strip()
    url_host = _host_from_http_url(url)
    if host and _host_matches_domains(host, allowed_domains):
        return _cookie_payload(cookie, domain=domain, url=None)
    if url_host is not None and _host_matches_domains(url_host, allowed_domains):
        return _cookie_payload(cookie, domain=None, url=url)
    return None


def _cookie_for_reinjection(cookie: Mapping[str, object]) -> dict[str, object] | None:
    domain = str(cookie.get("domain") or "").strip()
    if domain:
        return _cookie_payload(cookie, domain=domain, url=None)
    url = str(cookie.get("url") or "").strip()
    if _host_from_http_url(url) is not None:
        return _cookie_payload(cookie, domain=None, url=url)
    return None


def _cookie_payload(
    cookie: Mapping[str, object],
    *,
    domain: str | None,
    url: str | None,
) -> dict[str, object] | None:
    name = cookie.get("name")
    value = cookie.get("value")
    if not isinstance(name, str) or not name or not isinstance(value, str):
        return None

    normalized: dict[str, object] = {"name": name, "value": value}
    if domain:
        normalized["domain"] = domain
        path = cookie.get("path")
        normalized["path"] = path if isinstance(path, str) and path else "/"
    elif url:
        normalized["url"] = url
    else:
        return None

    expires = cookie.get("expires")
    if isinstance(expires, int | float) and not isinstance(expires, bool):
        normalized["expires"] = expires
    for field in ("httpOnly", "secure"):
        value = cookie.get(field)
        if isinstance(value, bool):
            normalized[field] = value
    same_site = cookie.get("sameSite")
    if same_site in {"Strict", "Lax", "None"}:
        normalized["sameSite"] = same_site
    return normalized


def _origin_storage_for_site(
    origin_state: Mapping[str, object],
    allowed_domains: tuple[str, ...],
) -> tuple[str, list[dict[str, str]]]:
    origin = str(origin_state.get("origin", "")).strip()
    host = _host_from_http_url(origin)
    if host is None or not _host_matches_domains(host, allowed_domains):
        return "", []
    return origin, _local_storage_items(origin_state)


def _host_from_http_url(value: str) -> str | None:
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return parsed.hostname.lower().strip(".")


def _host_matches_domains(host: str, allowed_domains: tuple[str, ...]) -> bool:
    normalized_host = host.lower().strip(".")
    for domain in allowed_domains:
        normalized_domain = domain.lower().strip().lstrip(".")
        if normalized_host == normalized_domain or normalized_host.endswith("." + normalized_domain):
            return True
    return False


def _local_storage_items(origin_state: Mapping[str, object]) -> list[dict[str, str]]:
    return [
        {"name": item["name"], "value": item["value"]}
        for item in origin_state.get("localStorage", ())
        if (
            isinstance(item, Mapping)
            and isinstance(item.get("name"), str)
            and bool(item.get("name"))
            and isinstance(item.get("value"), str)
        )
    ]


def _has_reinjectable_storage_state(state: Mapping[str, object]) -> bool:
    cookies = state.get("cookies")
    if isinstance(cookies, list) and cookies:
        return True
    origins = state.get("origins")
    return isinstance(origins, list) and any(
        isinstance(origin_state, Mapping) and bool(origin_state.get("localStorage"))
        for origin_state in origins
    )


async def _maybe_await(value: bool | Awaitable[bool]) -> bool:
    if hasattr(value, "__await__"):
        return bool(await value)
    return bool(value)


def utc_now_snapshot() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


async def capture_validated_snapshot(
    *,
    context: Any,
    site: Channel,
    worker_id: str,
    encryptor: OpenSslSessionEncryptor,
    store: SessionSnapshotStore,
    validator: SnapshotValidator,
    captured_at: str | None = None,
) -> EncryptedSessionSnapshot | None:
    state = await context.storage_state()
    if not isinstance(state, Mapping):
        raise SnapshotValidationError("context.storage_state did not return an object")
    scoped_state = storage_state_for_site(state, site)
    if not _has_reinjectable_storage_state(scoped_state):
        return None
    if not await _maybe_await(validator(scoped_state)):
        return None
    encrypted = encryptor.encrypt(encode_storage_state(scoped_state))
    return store.save_validated_current(
        site=site,
        worker_id=worker_id,
        storage_state_enc=encrypted,
        captured_at=captured_at or utc_now_snapshot(),
    )


async def reinject_storage_state(
    context: Any,
    state: Mapping[str, object],
    *,
    site: Channel | None = None,
) -> None:
    if site is not None:
        state = storage_state_for_site(state, site)
    cookies = [
        normalized_cookie
        for cookie in state.get("cookies", ())
        if isinstance(cookie, Mapping)
        for normalized_cookie in [_cookie_for_reinjection(cookie)]
        if normalized_cookie is not None
    ]
    if cookies:
        await context.add_cookies(cookies)

    for origin_state in state.get("origins", ()):
        if not isinstance(origin_state, Mapping):
            continue
        origin = str(origin_state.get("origin", "")).strip()
        local_storage = _local_storage_items(origin_state)
        if not origin or not local_storage:
            continue
        page = await context.new_page()
        try:
            await page.goto(origin, wait_until="domcontentloaded", timeout=45000)
            await page.evaluate(
                """items => {
                    for (const item of items) {
                        window.localStorage.setItem(item.name, item.value);
                    }
                }""",
                local_storage,
            )
        finally:
            await _close_page_if_possible(page)


async def restore_latest_validated_snapshot(
    *,
    context: Any,
    site: Channel,
    worker_id: str,
    encryptor: OpenSslSessionEncryptor,
    store: SessionSnapshotStore,
) -> bool:
    records = _validated_snapshot_candidates(store, site=site, worker_id=worker_id)
    if not records:
        return False
    for record in records:
        try:
            state = decode_storage_state(encryptor.decrypt(record.storage_state_enc))
            scoped_state = storage_state_for_site(state, site)
            if not _has_reinjectable_storage_state(scoped_state):
                continue
            await reinject_storage_state(context, scoped_state)
            return True
        except Exception:
            continue
    return False


def _validated_snapshot_candidates(
    store: SessionSnapshotStore,
    *,
    site: Channel,
    worker_id: str,
) -> tuple[EncryptedSessionSnapshot, ...]:
    snapshots = getattr(store, "validated_snapshots", None)
    if callable(snapshots):
        return tuple(snapshots(site=site, worker_id=worker_id))
    record = store.latest_validated(site=site, worker_id=worker_id)
    return () if record is None else (record,)


async def validate_snapshot_by_reinjection(
    *,
    playwright: Any,
    site: Channel,
    state: Mapping[str, object],
    ready_check: Callable[[Any], Awaitable[bool]],
    browser: Any | None = None,
) -> bool:
    owns_browser = browser is None
    context: Any | None = None
    try:
        if owns_browser:
            browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context()
        await reinject_storage_state(context, state, site=site)
        page = await context.new_page()
        await _goto_search_surface(page, site, "")
        return await ready_check(page)
    finally:
        try:
            if context is not None:
                await context.close()
        finally:
            if owns_browser and browser is not None:
                await browser.close()
