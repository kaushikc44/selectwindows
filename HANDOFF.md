# Handoff: Worker mobile app (Phase E in progress)

Read this first if picking up this session cold. Full plan lives at
`/Users/kaushikchoudhury/.claude/plans/goofy-splashing-shell.md` (approved,
still accurate — read it for the *why*, this file is the *where we're at*).
If you're a different model/session picking this up: read this whole file
before touching code, it front-loads context that took a long session to
build up.

## What this whole effort is

Replacing the email/IMAP intake pipeline with a React Native app where field
workers fill a structured form (pickers, not free text) and photograph each
dimension into its own labelled slot (Width / Height), so the backend is
*told* the axis instead of a vision model guessing it. This eliminated the
exact class of bug (axis mislabeling, 940mm-vs-2470mm type conflicts) that
dominated the email-pipeline debugging earlier in this session.

Midway through building the app, the user got stakeholder feedback (an
external consultant's write-up, framed around the *real* client's paper
forms — the business is apparently referred to as "Ingrity" internally,
reviewed by someone named "Anthony") emphasizing that the point of this
whole project is **digitising the paper forms**, not just capturing
dimensions. That reframed Phase D: it's not just "add photos of
measurements," it's "every field on every page of the paper form should
have a proper digital equivalent, organised into small task-focused
screens (not one long form), with structured pickers replacing every
free-text/hand-drawn field — including the hand-drawn window/door
configuration grid, replaced by a tap-to-configure picker." This is now
baked into the screens built so far (see below).

## Status: Phases A–E done and live-verified. Phase F (below) also done —
## the Sales role (job creation, tradie assignment, scheduling, missed-
## visit/reschedule) — as of 2026-07-31, 411 backend tests passing,
## `tsc`/`expo export` clean on mobile.

### Done (Phases A–C, all tested, deployed, live-verified)

- **`app/auth.py`** — bcrypt password hashing + JWT (pyjwt), `get_current_worker`
  FastAPI dependency. `Worker` model in `app/models.py`. `POST /auth/login`
  in `app/main.py`. `scripts/create_worker.py` provisions accounts (no
  self-registration).
- **`app/ai/extract_ar_field.py`** — `extract_single_reading(image_bytes,
  mime_type, axis)`, much simpler than the grouped email-path extractor
  since axis is given, not inferred.
- **`app/api/worker_quotes.py`** — the full structured submission API,
  mounted in `app/main.py`:
  - `POST /worker/quotes` — draft quote from header+installation JSON
  - `POST /worker/quotes/{id}/items` — structured item (product_type/
    material/room/qty/screen/config_code, all from real enums)
  - `POST /worker/quotes/{id}/items/{item_id}/photos` — multipart, one
    photo + `field` (width|height) at a time. Runs
    `extract_single_reading`, feeds `app/engine/merge.py::resolve_dimension`
    (the same 15%-tolerance / minimum-of-multi-reading logic built earlier
    this session), returns `{resolved, value_mm, multi_reading, reason,
    conflict_values_mm}`. **Note:** fixed a real bug here where a later
    conflicting photo left a stale `width_mm`/`height_mm` from a prior
    successful resolution — always re-check this if touching this endpoint.
  - `POST /worker/quotes/{id}/submit` — validates client_name + every item
    has resolved dimensions, then fires the `process_worker_submission`
    Celery task (`app/workers/tasks.py`), which calls
    `process_worker_submission_pipeline` (`app/workers/pipeline.py`) — this
    reuses `run_pricing` → `run_enrichment_and_flags` → `send_for_approval`
    **completely unchanged** from the email path.
- **Model changes**: `QuoteStatus.draft` added; `Item.height_mm`/`width_mm`
  made nullable (item exists before photos do); `Attachment.item_id` +
  `dimension_field` added (links a photo to a specific item+axis);
  `Quote.created_by_worker_id` added.
- **`app/engine/config_codes.py`**: added a `PW` code for `powerlouvre` —
  it was the only `ProductType` with no config-code representation at all,
  found while building the mobile config picker (which needs every
  product type reachable through a code). Domain brief updated to match.
- **`GET /worker/quotes`** (list, worker-scoped, ownership-checked) and
  **`GET /worker/quotes/{id}`** (detail incl. items) — added so a draft can
  be resumed after an app restart and Job List can show real history,
  instead of only living in `DraftContext` memory. Deliberately separate
  from the pre-existing public `GET /quotes/{id}` (no ownership check
  there — that one's for the owner's approve/reject email flow).
- **`POST /worker/quotes/{id}/items/{item_id}/reference-photos`** (upload,
  any number per item, no extraction runs) + matching `GET` (list) — the
  paper form's general "+ Add Photo" per opening, distinct from the two
  dimension photos. Reuses `AttachmentKind.site_photo`.
- **DB migrated live** (non-destructively, `ALTER TABLE`/`ALTER TYPE ADD
  VALUE`) — the running Docker Postgres already has all of this.
- **356 backend tests pass.** Full suite: `.venv/bin/python -m pytest -q`.
- **Live end-to-end proof**: created a worker, logged in, built a draft
  quote, added a louvre-window item, uploaded the *exact* real photo
  (`w2.png`, the one with 2.7m/94cm/2.47m pills) once as "height" and once
  as "width" — both resolved cleanly on the first try (940mm, 2470mm — no
  conflict), submitted, and it reached `pending_approval` with correct
  pricing ($957.00 total) and a real approval email sent. This is the
  concrete proof the new approach works — the identical photo caused
  repeated spurious conflicts through the old email pipeline.
- Deploy pattern used throughout: `docker-compose up -d --build`, clear
  `lock:poll_and_process*` in Redis, confirm 5 containers healthy (give it
  a couple seconds — there's a startup race where curl can hit the port
  before uvicorn's fully up, harmless, just retry). Always cross-check new
  Python files parse under **Python 3.11** (Docker image), not just the
  local 3.13 venv — bit us once already this session with an
  f-string-with-backslash issue: `docker run --rm -v
  /Users/kaushikchoudhury/selectwindows:/srv -w /srv python:3.11-slim
  python -c "import ast; ast.parse(open('path/to/file.py').read())"`.

### In progress: `mobile/` (Expo React Native + TypeScript app)

Scaffolded via `npx create-expo-app@latest mobile --template blank-typescript`
(Expo ~57, React 19.2, RN 0.86). Installed:
`@react-navigation/native`, `@react-navigation/native-stack`,
`react-native-screens`, `react-native-safe-area-context`,
`expo-secure-store` (JWT storage), `expo-image-picker` (camera),
`@react-native-picker/picker` (installed but not actually used yet — the
app uses the custom `ChipPicker` component instead for a consistent
cross-platform look; the native picker package can probably be removed if
nothing ends up using it).

**`npx tsc --noEmit` and `npx expo export --platform ios` both pass clean**
as of this checkpoint — always re-run both after changes, they catch a lot
(the export step catches bundler/import issues tsc alone can miss).

**Files written so far** (all functional, not stubs):

- `mobile/src/api/types.ts` — mirrors backend enums/schemas exactly
  (`ProductType`, `Material`, `ExtractionHeader`, `ExtractionInstallation`,
  `RevealLining`, wind/water rating literals, etc.) — keep in sync with
  `app/models.py`/`app/schemas.py` if either changes.
- `mobile/src/api/configCodes.ts` — **new**, mirrors
  `app/engine/config_codes.py`'s exact vocabulary (`WINDOW_CONFIGS`,
  `DOOR_CONFIGS`, each entry carries its implied `productType` so the app
  never asks for product type and config separately — asking twice would
  just create a way for them to disagree). `buildConfigCode()` assembles
  the exact string the backend parser expects (`SL2`, `CA-L`, `BFD-4`,
  etc). **If `config_codes.py` ever gains/changes a code, mirror it here.**
- `mobile/src/api/client.ts` — fetch wrapper, attaches JWT from
  `expo-secure-store`, `ApiError` class, `apiGet`/`apiPostJson`/`apiPostForm`.
  `API_BASE_URL` defaults to `http://localhost:8000`, override via
  `EXPO_PUBLIC_API_BASE_URL` — **a physical device needs the dev machine's
  LAN IP here, not localhost.**
- `mobile/src/api/auth.ts` — `login()`, note `/auth/login` needs
  `application/x-www-form-urlencoded`, not JSON (FastAPI's
  `OAuth2PasswordRequestForm`) — handled separately from the JSON client.
- `mobile/src/api/quotes.ts` — `createDraftQuote`, `addItem`,
  `uploadDimensionPhoto` (multipart with RN's `{uri,name,type}` FormData
  shape), `submitQuote`, `getQuote` (old public endpoint, still used
  nowhere yet — candidate for removal), `getElevationPreview`,
  `listMyQuotes`, `getMyQuote` (the last two are the new worker-scoped
  read endpoints — types `QuoteSummary`/`WorkerQuoteDetail` in `types.ts`,
  deliberately distinct shapes from the older `QuoteDetail`).
- `mobile/src/auth/AuthContext.tsx` — token presence → `isLoggedIn`, wraps
  login/logout.
- `mobile/src/draft/DraftContext.tsx` — tracks the in-progress draft's
  items client-side (still the source of truth Items/ReviewSubmit render
  from, to avoid a round trip per render) — now also has
  `hydrateFromServer(detail: WorkerQuoteDetail)`, called by
  `JobListScreen` after fetching `getMyQuote()`, so tapping a draft in the
  job list actually resumes it instead of only working within one
  continuous session.
- `mobile/src/theme.ts` — shared `StyleSheet` (colors, card/button/chip
  styles) — reuse this, don't invent new ad hoc styles per screen.
- `mobile/src/components/ChipPicker.tsx` — generic single-select chip row,
  used everywhere instead of native pickers/dropdowns (simpler
  cross-platform look, and matches the "tap options, don't type" feedback).
- `mobile/src/components/ConfigCodePicker.tsx` — the tap-to-configure
  replacement for the paper form's hand-drawn window/door grid:
  window-or-door → type (Sliding/Awning/Bi-fold/etc, from
  `configCodes.ts`) → panel count or hinge side if that type needs one.
  Fires `{code, productType}` up to the parent as soon as enough is
  picked, and **now also fetches + renders a live elevation preview**
  (`SvgXml` from `react-native-svg`, hitting the new `GET
  /worker/elevation-preview` endpoint) as soon as a full code is picked —
  the "tap Sliding → app draws it" idea from feedback, done.
- `mobile/src/navigation/types.ts` — `RootStackParamList`: `Login`,
  `JobList`, `NewJob`, `PropertyDetails{header}`, `Items{quoteId}`,
  `AddItem{quoteId}`, `Capture{quoteId,itemId,itemLabel}`,
  `ReviewSubmit{quoteId}`.
- `mobile/src/navigation/RootNavigator.tsx` — done. Stack navigator,
  swaps between the unauthenticated (`Login`) and authenticated stack
  based on `useAuth().isLoggedIn`.
- `mobile/App.tsx` — done. Wraps everything in `AuthProvider` →
  `DraftProvider` → `RootNavigator`.
- `mobile/src/screens/LoginScreen.tsx` — done.
- `mobile/src/screens/NewJobScreen.tsx` — done, **rewritten** to be just
  the customer-details block (name/contact/phone/email/job no/site
  address/delivery address) — split out of what used to be one bigger
  form, per the "small task-focused screens" design principle from
  feedback. Navigates to `PropertyDetails` with the header-so-far as a
  param (doesn't hit the backend yet — no quote exists until
  PropertyDetails submits both header+installation together).
- `mobile/src/screens/PropertyDetailsScreen.tsx` — **new**, the big one.
  Digitises page 1's circled-option fields (colour, glass, wind/water
  rating, vent locks, acoustic seals, sump sills, 28mm/45mm reveal
  linings with species+DeFin) *and* page 3's installation fields
  (building type, construction, floor level, remove existing, brick
  removal m², scaffold/hoist/brick saw, asbestos, notes) in one screen
  with clear card sections. This is where `createDraftQuote()` actually
  fires (combining the customer header from `NewJobScreen` with
  everything collected here), then navigates into `Items`. **Fixed
  2026-07-29**: on success this called `navigation.reset({index: 0,
  routes: [{name: "Items", ...}]})`, which wiped the *entire* stack
  (including `JobList`) down to just `Items` — since native-stack only
  shows a header back button when there's a previous route, `Items` (and
  everything pushed after it: `AddItem`/`Capture`/`ReviewSubmit`) had no
  way back at all. The reset was intentional (stops "Continue to Items"
  from being double-tapped into a duplicate draft via re-submitting
  `NewJob`/`PropertyDetails`), so the fix keeps that but resets to
  `[JobList, Items]` instead of `[Items]` alone — `Items` now has a
  working back button that returns to the job list.
