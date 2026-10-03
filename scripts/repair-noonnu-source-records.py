#!/usr/bin/env python3
"""Build evidence-backed exceptions from publisher/repository files already found."""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import io
import json
import re
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from fontTools.ttLib import TTFont
from app.noonnu_fonts import _css_urls, _safe_font_url, normalize_noonnu_font
from app.font_registry import FONT_MAX_BYTES, inspect_font

spec = importlib.util.spec_from_file_location("source_audit", Path(__file__).with_name("audit-noonnu-fonts.py"))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
ROOT = Path("output/noonnu-source-audit-20261003")


def describe(content, url, kind, evidence, archive_member=None):
    with TTFont(io.BytesIO(content), lazy=True) as font:
        axis = next((axis for axis in font["fvar"].axes if axis.axisTag == "wght"), None) if "fvar" in font else None
        instance_names = {int(instance.coordinates["wght"]): font["name"].getDebugName(instance.subfamilyNameID) for instance in font["fvar"].instances if "wght" in instance.coordinates} if axis else {}
        weights = [int(axis.defaultValue)] if axis else [None]
        if axis:
            weights = [weight for weight in range(100, 1001, 100) if axis.minValue <= weight <= axis.maxValue]
    # Inspect one fixed instance; other weights are validated by the instancer
    # when imported, and constrained here to the file's actual axis limits.
    normalized, _ = normalize_noonnu_font(content, weight=400 if axis and axis.minValue <= 400 <= axis.maxValue else weights[0])
    inspected = inspect_font(normalized)
    result = []
    for weight in weights:
        weight = weight or inspected.weight
        face = {"key": str(weight) + ("i" if inspected.style == "italic" else ""), "weight": weight,
                "style": inspected.style, "font_family": inspected.family_name,
                "label": f"{instance_names.get(weight) or inspected.subfamily_name} · {weight}", "url": url, "source_kind": kind,
                "evidence_url": evidence, "checked_at": audit.now(), "source_sha256": hashlib.sha256(content).hexdigest(),
                "postscript_name": inspected.postscript_name}
        if archive_member:
            face["archive_member"] = archive_member
        result.append(face)
    return result


