# app/engine/pricing.py
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import yaml

from app.engine.geometry import apply_waste, line_area_m2

MONEY_QUANT = Decimal("0.01")


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def load_rules(path: str | Path) -> dict:
    with open(path) as f:
        raw = yaml.safe_load(f)
    return {
        "glass_prices_per_m2": {k: Decimal(str(v)) for k, v in raw["glass_prices_per_m2"].items()},
        "waste_percent": Decimal(str(raw["waste_percent"])),
        "minimum_charge_per_panel": Decimal(str(raw["minimum_charge_per_panel"])),
        "labour_per_panel": Decimal(str(raw["labour"]["per_panel"])),
        "labour_per_m2": Decimal(str(raw["labour"]["per_m2"])),
        "gst_percent": Decimal(str(raw["gst_percent"])),
    }


@dataclass
class PanelInput:
    label: str
    width_mm: int
    height_mm: int
    qty: int
    glass_type: str


@dataclass
class HardwareInput:
    code: str
    qty: int
    unit_price: Decimal


@dataclass
class PanelLineResult:
    label: str
    area_m2: Decimal
    line_total: Decimal


@dataclass
class PricingResult:
    panel_lines: list[PanelLineResult]
    glass_subtotal: Decimal
    waste_amount: Decimal
    labour_amount: Decimal
    hardware_subtotal: Decimal
    gst_amount: Decimal
    total: Decimal
    hardware_line_totals: list[Decimal] = field(default_factory=list)


def _price_panel(panel: PanelInput, rules: dict) -> tuple[PanelLineResult, Decimal, Decimal]:
    price_per_m2 = rules["glass_prices_per_m2"][panel.glass_type]
    area_no_waste = line_area_m2(panel.width_mm, panel.height_mm, panel.qty)
    effective_area = apply_waste(area_no_waste, rules["waste_percent"])

    raw_cost = quantize_money(area_no_waste * price_per_m2)
    cost_with_waste = quantize_money(effective_area * price_per_m2)
    line_total = max(cost_with_waste, rules["minimum_charge_per_panel"])

    line = PanelLineResult(label=panel.label, area_m2=area_no_waste, line_total=line_total)
    waste_contribution = line_total - raw_cost
    return line, line_total, waste_contribution


def price_quote(
    panels: list[PanelInput], hardware_lines: list[HardwareInput], rules: dict
) -> PricingResult:
    panel_lines: list[PanelLineResult] = []
    glass_subtotal = Decimal("0.00")
    waste_amount = Decimal("0.00")
    labour_amount = Decimal("0.00")

    for panel in panels:
        line, line_total, waste_contribution = _price_panel(panel, rules)
        panel_lines.append(line)
        glass_subtotal += line_total
        waste_amount += waste_contribution
        labour_amount += rules["labour_per_panel"] * panel.qty + rules["labour_per_m2"] * line.area_m2

    glass_subtotal = quantize_money(glass_subtotal)
    waste_amount = quantize_money(waste_amount)
    labour_amount = quantize_money(labour_amount)

    hardware_line_totals = [quantize_money(h.unit_price * h.qty) for h in hardware_lines]
    hardware_subtotal = quantize_money(sum(hardware_line_totals, Decimal("0.00")))

    subtotal_before_gst = glass_subtotal + hardware_subtotal + labour_amount
    gst_amount = quantize_money(subtotal_before_gst * rules["gst_percent"] / Decimal("100"))
    total = subtotal_before_gst + gst_amount

    return PricingResult(
        panel_lines=panel_lines,
        glass_subtotal=glass_subtotal,
        waste_amount=waste_amount,
        labour_amount=labour_amount,
        hardware_subtotal=hardware_subtotal,
        gst_amount=gst_amount,
        total=total,
        hardware_line_totals=hardware_line_totals,
    )
