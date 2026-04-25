"""exif-turbo — Cross-platform image EXIF metadata search and indexing tool."""

__version__ = "1.0.0"

from .data.image_index_repository import ImageIndexRepository
from .indexer import (
	ExifMetadataExtractor,
	ImageFinder,
	IndexerService,
	MetadataExtractor,
	IndexedImage,
	is_image_file,
	metadata_to_text,
)

__all__ = [
	"ExifMetadataExtractor",
	"ImageFinder",
	"IndexerService",
	"MetadataExtractor",
	"IndexedImage",
	"is_image_file",
	"metadata_to_text",
	"ImageIndexRepository",
]
