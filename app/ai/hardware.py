# app/ai/hardware.py
import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml

from app.ai.llm import LLMUnavailable, chat_completion
from app.schemas import PanelIn

logger = logging.getLogger(__name__)

MAX_QTY_PER_LINE = 500

HARDWARE_PROMPT_TEMPLATE = """You are estimating installation hardware for a glass job.
Panels to install:
{panels}

Choose ONLY from this catalog (use the exact "code" values, never invent new ones):
{catalog}

Return ONLY JSON, no markdown, no prose, in this exact shape:
{{"items": [{{"code": "SIL-CLEAR", "qty": 4}}]}}

Pick realistic quantities for installing these panels. Do not include price fields —
prices are looked up from the catalog, not from you."""


@dataclass
class CatalogItem:
    code: str
    name: str
    unit: str
    unit_price: Decimal


@dataclass
class PredictedHardwareLine:
    code: str
    name: str
    unit_price: Decimal
    qty: int
    estimated: bool = True


def load_catalog(path: str | Path) -> dict[str, CatalogItem]:
    with open(path) as f:
        raw = yaml.safe_load(f)
    return {
        item["code"]: CatalogItem(
            code=item["code"],
            name=item["name"],
            unit=item["unit"],
            unit_price=Decimal(str(item["unit_price"])),
        )
        for item in raw["items"]
    }


def _format_panels(panels: list[PanelIn]) -> str:
    return "\n".join(
        f"- {p.label}: {p.width_mm}x{p.height_mm}mm qty={p.qty} glass_type={p.glass_type}" for p in panels
    )


def _format_catalog(catalog: dict[str, CatalogItem]) -> str:
    return "\n".join(f"- {item.code}: {item.name} ({item.unit})" for item in catalog.values())


def _parse_items(raw_text: str) -> list:
    payload = json.loads(raw_text)
    return payload["items"]


def _build_line(entry: object, catalog: dict[str, CatalogItem]) -> PredictedHardwareLine | None:
    code = entry.get("code") if isinstance(entry, dict) else None
    qty = entry.get("qty") if isinstance(entry, dict) else None
    catalog_item = catalog.get(code)

    if catalog_item is None:
        logger.warning("Dropping unknown hardware code from LLM output: %r", code)
        return None
    if not isinstance(qty, int) or qty < 1:
        logger.warning("Dropping hardware line %s with invalid qty: %r", code, qty)
        return None

    capped_qty = min(qty, MAX_QTY_PER_LINE)
    if capped_qty != qty:
        logger.warning("Capping qty for %s from %s to %s", code, qty, capped_qty)

    return PredictedHardwareLine(
        code=catalog_item.code, name=catalog_item.name, unit_price=catalog_item.unit_price, qty=capped_qty
    )


def predict_hardware(
    panels: list[PanelIn], catalog: dict[str, CatalogItem]
) -> list[PredictedHardwareLine]:
    prompt = HARDWARE_PROMPT_TEMPLATE.format(
        panels=_format_panels(panels), catalog=_format_catalog(catalog)
    )
    try:
        raw_text = chat_completion([{"role": "user", "content": prompt}])
    except LLMUnavailable as exc:
        logger.error("Hardware prediction unavailable, skipping hardware lines: %s", exc)
        return []

    try:
        items = _parse_items(raw_text)
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.error("Hardware prediction returned unparseable JSON, skipping: %s", exc)
        return []

    lines = [_build_line(entry, catalog) for entry in items]
    return [line for line in lines if line is not None]
