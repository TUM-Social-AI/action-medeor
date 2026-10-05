from decimal import Decimal

import pytest

from app.catalog.package_contents import package_from_erp_description
from app.catalog.parser import parse_catalog_files
from tests.catalog.test_parser import ARTICLE_HEADER, TRANSLATION_HEADER


@pytest.mark.parametrize(
    "description,base_unit,count,unit",
    [
        ("Fixierpflaster 1,25 cm x 9,1 m Kunstseide, 24 Rollen", "PAKET", "24", "roll"),
        ("Acetylsalicylic acid 500 mg tablets, 1000", "DOSE", "1000", "tablet"),
        ("Paracetamol 500 mg tablets, blister, 10 x 10", "PAKET", "100", "tablet"),
        ("Amoxicillin 500 mg capsules, blister, 100*10", "PAKET", "1000", "capsule"),
        ("Tablet 500 mg, blister, 4 × 14", "PAKET", "56", "tablet"),
        ("Lidocaine 2% injection, vial (20 ml), 20", "PAKET", "20", "vial"),
        ("Diclofenac 25 mg/ml injection, ampoule (3 ml), 50", "PAKET", "50", "ampoule"),
        ("Food 92 g, 150 sachets", "PAKET", "150", "sachet"),
        ("Gloves size 7, 50 Paar", "PAKET", "50", "pair"),
        ("Mullkompressen 10 cm x 10 cm, 10 x 100 Stück", "PAKET", "1000", "piece"),
        ("Syringes 10 ml, 1.000 Stück", "DOSE", "1000", "piece"),
        ("Nahtmaterial, steril, 2Dtzd.", "PAKET", "24", "piece"),
        ("Nahtmaterial, 1 Dzd.", "PAKET", "12", "piece"),
        ("Nahtmaterial, 1 DZ", "PAKET", "12", "piece"),
        ("Ibuprofen 100 mg / 5 ml, bottle (200ml), 1", "FLASCHE", "1", "bottle"),
        ("Cream, tube (15g),1", "STÜCK", "1", "tube"),
        ("Tape 50 m, 1 Rolle", "ROLLE", "1", "roll"),
        ("DNA/RNA kit, 100 Tests", "PAKET", "100", "test"),
        ("Thermometer, 1 piece", "STÜCK", "1", "piece"),
    ],
)
def test_erp_final_segment_extracts_count_and_contained_unit(description, base_unit, count, unit):
    package = package_from_erp_description(description, base_unit)
    assert package is not None
    assert package.units_per_package == Decimal(count)
    assert package.unit == unit
    assert package.stock_unit == base_unit
    assert "ERP description" in package.package_label


@pytest.mark.parametrize(
    "description,base_unit",
    [
        ("Paracetamol 500 mg tablets", "DOSE"),
        ("Fixierpflaster, 5 cm", "PAKET"),
        ("Bottle, 100 ml", "PAKET"),
        ("Vitamin D, 10.000 IU", "DOSE"),
        ("Antibiotic, 500 mg", "DOSE"),
        ("Gigasept, 1,5kg Eimer", "EIMER"),
        ("Tablets, 1,5", "DOSE"),
        ("Syringes, 1,000 Stück", "DOSE"),
        ("Catheter CH18, 50", "PAKET"),
        ("Tablets and capsules, 100", "DOSE"),
        ("Syringes, 0 Stück", "PAKET"),
        ("Syringes, -50 Stück", "PAKET"),
        ("Tablets, 10 / 20", "PAKET"),
        ("Tablets, 0 x 10", "PAKET"),
        ("Bottle (100 ml), 10", "FLASCHE"),
        ("Tablet, 100", None),
        ("Tablet, 100", "unknown"),
        ("Tablet, 100", "mg"),
        ("Item, sterile", "PAKET"),
    ],
)
def test_measurements_and_ambiguous_suffixes_do_not_create_conversions(description, base_unit):
    assert package_from_erp_description(description, base_unit) is None


def test_import_uses_article_description_only_and_keeps_variants_separate():
    articles = (
        ARTICLE_HEADER
        + "401101000;;Tape, 24 Rollen;;PAKET;404;nein;0;0;0;2;nein;nein;nein\n"
        + "401101001;401101000;Tape, 24 Rollen;;PAKET;404;nein;60;15;5;2;nein;nein;ja\n"
        + "401101002;401101000;Tape, 12 Rollen;;PAKET;404;nein;100;0;0;2;nein;nein;nein\n"
        + "401101003;401101000;Tape;;PAKET;404;nein;100;0;0;2;nein;nein;nein\n"
    ).encode()
    translated = (TRANSLATION_HEADER + "401101003;ENU;Tape, 99 rolls;;\n").encode()
    parsed = parse_catalog_files(articles, translated)
    assert parsed.items[0].package is None
    assert parsed.items[1].package.units_per_package == 24
    assert parsed.items[2].package.units_per_package == 12
    assert parsed.items[3].package is None
