"""
SCB table configurations for the four priority series.
Each entry specifies the table_id, cadence, and query spec.
"""

SCB_TABLES = [
    {
        "table_id": "NV/NVN10/NVN10A",
        "title_sv": "Ny- och ombyggnad av flerbostadshus efter region och kvartal",
        "description": "Construction starts by municipality — Sigvik renovation pressure indicator",
        "cadence": "quarterly",
        "query_spec": {
            "query": [
                {"code": "Region", "selection": {"filter": "vs:RegionKommun07", "values": []}},
                {"code": "Tid", "selection": {"filter": "top", "values": ["8"]}},
            ],
            "response": {"format": "json"},
        },
    },
    {
        "table_id": "AM/AKU/AKU01",
        "title_sv": "Arbetskraftsundersökning (AKU) efter region och kön",
        "description": "Labour market by region — Kreditvakt regional risk baseline",
        "cadence": "monthly",
        "query_spec": {
            "query": [
                {"code": "Region", "selection": {"filter": "vs:RegionLan07", "values": []}},
                {"code": "Kon", "selection": {"filter": "item", "values": ["1", "2"]}},
                {"code": "Tid", "selection": {"filter": "top", "values": ["12"]}},
            ],
            "response": {"format": "json"},
        },
    },
    {
        "table_id": "NR/NR0103/NR0103ENS2010T01",
        "title_sv": "Regional BNP efter region och år",
        "description": "Regional GDP — sector risk baseline for Kreditvakt",
        "cadence": "annual",
        "query_spec": {
            "query": [
                {"code": "Region", "selection": {"filter": "vs:RegionLan07", "values": []}},
                {"code": "Tid", "selection": {"filter": "top", "values": ["8"]}},
            ],
            "response": {"format": "json"},
        },
    },
    {
        "table_id": "BO/BO0101/BO0101A/BO0101T03",
        "title_sv": "Bostadsbestånd efter region, hustyp och byggnadsår",
        "description": "Dwelling stock by building year & municipality — BRF energy risk",
        "cadence": "annual",
        "query_spec": {
            "query": [
                {"code": "Region", "selection": {"filter": "vs:RegionKommun07", "values": []}},
                {"code": "Hustyp", "selection": {"filter": "item", "values": ["FLERBOST"]}},
                {"code": "Tid", "selection": {"filter": "top", "values": ["5"]}},
            ],
            "response": {"format": "json"},
        },
    },
]

# Index by table_id for fast lookup
SCB_TABLE_MAP = {t["table_id"]: t for t in SCB_TABLES}
