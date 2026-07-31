import { API_BASE_URL, apiGet, apiPostForm, apiPostJson } from "./client";
import {
  DraftQuote,
  ExtractionHeader,
  ExtractionInstallation,
  Material,
  PhotoUploadResult,
  ProductType,
  QuoteDetail,
  QuoteSummary,
  RescheduleReason,
  WorkerQuoteDetail,
} from "./types";

// The tradie's on-site completion of a Sales-created job (Phase F) — Sales
// already created the bare customer header (see api/sales.ts::createSalesJob),
// this fills in the rest (colour/glass/ratings/reveal linings + installation)
// and moves the quote from "scheduled" to "draft". See
// app/api/worker_quotes.py::set_property_details.
export function setPropertyDetails(
  quoteId: string,
  header: ExtractionHeader,
  installation: ExtractionInstallation
): Promise<DraftQuote> {
  return apiPostJson<DraftQuote>(`/worker/quotes/${quoteId}/property-details`, { header, installation });
}

export function reportMissedVisit(
  quoteId: string,
  reason: RescheduleReason,
  otherDetail?: string
): Promise<DraftQuote> {
  return apiPostJson<DraftQuote>(`/worker/quotes/${quoteId}/missed`, {
    reason,
    other_detail: otherDetail || null,
  });
}

export interface NewItemInput {
  product_type: ProductType;
  material: Material;
  room?: string | null;
  qty?: number;
  screen?: "yes" | "no" | "unmarked";
  config_code?: string | null;
  sill_height_mm?: number | null;
}

export function addItem(quoteId: string, item: NewItemInput): Promise<{ item_id: string; item_no: number }> {
  return apiPostJson(`/worker/quotes/${quoteId}/items`, item);
}

export async function uploadDimensionPhoto(
  quoteId: string,
  itemId: string,
  field: "width" | "height",
  photoUri: string
): Promise<PhotoUploadResult> {
  const form = new FormData();
  form.append("field", field);
  // React Native's fetch/FormData accepts this {uri, name, type} shape for
  // a file picked via expo-image-picker — not a real Blob/File like on web.
  form.append("photo", {
    uri: photoUri,
    name: `${field}.jpg`,
    type: "image/jpeg",
  } as unknown as Blob);

  return apiPostForm<PhotoUploadResult>(`/worker/quotes/${quoteId}/items/${itemId}/photos`, form);
}

export function submitQuote(quoteId: string): Promise<DraftQuote> {
  return apiPostJson<DraftQuote>(`/worker/quotes/${quoteId}/submit`, {});
}

export function resubmitQuote(quoteId: string, note?: string): Promise<DraftQuote> {
  return apiPostJson<DraftQuote>(`/worker/quotes/${quoteId}/resubmit`, { note: note || null });
}

// Typed-in alternative to uploadDimensionPhoto — same response shape, no
// photo involved. See app/api/worker_quotes.py::enter_dimension_manually.
export function uploadManualDimension(
  quoteId: string,
  itemId: string,
  field: "width" | "height",
  valueMm: number
): Promise<PhotoUploadResult> {
  return apiPostJson<PhotoUploadResult>(`/worker/quotes/${quoteId}/items/${itemId}/dimensions`, {
    field,
    value_mm: valueMm,
  });
}

export function getQuote(quoteId: string): Promise<QuoteDetail> {
  return apiGet<QuoteDetail>(`/quotes/${quoteId}`);
}

export async function getElevationPreview(configCode: string): Promise<string> {
  const result = await apiGet<{ svg: string }>(`/worker/elevation-preview?config_code=${encodeURIComponent(configCode)}`);
  return result.svg;
}

export function listMyQuotes(): Promise<QuoteSummary[]> {
  return apiGet<QuoteSummary[]>("/worker/quotes");
}

export function getMyQuote(quoteId: string): Promise<WorkerQuoteDetail> {
  return apiGet<WorkerQuoteDetail>(`/worker/quotes/${quoteId}`);
}

export interface ReferencePhoto {
  attachment_id: string;
  filename: string;
}

// General "+ Add Photo" capture per opening — context/condition photos,
// not a measurement. No extraction runs on these, and any number can be
// attached (unlike the one dimension photo per width/height).
export async function uploadReferencePhoto(
  quoteId: string,
  itemId: string,
  photoUri: string
): Promise<ReferencePhoto> {
  const form = new FormData();
  form.append("photo", {
    uri: photoUri,
    name: "reference.jpg",
    type: "image/jpeg",
  } as unknown as Blob);

  return apiPostForm<ReferencePhoto>(`/worker/quotes/${quoteId}/items/${itemId}/reference-photos`, form);
}

export function listReferencePhotos(quoteId: string, itemId: string): Promise<ReferencePhoto[]> {
  return apiGet<ReferencePhoto[]>(`/worker/quotes/${quoteId}/items/${itemId}/reference-photos`);
}

// GET /worker/attachments/{id} streams the raw photo bytes, ownership-checked
// server-side. It requires the same bearer token as every other worker
// endpoint, so callers must pass it as an Image `headers` prop (see
// AuthedImage) rather than using this as a plain, unauthenticated <Image> uri.
export function attachmentUrl(attachmentId: string): string {
  return `${API_BASE_URL}/worker/attachments/${attachmentId}`;
}
