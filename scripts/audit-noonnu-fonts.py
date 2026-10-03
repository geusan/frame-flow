#!/usr/bin/env python3
"""Resumable, paced audit of every public Noonnu catalog/detail/download page.

Writes evidence locally; it never registers fonts or executes downloaded files.
Usage: PYTHONPATH=apps/api .venv/bin/python scripts/audit-noonnu-fonts.py --phase details
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import html
import json
import os
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

import httpx

from app.noonnu_fonts import _DetailParser, _variants
from app.video_downloaders import validate_public_url


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


class Fetcher:
    def __init__(self, root, concurrency=4):
        self.root = root / "http"
        self.root.mkdir(parents=True, exist_ok=True)
        self.limit = asyncio.Semaphore(concurrency)
        self.host_locks = defaultdict(asyncio.Lock)
        self.next_request = defaultdict(float)
        self.intervals = defaultdict(lambda: 0.8)
        self.intervals["noonnu.cc"] = 1.3
        self.url_locks = defaultdict(asyncio.Lock)
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(25, connect=8), follow_redirects=False,
                                        headers={"User-Agent": "Frameflow-FontSourceAudit/1.0"})

    async def get(self, url, *, probe=False, refresh=False, max_bytes=3 * 1024 * 1024):
        key = hashlib.sha256((url + ("#probe" if probe else "") + (f"#max={max_bytes}" if max_bytes != 3 * 1024 * 1024 else "")).encode()).hexdigest()
        async with self.url_locks[key]:
            meta_path = self.root / (key + ".json")
            body_path = self.root / (key + ".body")
            if not refresh and meta_path.exists() and body_path.exists():
                cached = json.loads(meta_path.read_text())
                if cached.get("status") not in {429, 503} and not cached.get("error"):
                    return cached, body_path.read_bytes()
            result = {"url": url, "checked_at": now(), "redirects": []}
            body = b""
            try:
                current = url
                for _ in range(10):
                    await asyncio.to_thread(validate_public_url, current)
                    host = urlsplit(current).hostname
                    async with self.host_locks[host]:
                        while self.next_request[host] > time.monotonic():
                            await asyncio.sleep(self.next_request[host] - time.monotonic())
                        self.next_request[host] = time.monotonic() + self.intervals[host]
                    headers = {"Accept": "application/json" if "format=json" in current else "*/*"}
                    if probe:
                        headers["Range"] = "bytes=0-4095"
                    async with self.limit:
                        async with self.client.stream("GET", current, headers=headers) as response:
                            result.update({"status": response.status_code, "final_url": str(response.url),
                                           "content_type": response.headers.get("content-type", ""),
                                           "content_disposition": response.headers.get("content-disposition", ""),
                                           "content_length": response.headers.get("content-length")})
                            if response.status_code in {429, 503} and host != "github.com":
                                retry_after = response.headers.get("retry-after", "60")
                                delay = max(30, min(180, int(retry_after) if retry_after.isdigit() else 60))
                                self.intervals[host] = min(6, self.intervals[host] * 1.5)
                                self.next_request[host] = max(self.next_request[host], time.monotonic() + delay)
                                print(f"Rate limited {host}; waiting {delay}s, interval {self.intervals[host]:.1f}s", flush=True)
                                if len(result.setdefault("rate_limits", [])) < 2:
                                    result["rate_limits"].append({"status": response.status_code, "retry_after": delay})
                                    continue
                            if response.is_redirect and response.headers.get("location"):
                                current = urljoin(current, response.headers["location"])
                                result["redirects"].append(current)
                                continue
                            chunks = bytearray()
                            limit = 4096 if probe else max_bytes
                            async for chunk in response.aiter_bytes(chunk_size=4096 if probe else 65536):
                                chunks.extend(chunk)
                                if len(chunks) >= limit:
                                    result["truncated"] = True
                                    break
                            body = bytes(chunks[:limit])
                            break
                result["body_sha256"] = hashlib.sha256(body).hexdigest()
            except Exception as exc:
                result["error"] = f"{type(exc).__name__}: {str(exc)[:250]}"
            body_path.write_bytes(body)
            write_json(meta_path, result)
            return result, body


def decode(body):
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return body.decode("cp949", errors="replace")


def preview_styles(text, font_id):
    """Only styles used by this font's own weight controls, not recommendations."""
    families = defaultdict(set)
    for tag in re.findall(r"<input\b[^>]*>", text, re.I):
        weight = re.search(rf'''\bid=["']font{font_id}-weight([0-9]+)["']''', tag)
        style = re.search(r'''\bstyle=["']([^"']*)["']''', tag)
        if not weight or not style:
            continue
        family = re.search(r"font-family\s*:\s*([^;]+)", html.unescape(style.group(1)))
        if family:
            families[family.group(1).strip().strip("'\"")].add(weight.group(1))
    result = []
    for style in re.findall(r"<style[^>]*>(.*?)</style>", text, re.S | re.I):
        for block in re.findall(r"@font-face\s*\{([^}]+)\}", html.unescape(style), re.I):
            family = re.search(r"font-family\s*:\s*([^;]+)", block)
            if not family:
                continue
            weights = families.get(family.group(1).strip().strip("'\""))
            if not weights:
                continue
            if len(weights) == 1:
                block = re.sub(r"font-weight\s*:[^;]+;?", "", block)
                block += f";font-weight:{next(iter(weights))};"
            result.append("@font-face {" + block + "}")
    return "\n".join(result)


