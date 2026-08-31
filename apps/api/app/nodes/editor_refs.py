from __future__ import annotations

import json
import re
from pathlib import Path


EDITOR_REF_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


class NodeEditorRefRegistry:
    def __init__(self, path: Path) -> None:
        document = json.loads(path.read_text())
        if document.get("schema_version") != "node.editor-refs.v1":
            raise ValueError("invalid Node editor ref catalog schema_version")
        refs = document.get("refs")
        if not isinstance(refs, list) or not refs:
            raise ValueError("Node editor ref catalog must contain refs")
        if any(not isinstance(ref, str) or not EDITOR_REF_PATTERN.fullmatch(ref) for ref in refs):
            raise ValueError("Node editor ref catalog contains an invalid ref")
        if len(refs) != len(set(refs)):
            raise ValueError("Node editor ref catalog contains duplicate refs")
        self.refs = frozenset(refs)

    def contains(self, ref: str) -> bool:
        return ref in self.refs


node_editor_ref_registry = NodeEditorRefRegistry(Path(__file__).with_name("editor_refs.v1.json"))
