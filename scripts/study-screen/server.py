"""Authenticated local Flutter screen renderer. No user database is accessed."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCK = threading.Lock()


def call(args, **kw):
    return subprocess.run(
        args, check=True, capture_output=True, text=True, timeout=180, **kw
    ).stdout


def revision(project, flutter):
    h = hashlib.sha256()
    paths = [
        HERE / "render_test.dart",
        HERE / "server.py",
        project / "pubspec.lock",
        project / "rust/target/debug/reel_furigana_export",
    ]
    paths += sorted((project / "lib/src").rglob("*.dart"))
    paths += sorted((project / "assets/fonts").glob("*"))
    for p in paths:
        if p.is_file():
            h.update(
                str(
                    p.relative_to(project) if p.is_relative_to(project) else p.name
                ).encode()
            )
            h.update(p.read_bytes())
    return "flutter-study-screen.v1:" + h.hexdigest()


def render(lesson, settings):
    if revision(settings.project, settings.flutter) != settings.revision:
        raise ValueError(
            "Renderer sources changed; restart the service and publish an updated Draft"
        )
    ja = lesson["ja"]
    ko = lesson["ko"]
    target = lesson["target"]
    if (
        not isinstance(ja, str)
        or not 1 <= len(ja) <= 180
        or not isinstance(ko, str)
        or not 1 <= len(ko) <= 240
    ):
        raise ValueError("Invalid sentence length")
    surface = target["surface"]
    if not isinstance(surface, str) or not surface or surface not in ja:
        raise ValueError("Target must occur in the Japanese sentence")
    for field in ["reading", "base", "base_reading", "ko", "pos"]:
        if not isinstance(target.get(field), str) or not 1 <= len(target[field]) <= 100:
            raise ValueError("Invalid target " + field)
    key = hashlib.sha256(
        json.dumps(
            [settings.revision, lesson], ensure_ascii=False, sort_keys=True
        ).encode()
    ).hexdigest()
    folder = settings.cache / key
    folder.mkdir(parents=True, exist_ok=True)
    question = folder / "app-question.png"
    answer = folder / "app-screen.png"
    with LOCK:
        if not (question.exists() and answer.exists()):
            tokens = json.loads(
                call(
                    [
                        str(
                            settings.project / "rust/target/debug/reel_furigana_export"
                        ),
                        str(settings.project / "assets/dict/lindera-ipadic"),
                    ],
                    input=json.dumps([{"id": "single", "ja": ja}], ensure_ascii=False),
                )
            )[0]["tokens"]
            # Keep the reviewed modern compound reading from the original renderer.
            corrected = []
            i = 0
            while i < len(tokens):
                if (
                    tokens[i]["surface"] == "既"
                    and i + 1 < len(tokens)
                    and tokens[i + 1]["surface"] == "読"
                ):
                    corrected.append(
                        {
                            "surface": "既読",
                            "reading": "キドク",
                            "pronunciation": "キドク",
                            "pos": "名詞",
                            "pos_detail1": "一般",
                            "base": "既読",
                        }
                    )
                    i += 2
                else:
                    corrected.append(tokens[i])
                    i += 1
            tokens = corrected
            if "".join(t["surface"] for t in tokens) != ja:
                raise ValueError("Tokenizer changed the sentence")
            start = ja.index(surface)
            t = {
                **target,
                "start": len(ja[:start].encode("utf-16-le")) // 2,
                "end": len(ja[: start + len(surface)].encode("utf-16-le")) // 2,
                "inflected": surface != target["base"],
            }
            row = {
                "id": 1,
                "total": 1,
                "uid": "single",
                "folder": str(folder),
                "ja": ja,
                "ko": ko,
                "direction": "오늘의 문장",
                "reading": "".join(
                    x["reading"] if x["reading"] != "*" else x["surface"]
                    for x in tokens
                ),
                "tokens": tokens,
                "target": t,
                "reading_override": {},
            }
            (folder / "render-input.json").write_text(
                json.dumps({"items": [row]}, ensure_ascii=False)
            )
            test = settings.project / "test" / f"frameflow_study_{key[:16]}_test.dart"
            if test.exists():
                raise RuntimeError("Renderer temporary test already exists")
            shutil.copyfile(HERE / "render_test.dart", test)
            try:
                log = call(
                    [
                        str(settings.flutter / "bin/flutter"),
                        "test",
                        "--no-pub",
                        "--concurrency=1",
                        f"--dart-define=REEL_JOB_ROOT={folder}",
                        f"--dart-define=FLUTTER_ROOT={settings.flutter}",
                        "--dart-define=REEL_PIXEL_RATIO=6",
                        str(test),
                    ],
                    cwd=settings.project,
                )
                (folder / "render.log").write_text(log)
            finally:
                test.unlink(missing_ok=True)
    return {
        "renderer_revision": settings.revision,
        "width": 2340,
        "height": 5064,
        "question": base64.b64encode(question.read_bytes()).decode(),
        "answer": base64.b64encode(answer.read_bytes()).decode(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--flutter", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8769)
    s = parser.parse_args()
    s.revision = revision(s.project, s.flutter)
    token = s.token_file.read_text().strip()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/render":
                self.send_error(404)
                return
            if not hmac.compare_digest(
                self.headers.get("Authorization", ""), "Bearer " + token
            ):
                self.send_error(401)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 32768:
                    raise ValueError("Invalid request size")
                lesson = json.loads(self.rfile.read(size))
                result = render(lesson, s)
                body = json.dumps(result).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except ValueError as exc:
                self.send_error(422, str(exc))
            except Exception as exc:
                print(
                    type(exc).__name__,
                    str(exc),
                    getattr(exc, "stdout", ""),
                    getattr(exc, "stderr", ""),
                    flush=True,
                )
                self.send_error(
                    503, "Native screen rendering failed; inspect renderer log"
                )

    print("study-screen renderer listening on 127.0.0.1:" + str(s.port), flush=True)
    ThreadingHTTPServer(("127.0.0.1", s.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
