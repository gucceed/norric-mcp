"""
Postcode-prefix → (kommunkod, county) mapping for Swedish municipalities.
Primary: 3-digit postcode prefix lookup.
Fallback: city name substring match.
"""
from __future__ import annotations

# Maps 3-digit postcode prefix → (kommunkod, county_name)
_PREFIX: dict[str, tuple[str, str]] = {
    # ── Skåne ────────────────────────────────────────────────────────────────
    "211": ("1280", "Skåne"), "212": ("1280", "Skåne"), "213": ("1280", "Skåne"),
    "214": ("1280", "Skåne"), "215": ("1280", "Skåne"), "216": ("1280", "Skåne"),
    "217": ("1280", "Skåne"), "218": ("1280", "Skåne"), "219": ("1280", "Skåne"),
    "220": ("1281", "Skåne"), "221": ("1281", "Skåne"), "222": ("1281", "Skåne"),
    "223": ("1281", "Skåne"), "224": ("1281", "Skåne"), "225": ("1281", "Skåne"),
    "226": ("1281", "Skåne"), "227": ("1281", "Skåne"), "228": ("1281", "Skåne"),
    "230": ("1287", "Skåne"), "231": ("1287", "Skåne"),  # Vellinge/Trelleborg area
    "232": ("1286", "Skåne"), "233": ("1286", "Skåne"),  # Malmö south / Staffanstorp
    "234": ("1285", "Skåne"),                              # Vellinge
    "235": ("1285", "Skåne"),
    "236": ("1230", "Skåne"),                              # Burlöv
    "237": ("1230", "Skåne"),
    "238": ("1281", "Skåne"),                              # Lund south
    "239": ("1287", "Skåne"),                              # Trelleborg
    "240": ("1282", "Skåne"),                              # Eslöv
    "241": ("1282", "Skåne"),
    "242": ("1282", "Skåne"),
    "243": ("1275", "Skåne"),                              # Perstorp
    "244": ("1270", "Skåne"),                              # Tomelilla
    "245": ("1293", "Skåne"),                              # Ystad
    "246": ("1293", "Skåne"),
    "247": ("1276", "Skåne"),                              # Klippan
    "248": ("1292", "Skåne"),                              # Simrishamn
    "249": ("1292", "Skåne"),
    "250": ("1283", "Skåne"),                              # Helsingborg
    "251": ("1283", "Skåne"), "252": ("1283", "Skåne"),
    "253": ("1283", "Skåne"), "254": ("1283", "Skåne"),
    "255": ("1283", "Skåne"), "256": ("1283", "Skåne"),
    "257": ("1283", "Skåne"), "258": ("1283", "Skåne"),
    "260": ("1278", "Skåne"),                              # Örkelljunga / Bjuv
    "261": ("1231", "Skåne"),                              # Landskrona
    "262": ("1231", "Skåne"),
    "263": ("1278", "Skåne"),                              # Åstorp
    "264": ("1290", "Skåne"),                              # Kristianstad area
    "265": ("1290", "Skåne"),
    "266": ("1272", "Skåne"),                              # Bromölla
    "267": ("1272", "Skåne"),
    "268": ("1277", "Skåne"),                              # Åstorp
    "269": ("1277", "Skåne"),
    "270": ("1263", "Skåne"),                              # Sjöbo
    "271": ("1263", "Skåne"),
    "272": ("1273", "Skåne"),                              # Osby
    "273": ("1273", "Skåne"),
    "274": ("1274", "Skåne"),                              # Östra Göinge
    "275": ("1291", "Skåne"),                              # Hässleholm
    "276": ("1291", "Skåne"),
    "277": ("1291", "Skåne"),
    "278": ("1291", "Skåne"),
    "279": ("1291", "Skåne"),
    "280": ("1284", "Skåne"),                              # Höganäs
    "281": ("1284", "Skåne"),
    "282": ("1261", "Skåne"),                              # Kävlinge
    "283": ("1261", "Skåne"),
    "284": ("1265", "Skåne"),                              # Sjöbo
    "285": ("1265", "Skåne"),
    "286": ("1266", "Skåne"),                              # Hörby
    "287": ("1266", "Skåne"),
    "288": ("1267", "Skåne"),                              # Höör
    "289": ("1267", "Skåne"),
    "290": ("1264", "Skåne"),                              # Skurup
    "291": ("1264", "Skåne"),
    "292": ("1290", "Skåne"),                              # Kristianstad
    "293": ("1290", "Skåne"),
    "294": ("1290", "Skåne"),
    "295": ("1272", "Skåne"),                              # Bromölla
    "296": ("1272", "Skåne"),
    "297": ("1272", "Skåne"),
    "298": ("1272", "Skåne"),
    "299": ("1283", "Skåne"),                              # Helsingborg N

    # ── Stockholm ─────────────────────────────────────────────────────────────
    "100": ("0180", "Stockholm"), "101": ("0180", "Stockholm"),
    "102": ("0180", "Stockholm"), "103": ("0180", "Stockholm"),
    "104": ("0180", "Stockholm"), "105": ("0180", "Stockholm"),
    "106": ("0180", "Stockholm"), "107": ("0180", "Stockholm"),
    "108": ("0180", "Stockholm"), "109": ("0180", "Stockholm"),
    "110": ("0180", "Stockholm"), "111": ("0180", "Stockholm"),
    "112": ("0180", "Stockholm"), "113": ("0180", "Stockholm"),
    "114": ("0180", "Stockholm"), "115": ("0180", "Stockholm"),
    "116": ("0180", "Stockholm"), "117": ("0180", "Stockholm"),
    "118": ("0180", "Stockholm"), "119": ("0180", "Stockholm"),
    "120": ("0180", "Stockholm"), "121": ("0127", "Stockholm"),  # Botkyrka
    "122": ("0163", "Stockholm"),                                  # Lidingö
    "123": ("0162", "Stockholm"),                                  # Nacka
    "124": ("0181", "Stockholm"),                                  # Södertälje
    "125": ("0127", "Stockholm"),
    "126": ("0184", "Stockholm"),                                  # Solna
    "127": ("0184", "Stockholm"),
    "128": ("0183", "Stockholm"),                                  # Sundbyberg
    "129": ("0183", "Stockholm"),
    "130": ("0182", "Stockholm"),                                  # Danderyd
    "131": ("0182", "Stockholm"),
    "132": ("0186", "Stockholm"),                                  # Värmdö
    "133": ("0186", "Stockholm"),
    "134": ("0185", "Stockholm"),                                  # Täby
    "135": ("0185", "Stockholm"),
    "136": ("0188", "Stockholm"),                                  # Norrtälje
    "137": ("0188", "Stockholm"),
    "138": ("0191", "Stockholm"),                                  # Sigtuna
    "139": ("0191", "Stockholm"),

    # ── Göteborg ──────────────────────────────────────────────────────────────
    "400": ("1480", "Västra Götaland"), "401": ("1480", "Västra Götaland"),
    "402": ("1480", "Västra Götaland"), "403": ("1480", "Västra Götaland"),
    "404": ("1480", "Västra Götaland"), "405": ("1480", "Västra Götaland"),
    "406": ("1480", "Västra Götaland"), "407": ("1480", "Västra Götaland"),
    "408": ("1480", "Västra Götaland"), "409": ("1480", "Västra Götaland"),
    "410": ("1480", "Västra Götaland"), "411": ("1480", "Västra Götaland"),
    "412": ("1480", "Västra Götaland"), "413": ("1480", "Västra Götaland"),
    "414": ("1480", "Västra Götaland"), "415": ("1480", "Västra Götaland"),
    "416": ("1480", "Västra Götaland"), "417": ("1480", "Västra Götaland"),
    "418": ("1480", "Västra Götaland"), "419": ("1480", "Västra Götaland"),
    "420": ("1481", "Västra Götaland"),                              # Mölndal
    "421": ("1481", "Västra Götaland"),
    "422": ("1482", "Västra Götaland"),                              # Kungälv
    "423": ("1482", "Västra Götaland"),
    "424": ("1484", "Västra Götaland"),                              # Alingsås
    "425": ("1484", "Västra Götaland"),

    # ── Uppsala ────────────────────────────────────────────────────────────────
    "750": ("0380", "Uppsala"), "751": ("0380", "Uppsala"),
    "752": ("0380", "Uppsala"), "753": ("0380", "Uppsala"),
    "754": ("0380", "Uppsala"), "755": ("0380", "Uppsala"),
    "756": ("0380", "Uppsala"),

    # ── Linköping / Norrköping ────────────────────────────────────────────────
    "580": ("0580", "Östergötland"), "581": ("0580", "Östergötland"),
    "582": ("0580", "Östergötland"), "583": ("0580", "Östergötland"),
    "584": ("0580", "Östergötland"),
    "600": ("0581", "Östergötland"), "601": ("0581", "Östergötland"),
    "602": ("0581", "Östergötland"), "603": ("0581", "Östergötland"),
    "604": ("0581", "Östergötland"),
}

