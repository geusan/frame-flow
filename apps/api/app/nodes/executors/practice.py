"""Independent native-screen, audio arrangement, motion adapter and cue contracts."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import tempfile
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path

from ..contracts import NodeArtifactWrite, NodeExecutionResult
from ..port_types import port_type_registry
from .media_tools import (
    media_duration_seconds,
    probe_media,
    run_media_command,
    write_media_artifact,
)
from .text_support import input_lineage


class PracticeValidationError(ValueError):
    retryable = False


class PracticeRuntimeError(RuntimeError):
    retryable = True


def input_artifact(context, inputs, key):
    ports = context.definition.ports.inputs
    idx = next(i for i, p in enumerate(ports) if p.key == key)
    p = ports[idx]
    kind = port_type_registry.get(p.type).legacy_type
    matches = [
        x
        for x in inputs
        if x.get("target_port") in {key, "input-" + key, f"input-{kind}-{idx}"}
    ]
    if not matches:
        candidates = [x for x in inputs if x.get("type") == kind]
        same = [x for x in ports if x.type == p.type]
        if len(same) == 1:
            matches = candidates
    ids = [a for x in matches for a in x.get("artifact_ids", [])]
    if len(ids) != 1:
        raise PracticeValidationError(f"Exactly one typed {key} input is required")
    value = context.require_artifact_store().read(ids[0])
    if value.type != kind:
        raise PracticeValidationError(f"{key} must be {kind}")
    return value


def write_artifact(
    context, config, inputs, kind, schema, content, mime, name, role, extra=None
):
    ids, roles = input_lineage(context, inputs)
    return context.require_artifact_store().create(
        NodeArtifactWrite(
            artifact_type=kind,
            schema_id=schema,
            input_artifact_ids=ids,
            input_artifact_roles=roles,
            metadata={
                "immutable": True,
                "experiment_id": context.experiment_id,
                "request_hash": context.request_hash,
                "normalized_config": config,
                "executor_revision": context.definition.execution.revision,
                "output_role": role,
                **(extra or {}),
            },
            content=content,
            content_type=mime,
            filename=name,
        )
    )


def result(context, refs, kind, title, content=None, extra=None):
    store = context.require_artifact_store()
    store.flush()
    output = {"kind": kind, "title": title, "url": store.content_url(refs[0].id)}
    if content is not None:
        output["text"] = json.dumps(content, ensure_ascii=False)
    if kind == "image":
        output["mimeType"] = "image/png"
    if kind == "audio":
        output["mimeType"] = "audio/wav"
    return NodeExecutionResult(
        output=output,
        output_artifact_ids=[a.id for a in refs],
        provider_request_id="local_" + context.request_hash[:20],
        cost_usd=0,
        metadata={
            "retryable": False,
            "executor_revision": context.definition.execution.revision,
            **(extra or {}),
        },
    )


def parse_lesson(raw, japanese, korean):
    raw = raw.strip()
    if raw.startswith("```"):
        match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
        if not match:
            raise PracticeValidationError("Malformed lesson JSON code fence")
        raw = match.group(1)
    try:
        lesson = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise PracticeValidationError("Lesson must be a JSON object") from exc
    if (
        not isinstance(lesson, dict)
        or lesson.get("ja") != japanese
        or lesson.get("ko") != korean
    ):
        raise PracticeValidationError(
            "Generated lesson must preserve both input sentences exactly"
        )
    t = lesson.get("target")
    if not isinstance(t, dict):
        raise PracticeValidationError("Lesson requires a target word")
    for field in ["surface", "reading", "base", "base_reading", "ko", "pos"]:
        if not isinstance(t.get(field), str) or not 1 <= len(t[field]) <= 100:
            raise PracticeValidationError("Invalid target " + field)
    if t["surface"] not in japanese:
        raise PracticeValidationError("Target word is absent from Japanese sentence")
    return {
        "ja": japanese,
        "ko": korean,
        "target": {
            k: t[k] for k in ["surface", "reading", "base", "base_reading", "ko", "pos"]
        },
    }


class StudyScreenExecutor:
    def runtime_revision(self, definition, config):
        return (
            definition.execution.revision
            + ":"
            + hashlib.sha256(config["renderer_revision"].encode()).hexdigest()[:24]
        )

    def execute(self, context, config, inputs):
        lesson = parse_lesson(
            input_artifact(context, inputs, "lesson").data.decode(),
            config["japanese"],
            config["korean"],
        )
        token_file = Path(
            os.environ.get("STUDY_SCREEN_TOKEN_FILE", "/imports/.study-screen-token")
        )
        if not token_file.is_file():
            raise PracticeRuntimeError(
                "Native study screen renderer is not configured; start scripts/study-screen/server.py"
            )
        url = os.environ.get(
            "STUDY_SCREEN_SERVICE_URL", "http://host.docker.internal:8769/render"
        )
        request = urllib.request.Request(
            url,
            data=json.dumps(lesson, ensure_ascii=False).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + token_file.read_text().strip(),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=240) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 422:
                raise PracticeValidationError(
                    "Native screen renderer rejected the lesson"
                ) from exc
            raise PracticeRuntimeError("Native screen renderer is unavailable") from exc
        except (OSError, ValueError) as exc:
            raise PracticeRuntimeError("Native screen renderer is unavailable") from exc
        if payload.get("renderer_revision") != config["renderer_revision"]:
            raise PracticeValidationError(
                "Renderer revision changed; explicitly update the Draft and publish a new version"
            )
        try:
            png = base64.b64decode(payload[config["state"]], validate=True)
        except (KeyError, ValueError) as exc:
            raise PracticeRuntimeError("Invalid screen renderer response") from exc
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise PracticeRuntimeError("Renderer did not return PNG")
        ref = write_artifact(
            context,
            config,
            inputs,
            "Image",
            "image.study_screen.v1",
            png,
            "image/png",
            config["state"] + ".png",
            "study_screen",
            {
                "renderer_revision": payload["renderer_revision"],
                "width": payload["width"],
                "height": payload["height"],
            },
        )
        return result(
            context,
            [ref],
            "image",
            "빈칸 화면" if config["state"] == "question" else "정답 화면",
        )


def practice_timing(voice_seconds, config):
    if not math.isfinite(voice_seconds) or not 0 < voice_seconds <= 15:
        raise PracticeValidationError("Pronunciation must be between 0 and 15 seconds")
    bar = config["beats_per_bar"] * 60 / config["bpm"]
    fps = config["fps"]
    phase = (
        math.ceil(
            (voice_seconds + config["lead_seconds"] + config["voice_margin_seconds"])
            / bar
        )
        * bar
    )
    phase = math.ceil(phase * fps) / fps
    # Keep the minimum silence after 30→24fps clip quantization and AAC framing.
    # Two source frames cover one 24fps frame plus one 48kHz AAC frame.
    total = (math.ceil((3 * phase + config["ending_silence_seconds"]) * fps) + 2) / fps
    if total - phase > 30:
        raise PracticeValidationError(
            "Sentence is too long for the 30-second answer scene; shorten it"
        )
    return {
        "schema_version": "practice.timing.v1",
        "fps": fps,
        "voice_seconds": voice_seconds,
        "phase_seconds": phase,
        "question_seconds": phase,
        "answer_seconds": total - phase,
        "replay_start": 2 * phase + config["lead_seconds"],
        "content_end": 3 * phase,
        "ending_silence_seconds": config["ending_silence_seconds"],
        "duration_seconds": total,
    }


def read_timing(context, inputs):
    a = input_artifact(context, inputs, "timing")
    try:
        t = json.loads(a.data)
    except ValueError as exc:
        raise PracticeValidationError("Invalid practice timing JSON") from exc
    if (
        a.schema_id != "practice.timing.v1"
        or t.get("schema_version") != "practice.timing.v1"
    ):
        raise PracticeValidationError("Expected practice.timing.v1")
    for key in [
        "phase_seconds",
        "question_seconds",
        "answer_seconds",
        "content_end",
        "duration_seconds",
        "ending_silence_seconds",
    ]:
        if (
            not isinstance(t.get(key), (int, float))
            or not math.isfinite(t[key])
            or t[key] <= 0
        ):
            raise PracticeValidationError("Invalid timing " + key)
    if (
        t.get("fps") != 30
        or t["ending_silence_seconds"] < 1.5
        or abs(t["question_seconds"] + t["answer_seconds"] - t["duration_seconds"])
        > 0.001
        or t["duration_seconds"] - t["content_end"] < 1.5 - 1e-6
    ):
        raise PracticeValidationError("Inconsistent practice timing")
    return t


@lru_cache(maxsize=1)
def ffmpeg_revision():
    return run_media_command(["ffmpeg", "-version"]).stdout.splitlines()[0]


class PracticeTrackExecutor:
    def runtime_revision(self, definition, config):
        return (
            "practice-track.v1.1"
            + ":"
            + hashlib.sha256(ffmpeg_revision().encode()).hexdigest()[:24]
        )

    def execute(self, context, config, inputs):
        voice = input_artifact(context, inputs, "voice")
        beat = input_artifact(context, inputs, "beat")
        with tempfile.TemporaryDirectory(prefix="practice-track-") as temp:
            root = Path(temp)
            v = write_media_artifact(root, voice, 0)
            b = write_media_artifact(root, beat, 1)
            t = practice_timing(media_duration_seconds(probe_media(v)), config)
            out = root / "practice.wav"
            lead = round(config["lead_seconds"] * 1000)
            replay = round(t["replay_start"] * 1000)
            filters = f"[0:a]asplit=2[v0][v1];[v0]adelay={lead}:all=1[a0];[v1]adelay={replay}:all=1[a1];[a0][a1]amix=inputs=2:normalize=0,apad,atrim=duration={t['content_end']}[speech];[1:a]atrim=duration={t['content_end']},asetpts=PTS-STARTPTS,volume={config['beat_gain']}[beat];[speech][beat]amix=inputs=2:normalize=0,alimiter=limit=0.95:level=false:latency=true,apad,atrim=duration={t['duration_seconds']}[a]"
            run_media_command(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(v),
                    "-stream_loop",
                    "-1",
                    "-i",
                    str(b),
                    "-filter_complex",
                    filters,
                    "-map",
                    "[a]",
                    "-ar",
                    "48000",
                    "-ac",
                    "2",
                    "-c:a",
                    "pcm_s16le",
                    str(out),
                ]
            )
            audio = write_artifact(
                context,
                config,
                inputs,
                "Audio",
                "audio.practice_track.v1",
                out.read_bytes(),
                "audio/wav",
                "practice.wav",
                "practice_audio",
                {"timing": t, "ffmpeg_revision": ffmpeg_revision()},
            )
        timing = write_artifact(
            context,
            config,
            inputs,
            "PracticeTiming",
            "practice.timing.v1",
            json.dumps(t).encode(),
            "application/json",
            "timing.json",
            "practice_timing",
        )
        return result(
            context,
            [audio, timing],
            "audio",
            "듣기 → 따라 말하기 → 다시 듣기 → 1.5초 쉼",
            extra={"timing": t, "ffmpeg_revision": ffmpeg_revision()},
        )


class PracticeMotionExecutor:
    def execute(self, context, config, inputs):
        image = input_artifact(context, inputs, "image")
        t = read_timing(context, inputs)
        motion = {
            "schema_version": "image.motion.v4",
            "source": {
                "artifact_id": image.id,
                "sha256": image.sha256,
                "content_type": image.content_type,
            },
            "duration_seconds": t[config["phase"] + "_seconds"],
            "fps": t["fps"],
            "start": {"scale": 1.0, "x": 0.5, "y": 0.5},
            "end": {"scale": 1.0, "x": 0.5, "y": 0.5},
            "coordinate_space": "source_image_view_center",
            "path": {
                "type": "linear",
                "control_1": {"x": 0.4, "y": 0.35},
                "control_2": {"x": 0.6, "y": 0.65},
                "end_progress": 0.7,
            },
            "zoom": {"end_progress": 0.7, "easing": "ease_in_out"},
        }
        ref = write_artifact(
            context,
            config,
            inputs,
            "MediaMotion",
            "image.motion.v4",
            json.dumps(motion).encode(),
            "application/json",
            "motion.json",
            "motion_plan",
        )
        return result(context, [ref], "json", "학습 화면 길이", motion)


class PracticeGuideExecutor:
    def execute(self, context, config, inputs):
        t = read_timing(context, inputs)
        phase = t["phase_seconds"]
        stamp = lambda sec: f"{int(sec // 60):02d}:{sec % 60:06.3f}"
        content = [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": f"[{stamp(start)}-{stamp(end)}] " + label}
                ],
            }
            for start, end, label in [
                (phase, 2 * phase, config["repeat_label"]),
                (2 * phase, t["content_end"], config["listen_label"]),
            ]
        ]
        document = context.require_media_runtime().canonical_caption_document(
            {
                "schema_version": "caption.document.v1",
                "default_style": {
                    "font_size": config["font_size"],
                    "color": config["color"],
                },
                "content": {"type": "doc", "content": content},
            }
        )
        ref = write_artifact(
            context,
            config,
            inputs,
            "CaptionDocument",
            "caption.document.v1",
            json.dumps(document, ensure_ascii=False).encode(),
            "application/json",
            "guide.json",
            "caption_document",
        )
        return result(context, [ref], "json", "학습 안내 · 자동 타이밍", document)
