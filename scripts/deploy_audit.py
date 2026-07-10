#!/usr/bin/env python3
"""Basic pre-deploy checks for the YupiTech static site."""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOMAIN = "https://yupitech.mutechlabs.com/"
WHATSAPP = "wa.me/50376034860"


def fail(message: str) -> None:
    raise SystemExit(f"deploy audit failed: {message}")


def main() -> int:
    index = (ROOT / "index.html").read_text(encoding="utf-8")
    robots = (ROOT / "robots.txt").read_text(encoding="utf-8")
    sitemap = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
    llms = (ROOT / "llms.txt").read_text(encoding="utf-8")

    if f'<link rel="canonical" href="{DOMAIN}">' not in index:
        fail("canonical domain is not yupitech.mutechlabs.com")
    if WHATSAPP not in index:
        fail("WhatsApp quote link is missing")
    if "Cotizar mi agente" not in index:
        fail("primary conversion CTA is missing")
    if f"Sitemap: {DOMAIN}sitemap.xml" not in robots:
        fail("robots.txt sitemap URL is wrong")
    if f"<loc>{DOMAIN}</loc>" not in sitemap:
        fail("sitemap root URL is wrong")
    if DOMAIN not in llms:
        fail("llms.txt domain is wrong")

    meta = re.search(r'<meta name="description" content="([^"]+)">', index)
    if not meta:
        fail("meta description is missing")
    if not (90 <= len(meta.group(1)) <= 165):
        fail(f"meta description length should be 90-165 chars, got {len(meta.group(1))}")

    print("deploy audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
