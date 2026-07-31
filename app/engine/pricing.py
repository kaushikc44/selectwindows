# app/engine/pricing.py
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import yaml

MONEY_QUANT = Decimal("0.01")
MIN_DIM_MM = 100
# 20000, not 6000 — a summed multi-section commercial opening (see
# app/workers/routing.py::_sum_partial_segments) can legitimately exceed a
# single window/door's span. Keep in sync with app/schemas.py's bounds.
MAX_DIM_MM = 20000

_GLASS_KEYWORDS: dict[str, list[str]] = {
    "double_glazed": ["double glazed", "double-glazed", "double_glazed"],
    "acoustic": ["acoustic"],
    "BAL40_pyro": ["bal40", "bal-40", "bal 40", "pyro"],
    "toughened": ["toughened", "temper"],
    "single": ["single"],
}


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def validate_dimensions(width_mm: int, height_mm: int) -> None:
    for name, value in (("width_mm", width_mm), ("height_mm", height_mm)):
        if not (MIN_DIM_MM <= value <= MAX_DIM_MM):
            raise ValueError(f"{name}={value} out of range [{MIN_DIM_MM}, {MAX_DIM_MM}]")


def load_rules(path: str | Path) -> dict:
    with open(path) as f:
        raw = yaml.safe_load(f)
    return {
        "placeholder": raw.get("placeholder", False),
        "base_prices": {
            product: {material: Decimal(str(price)) for material, price in materials.items()}
            for product, materials in raw["base_prices"].items()
        },
        "size_bands": [
            {"band": b["band"], "max_mm": b["max_mm"], "multiplier": Decimal(str(b["multiplier"]))}
            for b in raw["size_bands"]
        ],
        "glass_multipliers": {k: Decimal(str(v)) for k, v in raw["glass_multipliers"].items()},
        "installation": {
            "per_item_base_fee": Decimal(str(raw["installation"]["per_item_base_fee"])),
            "floor_level_surcharge": {
                k: Decimal(str(v)) for k, v in raw["installation"]["floor_level_surcharge"].items()
            },
            "brick_removal_per_m2": Decimal(str(raw["installation"]["brick_removal_per_m2"])),
            "scaffold_flat_fee": Decimal(str(raw["installation"]["scaffold_flat_fee"])),
            "hoist_flat_fee": Decimal(str(raw["installation"]["hoist_flat_fee"])),
            "brick_saw_flat_fee": Decimal(str(raw["installation"]["brick_saw_flat_fee"])),
        },
        "gst_percent": Decimal(str(raw["gst_percent"])),
    }


@dataclass
class ItemInput:
    item_no: int
    product_type: str
    material: str
    height_mm: int
    width_mm: int
    qty: int


@dataclass
class InstallationInput:
    floor_level: str | None = None
    brick_removal_m2: float | None = None
    scaffold: str | None = None
    hoist: str | None = None
    brick_saw: str | None = None


@dataclass
class ItemLineResult:
    item_no: int
    size_band: str
    unit_price: Decimal
    line_total: Decimal


@dataclass
class PricingResult:
    item_lines: list[ItemLineResult]
    items_subtotal: Decimal
    installation_subtotal: Decimal
    gst_amount: Decimal
    total: Decimal
    item_lines_by_no: dict[int, ItemLineResult] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.item_lines_by_no = {line.item_no: line for line in self.item_lines}


def size_band(height_mm: int, width_mm: int, rules: dict) -> tuple[str, Decimal]:
    validate_dimensions(width_mm, height_mm)
    largest = max(height_mm, width_mm)
    for band in rules["size_bands"]:
        if largest <= band["max_mm"]:
            return band["band"], band["multiplier"]
    last = rules["size_bands"][-1]
    return last["band"], last["multiplier"]


def map_glass_option(glass_text: str | None, rules: dict) -> str:
    if not glass_text:
        return "single"
    normalized = glass_text.lower()
    for option, keywords in _GLASS_KEYWORDS.items():
        if option in rules["glass_multipliers"] and any(kw in normalized for kw in keywords):
            return option
    return "single"


def price_item(item: ItemInput, glass_option: str, rules: dict) -> ItemLineResult:
    band, multiplier = size_band(item.height_mm, item.width_mm, rules)
    product_prices = rules["base_prices"].get(item.product_type, rules["base_prices"]["unknown"])
    base = product_prices.get(item.material, product_prices["unknown"])
    glass_multiplier = rules["glass_multipliers"].get(glass_option, Decimal("1.0"))

    unit_price = quantize_money(base * multiplier * glass_multiplier)
    line_total = quantize_money(unit_price * item.qty)
    return ItemLineResult(item_no=item.item_no, size_band=band, unit_price=unit_price, line_total=line_total)


def price_installation(installation: InstallationInput | None, item_count: int, rules: dict) -> Decimal:
    rules_i = rules["installation"]
    fee = rules_i["per_item_base_fee"] * item_count

    if installation is not None:
        if installation.floor_level and installation.floor_level != "unmarked":
            fee += rules_i["floor_level_surcharge"].get(installation.floor_level, Decimal("0.00"))
        if installation.brick_removal_m2:
            fee += rules_i["brick_removal_per_m2"] * Decimal(str(installation.brick_removal_m2))
        if installation.scaffold == "yes":
            fee += rules_i["scaffold_flat_fee"]
        if installation.hoist == "yes":
            fee += rules_i["hoist_flat_fee"]
        if installation.brick_saw == "yes":
            fee += rules_i["brick_saw_flat_fee"]

    return quantize_money(fee)


def price_quote(
    items: list[ItemInput], installation: InstallationInput | None, glass_text: str | None, rules: dict
) -> PricingResult:
    glass_option = map_glass_option(glass_text, rules)
    item_lines = [price_item(item, glass_option, rules) for item in items]

    items_subtotal = quantize_money(sum((line.line_total for line in item_lines), Decimal("0.00")))
    installation_subtotal = price_installation(installation, len(items), rules)

    subtotal_before_gst = items_subtotal + installation_subtotal
    gst_amount = quantize_money(subtotal_before_gst * rules["gst_percent"] / Decimal("100"))
    total = subtotal_before_gst + gst_amount

    return PricingResult(
        item_lines=item_lines,
        items_subtotal=items_subtotal,
        installation_subtotal=installation_subtotal,
        gst_amount=gst_amount,
        total=total,
    )
