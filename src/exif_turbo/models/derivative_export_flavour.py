from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar


class DerivativeFormat(StrEnum):
    ORIGINAL = "original"
    JPEG = "jpeg"
    PNG = "png"
    TIFF = "tiff"


class MetadataMode(StrEnum):
    NONE = "none"
    ORIGINAL = "original"
    CUSTOM = "custom"


class ResizeMode(StrEnum):
    ORIGINAL_PIXELS = "original_pixels"
    LONGEST_EDGE = "longest_edge"
    WIDTH = "width"
    HEIGHT = "height"


class TiffCompression(StrEnum):
    NONE = "none"
    LZW = "lzw"
    ZIP = "zip"


_EnumT = TypeVar("_EnumT", bound=StrEnum)
_FLAVOUR_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_INVALID_SUFFIX_CHARACTERS = set('/\\<>:"|?*')


def _parse_enum(enum_type: type[_EnumT], value: object, field: str) -> _EnumT:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"invalid {field}: {value}") from exc


def _parse_int(value: object, field: str, *, optional: bool = False) -> int | None:
    if optional and value is None:
        return None
    if type(value) is not int:
        raise ValueError(f"{field} must be an integer")
    return value


def _parse_required_int(value: object, field: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{field} must be an integer")
    return value


def _parse_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


@dataclass(frozen=True, slots=True)
class DerivativeExportFlavour:
    flavour_id: str
    name: str
    output_format: DerivativeFormat
    filename_suffix: str = ""
    selected_by_default: bool = False
    metadata_mode: MetadataMode = MetadataMode.CUSTOM
    resize_mode: ResizeMode = ResizeMode.ORIGINAL_PIXELS
    pixel_limit: int | None = None
    no_upscale: bool = True
    dpi: int | None = None
    jpeg_quality: int = 85
    png_compression: int = 6
    tiff_compression: TiffCompression = TiffCompression.LZW

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, enum_type)
            for value, enum_type in (
                (self.output_format, DerivativeFormat),
                (self.metadata_mode, MetadataMode),
                (self.resize_mode, ResizeMode),
                (self.tiff_compression, TiffCompression),
            )
        ):
            raise ValueError("format settings must use supported values")
        if not isinstance(self.flavour_id, str) or not _FLAVOUR_ID_RE.fullmatch(
            self.flavour_id
        ):
            raise ValueError("flavour_id must be a stable identifier")
        if (
            not isinstance(self.name, str)
            or not self.name
            or self.name != self.name.strip()
            or len(self.name) > 80
        ):
            raise ValueError("name must contain 1 to 80 non-whitespace characters")
        if any(ord(character) < 32 for character in self.name):
            raise ValueError("name cannot contain control characters")
        if not isinstance(self.filename_suffix, str) or len(self.filename_suffix) > 40 or any(
            character in _INVALID_SUFFIX_CHARACTERS or ord(character) < 32
            for character in self.filename_suffix
        ):
            raise ValueError("filename_suffix contains unsafe characters")
        if self.filename_suffix.endswith((" ", ".")):
            raise ValueError("filename_suffix cannot end with a space or period")
        if type(self.selected_by_default) is not bool or type(self.no_upscale) is not bool:
            raise ValueError("selection and resize flags must be booleans")
        if type(self.jpeg_quality) is not int or not 1 <= self.jpeg_quality <= 100:
            raise ValueError("jpeg_quality must be between 1 and 100")
        if type(self.png_compression) is not int or not 0 <= self.png_compression <= 9:
            raise ValueError("png_compression must be between 0 and 9")
        if self.pixel_limit is not None and (
            type(self.pixel_limit) is not int or self.pixel_limit <= 0
        ):
            raise ValueError("pixel_limit must be a positive integer")
        if self.dpi is not None and (type(self.dpi) is not int or self.dpi <= 0):
            raise ValueError("dpi must be a positive integer")
        if self.resize_mode is ResizeMode.ORIGINAL_PIXELS:
            if self.pixel_limit is not None:
                raise ValueError("pixel_limit is only valid for limited resize modes")
        elif self.pixel_limit is None:
            raise ValueError("limited resize modes require a positive pixel_limit")
        if self.output_format is DerivativeFormat.ORIGINAL:
            if self.metadata_mode is not MetadataMode.ORIGINAL:
                raise ValueError("Original (as is) requires Original metadata mode")
            if self.resize_mode is not ResizeMode.ORIGINAL_PIXELS or self.dpi is not None:
                raise ValueError("Original (as is) cannot resize or change output DPI")

    def to_dict(self) -> dict[str, str | int | bool | None]:
        return {
            "id": self.flavour_id,
            "name": self.name,
            "format": self.output_format.value,
            "suffix": self.filename_suffix,
            "selected_by_default": self.selected_by_default,
            "metadata_mode": self.metadata_mode.value,
            "resize_mode": self.resize_mode.value,
            "pixel_limit": self.pixel_limit,
            "no_upscale": self.no_upscale,
            "dpi": self.dpi,
            "jpeg_quality": self.jpeg_quality,
            "png_compression": self.png_compression,
            "tiff_compression": self.tiff_compression.value,
        }

    @classmethod
    def from_dict(cls, value: object) -> DerivativeExportFlavour:
        if not isinstance(value, dict):
            raise ValueError("flavour must be an object")
        try:
            flavour_id = value["id"]
            name = value["name"]
            if not isinstance(flavour_id, str) or not isinstance(name, str):
                raise ValueError("flavour id and name must be strings")
            return cls(
                flavour_id=flavour_id,
                name=name,
                output_format=_parse_enum(DerivativeFormat, value["format"], "format"),
                filename_suffix=value.get("suffix", ""),
                selected_by_default=_parse_bool(
                    value.get("selected_by_default", False), "selected_by_default"
                ),
                metadata_mode=_parse_enum(
                    MetadataMode, value.get("metadata_mode", "custom"), "metadata_mode"
                ),
                resize_mode=_parse_enum(
                    ResizeMode,
                    value.get("resize_mode", "original_pixels"),
                    "resize_mode",
                ),
                pixel_limit=_parse_int(
                    value.get("pixel_limit"), "pixel_limit", optional=True
                ),
                no_upscale=_parse_bool(value.get("no_upscale", True), "no_upscale"),
                dpi=_parse_int(value.get("dpi"), "dpi", optional=True),
                jpeg_quality=_parse_required_int(
                    value.get("jpeg_quality", 85), "jpeg_quality"
                ),
                png_compression=_parse_required_int(
                    value.get("png_compression", 6), "png_compression"
                ),
                tiff_compression=_parse_enum(
                    TiffCompression,
                    value.get("tiff_compression", "lzw"),
                    "tiff_compression",
                ),
            )
        except KeyError as exc:
            raise ValueError(f"missing flavour field: {exc.args[0]}") from exc


