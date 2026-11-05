"""Conservative, offline language labels for item names (no LLM requests)."""

from functools import lru_cache

from lingua import LanguageDetectorBuilder


@lru_cache(maxsize=1)
def _detector():
    return LanguageDetectorBuilder.from_all_languages().build()


@lru_cache(maxsize=4096)
def item_language(name: str) -> str | None:
    if sum(character.isalpha() for character in name) < 5:
        return None
    confidence = _detector().compute_language_confidence_values(name)
    # Medical names, brand names and abbreviations often occur in many languages.
    # Prefer an unknown label over presenting a weak guess as a fact.
    if not confidence or confidence[0].value < 0.70:
        return None
    return confidence[0].language.iso_code_639_1.name.lower()
