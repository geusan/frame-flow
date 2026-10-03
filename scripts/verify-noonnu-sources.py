#!/usr/bin/env python3
"""Verify font signatures and resolve download links using saved audit evidence."""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from app.noonnu_fonts import _css_urls, _safe_stylesheet_url, _variants


spec = importlib.util.spec_from_file_location("noonnu_audit", Path(__file__).with_name("audit-noonnu-fonts.py"))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def normalized(value):
    return re.sub(r"[\W_]+", "", value.casefold())


def download_score(link, names):
    value = unquote(link["url"] + " " + link["label"])
    score = 0
    if re.search(r"\.(ttf|otf|woff2?|zip)(?:[?#]|$)", link["url"], re.I):
        score += 40
    if re.search(r"다운|download|첨부|ttf|otf|zip|글꼴|서체", value, re.I):
        score += 15
    if any(len(name) > 2 and name in normalized(value) for name in names):
        score += 60
    if re.search(r"login|signin|privacy|terms|youtube|facebook|instagram|mailto|로그인|개인정보|이용약관", value, re.I):
        score -= 100
    return score


async def verify_font(fetcher, root, font):
    detail_path = root / "details" / f"{font['id']}.json"
    detail = json.loads(detail_path.read_text()) if detail_path.exists() else {}
    css = detail.get("webfont_css") or font.get("cdn_server_html") or ""
    preview_css = detail.get("preview_css", "")
    hints = [font["name"], font.get("name_en", "")]
    faces = {face["key"]: face for face in _variants(css, family_hints=hints)}
    for face in _variants(preview_css):
        faces.setdefault(face["key"], face)
    stylesheet_checks = []
    for url in dict.fromkeys(_css_urls(css)):
        if _safe_stylesheet_url(url):
            meta, body = await fetcher.get(url)
            stylesheet_checks.append(meta)
            if meta.get("status") == 200:
                for face in _variants(audit.decode(body), base_url=url, family_hints=hints):
                    faces.setdefault(face["key"], {**face, "source_kind": "google_fonts", "stylesheet_url": url})
    verified = []
    failed = []
    for face in faces.values():
        for candidate in dict.fromkeys(face.get("urls", [face["url"]])):
            meta, body = await fetcher.get(candidate, probe=True)
            if meta.get("status") in {200, 206} and audit.file_type(body) == "font":
                verified.append({**face, "url": candidate, "checked_at": meta["checked_at"], "final_url": meta.get("final_url"), "signature": body[:4].hex()})
                break
            failed.append({"variant": face["key"], "url": candidate, "visit": meta})
    result = {"id": font["id"], "name": font["name"], "detail_visited": detail.get("parsed", False),
              "verified_variants": verified, "failed_variants": failed, "stylesheet_checks": stylesheet_checks}
    audit.write_json(root / "verified" / f"{font['id']}.json", result)
    return result


async def resolve_publisher(fetcher, root, font):
    path = root / "publishers" / f"{font['id']}.json"
    if not path.exists():
        return None
    source = json.loads(path.read_text())
    target = root / "resolved-publishers" / f"{font['id']}.json"
    if target.exists():
        return json.loads(target.read_text())
    names = [normalized(font.get("name", "")), normalized(font.get("name_en", ""))]
    checked, downloads = [], []
    frontier = []
    for page in source["pages"]:
        for link in page["files"]:
            frontier.append((link, 0, page["visit"].get("final_url")))
        if not page["files"]:
            candidates = sorted(page["links"], key=lambda link: download_score(link, names), reverse=True)
            frontier.extend((link, 0, page["visit"].get("final_url")) for link in candidates[:4] if download_score(link, names) >= 15)
        # Naver blog download attachments are in its publicly linked post frame.
        frontier.extend(({"url": frame, "label": "embedded publisher page"}, 0, page["visit"].get("final_url")) for frame in page.get("frames", [])[:1])
    visited = set()
    while frontier and len(visited) < 12:
        link, depth, from_url = frontier.pop(0)
        url = link["url"]
        if url in visited:
            continue
        visited.add(url)
        if "fonts.google.com" == urlsplit(url).hostname:
            checked.append({"url": url, "kind": "google_fonts", "found_on": from_url})
            continue
        meta, prefix = await fetcher.get(url, probe=True)
        kind = audit.file_type(prefix)
        checked.append(meta)
        if meta.get("status") in {200, 206} and kind:
            downloads.append({"url": url, "final_url": meta.get("final_url"), "label": link["label"], "kind": kind,
                              "found_on": from_url, "checked_at": meta["checked_at"], "name_match": download_score(link, names) >= 60})
        elif meta.get("status") == 200 and depth < 1 and ("html" in meta.get("content_type", "") or prefix.lstrip().startswith(b"<")):
            page_meta, body = await fetcher.get(url)
            links, _ = audit.page_links(body, page_meta.get("final_url", url))
            candidates = sorted(links, key=lambda candidate: download_score(candidate, names), reverse=True)
            frontier.extend((candidate, depth + 1, page_meta.get("final_url", url)) for candidate in candidates[:4] if download_score(candidate, names) >= 15)
    result = {"id": font["id"], "name": font["name"], "downloads": downloads, "checked": checked}
    audit.write_json(target, result)
    return result


async def run(args):
    root = Path(args.output)
    fonts = json.loads((root / "catalog.json").read_text())["fonts"]
    fetcher = audit.Fetcher(root, concurrency=6)
    for host in ["cdn.jsdelivr.net", "fastly.jsdelivr.net", "fonts.gstatic.com", "hangeul.pstatic.net"]:
        fetcher.intervals[host] = 0.18
    work = asyncio.Semaphore(10)
    try:
        async def one(font):
            async with work:
                return await (resolve_publisher(fetcher, root, font) if args.phase == "publishers" else verify_font(fetcher, root, font))
        done = []
        for task in asyncio.as_completed([one(font) for font in fonts]):
            row = await task
            done.append(row)
            if len(done) % 100 == 0 or len(done) == len(fonts):
                print(f"{args.phase}: {len(done)}/{len(fonts)}", flush=True)
        audit.write_json(root / ("verified.json" if args.phase == "fonts" else "resolved-publishers.json"), [row for row in done if row])
    finally:
        await fetcher.client.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="output/noonnu-source-audit-20261003")
    parser.add_argument("--phase", choices=["fonts", "publishers"], default="fonts")
    asyncio.run(run(parser.parse_args()))
