"""Conservative medicine/equipment suggestions for extracted request lines."""

from __future__ import annotations

import re
from typing import Literal

from app.parsing.keywords import normalize

ProductDomain = Literal["medicine", "equipment"]

_MEDICINE_UNITS = {
    "tab", "tabs", "tablet", "tablets", "comprime", "comprimes",
    "caps", "capsule", "capsules", "gelule", "gelules",
    "vial", "vials", "ampoule", "ampoules", "ampullen",
    "suppository", "suppositories", "sachet", "sachets",
}
_EQUIPMENT_UNITS = {"pair", "pairs", "roll", "rolls", "set", "sets", "kit", "kits"}

_MEDICINE_NAME = re.compile(
    r"\b(tablets?|capsules?|pills?|ampoules?|vials?|sachets?|suppositor(?:y|ies)|"
    r"syrup|ointment|antibiotics?|vaccines?|insulin|amoxicillin|paracetamol|"
    r"ibuprofen|oral rehydration salts?|ors|oral suspension|"
    r"tabletten?|kapseln?|comprim[ée]s?|gelules?|"
    r"\d+(?:[.,]\d+)?\s*(?:mg|mcg|micrograms?|iu)|"
    r"solution for (?:injection|infusion)|eye drops?|nasal spray)\b"
)
_EQUIPMENT_NAME = re.compile(
    r"\b(catheters?|syringes?|needles?|gloves?|gauze|bandages?|dressings?|"
    r"cannulas?|masks?|scalpels?|stethoscopes?|thermometers?|test strips?|"
    r"forceps|scissors|sutures?|tubing|wheelchairs?|instruments?|"
    r"oxygen concentrators?|infusion sets?|medical devices?|"
    r"katheter|spritzen?|nadeln?|handschuhe|verbande|"
    r"seringues?|aiguilles?|gants?)\b"
)
_MEDICINE_LABEL = re.compile(
    r"\b(medicine|medicines|medication|medications|drugs?|pharmaceuticals?|"
    r"arzneimittel|medikament|medikamente|medicament|medicaments)\b|دواء|أدوية"
)
_EQUIPMENT_LABEL = re.compile(
    r"\b(equipment|devices?|medical supplies|medical materials|"
    r"medizinprodukte|medizingerate|gerate|dispositifs? medicaux|"
    r"materiel medical|equipement)\b|معدات|أجهزة"
)


def explicit_domain(value: str) -> ProductDomain | None:
    """Read a source column's classification only when it unambiguously names one domain."""
    folded = normalize(value)
    medicine = bool(_MEDICINE_LABEL.search(folded))
    equipment = bool(_EQUIPMENT_LABEL.search(folded))
    if medicine == equipment:
        return None
    return "medicine" if medicine else "equipment"


def suggest_domain(name: str, unit: str, *, source_type: str = "") -> ProductDomain | None:
    """Prefer an explicit source type, then a specific unit, then recognizable name wording.

    Generic quantities such as pieces, boxes and bags give no domain signal. Conflicting
    unit/name signals stay unclassified for human review.
    """
    if source_type:
        stated = explicit_domain(source_type)
        if stated:
            return stated

    unit_tokens = re.findall(r"[\w]+", normalize(unit))
    unit_medicine = any(token in _MEDICINE_UNITS for token in unit_tokens)
    unit_equipment = any(token in _EQUIPMENT_UNITS for token in unit_tokens)
    name_folded = normalize(name)
    name_medicine = bool(_MEDICINE_NAME.search(name_folded))
    name_equipment = bool(_EQUIPMENT_NAME.search(name_folded))

    if (unit_medicine or name_medicine) and (unit_equipment or name_equipment):
        return None
    if unit_medicine:
        return "medicine"
    if unit_equipment:
        return "equipment"
    if name_medicine:
        return "medicine"
    if name_equipment:
        return "equipment"
    return None