# City name → (kommunkod, county) fallback for common cities
_CITY_FALLBACK: dict[str, tuple[str, str]] = {
    "malmö": ("1280", "Skåne"),
    "lund": ("1281", "Skåne"),
    "helsingborg": ("1283", "Skåne"),
    "kristianstad": ("1290", "Skåne"),
    "hässleholm": ("1291", "Skåne"),
    "landskrona": ("1231", "Skåne"),
    "trelleborg": ("1287", "Skåne"),
    "ystad": ("1293", "Skåne"),
    "eslöv": ("1282", "Skåne"),
    "vellinge": ("1285", "Skåne"),
    "burlöv": ("1230", "Skåne"),
    "staffanstorp": ("1286", "Skåne"),
    "höganäs": ("1284", "Skåne"),
    "kävlinge": ("1261", "Skåne"),
    "sjöbo": ("1263", "Skåne"),
    "hörby": ("1266", "Skåne"),
    "höör": ("1267", "Skåne"),
    "skurup": ("1264", "Skåne"),
    "bjuv": ("1278", "Skåne"),
    "klippan": ("1276", "Skåne"),
    "åstorp": ("1277", "Skåne"),
    "örkelljunga": ("1278", "Skåne"),
    "perstorp": ("1275", "Skåne"),
    "osby": ("1273", "Skåne"),
    "bromölla": ("1272", "Skåne"),
    "simrishamn": ("1292", "Skåne"),
    "tomelilla": ("1270", "Skåne"),
    "östra göinge": ("1274", "Skåne"),
    "stockholm": ("0180", "Stockholm"),
    "göteborg": ("1480", "Västra Götaland"),
    "gothenburg": ("1480", "Västra Götaland"),
    "uppsala": ("0380", "Uppsala"),
    "linköping": ("0580", "Östergötland"),
    "norrköping": ("0581", "Östergötland"),
    "örebro": ("1880", "Örebro"),
    "västerås": ("1980", "Västmanland"),
    "sundsvall": ("2281", "Västernorrland"),
    "umeå": ("2480", "Västerbotten"),
}


def resolve_kommunkod(postcode: str, city: str) -> tuple[str, str]:
    """Return (kommunkod, county). Empty string if unknown."""
    clean = postcode.replace(" ", "")
    if len(clean) >= 3:
        prefix = clean[:3]
        if prefix in _PREFIX:
            return _PREFIX[prefix]

    norm_city = city.lower().strip()
    if norm_city in _CITY_FALLBACK:
        return _CITY_FALLBACK[norm_city]

    # Partial city match
    for key, val in _CITY_FALLBACK.items():
        if key in norm_city or norm_city in key:
            return val

    return ("", "")
