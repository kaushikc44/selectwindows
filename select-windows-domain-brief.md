# Select Window Installations — domain brief

Authoritative reference for field meanings, taxonomy, and business rules used
across the extraction/enrichment/pricing pipeline. If code and this brief
disagree, this brief wins for *meaning*; `app/engine/rules.yaml` and
`app/engine/defaults.yaml` win for *placeholder values* (neither holds real
Select Windows prices yet — both are explicitly flagged `placeholder: true`).

## The business

Select Window Installations (Brookvale, Sydney, since 2007) supplies and
installs replacement windows and doors — residential, commercial, strata/unit
blocks. They do **not** sell raw glass by the m². They quote per **product
unit** (a window or door of a given type, material, and size), plus
installation labour. Workflow: initial quote → check-measure on site →
manufacture → install. 10-year installation warranty. GST applies (AU).

## What gets digitized, and how

One email = one job. The email may contain **any mix** of:

- **AR-measure screenshots** (iPhone Measure app): a photo with overlay
  "pills" showing a reading, e.g. `"79 cm"`, `"1.48 m"`. Accuracy is only
  ±10–20mm, so every AR-sourced dimension carries a mandatory flag:
  *"AR measurement ±20mm — site check measure required before ordering."*
  Orientation is ambiguous — a `"79 cm"` pill could be depth, width, or
  height — pair values where possible but mark the axis `"unlabelled"`
  unless the email body clarifies it.
- **Photos of the Select paper form** (pages 1–3, schema below).
- **Hand sketches** — store the crop; extract *only* written numeric
  annotations (`source="sketch_annotation"`). Never interpret the drawn
  geometry itself.
- **Email body free text** — client name, product, room, site conditions.

Nothing is guaranteed present except at least one dimension source.

## The paper form (pages 1–3)

**Page 1 — Quote Request header + items table.** Header fields: Client
Name, Client Address, Contact Name, Phone, Mobile, Fax/Email, Job No, Rep,
Delivery Address, Delivery Instructions, Colour, Glass, Trend Rep / Trend
Quote No, Order Value. Circled-option fields (one value circled per row —
report which value is circled, or `"unmarked"`, never guess):

- Wind Rating: `700 | 1000 | 1500 | 2000 | Other`
- Water Rating: `150 | 200 | 300 | 400 | 450 | Other`
- Vent Locks / Acoustic Seals / Sump Sills: `YES | NO`
- Timber Products: `WRC Meranti | Primed Unprimed`; Square Profile Ovolo-WRC
  Only
- Storm Moulds: `28x16 | 40x18`
- Reveal Linings Std 28mm: `YES|NO`, `Maple|Pine`,
  `DeFin 80|100|116|138|165|Other`
- Reveal Linings Std 45mm: same options as above

Items table columns: Item # | Room | Qty | Description (+ "Config:" line) |
H | W | Screen | sketch grid ("as viewed from outside").

**Page 2** — continuation items table, same columns.

**Page 3 — Installation Details** (drives labour cost). Building Type
(Residence/Unit/Strata/Other), Construction (Timber Frame/B.Veneer/Cavity
Brick/Other), Visible Structure Over (Yes/No/Lintel). Materials & Costs:
Internal/External Finish, Angles, Architraves (species, profile, size,
thickness), Back Reveals, Sill Reveal Infill/Nosing/Skirt, Moulding, WRC
Storm Moulds, Cover Plates, Rubbish (Select/Owner/Other), Door Furniture,
Asbestos (Yes/No — **Select will not remove**), Brick Removal (type + area
m²), Equipment Hire (scaffold, hoist, brick saw), Ladders. Installation
block: Remove Existing (Timber/Aluminium/Steel/Prep Openings), Access
(hoisting, cranage, floor level Ground/1st/2nd/3rd, lift, stairs), 8
yes/no site questions, Site Measure Reqd, Installers Men Reqd, Time Estimate
(hrs), Additional Quote Notes.

## Measurement conventions (critical)

- H and W are integer **millimetres** per item row; H comes before W on the
  form. All source units (cm, m, mm, in) must be normalized to mm.
- **Unit conversion is deterministic code, never LLM arithmetic** —
  `app/engine/units.py::normalize_to_mm()`. The model reads raw `{value,
  unit}` pairs; it never does the math itself.
- Qty defaults to 1 if blank, but must be flagged low-confidence.
- Optional multi-point readings: `width_readings [top, mid, bottom]` and
  `height_readings [left, centre, right]` — when present, the engine uses
  the **minimum** of the set, not an average or maximum (standard trade
  practice: size to the tightest constraint so the manufactured unit is
  never too big to fit an imprecise opening). Originally documented as
  paper-form-only, but a single AR/LiDAR photo can also yield multiple
  points for one edge (e.g. a quadrilateral trace with a top-edge and a
  bottom-edge reading) — same rule applies, see `app/engine/merge.py`.
- Reveal lining depth (28 vs 45mm) depends on wall construction — changes
  materials and pricing.

## Multi-source merge (deterministic, `app/engine/merge.py`)

Precedence when sources conflict: **form_field > ar_overlay >
sketch_annotation > email_body**. A dimension disagreement of **>15%**
between any two sources → `needs_manual` — never resolved automatically;
the conflict itself is the signal something needs a human. Within that
threshold, multiple readings that share the single highest-precedence tier
present (e.g. two AR-overlay photos of the same edge) but still disagree
resolve to their **minimum** (never averaged, never maxed) rather than
arbitrarily picking one — always flagged on the item
(`dimensions_multi_reading`) so it's never silent. A lower-precedence
reading is never blended in regardless of how close it is; it's simply
outranked as before.

