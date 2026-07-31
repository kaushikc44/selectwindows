import { apiGet, apiPostJson } from "./client";
import { RescheduleReason } from "./types";

export interface SalesJobSummary {
  quote_id: string;
  status: string;
  client_name: string | null;
  assigned_tradie_name: string | null;
  scheduled_date: string | null;
  created_at: string;
}

export interface SalesCommentOut {
  id: string;
  author: string;
  body: string;
  action: string | null;
  created_at: string;
}

export interface SalesJobDetail {
  quote_id: string;
  status: string;
  client_name: string | null;
  client_address: string | null;
  contact_name: string | null;
  phone: string | null;
  email: string | null;
  job_no: string | null;
  assigned_tradie_id: string | null;
  assigned_tradie_name: string | null;
  scheduled_date: string | null;
  comments: SalesCommentOut[];
}

export interface Tradie {
  id: string;
  name: string;
}

export interface NewSalesJobInput {
  client_name: string;
  client_address?: string | null;
  contact_name?: string | null;
  phone?: string | null;
  email?: string | null;
  job_no?: string | null;
  assigned_tradie_id: string;
  scheduled_date: string;
}

export function listTradies(): Promise<Tradie[]> {
  return apiGet<Tradie[]>("/sales/tradies");
}

export function createSalesJob(input: NewSalesJobInput): Promise<{ quote_id: string; status: string }> {
  return apiPostJson("/sales/quotes", input);
}

export function listSalesJobs(): Promise<SalesJobSummary[]> {
  return apiGet<SalesJobSummary[]>("/sales/quotes");
}

export function getSalesJob(quoteId: string): Promise<SalesJobDetail> {
  return apiGet<SalesJobDetail>(`/sales/quotes/${quoteId}`);
}

export function rescheduleJob(
  quoteId: string,
  newDate: string,
  reason: RescheduleReason,
  otherDetail?: string
): Promise<{ quote_id: string; status: string; scheduled_date: string }> {
  return apiPostJson(`/sales/quotes/${quoteId}/reschedule`, {
    new_date: newDate,
    reason,
    other_detail: otherDetail || null,
  });
}
