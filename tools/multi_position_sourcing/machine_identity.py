"""Canonical fleet machine identity contract.

Aliases are accepted only by explicit external-input boundaries. Internal
objects, persistence writes, lock keys, and execution state require one of the
three canonical identifiers exactly as written.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, TypeAlias, cast

MachineId: TypeAlias = Literal["macmini", "macbook", "winpc"]

CANONICAL_MACHINE_IDS: tuple[MachineId, ...] = (
    "macmini",
    "macbook",
    "winpc",
)
MACHINE_ID_ALIASES: Mapping[str, MachineId] = {
    "macbook_pro": "macbook",
    "win": "winpc",
    "windows": "winpc",
    "윈도우": "winpc",
    "윈도우pc": "winpc",
    "맥미니": "macmini",
    "mini": "macmini",
    "맥북": "macbook",
}
_CANONICAL_SET = frozenset(CANONICAL_MACHINE_IDS)


class MachineIdentityError(ValueError):
    """Structured rejection for unknown or non-canonical machine identity."""

    def __init__(
        self,
        code: Literal["invalid_type", "unknown_machine", "noncanonical_machine"],
        *,
        field: str = "machine",
        value: Any = None,
    ) -> None:
        self.code = code
        self.field = field
        self.value = value
        super().__init__(f"{field}: {code}")


def normalize_machine_id(value: Any, *, field: str = "machine") -> MachineId:
    """Normalize one exact external value without trimming or case folding."""

    if not isinstance(value, str):
        raise MachineIdentityError("invalid_type", field=field, value=value)
    if value in _CANONICAL_SET:
        return cast(MachineId, value)
    alias = MACHINE_ID_ALIASES.get(value)
    if alias is not None:
        return alias
    raise MachineIdentityError("unknown_machine", field=field, value=value)


def require_machine_id(value: Any, *, field: str = "machine") -> MachineId:
    """Require an already-canonical internal or persistence-bound value."""

    if not isinstance(value, str):
        raise MachineIdentityError("invalid_type", field=field, value=value)
    if value not in _CANONICAL_SET:
        raise MachineIdentityError("noncanonical_machine", field=field, value=value)
    return cast(MachineId, value)


def canonicalize_legacy_machine_id(
    value: Any,
    *,
    field: str = "machine",
) -> MachineId:
    """Read compatibility for known historic aliases; unknown values fail."""

    return normalize_machine_id(value, field=field)


def canonicalize_machine_mapping(
    value: Mapping[str, Any],
    *,
    fields: tuple[str, ...] = ("machine",),
) -> dict[str, Any]:
    """Return a copy whose present machine fields contain canonical IDs."""

    result = dict(value)
    for field in fields:
        if field in result and result[field] is not None:
            result[field] = canonicalize_legacy_machine_id(
                result[field],
                field=field,
            )
    return result


__all__ = [
    "CANONICAL_MACHINE_IDS",
    "MACHINE_ID_ALIASES",
    "MachineId",
    "MachineIdentityError",
    "canonicalize_legacy_machine_id",
    "canonicalize_machine_mapping",
    "normalize_machine_id",
    "require_machine_id",
]
