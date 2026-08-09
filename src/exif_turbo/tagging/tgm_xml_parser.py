from __future__ import annotations

from io import BytesIO
import re
from xml.etree import ElementTree

from .tgm_source_record import ParsedTgmSource, TgmSourceRecord


_CREATED_PATTERN = re.compile(
    rb"Created:\s*(\d{1,2})/(\d{1,2})/(\d{4})\s+"
    rb"(\d{1,2}):(\d{2}):(\d{2})\s*([AP]M)",
    re.IGNORECASE,
)
_DOCTYPE_PATTERN = re.compile(
    rb"<!DOCTYPE\s+THESAURUS\s*\[(.*?)\]\s*>",
    re.IGNORECASE | re.DOTALL,
)
_ELEMENT_DECLARATION_PATTERN = re.compile(
    rb"<!ELEMENT\s+[A-Za-z][A-Za-z0-9_-]*\s+[^>]+>",
    re.IGNORECASE,
)


class TgmXmlParser:
    def parse(self, raw: bytes) -> ParsedTgmSource:
        parse_bytes = self._without_official_dtd(raw)

        records: list[TgmSourceRecord] = []
        root_tag: str | None = None
        for event, element in ElementTree.iterparse(
            BytesIO(parse_bytes), events=("start", "end")
        ):
            tag = self._local_name(element.tag)
            if event == "start" and root_tag is None:
                root_tag = tag
                if root_tag != "THESAURUS":
                    raise ValueError("TGM XML root must be THESAURUS")
            if event != "end" or tag != "CONCEPT":
                continue
            records.append(self._record_from_element(element))
            element.clear()
        return ParsedTgmSource(
            records=tuple(records),
            distribution_date=self._distribution_date(raw),
        )

    @staticmethod
    def _without_official_dtd(raw: bytes) -> bytes:
        lowered = raw.lower()
        if b"<!doctype" not in lowered:
            if b"<!entity" in lowered:
                raise ValueError("TGM XML must not contain entity declarations")
            return raw

        match = _DOCTYPE_PATTERN.search(raw)
        if match is None:
            raise ValueError("TGM XML contains an unsupported DTD declaration")
        internal_subset = match.group(1)
        if b"<!entity" in internal_subset.lower():
            raise ValueError("TGM XML must not contain DTD or entity declarations")
        remainder = _ELEMENT_DECLARATION_PATTERN.sub(b"", internal_subset)
        if remainder.strip():
            raise ValueError("TGM XML contains unsupported DTD declarations")
        return raw[: match.start()] + raw[match.end() :]

    @staticmethod
    def _record_from_element(element: ElementTree.Element) -> TgmSourceRecord:
        fields: dict[str, list[str]] = {}
        for child in element:
            value = "".join(child.itertext()).strip()
            if value:
                fields.setdefault(TgmXmlParser._local_name(child.tag), []).append(value)
        descriptors = fields.pop("DESCRIPTOR", [])
        non_descriptors = fields.pop("NON-DESCRIPTOR", [])
        labels = descriptors or non_descriptors
        if not labels:
            raise ValueError("TGM CONCEPT must contain DESCRIPTOR or NON-DESCRIPTOR")
        return TgmSourceRecord(
            label=labels[0],
            is_descriptor=bool(descriptors),
            fields={key: tuple(values) for key, values in fields.items()},
        )

    @staticmethod
    def _local_name(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    @staticmethod
    def _distribution_date(raw: bytes) -> str | None:
        match = _CREATED_PATTERN.search(raw[:4096])
        if match is None:
            return None
        month, day, year, hour, minute, second, meridiem = match.groups()
        hour_value = int(hour) % 12 + (12 if meridiem.upper() == b"PM" else 0)
        return (
            f"{int(year):04d}-{int(month):02d}-{int(day):02d}T"
            f"{hour_value:02d}:{int(minute):02d}:{int(second):02d}"
        )