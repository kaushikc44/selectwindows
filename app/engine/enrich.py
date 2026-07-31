# app/engine/enrich.py
"""Tier-3 enrichment: glass spec, safety-glass mandate, hardware, energy
figures, base labour. NEVER extracted from an email/photo, NEVER invented by
an LLM — filled only from defaults.yaml, keyed by product_type x material x
size_band. source is always "default"; an unrecognized product_type/material
is flagged rather than silently substituted."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


def load_defaults(path: str | Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


@dataclass
class EnrichmentResult:
    glass_spec: str
    safety_glass_required: bool
    hardware: list[str]
    energy_u_value: float | None
    energy_shgc: float | None
    labour_hours: float
    men_required: int
    unrecognized: bool
    source: str = field(default="default")
    # Populated only when source == "llm_estimate" — an interim,
    # user-approved AI-generated materials breakdown, never filled by
    # enrich_item()'s deterministic YAML lookup.
    frame_components: list[str] | None = None
    sealant_and_fixings: list[str] | None = None
    notes: str | None = None


def enrich_item(product_type: str, material: str, size_band: str, defaults: dict) -> EnrichmentResult:
    table = defaults["enrichment"]
    fallback_row = table["unknown"]["unknown"]

    unrecognized = product_type not in table
    product_row = table.get(product_type, table["unknown"])

    unrecognized = unrecognized or (material not in product_row)
    material_row = product_row.get(material, product_row.get("unknown", fallback_row))

    labour_by_band = material_row["labour_hours_per_item"]
    labour_hours = labour_by_band.get(size_band, labour_by_band["medium"])

    return EnrichmentResult(
        glass_spec=material_row["glass_spec"],
        safety_glass_required=material_row["safety_glass_required"],
        hardware=list(material_row["hardware"]),
        energy_u_value=material_row["energy"]["u_value"],
        energy_shgc=material_row["energy"]["shgc"],
        labour_hours=labour_hours,
        men_required=material_row["men_required"],
        unrecognized=unrecognized,
    )


def wind_rating_n_class(wind_rating: str, defaults: dict) -> str:
    table = defaults["wind_rating_to_n_class"]
    return table.get(wind_rating, table["other"])


def reveal_depth_for_construction(construction: str | None, defaults: dict) -> str | int:
    table = defaults["reveal_depth_by_construction"]
    if construction is None:
        return table["other"]
    return table.get(construction, table["other"])
