from __future__ import annotations

from datetime import datetime, timezone

import pytest

from exif_turbo.models.tgm import TgmCategory, TgmDiagnosticCode, TgmSourceFormat
from exif_turbo.tagging.tgm_importer import TgmImporter, TgmImportError


XML_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<!-- Created: 7/29/2026 11:55:28 AM -->
<THESAURUS>
  <CONCEPT>
    <DESCRIPTOR>Sunlight</DESCRIPTOR>
    <UF>Sun rays</UF>
    <BT>Light</BT>
    <RT>Missing relation</RT>
    <SN>Natural illumination</SN>
    <HN>Formerly filed elsewhere</HN>
    <FCNlctgm>sh85130432</FCNlctgm>
    <TNR>tgm012345</TNR>
    <TTCSubj>MARC 150/650</TTCSubj>
    <TTCForm>MARC 155/655</TTCForm>
  </CONCEPT>
  <CONCEPT>
    <DESCRIPTOR>Light</DESCRIPTOR>
    <NT>Sunlight</NT>
    <TNR>tgm000002</TNR>
    <TTCSubj>MARC 150/650</TTCSubj>
  </CONCEPT>
  <CONCEPT>
    <NON-DESCRIPTOR>Solar rays</NON-DESCRIPTOR>
    <USE>Sunlight</USE>
    <TNR>tgm099999</TNR>
    <TTCRef>Reference</TTCRef>
  </CONCEPT>
  <CONCEPT>
    <DESCRIPTOR>Antennas</DESCRIPTOR>
    <TTCSubj>MARC 150/650</TTCSubj>
  </CONCEPT>
</THESAURUS>
"""

TEXT_FIXTURE = """7/29/2026 11:55:28 AM

Sunlight
  UF: Sun rays
  BT: Light
  RT: Missing relation
  SN: Natural
    illumination
  HN: Formerly filed elsewhere
  FCNlctgm: sh85130432
  TNR: tgm012345
  TTCSubj: MARC 150/650
  TTCForm: MARC 155/655

Light
  NT: Sunlight
  TNR: tgm000002
  TTCSubj: MARC 150/650

Solar rays
  USE: Sunlight
  TNR: tgm099999
  TTCRef: Reference

Antennas
  TTCSubj: MARC 150/650
