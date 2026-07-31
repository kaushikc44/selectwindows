import { apiGet, apiPostJson } from "./client";
import { AiLogsResponse, ExtractionHeader, ExtractionInstallation, Material, OwnerMapResponse, OwnerQuoteDetail, OwnerQuoteSummary, ProductType } from "./types";

export function listOwnerQueue(): Promise<OwnerQuoteSummary[]> {
  return apiGet<OwnerQuoteSummary[]>("/owner/quotes");
}

// Anthony's job map (maps branch) — geocoded NSW pins for his in-flight work.
// Owner-only on the backend, so this returns 403 for non-owner tokens.
export function getOwnerMap(): Promise<OwnerMapResponse> {
  return apiGet<OwnerMapResponse>("/owner/quotes/map");
}

// Anthony's AI audit trail (maps branch) — every LLM call per job, with the
// input sent and the output returned. Owner-only.
export function getAiLogs(quoteId?: string): Promise<AiLogsResponse> {
  const qs = quoteId ? `?quote_id=${encodeURIComponent(quoteId)}` : "";
  return apiGet<AiLogsResponse>(`/owner/ai-logs${qs}`);
}

export function getOwnerQuote(quoteId: string): Promise<OwnerQuoteDetail> {
  return apiGet<OwnerQuoteDetail>(`/owner/quotes/${quoteId}`);
}

export type CommentAction = "comment" | "approve" | "reject" | "request_changes";

export function postComment(
  quoteId: string,
  body: string,
  action: CommentAction
): Promise<{ quote_id: string; status: string }> {
  return apiPostJson(`/owner/quotes/${quoteId}/comments`, { body, action });
}

export interface OwnerItemEditInput {
  item_id: string | null;
  delete: boolean;
  product_type: ProductType;
  material: Material;
  room: string | null;
  config_code: string | null;
  qty: number;
  width_mm: number | null;
  height_mm: number | null;
  sill_height_mm: number | null;
  glass_spec: string;
  hardware: string[];
  frame_components: string[];
  sealant_and_fixings: string[];
  enrichment_notes: string | null;
}

// Anthony can change anything on a quote while it's still his to decide on
// — header, installation, every item field, and add/remove items outright.
// `items` must be the COMPLETE current item list every time (mark an item
// `delete: true` to remove it rather than omitting it) — see
// app/api/owner_quotes.py::edit_quote.
export function editQuote(
  quoteId: string,
  header: ExtractionHeader,
  installation: ExtractionInstallation,
  items: OwnerItemEditInput[]
): Promise<OwnerQuoteDetail> {
  return apiPostJson<OwnerQuoteDetail>(`/owner/quotes/${quoteId}/edit`, { header, installation, items });
}