async def catalog(fetcher, root):
    path = root / "catalog.json"
    if path.exists():
        return json.loads(path.read_text())["fonts"]
    fonts = {}
    page = 1
    expected = None
    while True:
        # Popularity changes while traversing; use the site's stable name sort.
        meta, body = await fetcher.get(f"https://noonnu.cc/index?format=json&order_by=na&page={page}")
        if meta.get("status") != 200:
            raise RuntimeError(f"Catalog page {page}: {meta}")
        data = json.loads(body)
        expected = data["total_count"]
        for font in data["fonts"]:
            if not font.get("is_market"):
                fonts[font["id"]] = font
        if page % 10 == 0:
            print(f"Catalog {len(fonts)}/{expected}", flush=True)
        if data.get("is_last_page") or not data["fonts"]:
            break
        page += 1
    if len(fonts) != expected:
        raise RuntimeError(f"Catalog changed during traversal: {len(fonts)} != {expected}")
    write_json(path, {"checked_at": now(), "total": expected, "pages": page, "fonts": list(fonts.values())})
    return list(fonts.values())


async def detail(fetcher, root, font):
    target = root / "details" / f"{font['id']}.json"
    if target.exists():
        cached = json.loads(target.read_text())
        if cached.get("parsed"):
            return cached
    url = f"https://noonnu.cc/font_page/{font['id']}"
    meta, body = await fetcher.get(url)
    record = {"id": font["id"], "name": font["name"], "name_en": font.get("name_en", ""),
              "page_url": url, "visit": meta, "parsed": False}
    try:
        if meta.get("status") != 200:
            raise ValueError(meta.get("error") or f"HTTP {meta.get('status')}")
        parser = _DetailParser()
        parser.feed(decode(body))
        schema = next(json.loads(part) for part in parser.schema if '"SoftwareApplication"' in part)
        css = "".join(parser.webfont)
        record.update({"parsed": True, "schema": schema, "webfont_css": css, "variants": _variants(css),
                       "preview_css": preview_styles(decode(body), font["id"]),
                       "license_text": "".join(parser.license).strip(),
                       "permissions": {row[0]: row[2] for row in parser.rows if len(row) == 3},
                       "download_pages": [{"url": urljoin(url, href), "label": label} for href, label in parser.links if "다운로드 페이지로 이동" in label],
                       "external_links": [{"url": href, "label": label} for href, label in parser.links if href.startswith(("http://", "https://")) and urlsplit(href).hostname not in {"noonnu.cc", "www.noonnu.cc"}],
                       "css_urls": re.findall(r"https?://[^\s'\"<>\)]+", html.unescape(css))})
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {str(exc)[:250]}"
    write_json(target, record)
    return record


class PageLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.frames = []
        self._link = None

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if tag == "a" and data.get("href"):
            self._link = {"url": data["href"], "label": data.get("download", "") or ""}
        if tag in {"iframe", "frame"} and data.get("src"):
            self.frames.append(data["src"])
        for key, value in attrs:
            if value and re.search(r"\.(?:ttf|otf|woff2?|zip)(?:[?\"']|$)", value, re.I):
                self.links.append({"url": value, "label": data.get("download", "") or ""})

    def handle_data(self, data):
        if self._link:
            self._link["label"] += data.strip() + " "

    def handle_endtag(self, tag):
        if tag == "a" and self._link:
            self.links.append(self._link)
            self._link = None