## Product taxonomy

- `window_types`: awning | casement | sliding | double_hung | louvre |
  powerlouvre | bi_fold | sashless | gas_strut
- `door_types`: sliding | stacking | bi_fold | hinged | cedar_entry
- `materials`: aluminium | timber
- `glass_options`: single | double_glazed | acoustic | toughened | BAL40_pyro
- Special attributes: 6-star energy rated options, BAL40 bushfire
  (Pyro-protect seals + toughened glass), fall-prevention compliance,
  security screens.

The Description column on the form (or a config code, see below) maps to
`(product_type + material + attributes)`.

## Config code vocabulary

Shorthand a rep can write in the Description cell or the email body instead
of relying on a hand sketch — **recommended, since it removes sketch
interpretation entirely** (elevation diagrams are rendered deterministically
from the code instead of reading a drawing).

- **Windows**: `AW` awning · `CA-L`/`CA-R` casement (hinge side) · `DH`
  double hung · `SL2`/`SL3` sliding (lite count) · `LV` louvre · `PW`
  powerlouvre · `SS` sashless · `GS` gas strut · `BFW-n` bi-fold window
  (n panels)
- **Doors**: `HD-L`/`HD-R` hinged · `SD2`/`SD3` sliding · `STK-3` stacker ·
  `BFD-n[+L/+R]` bi-fold (n panels, fold direction) · `CED` cedar entry
- **Combinations** use hyphens, e.g. `DH-PIC-DH` (quarter-half-quarter,
  `PIC` = fixed picture window segment).
- An unrecognized code (or unrecognized segment of a combination) →
  `product_type=unknown`, flagged. Never guessed.

## Elevation rendering (`app/render/elevation.py`)

Deterministic SVG rendered from `config_code + height_mm + width_mm`, viewed
from outside: dashed lines meet at an apex pointing to the **hinge side**
(e.g. awning = apex top-centre); arrows show slide/fold direction; `"F"`
marks fixed lites; dimensions (W × H, mm) printed below each elevation. This
replaces reading hand sketches once a rep uses config codes.

## Tiered field model

Every optional field is wrapped: `{"value": ..., "source": ..., "confidence":
0.0-1.0 | null}`. Sources: `ar_overlay | form_field | email_body |
sketch_annotation | rep_reply | default | assumed | missing`.

- **Tier 1 — core**: at least one item with `height_mm` + `width_mm` (int,
  100–6000). None found → `needs_manual`.
- **Tier 2 — context**: client_name, room, qty, product_type, material,
  config_code, screen, install_type, site fields (floor_level, scaffold,
  asbestos, access). Missing critical tier-2 (`product_type`,
  `client_name`) → auto-reply loop, status `awaiting_info`.
- **Tier 3 — enrichment**: glass spec, safety-glass mandate, hardware list,
  energy figures, base labour hours/men. **Never extracted, never
  LLM-invented** — filled only from `app/engine/defaults.yaml`, keyed by
  `config_code` × `material` × `size_band`. `source="default"` always.
- **Tier 4 — flags** (rule-generated, `app/engine/flags.py`): every quote
  lists its assumptions and blockers —
  - any `ar_overlay` dimension → the ±20mm site-check flag
  - asbestos present → *"SELECT WILL NOT REMOVE — client clearance
    certificate required; blocks scheduling"*
  - doors, or glazing with sill `<500mm` → safety glass mandatory
    (AS1288), enforced by rule, flagged if extracted spec conflicts
  - any field with `source` in `{assumed, default}` that affects price →
    printed on the quote with an asterisk

## Advanced spec fields (AU-specific, tier-3 default keys)

Wind rating as N-class (N1–N6; the form's 700/1000/1500/2000 Pa maps to
N-ratings via a **placeholder** lookup table — not yet verified against
AS1170.2/AS2047, treat as provisional like all other `defaults.yaml`
values), AS1288 Grade A safety glass mandatory for all doors and glazing
with sill `<500mm`, WERS energy figures (U-value, SHGC), Rw acoustic rating
for the acoustic glass line, BAL40 option (Pyro-protect seals + toughened),
powder coat colour codes (not free text), reveal depth 28/45mm tied to wall
construction, `install_type` per item: `pocket_insert | full_frame_replacement`.

## Quote state machine

`received → classifying → extracted → awaiting_info → enriched → priced →
pending_approval → approved | rejected | needs_manual`. `awaiting_info`
re-enters at `extracted` when the rep replies (matched via the outbound
clarification email's `Message-ID` against the reply's
`In-Reply-To`/`References` header — best-effort; not fully robust against
mail clients that rewrite headers).

## Hard constraints

- LLM extracts and classifies only — no arithmetic, no invented specs, no
  invented prices. Unit conversion, dimension merge/conflict detection,
  tier-3 enrichment, pricing, and elevation rendering are all deterministic
  Python in `app/engine/` / `app/render/` (enforced by a test asserting
  those modules never import `openai`).
- Decimal money, `ROUND_HALF_UP`; int mm; GST 10% as the final line;
  per-item pricing (`product_type × material × size_band` from the
  placeholder `rules.yaml` matrix) + labour + equipment.
- Any failure path → `needs_manual`, never a crash.
- Approval gate before anything leaves the system — owner-only; no customer
  email in this PoC (the `awaiting_info` clarification email goes to the
  **rep**, who is internal staff, not the end customer).
