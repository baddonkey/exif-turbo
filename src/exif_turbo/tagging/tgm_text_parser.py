from __future__ import annotations

from datetime import datetime
import re

from .tgm_source_record import ParsedTgmSource, TgmSourceRecord


_FIELD_PATTERN = re.compile(r"^\s+([A-Za-z]+):\s*(.*)$")
_TIMESTAMP_FORMAT = "%m/%d/%Y %I:%M:%S %p"


class TgmTextParser:
    def parse(self, raw: bytes) -> ParsedTgmSource:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("TGM tagged text must be UTF-8") from exc
        lines = text.splitlines()
        distribution_date = self._distribution_date(lines[0] if lines else "")
        record_lines = lines[1:] if distribution_date is not None else lines
        records = tuple(
            self._parse_record(chunk)
            for chunk in self._chunks(record_lines)
            if chunk
        )
        return ParsedTgmSource(records=records, distribution_date=distribution_date)

    @staticmethod
    def _chunks(lines: list[str]) -> tuple[list[str], ...]:
        chunks: list[list[str]] = []
        current: list[str] = []
        for line in lines:
            if not line.strip():
                if current:
                    chunks.append(current)
                    current = []
                continue
            current.append(line)
        if current:
            chunks.append(current)
        return tuple(chunks)

    @staticmethod
    def _parse_record(lines: list[str]) -> TgmSourceRecord:
        label = lines[0].strip()
        if not label or lines[0][:1].isspace():
            raise ValueError("TGM tagged-text record must start with an unindented term")
        fields: dict[str, list[str]] = {}
        previous_field: str | None = None
        for line in lines[1:]:
            match = _FIELD_PATTERN.match(line)
            if match is not None:
                field, value = match.groups()
                fields.setdefault(field, []).append(value.strip())
                previous_field = field
                continue
            if not line[:1].isspace() or previous_field is None:
                raise ValueError(f"invalid TGM tagged-text line: {line!r}")
            fields[previous_field][-1] = (
                f"{fields[previous_field][-1]} {line.strip()}".strip()
            )
        return TgmSourceRecord(
            label=label,
            is_descriptor="USE" not in fields,
            fields={key: tuple(values) for key, values in fields.items()},
        )

    @staticmethod
    def _distribution_date(value: str) -> str | None:
        try:
            parsed = datetime.strptime(value.strip(), _TIMESTAMP_FORMAT)
        except ValueError:
            return None
        return parsed.isoformat(timespec="seconds")