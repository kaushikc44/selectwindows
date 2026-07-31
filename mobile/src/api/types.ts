// Mirrors app/models.py's ProductType/Material enums and app/schemas.py's
// ExtractionHeader/ExtractionInstallation Literal fields exactly — these
// drive the picker options, so they must stay in sync with the backend.
// "Full structured form": nothing here is free text guessed by an LLM.

// Shared by the tradie's "Couldn't Complete This Visit" report and Sales's
// reschedule action — one taxonomy, mirrors
// app/schemas.py::RescheduleReason/RESCHEDULE_REASON_LABELS exactly.
export const RESCHEDULE_REASONS = [
  "customer_rescheduled",
  "tradie_unavailable",
  "weather",
  "access_issue",
  "other",
] as const;
export type RescheduleReason = (typeof RESCHEDULE_REASONS)[number];

export const RESCHEDULE_REASON_LABELS: Record<RescheduleReason, string> = {
  customer_rescheduled: "Customer rescheduled",
  tradie_unavailable: "Tradie unavailable",
  weather: "Weather",
  access_issue: "Access issue",
  other: "Other",
};

export const PRODUCT_TYPES = [
  "awning",
  "casement",
  "sliding",
  "double_hung",
  "louvre",
  "powerlouvre",
  "bi_fold",
  "sashless",
  "gas_strut",
  "stacking",
  "hinged",
  "cedar_entry",
] as const;
export type ProductType = (typeof PRODUCT_TYPES)[number];

export const PRODUCT_TYPE_LABELS: Record<ProductType, string> = {
  awning: "Awning window",
  casement: "Casement window",
  sliding: "Sliding window/door",
  double_hung: "Double hung window",
  louvre: "Louvre window",
  powerlouvre: "Powerlouvre window",
  bi_fold: "Bi-fold window/door",
  sashless: "Sashless window",
  gas_strut: "Gas strut window",
  stacking: "Stacking door",
  hinged: "Hinged door",
  cedar_entry: "Cedar entry door",
};

export const MATERIALS = ["aluminium", "timber"] as const;
export type Material = (typeof MATERIALS)[number];

export const YES_NO_UNMARKED = ["yes", "no", "unmarked"] as const;
export type YesNoUnmarked = (typeof YES_NO_UNMARKED)[number];

export const WIND_RATINGS = ["700", "1000", "1500", "2000", "other", "unmarked"] as const;
export const WATER_RATINGS = ["150", "200", "300", "400", "450", "other", "unmarked"] as const;

export const ROOMS = [
  "Living Room",
  "Kitchen",
  "Bedroom",
  "Bathroom",
  "Laundry",
  "Study",
  "Garage",
  "Other",
] as const;

export interface RevealLining {
  selected: boolean;
  species: "maple" | "pine" | "unmarked";
  defin: "80" | "100" | "116" | "138" | "165" | "other" | "unmarked";
}

export const EMPTY_REVEAL: RevealLining = { selected: false, species: "unmarked", defin: "unmarked" };

export interface ExtractionHeader {
  client_name?: string | null;
  client_address?: string | null;
  contact_name?: string | null;
  phone?: string | null;
  email?: string | null;
  job_no?: string | null;
  rep?: string | null;
  date?: string | null;
  delivery_address?: string | null;
  colour?: string | null;
  glass?: string | null;
  wind_rating?: (typeof WIND_RATINGS)[number];
  water_rating?: (typeof WATER_RATINGS)[number];
  vent_locks?: YesNoUnmarked;
  acoustic_seals?: YesNoUnmarked;
  sump_sills?: YesNoUnmarked;
  reveal_28?: RevealLining;
  reveal_45?: RevealLining;
}

export interface ExtractionInstallation {
  building_type?: string | null;
  construction?: string | null;
  remove_existing?: string | null;
  floor_level?: string | null;
  brick_removal_m2?: number | null;
  scaffold?: YesNoUnmarked;
  hoist?: YesNoUnmarked;
  brick_saw?: YesNoUnmarked;
  men_reqd?: number | null;
  time_estimate_hrs?: number | null;
  asbestos?: YesNoUnmarked;
  notes?: string;
}

export interface DraftQuote {
  quote_id: string;
  status: string;
}

export interface DraftItem {
  item_id: string;
  item_no: number;
  product_type: ProductType;
  material: Material;
  room: string | null;
  width_mm: number | null;
  height_mm: number | null;
}

