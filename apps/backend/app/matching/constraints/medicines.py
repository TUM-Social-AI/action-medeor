"""Known medicine attribute names; business severities live in policy data."""

MEDICINE_ATTRIBUTES = frozenset(
    {
        "active_ingredient",
        "strength",
        "concentration",
        "dosage_form",
        "route",
        "sterile",
    }
)
