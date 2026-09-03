from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .contracts import NodeDefinition, NodeExecutionContext, NodeExecutionResult, NodeExecutor
from .editor_refs import node_editor_ref_registry
from .executors import (
    AudioExtractExecutor,
    CharacterGenerationCapabilityExecutor,
    FalLoraImageCapabilityExecutor,
    FFmpegMediaCapabilityExecutor,
    FalLoraTrainingExecutor,
    ImageGenerationCapabilityExecutor,
    ImageStoryVideoExecutor,
    LegacyCompatibilityExecutor,
    LocalSubscriptionAgentExecutor,
    MediaStoryVideoExecutor,
    MotionControlVideoExecutor,
    MotionSegmentExecutor,
    SpeechGenerationCapabilityExecutor,
    TextGenerationCapabilityExecutor,
    VideoRetimeExecutor,
    VideoGenerationCapabilityExecutor,
    VideoClipSelectExecutor,
    VideoSplitExecutor,
    XAITextCapabilityExecutor,
)


class NodeRegistry:
    def __init__(self, *, definitions_dir: Path, executors: dict[str, NodeExecutor]) -> None:
        self._definitions: dict[tuple[str, int], NodeDefinition] = {}
        self._executors = executors
        for path in sorted(definitions_dir.glob("*.json")):
            document = json.loads(path.read_text())
            payloads = document if isinstance(document, list) else [document]
            for payload in payloads:
                definition = NodeDefinition.model_validate(payload)
                key = (definition.type_key, definition.contract_version)
                if key in self._definitions:
                    raise ValueError(f"duplicate Node Definition: {definition.type_key}@{definition.contract_version}")
                if definition.execution.executor not in executors:
                    raise ValueError(f"unregistered Node executor: {definition.execution.executor}")
                if definition.editor.kind == "custom" and not node_editor_ref_registry.contains(str(definition.editor.ref)):
                    raise ValueError(f"unregistered Node editor ref: {definition.editor.ref}")
                self._definitions[key] = definition

    def list(self, *, lifecycle: str | None = None) -> list[NodeDefinition]:
        definitions = sorted(self._definitions.values(), key=lambda item: (item.type_key, item.contract_version))
        return [item for item in definitions if lifecycle is None or item.lifecycle == lifecycle]

    def get(self, type_key: str, contract_version: int = 1) -> NodeDefinition | None:
        return self._definitions.get((type_key, contract_version))

    @staticmethod
    def uses_legacy_runtime(definition: NodeDefinition | None) -> bool:
        return bool(definition and definition.execution.executor == "legacy-compatibility")

    def execute(
        self,
        context: NodeExecutionContext,
        parameters: dict[str, Any],
        typed_inputs: list[dict[str, Any]],
    ) -> NodeExecutionResult:
        config = self.resolve_config(context.definition, parameters)
        return self._executors[context.definition.execution.executor].execute(context, config, typed_inputs)

    def can_execute(self, context: NodeExecutionContext) -> bool:
        executor = self._executors[context.definition.execution.executor]
        supports = getattr(executor, "supports", None)
        return bool(supports(context)) if callable(supports) else True

    def runtime_revision(self, definition: NodeDefinition, resolved_config: dict[str, Any]) -> str:
        executor = self._executors[definition.execution.executor]
        revision = getattr(executor, "runtime_revision", None)
        return str(revision(definition, resolved_config)) if callable(revision) else definition.execution.revision

    @staticmethod
    def resolve_config(definition: NodeDefinition, parameters: dict[str, Any]) -> dict[str, Any]:
        schema = definition.config_schema
        properties = dict(schema.get("properties") or {})
        unknown = sorted(key for key, value in parameters.items() if key not in properties and value is not None)
        if unknown and not NodeRegistry.uses_legacy_runtime(definition):
            raise ValueError(f"unknown config fields for {definition.type_key}: {', '.join(unknown)}")
        resolved: dict[str, Any] = {}
        for key, field in properties.items():
            value = parameters.get(key)
            if value is None:
                value = field.get("default")
            if value is None and key in schema.get("required", []):
                raise ValueError(f"missing required config field: {key}")
            if value is None:
                continue
            field_type = field.get("type")
            if field_type == "string" and not isinstance(value, str):
                raise ValueError(f"{key} must be a string")
            if field_type == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
                raise ValueError(f"{key} must be an integer")
            if field_type == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
                raise ValueError(f"{key} must be a number")
            if field_type == "boolean" and not isinstance(value, bool):
                raise ValueError(f"{key} must be a boolean")
            if "enum" in field and value not in field["enum"]:
                raise ValueError(f"{key} must be one of {field['enum']}")
            if isinstance(value, str):
                if len(value) < int(field.get("minLength", 0)):
                    raise ValueError(f"{key} is too short")
                if "maxLength" in field and len(value) > int(field["maxLength"]):
                    raise ValueError(f"{key} is too long")
                if field.get("pattern") and not re.fullmatch(str(field["pattern"]), value):
                    raise ValueError(f"{key} has an invalid format")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if "minimum" in field and value < field["minimum"]:
                    raise ValueError(f"{key} must be at least {field['minimum']}")
                if "exclusiveMinimum" in field and value <= field["exclusiveMinimum"]:
                    raise ValueError(f"{key} must be greater than {field['exclusiveMinimum']}")
                if "maximum" in field and value > field["maximum"]:
                    raise ValueError(f"{key} must be at most {field['maximum']}")
            resolved[key] = value
        return resolved


node_registry = NodeRegistry(
    definitions_dir=Path(__file__).with_name("definitions"),
    executors={
        "audio-extract": AudioExtractExecutor(),
        "fal-lora-training": FalLoraTrainingExecutor(),
        "legacy-compatibility": LegacyCompatibilityExecutor((XAITextCapabilityExecutor(), TextGenerationCapabilityExecutor(), ImageGenerationCapabilityExecutor(), CharacterGenerationCapabilityExecutor(), FalLoraImageCapabilityExecutor(), VideoGenerationCapabilityExecutor(), SpeechGenerationCapabilityExecutor(), FFmpegMediaCapabilityExecutor())),
        "image-story-video": ImageStoryVideoExecutor(),
        "local-subscription-agent": LocalSubscriptionAgentExecutor(),
        "media-story-video": MediaStoryVideoExecutor(),
        "motion-control-video": MotionControlVideoExecutor(),
        "motion-segment": MotionSegmentExecutor(),
        "video-clip-select": VideoClipSelectExecutor(),
        "video-retime": VideoRetimeExecutor(),
        "video-split": VideoSplitExecutor(),
    },
)
