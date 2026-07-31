import React, { createContext, useContext, useState } from "react";

import { Material, ProductType, WorkerQuoteDetail } from "../api/types";

// Tracks the in-progress draft client-side for a session (create job ->
// add items -> capture photos -> submit), refreshed locally as each step
// completes so Items/ReviewSubmit don't need a round trip per render.
// GET /worker/quotes/{id} (see api/quotes.ts::getMyQuote) now exists, so a
// draft CAN be resumed after a restart via `hydrateFromServer` — see
// JobListScreen, which fetches it and calls that before navigating in.
export interface DraftItem {
  item_id: string;
  item_no: number;
  product_type: ProductType;
  material: Material;
  room: string | null;
  width_mm: number | null;
  height_mm: number | null;
}

interface DraftContextValue {
  quoteId: string | null;
  clientName: string | null;
  items: DraftItem[];
  // "draft" for a fresh job, "changes_requested" when resuming one Anthony
  // sent back for fixes (see QuoteDetailScreen's "Fix This Job") — null
  // until a draft is started/hydrated. ItemsScreen/ReviewSubmitScreen use
  // this to submit vs resubmit.
  status: string | null;
  startDraft: (quoteId: string, clientName: string) => void;
  hydrateFromServer: (detail: WorkerQuoteDetail) => void;
  addItem: (item: DraftItem) => void;
  setItemDimension: (itemId: string, field: "width" | "height", valueMm: number) => void;
  reset: () => void;
}

const DraftContext = createContext<DraftContextValue | undefined>(undefined);

export function DraftProvider({ children }: { children: React.ReactNode }) {
  const [quoteId, setQuoteId] = useState<string | null>(null);
  const [clientName, setClientName] = useState<string | null>(null);
  const [items, setItems] = useState<DraftItem[]>([]);
  const [status, setStatus] = useState<string | null>(null);

  const startDraft = (newQuoteId: string, newClientName: string) => {
    setQuoteId(newQuoteId);
    setClientName(newClientName);
    setItems([]);
    setStatus("draft");
  };

  const hydrateFromServer = (detail: WorkerQuoteDetail) => {
    setQuoteId(detail.quote_id);
    setClientName(detail.client_name);
    setStatus(detail.status);
    setItems(
      detail.items.map((it) => ({
        item_id: it.item_id,
        item_no: it.item_no,
        product_type: it.product_type,
        material: it.material,
        room: it.room,
        width_mm: it.width_mm,
        height_mm: it.height_mm,
      }))
    );
  };

  const addItem = (item: DraftItem) => setItems((prev) => [...prev, item]);

  const setItemDimension = (itemId: string, field: "width" | "height", valueMm: number) => {
    setItems((prev) =>
      prev.map((it) => (it.item_id === itemId ? { ...it, [field === "width" ? "width_mm" : "height_mm"]: valueMm } : it))
    );
  };

  const reset = () => {
    setQuoteId(null);
    setClientName(null);
    setItems([]);
    setStatus(null);
  };

  return (
    <DraftContext.Provider
      value={{ quoteId, clientName, items, status, startDraft, hydrateFromServer, addItem, setItemDimension, reset }}
    >
      {children}
    </DraftContext.Provider>
  );
}

export function useDraft(): DraftContextValue {
  const ctx = useContext(DraftContext);
  if (!ctx) throw new Error("useDraft must be used within a DraftProvider");
  return ctx;
}