async def run():
    fonts = {font["id"]: font for font in json.loads((ROOT / "catalog.json").read_text())["fonts"]}
    fetcher = audit.Fetcher(ROOT)
    entries = {}
    source_specs = []
    evidence_root = ROOT / "repository-evidence"
    evidence_root.mkdir(exist_ok=True)
    for filename, url in {
        "google-tree.json": "https://api.github.com/repos/google/fonts/git/trees/main?recursive=1",
        "wanted-tree.json": "https://api.github.com/repos/wanteddev/wanted-sans/git/trees/v1.0.1?recursive=1",
        "elice-brand.html": "https://elice.io/ko/resources/brand",
    }.items():
        if not (evidence_root / filename).exists():
            meta, body = await fetcher.get(url, max_bytes=16 * 1024 * 1024)
            if meta.get("status") != 200 or meta.get("truncated"):
                raise RuntimeError(f"Publisher evidence unavailable: {url}")
            (evidence_root / filename).write_bytes(body)
    # Exact paths were found in Google's official repository tree snapshot.
    tree = json.loads((ROOT / "repository-evidence/google-tree.json").read_text())
    google_families = {32: "kopubbatang", 49: "jejugothic", 50: "jejumyeongjo", 51: "jejuhallasan", 52: "hanna"}
    for font_id, family in google_families.items():
        for file in tree["tree"]:
            if file["path"].startswith(f"ofl/{family}/") and file["path"].endswith((".ttf", ".otf")):
                source_specs.append((font_id, "https://raw.githubusercontent.com/google/fonts/main/" + file["path"], "google_fonts_repository", "https://github.com/google/fonts/tree/main/ofl/" + family, None))
    # These sources were published in Noonnu CSS, but missing/colliding weight
    # declarations hid their faces. Read the actual font names and OS/2 weights.
    for font_id in [26, 1760, 1651, 1652, 1688]:
        detail = json.loads((ROOT / "details" / f"{font_id}.json").read_text())
        urls = [url for url in _css_urls(detail["webfont_css"]) if _safe_font_url(url)]
        full_ttf_urls = [url for url in urls if urlsplit(url).path.lower().endswith(".ttf")]
        if full_ttf_urls:
            urls = full_ttf_urls
        urls.sort(key=lambda url: not urlsplit(url).path.lower().endswith((".ttf", ".otf")))
        for url in dict.fromkeys(urls):
            source_specs.append((font_id, url, "noonnu_metadata_correction", detail["page_url"], None))
    # Complete Wanted Sans file: path from the publisher's v1.0.1 repository tree.
    tree = json.loads((ROOT / "repository-evidence/wanted-tree.json").read_text())
    path = next(file["path"] for file in tree["tree"] if file["path"].startswith("packages/wanted-sans/") and "/complete/" in file["path"] and file["path"].endswith("WantedSansVariable.woff2"))
    source_specs.append((1269, "https://raw.githubusercontent.com/wanteddev/wanted-sans/v1.0.1/" + path, "publisher_font", "https://github.com/wanteddev/wanted-sans/tree/v1.0.1/packages/wanted-sans", None))
    # Exact ZIP links come from the current publisher HTML saved during audit.
    naver = json.loads((ROOT / "publishers/37.json").read_text())
    for font_id, filename in [(36, "nanum-barun-gothic.zip"), (37, "nanum-square.zip")]:
        url = next(link["url"] for page in naver["pages"] for link in page["files"] if link["url"].endswith("/" + filename))
        source_specs.append((font_id, url, "publisher_archive", "https://hangeul.naver.com/fonts/search?f=nanum", "all"))
    elice_html = (ROOT / "repository-evidence/elice-brand.html").read_text()
    elice_url = next(url for url in re.findall(r'https?[^\s<>"\x27]+\.zip', elice_html) if url.endswith("EliceDXNeolli_TTF.zip"))
    source_specs.append((1229, elice_url, "publisher_archive", "https://elice.io/ko/resources/brand#elice_dx_neolli", "all"))
    try:
        for font_id, url, kind, evidence, archive in source_specs:
            entry = entries.setdefault(str(font_id), {"id": font_id, "name": fonts[font_id]["name"], "name_en": fonts[font_id].get("name_en", ""), "variants": [], "downloads": [], "errors": []})
            try:
                meta, body = await fetcher.get(url, max_bytes=96 * 1024 * 1024 if archive else FONT_MAX_BYTES)
                if meta.get("status") != 200 or meta.get("truncated"):
                    raise ValueError(f"HTTP {meta.get('status')}, truncated={meta.get('truncated', False)}")
                faces = []
                if archive:
                    with zipfile.ZipFile(io.BytesIO(body)) as package:
                        for member in package.infolist():
                            if not member.filename.lower().endswith((".ttf", ".otf")) or member.filename.startswith("__MACOSX/"):
                                continue
                            if member.file_size > FONT_MAX_BYTES:
                                continue
                            if not member.filename.lower().endswith(".ttf"):
                                continue
                            if font_id == 37 and "_ac" in member.filename.lower():
                                continue
                            faces.extend(describe(package.read(member), url, kind, evidence, member.filename))
                    entry["downloads"].append({"url": url, "label": "제작사 TTF ZIP", "kind": "zip", "evidence_url": evidence, "checked_at": meta["checked_at"]})
                else:
                    faces = describe(body, url, kind, evidence)
                for face in faces:
                    if any((old["font_family"], old["weight"], old["postscript_name"]) == (face["font_family"], face["weight"], face["postscript_name"]) for old in entry["variants"]):
                        continue
                    if any(old["key"] == face["key"] for old in entry["variants"]):
                        face["key"] += "-" + hashlib.sha256((url + face.get("archive_member", "")).encode()).hexdigest()[:8]
                        face["label"] = face["font_family"] + " · " + face["label"]
                    entry["variants"].append(face)
                print(font_id, fonts[font_id]["name"], len(faces), kind, flush=True)
            except Exception as exc:
                entry["errors"].append({"url": url, "error": str(exc)})
                print(font_id, "ERROR", str(exc), flush=True)
            audit.write_json(ROOT / "repairs.json", entries)
    finally:
        await fetcher.client.aclose()


if __name__ == "__main__":
    asyncio.run(run())
