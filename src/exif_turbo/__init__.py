"""exif-turbo — Cross-platform image EXIF metadata search and indexing tool."""

__version__ = "1.13.4"

from .data.image_index_repository import ImageIndexRepository
from .indexing.exif_metadata_extractor import ExifMetadataExtractor
from .indexing.image_finder import ImageFinder
from .indexing.image_utils import is_image_file
from .indexing.indexer_service import IndexerService, metadata_to_text
from .indexing.metadata_extractor import MetadataExtractor
from .models.indexed_image import IndexedImage

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
