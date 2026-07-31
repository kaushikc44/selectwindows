# Project phases

## Phase 0 — GlassQuote PoC bring-up

Starting point: a generic "glass panel priced per m²" quoting PoC. The goal of
this phase was to get the existing app actually running end-to-end (LLM calls,
Docker stack, real inbox), not to change what it did.

**LLM configuration**
- Found `.env.example` had a real DeepSeek API key committed to a git-tracked
  file, with `LLM_BASE_URL` and `LLM_MODEL` swapped (a URL where a model name
  should be, and vice versa). Moved the real key to the gitignored `.env`,
  restored `.env.example` to placeholders, and fixed the swapped values.
- DeepSeek has no vision model, so the OpenAI-compatible client
  (`app/ai/llm.py`) was split into two: `client` (text/chat, DeepSeek) and
  `vision_client` (images, NVIDIA's `integrate.api.nvidia.com`, model
  `google/diffusiongemma-26b-a4b-it`), independently configurable via
  `LLM_VISION_BASE_URL`/`LLM_VISION_API_KEY` (falling back to the main
  `LLM_BASE_URL`/`LLM_API_KEY` if unset).
- Verified both providers live: `predict_hardware()` (DeepSeek) and
  `extract_panels()` (NVIDIA vision) each produced correct real output against
  sample data.

**Infrastructure**
- Fixed `Dockerfile`: `libgdk-pixbuf2.0-0` no longer exists on the
  `python:3.11-slim` base image's Debian release — renamed to
  `libgdk-pixbuf-2.0-0`.
- Brought up the full `docker-compose` stack (Postgres, Redis, FastAPI app,
  Celery worker, Celery beat) successfully.

**Email intake**
- Configured Gmail (via an App Password) as both the intake IMAP inbox and the
  SMTP-sent approval-email recipient, for a self-contained single-account test
  loop.
- Found the test Gmail account had ~4,400+ unseen legacy emails (old
  Facebook/game notifications going back to 2012); `imaplib`'s default 1MB
  `SEARCH` response line limit was too small for that backlog — raised
  `imaplib._MAXLINE`.
- Added `IMAP_SUBJECT_FILTER` config so the poller's IMAP `SEARCH` only matches
  unseen mail with a given subject substring (e.g. `"select windows"`),
  sidestepping the backlog entirely rather than churning through it.

**Result**: validated the full pipeline end-to-end on the *original* flat
glass-panel model — email with one photo attached → IMAP poll → AI panel
extraction → AI hardware-line prediction from a fixed catalog → deterministic
pricing (price per m² of glass + waste % + labour + GST) → PDF generation →
approval email sent with Approve/Reject links.

This confirmed the plumbing worked, but the pricing model itself (glass sold
by area) turned out not to match the real business at all — which motivated
Phase 1.

---

## Phase 1 — Rebuilt for Select Window Installations' real business

Select Window Installations (Brookvale, Sydney) doesn't sell glass by the m² —
they quote per **product unit** (a window or door of a given type + material +
size) plus installation labour plus GST. This phase replaced the extraction
schema, data model, pricing engine, and PDF from scratch to match that.

**Real field-capture workflow**

A field worker measures an opening on-site with an **iPhone LiDAR measuring
app** (digital measurement rendered directly on the photo, not a physical tape
measure) and emails the photo(s) with a plain-language description of what's
needed in the email body (e.g. *"bi-fold window, aluminium, laundry"*),
referencing Select's real product range. One vision LLM call receives all
photos plus the email body text together and correlates them itself — no
manual photo/text pairing logic.

**Extraction schema (`app/schemas.py`, `app/ai/extract.py`)**
- `ExtractionHeader` — office-side fields (client name/address, job no, wind/
  water rating, reveal linings, etc.). Nearly always `null`/`"unmarked"` on a
  quick on-site capture; only filled if the email text explicitly states it.
  Kept in the schema for when the office adds this data later.
