import pytest

from app.parsing.item_language import item_language


@pytest.mark.parametrize(('name', 'expected'), [
    ('Aiguille stérile à usage unique', 'fr'),
    ('حقنة معقمة للاستخدام مرة واحدة', 'ar'),
    ('Dies ist eine sterile Einmalspritze für den medizinischen Gebrauch', 'de'),
    ('', None),
    ('12345', None),
    ('Paracetamol 500mg', None),
])
def test_detects_source_language_without_guessing_ambiguous_names(name, expected):
    assert item_language(name) == expected
