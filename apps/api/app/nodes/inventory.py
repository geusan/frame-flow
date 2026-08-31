from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal, TypedDict


ExecutionKind = Literal["source", "provider", "local", "human_gate", "composite"]


class NodeInventory(TypedDict):
    schema_version: str
    canvas_only: dict[str, str]
    production_nodes: dict[ExecutionKind, list[str]]
    legacy_pipeline: list[str]
    library_duplicates: dict[str, int]


@lru_cache(maxsize=1)
def load_node_inventory() -> NodeInventory:
    path = Path(__file__).with_name("inventory.v1.json")
    payload = json.loads(path.read_text())
    if payload.get("schema_version") != "node.inventory.v1":
        raise ValueError("unsupported Node inventory schema")
    return payload


def production_node_keys() -> set[str]:
    inventory = load_node_inventory()
    return {
        type_key
        for keys in inventory["production_nodes"].values()
        for type_key in keys
    }


def canvas_only_keys() -> set[str]:
    return set(load_node_inventory()["canvas_only"])
