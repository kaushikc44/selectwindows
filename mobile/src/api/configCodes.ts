// Mirrors app/engine/config_codes.py's vocabulary exactly — the config
// code produced here must parse cleanly on the backend. Replaces the old
// free-text config_code field with a structured "tap to configure" picker
// (per the stakeholder feedback: no freehand drawing, tap panels/type
// instead), so a worker never has to remember/type the shorthand.

export interface ConfigOption {
  code: string; // exact code the backend expects, e.g. "SL2", "BFW-4"
  label: string;
  category: "window" | "door";
  // The ProductType this config code always implies (see
  // app/engine/product_hint.py / app/models.py::ProductType) — derived
  // automatically rather than asked for separately, so there's no way for
  // a worker to pick a config code and product type that disagree.
  productType: string;
  needsPanelCount?: boolean; // SL/SD/BFW/BFD/STK take a panel/lite count
  needsDirection?: boolean; // CA/HD take a hinge side
}

export const WINDOW_CONFIGS: ConfigOption[] = [
  { code: "AW", label: "Awning", category: "window", productType: "awning" },
  { code: "CA", label: "Casement", category: "window", productType: "casement", needsDirection: true },
  { code: "DH", label: "Double Hung", category: "window", productType: "double_hung" },
  { code: "SL", label: "Sliding", category: "window", productType: "sliding", needsPanelCount: true },
  { code: "LV", label: "Louvre", category: "window", productType: "louvre" },
  { code: "PW", label: "Powerlouvre", category: "window", productType: "powerlouvre" },
  { code: "SS", label: "Sashless", category: "window", productType: "sashless" },
  { code: "GS", label: "Gas Strut", category: "window", productType: "gas_strut" },
  { code: "BFW", label: "Bi-fold", category: "window", productType: "bi_fold", needsPanelCount: true },
];

export const DOOR_CONFIGS: ConfigOption[] = [
  { code: "HD", label: "Hinged", category: "door", productType: "hinged", needsDirection: true },
  { code: "SD", label: "Sliding", category: "door", productType: "sliding", needsPanelCount: true },
  { code: "STK", label: "Stacker", category: "door", productType: "stacking", needsPanelCount: true },
  { code: "BFD", label: "Bi-fold", category: "door", productType: "bi_fold", needsPanelCount: true },
  { code: "CED", label: "Cedar Entry", category: "door", productType: "cedar_entry" },
];

export const PANEL_COUNTS = [2, 3, 4, 5, 6] as const;
export const DIRECTIONS = [
  { value: "L", label: "Left" },
  { value: "R", label: "Right" },
] as const;

// Builds the exact string app/engine/config_codes.py::parse_config_code
// expects, e.g. "SL2", "CA-L", "BFD-4".
export function buildConfigCode(
  option: ConfigOption,
  panelCount: number | null,
  direction: "L" | "R" | null
): string {
  if (option.needsPanelCount && panelCount) return `${option.code}${panelCount}`;
  if (option.needsDirection && direction) return `${option.code}-${direction}`;
  return option.code;
}