- `mobile/src/screens/ItemsScreen.tsx` — done. List of items added so far
  (from `DraftContext`), tap one to jump back into its `Capture` screen,
  "Add Item" / "Review & Submit" (enabled once every item has both
  dimensions) at the bottom.
- `mobile/src/screens/AddItemScreen.tsx` — done, **rewritten** to use
  `ConfigCodePicker` as the primary input (product type is *derived* from
  the chosen config, not asked separately) plus material/room/flyscreen
  pickers.
- `mobile/src/screens/CaptureScreen.tsx` — the important one: two
  `FieldCapture` cards (Width, Height). **Corrected 2026-07-29**: these no
  longer open the plain Camera. Apple's Measure app (the AR/LiDAR app whose
  overlay "pills" are what the whole extraction pipeline reads) has no
  public URL scheme or picker API a third-party app can launch and get a
  result back from — `expo-image-picker` can only drive the system Camera
  or Photo Library. So the flow is now: on-screen copy tells the worker to
  open Measure themselves, take the AR reading, screenshot it, then come
  back and tap "Choose Width/Height Screenshot", which calls
  `ImagePicker.launchImageLibraryAsync()` (photo library picker, not
  camera) → immediate upload → shows resolved value with a "Choose a
  Different Screenshot" retry option, or an inline "unreadable"/"conflict"
  message (this is the real-time replacement for the old async email
  dimension-conflict retry flow). `app.json` updated to request
  `NSPhotoLibraryUsageDescription`/`READ_MEDIA_IMAGES` alongside the
  existing camera permission. **Plus a "Reference Photos" card** — "+ Add
  Photo", still camera-based (`launchCameraAsync`, unchanged — these are
  plain site/context photos, not AR readings, so the camera is correct
  there), unlimited count, no extraction, just a running count shown (no
  thumbnails — there's no image-serving endpoint yet, see gaps).
- `mobile/src/screens/ReviewSubmitScreen.tsx` — done. Summary list from
  `DraftContext` + Submit → success/error state inline.
- `mobile/src/screens/JobListScreen.tsx` — **rewritten**, now a real job
  history via `listMyQuotes()`: pull-to-refresh, status badges, tapping a
  `draft`-status job resumes it (`getMyQuote` → `hydrateFromServer` →
  navigate into `Items`); non-draft jobs are shown but not tappable yet
  (no screen to view a submitted/priced quote's read-only detail — see
  gaps). Refreshes on screen focus (`useFocusEffect`), so returning from a
  submitted job shows it immediately.
- `mobile/app.json` — camera *and* photo-library permission strings added
  for both platforms (`NSCameraUsageDescription` +
  `NSPhotoLibraryUsageDescription` for iOS, `CAMERA` + `READ_MEDIA_IMAGES`
  + the `expo-image-picker` plugin's `cameraPermission`/`photosPermission`
  for Android) — the library permission was added 2026-07-29 when
  dimension capture switched from camera to photo-library picker (see
  `CaptureScreen.tsx` note above).

### Known gaps / not yet written — pick up here

1. ~~No live elevation-diagram preview~~ **DONE.** New `GET
   /worker/elevation-preview?config_code=...` in `app/api/worker_quotes.py`
   (`preview_router`, mounted separately from the quotes router since it's
   not quote-scoped — both are mounted in `app/main.py`), calls the
   existing `app/render/elevation.py::render_elevation` unchanged (with
   fixed placeholder dimensions 1200×900mm — that function only uses
   height/width for the printed label text, never the drawn shape, so a
   placeholder is fine for a config-only preview). `ConfigCodePicker.tsx`
   fetches it via `getElevationPreview()` (`api/quotes.ts`) on every config
   change and renders with `react-native-svg`'s `SvgXml` (installed via
   `npx expo install react-native-svg`). Live-verified against the running
   Docker deployment; 3 new backend tests
   (`test_elevation_preview_*` in `test_worker_quotes.py`).
