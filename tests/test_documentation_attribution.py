from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
CC_BY_SA_SCREENSHOTS = (
    "02_search_all",
    "03_search_eagle",
    "04_search_milky_way",
    "05_browse_tab",
    "07_folder_filter",
    "09_ai_search_mode",
)
CC0_SCREENSHOTS = ("08_gps_location_bar", "10_tagging_drawer")


def _credit_after_screenshot(document: Path, screenshot: str) -> str:
    lines = document.read_text(encoding="utf-8").splitlines()
    image_line = next(
        index for index, line in enumerate(lines) if f"{screenshot}.png)" in line
    )
    return " ".join(lines[image_line + 1 : image_line + 4])


def test_screenshot_attribution_manifest_all_photo_screenshots_maps_sources() -> None:
    # Arrange
    attribution = (REPO_ROOT / "tests" / "sample-data" / "ATTRIBUTION.md").read_text(
        encoding="utf-8"
    )

    # Act
    missing = [
        screenshot
        for screenshot in (*CC_BY_SA_SCREENSHOTS, *CC0_SCREENSHOTS)
        if f"docs/screenshots/{screenshot}.png" not in attribution
    ]

    # Assert
    assert missing == []


def test_user_documents_photo_screenshots_credit_immediately_after_image() -> None:
    # Arrange
    expected = {
        REPO_ROOT / "README.md": (
            "03_search_eagle",
            "09_ai_search_mode",
            "10_tagging_drawer",
        ),
        REPO_ROOT / "docs" / "user-manual.md": (
            "02_search_all",
            "04_search_milky_way",
            "05_browse_tab",
            "07_folder_filter",
            "08_gps_location_bar",
            "09_ai_search_mode",
            "10_tagging_drawer",
        ),
    }

    # Act
    missing = [
        f"{document.name}:{screenshot}"
        for document, screenshots in expected.items()
        for screenshot in screenshots
        if "*Photo" not in _credit_after_screenshot(document, screenshot)
    ]

    # Assert
    assert missing == []


def test_screenshot_license_notice_cc_by_sa_composites_identifies_treatment() -> None:
    # Arrange
    notice = (REPO_ROOT / "docs" / "screenshots" / "README.md").read_text(
        encoding="utf-8"
    )

    # Act
    missing = [
        screenshot
        for screenshot in CC_BY_SA_SCREENSHOTS
        if f"`{screenshot}.png`" not in notice
    ]

    # Assert
    assert missing == []
    assert "scaled and/or cropped" in notice
    assert "are distributed\nunder" in notice
    assert "Creative Commons Attribution-ShareAlike 4.0 International" in notice