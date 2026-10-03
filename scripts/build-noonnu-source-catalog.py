#!/usr/bin/env python3
"""Publish the audited source inventory and a standalone, searchable report."""
from __future__ import annotations

import html
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("output/noonnu-source-audit-20261003")
TARGET = Path("apps/api/app/noonnu_sources.v1.json")


def read(path):
    return json.loads(path.read_text()) if path.exists() else {}


catalog = read(ROOT / "catalog.json")
repairs = read(ROOT / "repairs.json")
entries = {}
original_statuses = Counter()
for font in catalog["fonts"]:
    key = str(font["id"])
    detail = read(ROOT / "details" / f"{key}.json")
    verified = read(ROOT / "verified" / f"{key}.json")
    publisher = read(ROOT / "publishers" / f"{key}.json")
    repair = repairs.get(key)
    assert detail.get("parsed"), f"No successful Noonnu visit: {key}"
    assert publisher.get("pages"), f"No publisher visit: {key}"
    variants = repair["variants"] if repair and repair.get("variants") else verified.get("verified_variants", [])
    assert variants, f"No verified download for {font['name']} ({key})"
    originals = []
    for page in publisher["pages"]:
        visit = page["visit"]
        originals.append({"url": visit["url"], "final_url": visit.get("final_url"), "status": visit.get("status"),
                          "error": visit.get("error"), "checked_at": visit["checked_at"]})
        original_statuses[str(visit.get("status") or "network_error")] += 1
    checked_at = max(face["checked_at"] for face in variants)
    faces = []
    for face in variants:
        value = {name: face[name] for name in ("key", "weight", "style", "font_family", "label", "url", "source_kind", "stylesheet_url", "archive_member", "evidence_url", "checked_at") if name in face}
        value.setdefault("source_kind", "noonnu_webfont")
        value.setdefault("evidence_url", detail["page_url"])
        faces.append(value)
    faces.sort(key=lambda face: (face["style"] == "italic", face["weight"], face["key"]))
    downloads = repair.get("downloads", []) if repair else []
    if not downloads:
        representative = next((face for face in faces if face["key"] == "400"), faces[0])
        downloads = [{"url": representative["url"], "label": "확인된 폰트 파일", "kind": "font", "checked_at": representative["checked_at"], "evidence_url": representative["evidence_url"]}]
    permissions = detail["permissions"]
    entries[key] = {"id": font["id"], "name": font["name"], "name_en": font.get("name_en", ""),
                    "page_url": detail["page_url"], "status": "verified", "checked_at": checked_at,
                    "original_pages": originals, "variants": faces, "downloads": downloads,
                    "repaired": bool(repair),
                    "automatic_import_allowed": bool(detail.get("license_text")) and all(permissions.get(scope) == "사용 가능" for scope in ("영상", "웹사이트", "임베딩"))}

summary = {"catalog_total": len(entries), "noonnu_pages_visited": len(entries), "publisher_pages_checked": len(entries),
           "verified_downloads": sum(bool(entry["variants"]) for entry in entries.values()),
           "verified_styles": sum(len(entry["variants"]) for entry in entries.values()),
           "repaired_families": sum(entry["repaired"] for entry in entries.values()),
           "archive_families": sum(any(face.get("archive_member") for face in entry["variants"]) for entry in entries.values()),
           "automatic_import_allowed": sum(entry["automatic_import_allowed"] for entry in entries.values()),
           "publisher_http_statuses": dict(original_statuses), "checked_at": datetime.now(timezone.utc).isoformat()}
document = {"schema_version": "noonnu.font_sources.v1", "summary": summary, "fonts": entries}
TARGET.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n")
(ROOT / "download-sources.json").write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n")

