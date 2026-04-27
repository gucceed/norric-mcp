"""
Lightweight keyword tagger for diarium cases.
No ML — deterministic keyword matching. Fast and predictable.
"""

_VOCAB: dict[str, list[str]] = {
    "procurement": [
        "upphandling", "anbud", "avtal", "ramavtal", "kontrakt",
        "leverantör", "inköp", "offert",
    ],
    "eldercare": [
        "äldreomsorg", "hemtjänst", "äldreboende", "omsorg", "vård och omsorg",
        "äldre", "demens", "Lov",
    ],
    "edtech": [
        "skola", "utbildning", "förskola", "lärare", "pedagogik",
        "gymnasium", "grundskola", "e-lärande",
    ],
    "it_digital": [
        "it-", "digital", "system", "plattform", "software", "saas",
        "licens", "infrastruktur", "molntjänst",
    ],
    "facilities": [
        "fastighet", "lokalvård", "städ", "drift", "underhåll",
        "fastighetsdrift", "förvaltning",
    ],
    "construction": [
        "bygg", "renovering", "ombyggnad", "nybyggnad", "entreprenad",
        "mark", "anläggning", "infrastruktur",
    ],
    "hr_workforce": [
        "personal", "bemanning", "rekryt", "lön", "kompetens",
        "personaluthyrning",
    ],
    "energy": [
        "energi", "el", "fjärrvärme", "solcell", "hållbarhet",
        "klimat", "energieffektivisering",
    ],
    "planning": [
        "detaljplan", "översiktsplan", "planbesked", "markanvisning",
        "exploatering", "plan- och bygglagen",
    ],
    "building_permit": [
        "bygglov", "rivningslov", "marklov", "förhandsbesked",
        "attefallsåtgärd",
    ],
}


def tag_case(title: str, text: str = "") -> list[str]:
    """Return list of matching tags for a case."""
    combined = (title + " " + text).lower()
    tags = []
    for tag, keywords in _VOCAB.items():
        if any(kw.lower() in combined for kw in keywords):
            tags.append(tag)
    return tags
