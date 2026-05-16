from __future__ import annotations

from pathlib import Path

from exif_turbo.utils.video_frame import extract_video_frame


def test_extract_video_frame_webm_sample_returns_thumbnail_sized_image() -> None:
    # Arrange
    video_path = Path("tests/sample-data/Swiss_silk_Manufaktur_Bolligen_Video.webm")

    # Act
    image = extract_video_frame(str(video_path), target_long_edge=256)

    # Assert
    assert image.mode == "RGB"
    assert max(image.size) == 256
