# scripts/demo_extract.py
"""Walks through the real LiDAR-photo + email-text -> quote extraction
pipeline, using a synthetic image standing in for an iPhone LiDAR measuring
app's on-screen digital overlay.

Usage: .venv/bin/python scripts/demo_extract.py
"""
import io

from PIL import Image, ImageDraw

from app.ai.extract import extract_quote
from app.config import settings


def rule(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


rule("1. INPUT: synthetic photo standing in for a LiDAR app's digital overlay")
img = Image.new("RGB", (400, 200), "white")
d = ImageDraw.Draw(img)
d.text((20, 20), "Opening", fill="black")
d.text((20, 60), "Width:  0.90 m", fill="black")
d.text((20, 100), "Height: 1.20 m", fill="black")
buf = io.BytesIO()
img.save(buf, format="PNG")
image_bytes = buf.getvalue()
print(f"  Generated a {img.size[0]}x{img.size[1]} PNG ({len(image_bytes)} bytes) with a 0.90m x 1.20m readout")

body_text = "Bi-fold window, aluminium, laundry. Double glazed if possible."
print(f"\n  Email body text: {body_text!r}")

rule(
    "2. Calling vision model: "
    + settings.LLM_VISION_MODEL
    + " @ "
    + (settings.LLM_VISION_BASE_URL or settings.LLM_BASE_URL)
)
outcome = extract_quote([(image_bytes, "image/png")], body_text)

rule("3. RESULT")
if outcome.result is None:
    print(f"  Extraction failed: needs_manual={outcome.needs_manual} reason={outcome.reason}")
else:
    result = outcome.result
    print(f"  needs_manual={outcome.needs_manual}  overall_confidence={result.overall_confidence}")
    print(f"  unreadable_fields: {result.unreadable_fields}")
    print(f"  header.glass: {result.header.glass!r}")
    print(f"  installation: {result.installation}\n")
    for item in result.items:
        print(
            f"  #{item.item_no} {item.room}: {item.product_type}/{item.material} "
            f"{item.width_mm}x{item.height_mm}mm qty={item.qty} confidence={item.confidence}"
        )

rule("Done")