export interface PhotoUploadResult {
  resolved: boolean;
  value_mm: number | null;
  multi_reading: boolean;
  reason: "unreadable" | "conflict" | null;
  conflict_values_mm: number[] | null;
}

export interface QuoteDetail {
  id: string;
  status: string;
  header: { client_name: string | null } | null;
  items: { item_no: number; product_type: string; height_mm: number | null; width_mm: number | null }[];
  total: string | null;
}

// GET /worker/quotes (list) and GET /worker/quotes/{id} (detail) — the
// worker-scoped, ownership-checked read endpoints used for Job List and
// draft resumption. Deliberately a different shape from QuoteDetail above
// (which mirrors the public, non-worker-scoped GET /quotes/{id}).
export interface QuoteSummary {
  quote_id: string;
  status: string;
  client_name: string | null;
  created_at: string;
  total: string | null;
  scheduled_date: string | null;
}

export interface WorkerItemSummary {
  item_id: string;
  item_no: number;
  product_type: ProductType;
  material: Material;
  room: string | null;
  config_code: string | null;
  width_mm: number | null;
  height_mm: number | null;
  sill_height_mm: number | null;
  line_total: string | null;
}

export interface QuoteFlag {
  code: string;
  message: string;
}

export interface CommentOut {
  id: string;
  author: string;
  body: string;
  action: string | null;
  created_at: string;
}

export interface WorkerQuoteDetail {
  quote_id: string;
  status: string;
  client_name: string | null;
  total: string | null;
  scheduled_date: string | null;
  flags: QuoteFlag[];
  items: WorkerItemSummary[];
  comments: CommentOut[];
}

export interface OwnerQuoteSummary {
  quote_id: string;
  status: string;
  client_name: string | null;
  created_at: string;
  total: string | null;
  tradie_name: string | null;
  readiness_score: number | null;
}

export interface OwnerHeader {
  client_address: string | null;
  contact_name: string | null;
  phone: string | null;
  email: string | null;
  job_no: string | null;
  rep: string | null;
  delivery_address: string | null;
  colour: string | null;
  glass: string | null;
  wind_rating: string | null;
  water_rating: string | null;
  vent_locks: string | null;
  acoustic_seals: string | null;
  sump_sills: string | null;
}

export interface OwnerInstallation {
  building_type: string | null;
  construction: string | null;
  floor_level: string | null;
  remove_existing: string | null;
  brick_removal_m2: number | null;
  scaffold: string | null;
  hoist: string | null;
  brick_saw: string | null;
  asbestos: string | null;
  notes: string | null;
}

export interface OwnerItemSummary {
  item_id: string;
  item_no: number;
  product_type: ProductType;
  material: Material;
  room: string | null;
  config_code: string | null;
  width_mm: number | null;
  height_mm: number | null;
  sill_height_mm: number | null;
  qty: number;
  unit_price: string | null;
  line_total: string | null;
  glass_spec: string | null;
  hardware: string[];
  frame_components: string[];
  sealant_and_fixings: string[];
  enrichment_notes: string | null;
}

export interface OwnerQuoteDetail {
  quote_id: string;
  status: string;
  client_name: string | null;
  header: OwnerHeader;
  installation: OwnerInstallation;
  items_subtotal: string | null;
  installation_subtotal: string | null;
  gst_amount: string | null;
  total: string | null;
  flags: QuoteFlag[];
  agent_notes: string[];
  items: OwnerItemSummary[];
  comments: CommentOut[];
  tradie_name: string | null;
  readiness_score: number | null;
}

// GET /owner/quotes/map (maps branch) — geocoded pins for Anthony's in-flight
// NSW jobs. "pending" = a job still awaiting Anthony's decision; "ongoing" =
// already past his desk (or a Sales-booked site visit). Only the owner role
// can reach the endpoint, so only Anthony sees job locations. Mirrors
// app/api/owner_quotes.py::OwnerMapPin / OwnerMapResponse.
export type OwnerMapCategory = "pending" | "ongoing";

export interface OwnerMapPin {
  quote_id: string;
  status: string;
  category: OwnerMapCategory;
  client_name: string | null;
  address: string | null;
  lat: number;
  lng: number;
  total: string | null;
  scheduled_date: string | null;
  tradie_name: string | null;
  readiness_score: number | null;
}

export interface OwnerMapResponse {
  pins: OwnerMapPin[];
  // In-scope jobs that couldn't be pinpointed (no address / unresolvable).
  unmapped: number;
}