""".encode("utf-8")


def test_tgm_importer_xml_normalizes_canonical_concepts_and_diagnostics() -> None:
    # Arrange
    importer = TgmImporter()

    # Act
    snapshot = importer.import_bytes(
        XML_FIXTURE,
        source_url="https://example.test/tgm.xml",
        source_format=TgmSourceFormat.XML,
        imported_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
    )

    # Assert
    sunlight = snapshot.concept_by_id("loc-tgm:tgm012345")
    assert sunlight is not None
    assert sunlight.label == "Sunlight"
    assert sunlight.categories == (
        TgmCategory.SUBJECT,
        TgmCategory.GENRE_FORMAT,
    )
    assert sunlight.aliases == ("Solar rays", "Sun rays")
    assert sunlight.broader_ids == ("loc-tgm:tgm000002",)
    assert sunlight.related_ids == ()
    assert sunlight.scope_notes == ("Natural illumination",)
    assert sunlight.history_notes == ("Formerly filed elsewhere",)
    assert sunlight.former_lctgm_ids == ("sh85130432",)
    assert snapshot.resolve_label("sun rays") == sunlight
    assert snapshot.resolve_label("SOLAR RAYS") == sunlight
    assert snapshot.distribution_date == "2026-07-29T11:55:28"
    assert {diagnostic.code for diagnostic in snapshot.diagnostics} == {
        TgmDiagnosticCode.MISSING_TNR,
        TgmDiagnosticCode.UNRESOLVED_RELATION,
    }


def test_tgm_importer_tagged_text_matches_xml_normalized_shape() -> None:
    # Arrange
    importer = TgmImporter()
    imported_at = datetime(2026, 8, 9, tzinfo=timezone.utc)

    # Act
    xml_snapshot = importer.import_bytes(
        XML_FIXTURE,
        source_url="https://example.test/tgm.xml",
        source_format=TgmSourceFormat.XML,
        imported_at=imported_at,
    )
    text_snapshot = importer.import_bytes(
        TEXT_FIXTURE,
        source_url="https://example.test/tgm.txt",
        source_format=TgmSourceFormat.TAGGED_TEXT,
        imported_at=imported_at,
    )

    # Assert
    assert text_snapshot.concepts == xml_snapshot.concepts
    assert text_snapshot.diagnostics == xml_snapshot.diagnostics
    assert text_snapshot.distribution_date == xml_snapshot.distribution_date


def test_tgm_importer_non_descriptor_tnr_collision_keeps_descriptor() -> None:
    # Arrange
    raw = b"""<THESAURUS>
      <CONCEPT><DESCRIPTOR>Chair caning</DESCRIPTOR><TNR>tgm013479</TNR><TTCSubj>MARC 150/650</TTCSubj></CONCEPT>
      <CONCEPT><DESCRIPTOR>Fissures</DESCRIPTOR><TNR>tgm000003</TNR><TTCSubj>MARC 150/650</TTCSubj></CONCEPT>
      <CONCEPT><NON-DESCRIPTOR>Crevasses</NON-DESCRIPTOR><USE>Fissures</USE><TNR>tgm013479</TNR></CONCEPT>
    </THESAURUS>"""

    # Act
    snapshot = TgmImporter().import_bytes(
        raw,
        source_url="https://example.test/tgm.xml",
        source_format=TgmSourceFormat.XML,
        imported_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
    )

    # Assert
    chair_caning = snapshot.concept_by_id("loc-tgm:tgm013479")
    assert chair_caning is not None
    assert chair_caning.label == "Chair caning"
    assert snapshot.resolve_label("Crevasses") is None
    assert snapshot.diagnostics[0].code is TgmDiagnosticCode.DUPLICATE_ALIAS_COLLISION


def test_tgm_importer_conflicting_descriptor_tnr_raises_import_error() -> None:
    # Arrange
    raw = b"""<THESAURUS>
      <CONCEPT><DESCRIPTOR>First</DESCRIPTOR><TNR>tgm000001</TNR><TTCSubj>MARC 150/650</TTCSubj></CONCEPT>
      <CONCEPT><DESCRIPTOR>Second</DESCRIPTOR><TNR>tgm000001</TNR><TTCSubj>MARC 150/650</TTCSubj></CONCEPT>
    </THESAURUS>"""

    # Act / Assert
    with pytest.raises(TgmImportError, match="conflicting descriptor TNR"):
        TgmImporter().import_bytes(
            raw,
            source_url="https://example.test/tgm.xml",
            source_format=TgmSourceFormat.XML,
            imported_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        )


def test_tgm_importer_unresolved_and_unsupported_records_are_diagnostics() -> None:
    # Arrange
    raw = b"""<THESAURUS>
      <CONCEPT><DESCRIPTOR>Valid</DESCRIPTOR><TNR>tgm000001</TNR><TTCSubj>MARC 150/650</TTCSubj></CONCEPT>
      <CONCEPT><DESCRIPTOR>Unsupported</DESCRIPTOR><TNR>tgm000002</TNR><TTCSubj>MARC 100/600</TTCSubj></CONCEPT>
      <CONCEPT><DESCRIPTOR>Reference only</DESCRIPTOR><TNR>tgm000003</TNR><TTCRef>Reference</TTCRef></CONCEPT>
      <CONCEPT><NON-DESCRIPTOR>Lost alias</NON-DESCRIPTOR><USE>Missing target</USE><TNR>tgm000004</TNR></CONCEPT>
    </THESAURUS>"""

    # Act
    snapshot = TgmImporter().import_bytes(
        raw,
        source_url="https://example.test/tgm.xml",
        source_format=TgmSourceFormat.XML,
        imported_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
    )

    # Assert
    reference = snapshot.concept_by_id("loc-tgm:tgm000003")
    assert reference is not None
    assert not reference.selectable
    assert len(snapshot.selectable_concepts) == 1
    assert {diagnostic.code for diagnostic in snapshot.diagnostics} == {
        TgmDiagnosticCode.UNRESOLVED_USE,
        TgmDiagnosticCode.UNSUPPORTED_CATEGORY,
    }


def test_tgm_importer_xml_with_entity_declaration_is_rejected() -> None:
    # Arrange
    raw = b"""<?xml version="1.0"?>
    <!DOCTYPE THESAURUS [<!ENTITY external SYSTEM "https://example.test/value">]>
    <THESAURUS><CONCEPT><DESCRIPTOR>&external;</DESCRIPTOR><TNR>tgm000001</TNR></CONCEPT></THESAURUS>"""

    # Act / Assert
    with pytest.raises(ValueError, match="DTD or entity"):
        TgmImporter().import_bytes(
            raw,
            source_url="https://example.test/tgm.xml",
            source_format=TgmSourceFormat.XML,
            imported_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        )


    def test_tgm_importer_xml_with_official_element_dtd_is_accepted() -> None:
      # Arrange
      raw = b"""<?xml version="1.0" encoding="utf-8"?>
      <!-- Created: 7/29/2026 11:55:28 AM -->
      <!DOCTYPE THESAURUS [
      <!ELEMENT THESAURUS (CONCEPT+)>
      <!ELEMENT CONCEPT (DESCRIPTOR,TTCSubj,TNR)>
      <!ELEMENT DESCRIPTOR (#PCDATA)>
      <!ELEMENT TTCSubj (#PCDATA)>
      <!ELEMENT TNR (#PCDATA)>
      ]>
      <THESAURUS><CONCEPT>
        <DESCRIPTOR>Forests</DESCRIPTOR>
        <TTCSubj>Subject (MARC 150/650)</TTCSubj>
        <TNR>tgm000001</TNR>
      </CONCEPT></THESAURUS>"""

      # Act
      snapshot = TgmImporter().import_bytes(
        raw,
        source_url="https://example.test/tgm.xml",
        source_format=TgmSourceFormat.XML,
        imported_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
      )

      # Assert
      assert snapshot.selectable_concepts[0].concept_id == "loc-tgm:tgm000001"
      assert snapshot.distribution_date == "2026-07-29T11:55:28"