rows = []
for entry in sorted(entries.values(), key=lambda item: item["name"]):
    primary = next((face for face in entry["variants"] if face["key"] == "400"), entry["variants"][0])
    origin = entry["original_pages"][0]
    kind = "제작사 ZIP" if primary.get("archive_member") else "Google Fonts" if primary["source_kind"].startswith("google_fonts") else "폰트 파일"
    links = "".join(f'<li><a href="{html.escape(face["url"], quote=True)}" target="_blank" rel="noreferrer">{html.escape(face["label"])}</a>{" · ZIP 안의 " + html.escape(face["archive_member"]) if face.get("archive_member") else ""}</li>' for face in entry["variants"])
    rows.append(f'''<tr data-search="{html.escape((entry['name'] + ' ' + entry['name_en']).casefold(), quote=True)}" data-kind="{kind}"><td>{entry['id']}</td><td><a href="{entry['page_url']}" target="_blank" rel="noreferrer">{html.escape(entry['name'])}</a><small>{html.escape(entry['name_en'])}</small></td><td>{kind}<small>{len(entry['variants'])}개 스타일 · {'자동 등록 가능' if entry['automatic_import_allowed'] else '사용 범위 확인 필요'}</small></td><td><a href="{html.escape(origin.get('final_url') or origin['url'], quote=True)}" target="_blank" rel="noreferrer">제작사 페이지</a><small>원본 응답: {origin.get('status') or '접속 오류'}</small></td><td><a href="{html.escape(primary['url'], quote=True)}" target="_blank" rel="noreferrer">다운로드</a><details><summary>전체 스타일 보기</summary><ul>{links}</ul></details></td></tr>''')
report = '''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>눈누 폰트 다운로드 전수 확인</title><style>
body{margin:0;background:#f5f6f3;color:#20241f;font:14px/1.6 system-ui,sans-serif}main{max-width:1400px;margin:40px auto;padding:0 24px}h1{margin-bottom:6px}p{color:#62695f}.counts{display:flex;gap:12px;flex-wrap:wrap;margin:24px 0}.counts span{padding:12px 18px;background:white;border:1px solid #dce1d8;border-radius:8px}.counts b{font-size:20px;display:block}input,select{padding:12px;border:1px solid #ccd3c6;border-radius:7px;font:inherit}input{width:min(500px,65%)}table{border-collapse:collapse;width:100%;background:white;margin-top:20px}th,td{padding:12px;border-bottom:1px solid #e2e6df;text-align:left;vertical-align:top}th{position:sticky;top:0;background:#eaf0e6}a{color:#315731;overflow-wrap:anywhere}small{display:block;color:#788071}details{font-size:12px;margin-top:6px;max-width:450px}summary{cursor:pointer}li{overflow-wrap:anywhere}tr[hidden]{display:none}@media(max-width:700px){main{padding:0 10px}td,th{padding:8px}th:first-child,td:first-child{display:none}}
</style><main><h1>눈누 폰트 다운로드 전수 확인</h1><p>2026-10-03 기준. 눈누 상세 페이지와 제작사 링크를 방문하고, 폰트/ZIP 응답을 확인했습니다. 제작사 원래 링크에 오류가 있어도 별도의 확인된 폰트 경로를 제공합니다. 사용 범위는 폰트별 눈누·제작사 라이선스를 확인하세요.</p>COUNTS<div><input id="search" placeholder="폰트 이름 검색"><select id="kind"><option value="">모든 경로</option><option>폰트 파일</option><option>Google Fonts</option><option>제작사 ZIP</option></select><span id="result"></span></div><table><thead><tr><th>ID</th><th>폰트</th><th>확인된 경로</th><th>제작사 링크</th><th>다운로드</th></tr></thead><tbody>ROWS</tbody></table></main><script>const rows=[...document.querySelectorAll('tbody tr')];function filter(){const q=document.querySelector('#search').value.toLowerCase().replace(/\s/g,'');const kind=document.querySelector('#kind').value;let n=0;for(const r of rows){r.hidden=!(r.dataset.search.replace(/\s/g,'').includes(q)&&(!kind||r.dataset.kind===kind));if(!r.hidden)n++;}document.querySelector('#result').textContent=' '+n+'종';}document.querySelector('#search').addEventListener('input',filter);document.querySelector('#kind').addEventListener('change',filter);filter();</script></html>'''
counts = f'<div class="counts"><span><b>{summary["catalog_total"]:,}</b>전체 폰트</span><span><b>{summary["verified_downloads"]:,}</b>다운로드 경로 확인</span><span><b>{summary["verified_styles"]:,}</b>스타일</span><span><b>{summary["repaired_families"]}</b>특수 경로 보완</span></div>'
(ROOT / "download-report.html").write_text(report.replace("COUNTS", counts).replace("ROWS", "".join(rows)))
print(json.dumps(summary, ensure_ascii=False, indent=2))