def page_links(body, base):
    text = decode(body)
    parser = PageLinks()
    parser.feed(text)
    links = parser.links
    clean = html.unescape(text).replace("\\/", "/").replace("\\u0026", "&")
    for match in re.findall(r'''(?:https?:)?//[^\s<>"'`\\]+\.(?:ttf|otf|woff2?|zip)(?:\?[^\s<>"'`\\]*)?''', clean, re.I):
        links.append({"url": match, "label": "embedded file URL"})
    result = {}
    for link in links:
        url = urljoin(base, link["url"].strip())
        if urlsplit(url).scheme not in {"http", "https"} or urlsplit(url).username:
            continue
        result.setdefault(url, {"url": url, "label": " ".join(link["label"].split())[:250]})
    return list(result.values()), [urljoin(base, frame) for frame in parser.frames]


def file_type(body):
    if body[:4] in {b"\x00\x01\x00\x00", b"OTTO", b"true", b"wOFF", b"wOF2", b"ttcf"}:
        return "font"
    if body[:4] in {b"PK\x03\x04", b"PK\x05\x06"}:
        return "zip"
    return None


async def publisher(fetcher, root, record):
    target = root / "publishers" / f"{record['id']}.json"
    if target.exists():
        return json.loads(target.read_text())
    results = []
    for origin in record.get("download_pages", []):
        url = origin["url"]
        meta, body = await fetcher.get(url)
        result = {"visit": meta, "links": [], "files": [], "frames": []}
        if meta.get("status") == 200:
            binary = file_type(body)
            if binary:
                result["files"] = [{"url": meta["final_url"], "label": origin["label"], "signature": binary}]
            else:
                links, frames = page_links(body, meta["final_url"])
                result["links"] = [link for link in links if re.search(r"download|다운|\.zip|\.ttf|\.otf|google.com|github.com|font|서체", link["label"] + " " + link["url"], re.I)]
                result["frames"] = frames
                result["files"] = [link for link in links if re.search(r"\.(ttf|otf|woff2?|zip)(?:[?#]|$)", link["url"], re.I)]
        results.append(result)
    value = {"id": record["id"], "name": record["name"], "pages": results, "checked_at": now()}
    write_json(target, value)
    return value


async def run(args):
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    fetcher = Fetcher(root)
    try:
        fonts = await catalog(fetcher, root)
        if args.phase == "catalog":
            print(f"Catalog complete: {len(fonts)}", flush=True)
            return
        work = asyncio.Semaphore(6)
        async def limited_detail(font):
            async with work:
                return await detail(fetcher, root, font)
        records = []
        if args.phase == "origins":
            records = [json.loads(path.read_text()) for path in (root / "details").glob("*.json")]
            records = [record for record in records if record.get("parsed")]
        else:
            for task in asyncio.as_completed([limited_detail(font) for font in fonts]):
                records.append(await task)
                if len(records) % 50 == 0 or len(records) == len(fonts):
                    print(f"Details {len(records)}/{len(fonts)}; parsed={sum(bool(r['parsed']) for r in records)}", flush=True)
                    write_json(root / "progress.json", {"phase": "details", "done": len(records), "total": len(fonts), "updated_at": now()})
            write_json(root / "details.json", sorted(records, key=lambda row: row["id"]))
        if args.phase == "details":
            return
        async def limited_publisher(record):
            async with work:
                return await publisher(fetcher, root, record)
        done = []
        for task in asyncio.as_completed([limited_publisher(record) for record in records]):
            done.append(await task)
            if len(done) % 50 == 0 or len(done) == len(records):
                print(f"Publishers {len(done)}/{len(records)}", flush=True)
                write_json(root / "publisher-progress.json", {"phase": "publishers", "done": len(done), "total": len(records), "updated_at": now()})
        write_json(root / ("publishers-partial.json" if args.phase == "origins" else "publishers.json"), sorted(done, key=lambda row: row["id"]))
    finally:
        await fetcher.client.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["catalog", "details", "publishers", "origins"], default="publishers")
    parser.add_argument("--output", default="output/noonnu-source-audit-20261003")
    asyncio.run(run(parser.parse_args()))
