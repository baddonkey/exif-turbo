from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TgmSourceRecord:
    label: str
    is_descriptor: bool
    fields: dict[str, tuple[str, ...]]

    def values(self, field: str) -> tuple[str, ...]:
        return self.fields.get(field, ())

    def first(self, field: str) -> str | None:
        values = self.values(field)
        return values[0] if values else None


@dataclass(frozen=True)
class ParsedTgmSource:
    records: tuple[TgmSourceRecord, ...]
    distribution_date: str | None