- `ExtractionItem` — `product_type` (window/door taxonomy enum), `material`
  (aluminium/timber/unknown), `height_mm`/`width_mm` (LiDAR overlay, any unit
  converted to integer mm), `room`, `qty` (defaults to 1, flagged low-confidence
  when defaulted), `confidence`.
- `ExtractionInstallation` — page-3-style fields (building type, construction,
  floor level, brick removal, scaffold, etc.), all nullable for the same
  reason as the header.
- `needs_manual`: true if `overall_confidence < 0.7`, any `unreadable_fields`
  are present, or any item's own confidence `< 0.7`.
- The old paper-form "sketch cell" concept (`config_sketch_ref`) was dropped —
  it was specific to a literal paper form, not applicable to LiDAR photos.

**Data model (`app/models.py`)** — `Panel`/`GlassType`/`HardwareLine` replaced
with `QuoteHeader` (1:1), `Item` (replaces `Panel`), `Installation` (1:1), all
under `Quote`. `Attachment` now holds one row per photo instead of one per
email.

**Pricing engine (`app/engine/pricing.py`, `rules.yaml`)** — deterministic,
`Decimal`-only, zero LLM/openai import (enforced by a test):
- `unit_price = base_prices[product_type][material] × size_band_multiplier ×
  glass_multiplier`, where the glass multiplier is matched from the header's
  free-text `glass` field (falls back to `"single"`).
- `installation_subtotal = per_item_base_fee × item_count`, plus conditional
  surcharges (floor level, brick removal m², scaffold) only when that data is
  actually present — since most on-site captures won't have page-3 detail.
- GST 10% applied as a final distinct line.
- `rules.yaml` is explicitly flagged `placeholder: true` — the prices are not
  real Select Windows prices, structured so a real price matrix can be dropped
  in by editing the file, no code changes needed.
- **Dropped** the old AI hardware/materials-catalog-matching feature
  (`ai/hardware.py`, `catalog.yaml`, `HardwareLine`) — the new pricing formula
  only has two buckets (item price, installation cost), not a third
  materials-catalog bucket.

**Output** — `app/output/pdf.py` rewritten for the new header/items/
installation shape, with a prominent **"DRAFT — placeholder pricing, not a
final customer quote"** banner (since `rules.yaml` prices are fake) carried
into both the PDF and the approval email body.

**Ingestion** — `app/ingest/poller.py` now collects *every* image attachment
per email (not just the first) plus the email body text; `vision_completion()`
accepts a list of images in one call instead of a single image.

**Processed-tracking fix** — the poller originally used the standard IMAP
`\Seen` flag to track "already processed by our system," gated via an
`UNSEEN` search. This is fragile: opening/previewing an email in Gmail (very
easy to do, especially when `OWNER_EMAIL` is also the intake inbox, as in this
self-testing setup) flips `\Seen` immediately, silently hiding that email from
all future polls even though it was never actually processed. Switched to a
dedicated custom IMAP keyword flag (`PROCESSED_FLAG = "GlassQuoteProcessed"`),
searched via `UNKEYWORD`, so a human reading their own inbox can never cause a
quote to be silently skipped. `\Seen` is still set alongside it (for normal
inbox read/unread UX), it's just no longer what the poller relies on.

**Verification**: full test suite rewritten (78 tests: schemas, models,
pricing golden-math, extraction retry/needs_manual paths, pipeline
integration, PDF, multi-attachment poller) — all passing. Also validated live
against the real DeepSeek + NVIDIA APIs with a synthetic LiDAR-style photo
("0.90m x 1.20m" overlay) + email body text ("Bi-fold window, aluminium,
laundry. Double glazed if possible.") — correctly extracted a
`bi_fold`/`aluminium`/`900×1200mm` item in the laundry with `glass="double
glazed"`, installation left `unmarked`, `needs_manual=False`.

Docker rebuild with a fresh Postgres volume (required since the schema changed
and there's no migration tooling) is a pending manual step — deliberately left
to the user since `docker-compose down -v` is a destructive command.