2. ~~No backend read endpoints for the app's own data~~ **DONE.** `GET
   /worker/quotes` (list) and `GET /worker/quotes/{id}` (detail incl.
   items) added, both worker-scoped via `created_by_worker_id` (see
   `_get_owned_quote` helper in `app/api/worker_quotes.py` — note this is
   a *different, less restrictive* helper than `_get_owned_draft_quote`:
   it allows any status, not just `draft`, since read access to an
   already-submitted quote is fine, only *mutating* one isn't).
   `DraftContext.hydrateFromServer()` + the rewritten `JobListScreen`
   consume these. Live-verified against the running Docker deployment
   using the real louvre-window quote from earlier in the session. 5 new
   backend tests.
   - ~~Loose end~~ **DONE 2026-07-29.** `GET /worker/quotes/{id}` now also
     returns `total` and `flags` (both already computed by the existing
     pricing/flags pipeline, just not surfaced before) plus `line_total`
     per item. New `mobile/src/screens/QuoteDetailScreen.tsx` (read-only —
     mutation endpoints reject non-draft quotes anyway) shown when tapping
     a non-draft row in `JobListScreen` (previously those rows were
     disabled/dimmed and did nothing). 2 new backend tests
     (`test_get_my_quote_includes_total_and_flags_fields`, plus the
     existing `ItemSummary`/`QuoteDetail` schema extension).
3. ~~Reference/site photos aren't captured at all~~ **DONE.** New `POST`/
   `GET /worker/quotes/{id}/items/{item_id}/reference-photos` — unlimited
   "+ Add Photo" per item, `AttachmentKind.site_photo`, no extraction runs
   on these (verified via a mocked `extract_single_reading` that asserts
   it's never called). `CaptureScreen.tsx` has a third card below
   Width/Height for it. Live-verified against the running Docker
   deployment. 5 new backend tests.
   - ~~Loose end: only shows a running count, no thumbnails~~ **DONE
     2026-07-29.** New `GET /worker/attachments/{id}` in
     `app/api/worker_quotes.py` (`preview_router`, so `/worker/...` not
     quote-scoped in the path) — ownership-checked via
     `attachment.quote.created_by_worker_id`, streams the file with
     `FileResponse`. New `mobile/src/api/quotes.ts::attachmentUrl()` +
     `mobile/src/components/AuthedImage.tsx` (a plain `<Image source={{uri}}>`
     can't attach the required bearer token, so this resolves the token
     from `expo-secure-store` first and passes it via
     `source={{uri, headers}}`). `CaptureScreen.tsx`'s reference-photos
     card now renders actual 72×72 thumbnails instead of just a count. 4
     new backend tests (`test_get_attachment_*`).
   - **361 backend tests pass total; `tsc`/`expo export --platform ios`
     both clean as of this checkpoint.**
4. **No AI-suggestions/compliance-recommendation surface in the app.**
   The feedback's "AI Integration" section (building type + age + room →
   suggest safety glass / wind rating / scaffold) doesn't have an
   equivalent yet — the backend's flags system (`app/engine/flags.py`)
   already generates some of this (AS1288 safety glass, asbestos,
   AR-measurement caveats) but only *after* submission, in the office
   approval email/PDF, not shown back to the worker in the app before
   they submit. Whether that's wanted as an on-device "review before
   submit" surface (matching the feedback's "Manager Review"/"AI Review"
   screens) is worth asking the user about — non-trivial scope addition,
   not implied as required by the approved plan.
5. **Bluetooth/laser measure integration** — explicitly mentioned in
   feedback as a nice-to-have ("Connect Leica Laser → auto-filled"), not
   attempted, genuinely out of scope for now (new native module, specific
   hardware). Worth noting to the user as a known non-goal unless they ask.
6. **Partially done: run in an actual simulator.** Booted an iOS 18.5
   simulator ("iPhone 16 Pro"), ran `npx expo start --ios` from `mobile/`,
   confirmed via screenshot that the real app boots and renders correctly
   through Expo Go — "Select Windows — Field App" title, styled Username
   field, all matching the actual `LoginScreen.tsx`/`theme.ts` code, not a
   template placeholder. **Could not complete a full interactive
   walkthrough** — this sandboxed environment has no working GUI/touch
   automation (`osascript`/System Events times out on accessibility
   permissions it can't be granted non-interactively; no `idb` or
   `cliclick` installed). A real user with normal desktop access hits
   none of these limits — if the dev server is still running
   (`npx expo start --ios` from `mobile/`; a worker account already
   exists: `testworker` / `testpass123`, created via
   `scripts/create_worker.py`), just click through it directly. Someone
   with real GUI access should still do the full walkthrough (esp. the
   camera capture flow against a real photo) before calling Phase D done.

## Phase E: manual entry, sill height, and the learning approval loop

Full plan at `/Users/kaushikchoudhury/.claude/plans/goofy-splashing-shell.md`
(overwritten from the Phase D plan — read it for the full *why*, including
the two scope decisions confirmed with the user before building: the owner
review surface is a role-gated screen in the *same* mobile app, not a
separate web dashboard, and v1 never auto-approves — the agent always
surfaces a note and Anthony still clicks Approve himself, even on a
confident match).

**1. Manual dimension entry.** `POST /worker/quotes/{id}/items/{item_id}/
dimensions` (`app/api/worker_quotes.py::enter_dimension_manually`) — same
candidate/merge machinery as photo upload (`_add_reading_and_resolve`, a
new shared helper both endpoints now call), just skipping the photo/
extraction step. `source="manual_entry"` was added to `FieldSource`
(`app/schemas.py`) and ranks *above* `ar_overlay` in `SOURCE_PRECEDENCE`
(`app/engine/merge.py`) — a deliberate typed measurement outranks an AR
estimate — and never carries the AR ±20mm flag (`ar_measurement_flags`
only flags `ar_overlay` readings, so this is correct by construction, no
flags.py change needed). Mobile: `CaptureScreen.tsx`'s `FieldCapture` now
has an "Or type it in" link below the screenshot button, revealing an
inline numeric input.

**2. Sill height.** A real, previously-silent gap: `app/engine/flags.py::
safety_glass_flags()` has always accepted a `sill_height_mm` dict for the
AS1288 mandatory-safety-glass rule, but nothing anywhere ever built one
from real data. New nullable `Item.sill_height_mm` column;
`build_flags()`/`run_enrichment_and_flags` (`app/workers/pipeline.py`) now
actually construct and pass that dict. Mobile: one optional "Sill Height
(mm)" input on `AddItemScreen.tsx`.

**3. The owner comment/learning loop.** New `Worker.is_owner` (an account
is either a tradie or the owner, never both — role-play both sides by
logging into different accounts); new `QuoteStatus.changes_requested`; new
`ApprovalComment` (the review thread) and `LearnedLesson` (v1's entire
"learning" mechanism — flat trigger/fix text, no embeddings/fine-tuning)
models. `app/auth.py::require_owner` gates the new `app/api/owner_quotes.py`
router (`GET /owner/quotes` — full queue across all tradies; `GET /owner/
quotes/{id}` — detail incl. flags/agent_notes/comment thread; `POST
/owner/quotes/{id}/comments` — `approve`/`reject`/`request_changes`/
`comment`, where `request_changes` creates a `LearnedLesson` from the
comment). New `app/ai/approval_agent.py::check_against_lessons` — one
`chat_completion` call (JSON-only prompt, `LLMUnavailable`-safe, same
pattern as every other `app/ai/*` extractor) checking a quote's flags/items
against stored lessons; called from `send_for_approval`
(`app/workers/pipeline.py`) right after a quote reaches `pending_approval`,
result stored on new `Quote.agent_notes` — wrapped in its own try/except so
a failure there never blocks the approval email. Tradie side: mutation
endpoints in `worker_quotes.py` now accept `changes_requested` as well as
`draft` (new `_get_owned_editable_quote` helper), and a new `POST /worker/
quotes/{id}/resubmit` re-validates and re-runs the pipeline. Mobile: new
role-gated stack (`RootNavigator.tsx` branches on `AuthContext.isOwner`,
persisted via `expo-secure-store` alongside the JWT) —
`OwnerQueueScreen.tsx` (full queue, all tradies) and
`OwnerQuoteReviewScreen.tsx` (flags/agent notes/comment thread/Approve-
Reject-Send Back buttons). Tradie's `QuoteDetailScreen.tsx` now shows the
comment thread and a "Fix This Job" button when `changes_requested`, which
resumes into `Items`/`Capture` exactly like a draft; `ReviewSubmitScreen.tsx`
becomes "Review & Resend" and calls resubmit instead of submit in that case
(`DraftContext` gained a `status` field to know which).

**No Alembic in this project** — `app/db.py::create_all()` only creates
missing *tables*, never alters an existing one. New nullable columns and
the new enum value needed an explicit, idempotent patch
(`app/db.py::_SCHEMA_PATCHES`, `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` /
`ALTER TYPE ... ADD VALUE IF NOT EXISTS`, run autocommit since Postgres
can't use a new enum value in the same transaction that added it) — this
mattered because the live DB already had real data (a job created through
the app during this session) that a naive schema change would have
required dropping. Worth remembering for any future column/enum addition.

**Demo data**: `scripts/seed_demo_quotes.py` — builds 3 quotes through the
*real* pipeline functions (not fixtures), reusing `testworker`/`testpass123`
and creating `anthony`/`anthonypass123` (owner). Since sill height (#2
above) now makes safety glass auto-flag deterministically, the seeded
"learning" thread had to be something no deterministic rule covers instead
— a Strata building needing a body-corporate-approval note. Quote 1 is
scripted history (Anthony already requested changes, tradie already fixed
it, already approved — this is what creates the real `LearnedLesson`, via
the exact same fields the real endpoints use, not a hand-authored row).
Quote 2 is a *new* Strata job submitted after that lesson exists — this is
the one to check: its `agent_notes` should already reference the Strata
lesson, computed for real by a live LLM call, not faked. **Verified
2026-07-29**: ran it against the live Docker deployment (`docker-compose
exec -T app sh -c "PYTHONPATH=/srv python scripts/seed_demo_quotes.py"` —
note the explicit `PYTHONPATH=/srv`, needed because Python prepends the
*script's* directory to `sys.path`, not the cwd, when run as `python
scripts/foo.py`), then confirmed over real HTTP (`/auth/login` as
`anthony` returns `is_owner: true`; `GET /owner/quotes` lists the full
mixed queue including old email-pipeline quotes from earlier sessions;
`GET /owner/quotes/{quote2_id}` shows `agent_notes` correctly populated
with the Strata note) — the learning loop works end-to-end for real, not
just in tests.

`scripts/create_worker.py` gained an `--owner` flag (now uses `argparse`
instead of raw `sys.argv`).

**Verification**: 33 new backend tests (`test_approval_agent.py`,
`test_owner_quotes.py`, plus additions to `test_worker_quotes.py`,
`test_flags.py`, `test_pipeline.py`) — 394 passed, 1 skipped, full suite.
`tsc --noEmit` and `expo export --platform ios` both clean on mobile.

## Phase F: Sales role — job creation, tradie assignment, scheduling,
## missed-visit/reschedule

Plan overwritten in place at the same path (read it for the full *why*,
including the confirmed scope decisions: every job now originates from
Sales — the tradie's own "Start New Job" is gone entirely; missed visits
are tradie-*reported*, not date-inferred; the reason taxonomy is a small
fixed list + Other, shared by both missed-visit and reschedule; Sales sees
scheduling only, never pricing/flags/materials — that stays Anthony-only).

**Role model migration.** `Worker.is_owner: bool` (Phase E) replaced
outright with `Worker.role: WorkerRole` (`tradie`/`sales`/`owner` — tradie
is the default). `app/auth.py::require_owner` now checks `role ==
WorkerRole.owner`; new parallel `require_sales`. `app/db.py::
_SCHEMA_PATCHES` handles the live migration: creates the new `worker_role`
Postgres enum type (guarded — `CREATE TYPE` has no `IF NOT EXISTS`, so a
`DO $$ ... EXCEPTION WHEN duplicate_object THEN null; END $$` block
swallows the "already exists" case on a DB where `create_all()` already
created it from the Python enum), adds the `role` column, **backfills**
any existing `is_owner=true` row to `role='owner'` (guarded to no-op on a
DB that never had `is_owner` at all), then drops the now-dead `is_owner`
column. This mattered because the live DB already had a real `anthony`
account from Phase E's seed script — live-verified the backfill actually
ran (didn't silently demote him) before trusting this further.

**Ownership model shift.** `Quote.assigned_tradie_id` (new) is now what
gates every tradie-side mutation endpoint in `app/api/worker_quotes.py`
(`_get_owned_quote`/`_get_owned_editable_quote`, plus `get_attachment`) —
not `created_by_worker_id`, which since this phase means "the Sales rep
who created the job." `app/api/owner_quotes.py`'s `tradie_name` field
falls back to `created_by_worker` when `assigned_tradie` is unset, so
older Phase D/E quotes (created directly by a tradie, no Sales flow yet)
still display correctly in Anthony's queue — see `_tradie_name()` helper.

**Backend — new `app/api/sales_quotes.py`** (prefix `/sales/quotes`, all
behind `require_sales`, plus a small separate `/sales/tradies` router
mounted alongside it): `POST ""` creates a `Quote(status=scheduled)` with
just the bare customer header (name/address/phone/email/job_no) + an
`assigned_tradie_id` + `scheduled_date` (validated as an actual `tradie`-
role account, 422 otherwise) — no items/installation yet, that's the
tradie's on-site job. `GET ""`/`GET "/{id}"` return **scheduling fields
only** (client, assigned tradie, date, status, comment thread) — never
`total`/flags/materials, per the confirmed Sales-visibility decision.
`POST "/{id}/reschedule"` updates the date, flips `missed` → `scheduled`,
logs an `ApprovalComment(author="sales", action="reschedule")`.

**Backend — `app/api/worker_quotes.py` changes:** `POST /worker/quotes`
(create-draft) is gone — a tradie can no longer originate a quote at all.
New `POST /worker/quotes/{id}/property-details` is the tradie's on-site
completion of a Sales-created job: fills in the compliance/property fields
(colour, glass, ratings, reveal linings) and installation detail Sales
didn't supply, and flips a freshly `scheduled` quote to `draft` so the
rest of the flow (`add_item`/`submit`/etc., all unchanged) proceeds
exactly as it did pre-Phase-F. Deliberately never touches
`client_name`/`address`/`phone`/`email`/`job_no` even if the request body
includes them — those are Sales's fields, set once at creation. New
`POST /worker/quotes/{id}/missed` (only valid from `scheduled`) — the
tradie's "Couldn't Complete This Visit" report, reusing the same
`RescheduleReason` taxonomy (`app/schemas.py`) as Sales's reschedule.
`_get_owned_editable_quote` now also accepts `scheduled` (not just
`draft`/`changes_requested`) so `property-details` itself is reachable.

**Reused, not duplicated:** `ApprovalComment` (Phase E's owner-review
thread model) is reused verbatim for missed-visit (`action="missed_visit"`,
author `"tradie"`) and reschedule (`action="reschedule"`, author
`"sales"`) — no new table. `RescheduleReason`/`RESCHEDULE_REASON_LABELS`
(`app/schemas.py`) is one shared taxonomy used by both
`report_missed_visit` and `reschedule_job`, mirrored exactly in mobile's
`api/types.ts`.

**Mobile.** `AuthContext`/`api/client.ts`/`api/auth.ts`: `isOwner` boolean
replaced with a `role: "tradie"|"sales"|"owner"` string, persisted the
same way (`expo-secure-store`). `RootNavigator.tsx` is now a three-way
branch. **Tradie stack**: `NewJobScreen.tsx` deleted outright — no more
"Start New Job" entry point; `JobListScreen` lists jobs where
`assigned_tradie_id` matches, tapping a `scheduled` job goes to
`PropertyDetailsScreen` (repurposed: now takes `{quoteId}` not `{header}`,
fetches the client name for display via `getMyQuote`, calls the new
`property-details` endpoint instead of the removed `createDraftQuote`) —
that screen also carries the new "Couldn't Complete This Visit" card
(reason `ChipPicker` + conditional "Other" detail field), since it's the
only screen ever shown while a job is still `scheduled`. **New Sales
stack**: `SalesJobListScreen.tsx`, `NewSalesJobScreen.tsx` (customer
fields + a tradie `ChipPicker` populated from `GET /sales/tradies` + a
plain `YYYY-MM-DD` text field for the date — deliberately no native
date-picker dependency, matching this app's existing all-`TextInput`
pattern), `SalesJobDetailScreen.tsx` (schedule info, comment/reason
history, a "Reschedule" action). New `api/sales.ts`.

**Verification**: 33 new backend tests (`test_sales_quotes.py`, updates
across `test_owner_quotes.py`/`test_worker_quotes.py`/`test_models.py` for
the role migration and new endpoints) — 411 passed, 1 skipped, full suite.
`test_worker_quotes.py`'s fixture plumbing was rewritten: since a tradie
can no longer create their own quote via the API, its `_quote_with_item`
helper now constructs the starting `Quote`/`QuoteHeader` directly via
`db_session` (status=draft, `assigned_tradie_id=worker.id`) rather than
posting to the now-removed endpoint. `scripts/create_worker.py --owner`
replaced with `--role {tradie,sales,owner}`. `scripts/seed_demo_quotes.py`
extended with a 4th scripted quote demonstrating the missed→reschedule
loop end to end (Sales creates → tradie reports missed (weather) → Sales
reschedules), alongside a new demo `sales1`/`salespass123` account.
`tsc --noEmit` and `expo export --platform ios` both clean on mobile.

### After the screens are done (per the approved plan's Verification section)

- Run on iOS/Android simulator via Expo (`cd mobile && npm start`), walk
  one full real submission using the simulator's/a real device's camera
  against an actual measurement photo.
- Confirm the photo-confirm/retake/conflict UX against a real ambiguous
  photo (the `w1.png`/`w2.png` pair from earlier this session, still on
  disk in the worker container under `data/attachments/`, is a good test
  case — `w2.png` alone should resolve both axes cleanly, exactly as
  proven in the live curl test above).
- The plan's still-open question about deleting the email pipeline
  entirely vs. keeping it running in parallel was never answered by the
  user — default assumption in the plan is "keep it running until the app
  is proven," unless told otherwise.

## Quick orientation for whoever picks this up

- Backend: `/Users/kaushikchoudhury/selectwindows/app/` — FastAPI +
  SQLAlchemy + Celery + Postgres + Redis, all in `docker-compose.yml`.
  Tests: `.venv/bin/python -m pytest -q` from the repo root.
- Mobile: `/Users/kaushikchoudhury/selectwindows/mobile/` — Expo RN + TS.
  `cd mobile && npm start` to run; `npx tsc --noEmit` and `npx expo export
  --platform ios` are quick sanity checks that don't need a
  simulator/device.
- Deploy pattern for backend changes: `docker-compose up -d --build`,
  `docker-compose exec -T redis redis-cli DEL lock:poll_and_process
  lock:poll_and_process_replies`, check `docker-compose ps -a` all healthy
  (give it ~3s, there's a harmless startup race), `curl
  localhost:8000/docs` returns 200.
- Task list is tracked via TaskCreate/TaskUpdate/TaskList (task tool) —
  Phase D (#5) is `in_progress`; the rest (#1–#4) are `completed`. Check
  `TaskList` for current status if resuming.
- The user has said they may switch between this session and another
  model/session to keep working within usage limits — this file is meant
  to make that handoff lossless. Keep it updated at natural checkpoints
  (a phase finishing, a significant pivot like the stakeholder-feedback
  reframe) rather than only at the very end.