def default_derivative_export_flavours() -> tuple[DerivativeExportFlavour, ...]:
    return (
        DerivativeExportFlavour(
            "default-original-as-is",
            "Original (as is)",
            DerivativeFormat.ORIGINAL,
            "_original",
            True,
            MetadataMode.ORIGINAL,
        ),
        DerivativeExportFlavour(
            "default-web-jpeg",
            "Web JPEG",
            DerivativeFormat.JPEG,
            "_web-jpeg",
            True,
            MetadataMode.NONE,
            ResizeMode.LONGEST_EDGE,
            2048,
        ),
        DerivativeExportFlavour(
            "default-web-png",
            "Web PNG",
            DerivativeFormat.PNG,
            "_web-png",
            True,
            MetadataMode.NONE,
            ResizeMode.LONGEST_EDGE,
            2048,
        ),
        DerivativeExportFlavour(
            "default-full-resolution-png",
            "Full Resolution PNG",
            DerivativeFormat.PNG,
            "_full-resolution",
            False,
            MetadataMode.ORIGINAL,
            png_compression=9,
        ),
        DerivativeExportFlavour(
            "default-thumbnail-png",
            "Thumbnail PNG",
            DerivativeFormat.PNG,
            "_thumbnail",
            False,
            MetadataMode.NONE,
            ResizeMode.LONGEST_EDGE,
            512,
        ),
        DerivativeExportFlavour(
            "default-archive-tiff",
            "Archive TIFF",
            DerivativeFormat.TIFF,
            "_archive",
            False,
            MetadataMode.CUSTOM,
        ),
    )