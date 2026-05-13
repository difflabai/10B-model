#!/usr/bin/env python3
"""Generate the 10B system infographic via the Gemini Image API.

Equivalent to the nano-banana skill's `gemini_generate_image`, but invoked
directly because the configured `nanobanana-mcp` MCP package is no longer
on npm. Uses the same API key the MCP server was configured with.

Output: registry/global/10B/docs/infographic.png
"""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import tenb_root  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = tenb_root() / "docs"
OUT_PATH = OUT_DIR / "infographic.png"

API_KEY = os.environ.get("GEMINI_API_KEY")
MODEL = "gemini-3-pro-image-preview"

PROMPT = """A clean, professional infographic explaining the architecture of the "10B" human-needs model.

Conceptual layout: a layered diagram, top to bottom, on a soft warm cream background (#F2EFEA), with subtle teal (#557373) and deep olive (#272401) accents.

LAYER 1 (top) — "The 10B Needs Tree" — three horizontal bands labelled SUBSISTENCE, DEVELOPMENT, AGENCY. Inside each band, five rounded rectangles for the categories. Subsistence: food, water, shelter, health, safety. Development: education, work, energy, mobility, communications. Agency: governance, environment, belonging, meaning, agency. Pictograms inside each card (a wheat sheaf for food, a droplet for water, a house for shelter, etc.). Soft drop shadows. Anchored small-print credit underneath: "Maslow · Max-Neef · Doyal-Gough · UN SDGs".

LAYER 2 (middle) — "Country × Category Cells" — a flat grid of small tiles representing 258 countries × 15 categories, rendered as a 12x6 sample tile grid with colour gradient from beige (low score) to deep teal (high score), evoking a heatmap. Above it: small label "3,870 cells, each a model".

LAYER 3 (rollups) — three converging arrows flowing upward into a central hexagonal node labelled "10B EMBEDDING". The three arrow streams are labelled, left to right: "country rollups (258)", "regional rollups (6 UN regions)", "category world rollups (15)".

LAYER 4 (heads) — from the central 10B EMBEDDING hexagon, three labelled rays fan out to three rounded boxes:
  - LEFT ray: "UNSUPERVISED DYNAMICS — k-means clusters reveal macro-space attractors"  (small visual: 6 coloured dots clustered)
  - CENTRE ray: "SUPERVISED TRAJECTORY — predicts hold-out sociodemographic data"  (small visual: a curve with confidence intervals)
  - RIGHT ray: "PERSONAL AGENT — answers three founding questions"  (small visual: a chat bubble with three dots)

LAYER 5 (bottom) — three speech bubbles in a row containing the founding questions:
  "How can I connect with my neighbors?"
  "What economic value can I bring to my community?"
  "How can I effectively advocate for change?"

OVERALL STYLE: minimalist, modernist, infographic style, flat vector aesthetic, generous whitespace, sans-serif typography (DIN-style), small line-icons, clear labels. Colour palette: warm cream background, teal (#557373) primary accent, soft blue-gray (#DFE5F3) for cell tiles, deep olive (#272401) for arrows and titles, near-black (#0D0D0D) text. Aspect 4:3. High resolution, crisp lines. Avoid: photorealism, 3D effects, busy backgrounds, gibberish text, cartoonish elements, watermarks."""


def main() -> int:
    if not API_KEY:
        print("ERROR: set GEMINI_API_KEY in env", file=sys.stderr)
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": PROMPT}]}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"aspectRatio": "4:3"},
        },
    }

    # Send the API key in the `x-goog-api-key` header rather than the
    # URL query string — query params land in proxy / web-server logs
    # and don't belong in shell history either.
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": API_KEY,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        print(f"HTTPError {e.code}: {e.read().decode('utf-8', 'ignore')}", file=sys.stderr)
        return 1

    data = json.loads(body)
    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    for part in parts:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            img_bytes = base64.b64decode(inline["data"])
            OUT_PATH.write_bytes(img_bytes)
            print(f"wrote {OUT_PATH} ({len(img_bytes):,} bytes)")
            return 0

    print(f"no image returned; response keys: {list(data)}\nfull: {json.dumps(data)[:1500]}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
