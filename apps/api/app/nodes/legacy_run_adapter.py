from __future__ import annotations

from typing import Any


LEGACY_RUN_CONFIG_FIELDS = {
    "resolution": "resolution",
    "aspect_ratio": "aspectRatio",
    "transition": "transition",
    "target_duration_seconds": "targetDurationSeconds",
    "source_language": "sourceLanguage",
    "separate_music": "separateMusic",
    "scene_threshold": "sceneThreshold",
    "motion_sample_fps": "motionSampleFps",
    "motion_max_width": "motionMaxWidth",
    "motion_min_confidence": "motionMinConfidence",
    "motion_face_blendshapes": "motionFaceBlendshapes",
    "target_language": "targetLanguage",
    "voice_name": "voiceName",
    "caption_x": "captionX",
    "caption_y": "captionY",
    "caption_align": "captionAlign",
    "caption_font_size": "captionFontSize",
    "skill_id": "skillId",
    "character_name": "characterName",
    "shot_count": "shotCount",
    "duration_seconds": "durationSeconds",
    "lora_url": "loraUrl",
    "lora_scale": "loraScale",
    "trigger_word": "triggerWord",
}


def legacy_canvas_run_parameters(data: dict[str, Any]) -> dict[str, Any]:
    """Translate pre-canonical CanvasRun payloads at the compatibility boundary."""

    parameters = dict(data.get("config") or data.get("parameters") or {})
    for config_key, legacy_key in LEGACY_RUN_CONFIG_FIELDS.items():
        if config_key not in parameters and data.get(legacy_key) is not None:
            parameters[config_key] = data[legacy_key]
    if "provider" not in parameters and data.get("provider") is not None:
        parameters["provider"] = data["provider"]
    return parameters
