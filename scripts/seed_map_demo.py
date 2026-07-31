"""Seed a handful of NSW-address quotes so Anthony's job map (maps branch)
has something to pinpoint across pending + ongoing statuses. Idempotent —
re-running adds at most one of each (keyed on client_name + address)."""
from app.db import SessionLocal
from app.models import Item, Material, ProductType, Quote, QuoteHeader, QuoteStatus

TRADIE_ID = "2eae5ebe-9b64-4dcc-b17d-fe1f83307735"

# (client_name, status, address) — real NSW addresses so Nominatim resolves them.
JOBS = [
    ("Martin Ave Home", QuoteStatus.pending_approval, "1 Macquarie St, Sydney NSW 2000"),
    ("Burwood Reno", QuoteStatus.pending_approval, "12 Burwood Rd, Burwood NSW 2134"),
    ("York St Refit", QuoteStatus.needs_manual, "5 York St, Sydney NSW 2000"),
    ("Parramatta Build", QuoteStatus.approved, "100 George St, Parramatta NSW 2150"),
    ("McMahons Point", QuoteStatus.approved, "22 Blues Point Rd, McMahons Point NSW 2060"),
    ("Newcastle Job", QuoteStatus.scheduled, "401 Hunter St, Newcastle NSW 2300"),
    ("Wollongong Job", QuoteStatus.changes_requested, "90 Crown St, Wollongong NSW 2500"),
]

db = SessionLocal()
try:
    for name, status, address in JOBS:
        exists = db.query(Quote).join(QuoteHeader).filter(
            QuoteHeader.client_name == name, QuoteHeader.client_address == address
        ).first()
        if exists:
            continue
        q = Quote(status=status, assigned_tradie_id=TRADIE_ID)
        db.add(q)
        db.flush()
        db.add(QuoteHeader(quote_id=q.id, client_name=name, client_address=address))
        db.add(Item(
            quote_id=q.id, item_no=1, description_raw="aluminium awning window",
            product_type=ProductType.awning, material=Material.aluminium,
            height_mm=900, width_mm=600,
        ))
        db.commit()
        print(f"added {status.value:18} {name:20} {address}")
finally:
    db.close()