#!/usr/bin/env python3
"""Replace one Draft video.media_story node with the SRO image-story pipeline."""

from __future__ import annotations

import argparse
import json
import urllib.request
from typing import Any


SRO_KEYS = {
    "image.motion",
    "layout.media_frame",
    "video.frame_apply",
    "video.concatenate",
    "subtitle.layout",
    "video.compose",
}

FRAME_CONFIG_KEYS = (
    "aspect_ratio",
    "resolution",
    "frame_x",
    "frame_y",
    "frame_width",
    "frame_height",
    "media_fit",
    "background_color",
)


def request(api: str, path: str, *, method: str = "GET", body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(
        api.rstrip("/") + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def defaults(definition: dict[str, Any]) -> dict[str, Any]:
    return {
        key: field["default"]
        for key, field in definition["config_schema"]["properties"].items()
        if "default" in field
    }


def node_from_definition(
    definition: dict[str, Any],
    port_types: dict[str, str],
    *,
    node_id: str,
    label: str,
    position: dict[str, float],
    config: dict[str, Any],
) -> dict[str, Any]:
    inputs = definition["ports"]["inputs"]
    output = definition["ports"]["outputs"][0]
    kind = {"source": "input", "provider": "generate", "human_gate": "review"}.get(
        definition["execution"]["kind"], "logic"
    )
    return {
        "id": node_id,
        "type": "studio",
        "position": position,
        "data": {
            "key": definition["type_key"],
            "label": label,
            "description": definition["display"]["description"],
            "icon": definition["display"]["icon"],
            "kind": kind,
            "status": "BLOCKED" if any(port.get("required") for port in inputs) else "READY",
            "inputTypes": [port_types[port["type"]] for port in inputs],
            "requiredInputTypes": [port_types[port["type"]] for port in inputs if port.get("required")],
            "multiInputTypes": [port_types[port["type"]] for port in inputs if port.get("multiple")],
            "outputType": port_types[output["type"]],
            "provider": definition["execution"]["provider"],
            "model": definition["execution"]["model_alias"],
            "cost": definition["display"].get("cost_label"),
            "contractVersion": definition["contract_version"],
            "definitionDigest": definition["definition_digest"],
            "config": config,
            "executable": True,
            "attemptCount": 0,
            "logs": [],
        },
    }


def motion_config(definition: dict[str, Any], index: int, amount: float) -> dict[str, Any]:
    config = defaults(definition)
    scale = min(2, 1 + amount)
    variants = (
        {"start_scale": 1, "end_scale": scale, "start_x": 0.5, "start_y": 0.5, "end_x": 0.5, "end_y": 0.5},
        {"start_scale": scale, "end_scale": scale, "start_x": 0, "start_y": 0.5, "end_x": 1, "end_y": 0.5},
        {"start_scale": scale, "end_scale": 1, "start_x": 0.5, "start_y": 0.5, "end_x": 0.5, "end_y": 0.5},
        {"start_scale": scale, "end_scale": scale, "start_x": 1, "start_y": 0.5, "end_x": 0, "end_y": 0.5},
        {"start_scale": scale, "end_scale": scale, "start_x": 0.5, "start_y": 1, "end_x": 0.5, "end_y": 0},
        {"start_scale": scale, "end_scale": scale, "start_x": 0.5, "start_y": 0, "end_x": 0.5, "end_y": 1},
    )
    return {**config, **variants[index % len(variants)]}


def shared_frame_config(definition: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    return {
        **defaults(definition),
        **{key: source[key] for key in FRAME_CONFIG_KEYS if source.get(key) is not None},
    }


def backup_canvas(api: str, canvas: dict[str, Any], name: str) -> dict[str, Any]:
    backups = [item for item in request(api, "/canvases") if item.get("name") == name]
    return backups[0] if backups else request(api, "/canvases", method="POST", body={
        "name": name,
        "nodes": canvas["nodes"],
        "edges": canvas["edges"],
        "draft_contract": canvas["draft_contract"],
    })


def upgrade_existing_sro_canvas(
    *,
    api: str,
    canvas: dict[str, Any],
    definitions: dict[str, dict[str, Any]],
    port_types: dict[str, str],
    backup_name: str,
) -> None:
    shared_nodes = [node for node in canvas["nodes"] if (node.get("data") or {}).get("key") == "layout.media_frame"]
    frame_v2_nodes = [
        node for node in canvas["nodes"]
        if (node.get("data") or {}).get("key") == "video.frame_apply"
        and int((node.get("data") or {}).get("contractVersion") or 1) == 2
    ]
    if len(shared_nodes) == 1 and frame_v2_nodes:
        print(json.dumps({"status": "already_migrated", "canvas_id": canvas["id"]}, ensure_ascii=False))
        return

    legacy_frames = [
        node for node in canvas["nodes"]
        if (node.get("data") or {}).get("key") == "video.frame_apply"
        and int((node.get("data") or {}).get("contractVersion") or 1) == 1
    ]
    if not legacy_frames:
        raise RuntimeError("Canvas has neither video.media_story nor video.frame_apply@1 Nodes to migrate")
    frame_configs = [dict((node.get("data") or {}).get("config") or {}) for node in legacy_frames]
    if any({key: config.get(key) for key in FRAME_CONFIG_KEYS} != {key: frame_configs[0].get(key) for key in FRAME_CONFIG_KEYS} for config in frame_configs[1:]):
        raise RuntimeError("Existing Frame Apply Nodes use different layouts and cannot be merged without choosing one")

    backup = backup_canvas(api, canvas, backup_name)
    old_ids = {node["id"] for node in legacy_frames}
    removed_edges = [edge for edge in canvas["edges"] if edge.get("source") in old_ids or edge.get("target") in old_ids]
    nodes = [node for node in canvas["nodes"] if node["id"] not in old_ids]
    edges = [edge for edge in canvas["edges"] if edge not in removed_edges]
    by_id = {node["id"]: node for node in canvas["nodes"]}
    shared_id = legacy_frames[0]["id"]
    nodes.append(node_from_definition(
        definitions["layout.media_frame"],
        port_types,
        node_id=shared_id,
        label="공유 미디어 프레임",
        position={"x": 180, "y": -520},
        config=shared_frame_config(definitions["layout.media_frame"], frame_configs[0]),
    ))

    replacement_ids: dict[str, str] = {}
    for old_frame in legacy_frames:
        old_id = old_frame["id"]
        motion_edges = [edge for edge in removed_edges if edge.get("target") == old_id and (by_id.get(edge.get("source"), {}).get("data") or {}).get("outputType") == "MediaMotion"]
        outgoing = [edge for edge in removed_edges if edge.get("source") == old_id]
        if len(motion_edges) != 1 or not outgoing:
            raise RuntimeError(f"{old_id} must have one MediaMotion input and at least one output")
        apply_id = f"{old_id}-apply"
        replacement_ids[old_id] = apply_id
        nodes.append(node_from_definition(
            definitions["video.frame_apply"],
            port_types,
            node_id=apply_id,
            label=str((old_frame.get("data") or {}).get("label") or "프레임 적용"),
            position=dict(old_frame.get("position") or {}),
            config=defaults(definitions["video.frame_apply"]),
        ))
        motion_edge = motion_edges[0]
        edges.extend([
            {**motion_edge, "target": apply_id, "targetHandle": "input-MediaMotion-0"},
            {"id": f"edge-{shared_id}-{apply_id}", "source": shared_id, "target": apply_id, "sourceHandle": "output", "targetHandle": "input-MediaFrame-1", "type": "adaptive"},
            *[{**edge, "source": apply_id} for edge in outgoing],
        ])

    draft_contract = dict(canvas["draft_contract"])
    draft_contract["outputs"] = [
        {**output, "node_id": replacement_ids.get(str(output.get("node_id")), output.get("node_id"))}
        for output in draft_contract.get("outputs", [])
    ]
    saved = request(api, f"/canvases/{canvas['id']}", method="PUT", body={
        "name": canvas["name"],
        "nodes": nodes,
        "edges": edges,
        "expected_revision": canvas["revision"],
        "draft_contract": draft_contract,
    })
    print(json.dumps({
        "status": "shared_frame_migrated",
        "canvas_id": saved["id"],
        "backup_canvas_id": backup["id"],
        "shared_frame_node_id": shared_id,
        "shared_consumers": len(legacy_frames),
        "revision_before": canvas["revision"],
        "revision_after": saved["revision"],
        "node_count_before": canvas["node_count"],
        "node_count_after": saved["node_count"],
        "edge_count_before": canvas["edge_count"],
        "edge_count_after": saved["edge_count"],
    }, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("canvas_id")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--backup-suffix", default=" · SRO 전 백업")
    parser.add_argument("--backup-name")
    args = parser.parse_args()

    canvas = request(args.api, f"/canvases/{args.canvas_id}")
    definitions = {item["type_key"]: item for item in request(args.api, "/node-definitions")}
    missing = sorted(SRO_KEYS - definitions.keys())
    if missing:
        raise RuntimeError(f"SRO Node Definitions are unavailable: {', '.join(missing)}")
    port_types = {
        item["id"]: item["legacy_type"]
        for item in request(args.api, "/node-port-types")["types"]
    }
    story_nodes = [node for node in canvas["nodes"] if (node.get("data") or {}).get("key") == "video.media_story"]
    if not story_nodes:
        upgrade_existing_sro_canvas(
            api=args.api,
            canvas=canvas,
            definitions=definitions,
            port_types=port_types,
            backup_name=args.backup_name or canvas["name"] + " · 공유 프레임 전 백업",
        )
        return
    if len(story_nodes) != 1:
        raise RuntimeError("Migration requires exactly one video.media_story Node")
    story = story_nodes[0]
    story_id = story["id"]
    story_config = dict((story.get("data") or {}).get("config") or {})
    incoming = [edge for edge in canvas["edges"] if edge.get("target") == story_id]
    by_id = {node["id"]: node for node in canvas["nodes"]}
    image_sources = [by_id[edge["source"]] for edge in incoming if (by_id[edge["source"]].get("data") or {}).get("outputType") == "Image"]
    subtitle_sources = [by_id[edge["source"]] for edge in incoming if (by_id[edge["source"]].get("data") or {}).get("outputType") == "Subtitle"]
    audio_sources = [by_id[edge["source"]] for edge in incoming if (by_id[edge["source"]].get("data") or {}).get("outputType") == "Audio"]
    if not image_sources or len(subtitle_sources) != 1 or len(audio_sources) != 1:
        raise RuntimeError("Migration requires Image inputs plus exactly one Subtitle and Audio input")

    backup_name = args.backup_name or canvas["name"] + args.backup_suffix
    backup = backup_canvas(args.api, canvas, backup_name)

    nodes = [node for node in canvas["nodes"] if node["id"] != story_id]
    edges = [edge for edge in canvas["edges"] if edge.get("target") != story_id and edge.get("source") != story_id]
    motion_definition = definitions["image.motion"]
    frame_definition = definitions["video.frame_apply"]
    shared_frame_id = f"{story_id}-shared-frame"
    nodes.append(node_from_definition(
        definitions["layout.media_frame"], port_types, node_id=shared_frame_id,
        label="공유 미디어 프레임", position={"x": 180, "y": -520},
        config=shared_frame_config(definitions["layout.media_frame"], story_config),
    ))
    row_gap = 390
    for index, image in enumerate(image_sources):
        y = index * row_gap
        image["position"] = {"x": -300, "y": y}
        upstream = [edge for edge in edges if edge.get("target") == image["id"]]
        for edge in upstream:
            source = by_id.get(edge["source"])
            if source and (source.get("data") or {}).get("outputType") == "Prompt":
                source["position"] = {"x": -760, "y": y}
        motion_id = f"{image['id']}-motion"
        frame_id = f"{image['id']}-frame"
        nodes.append(node_from_definition(
            motion_definition, port_types, node_id=motion_id,
            label=f"장면 {index + 1} · 움직임", position={"x": 180, "y": y},
            config=motion_config(motion_definition, index, float(story_config.get("motion_amount", 0.12))),
        ))
        nodes.append(node_from_definition(
            frame_definition, port_types, node_id=frame_id,
            label=f"장면 {index + 1} · 프레임 적용", position={"x": 650, "y": y}, config=defaults(frame_definition),
        ))
        edges.extend([
            {"id": f"edge-{motion_id}", "source": image["id"], "target": motion_id, "sourceHandle": "output", "targetHandle": "input-Image-0", "type": "adaptive"},
            {"id": f"edge-{frame_id}", "source": motion_id, "target": frame_id, "sourceHandle": "output", "targetHandle": "input-MediaMotion-0", "type": "adaptive"},
            {"id": f"edge-{shared_frame_id}-{frame_id}", "source": shared_frame_id, "target": frame_id, "sourceHandle": "output", "targetHandle": "input-MediaFrame-1", "type": "adaptive"},
        ])

    midpoint = ((len(image_sources) - 1) * row_gap) / 2
    connect_id = f"{story_id}-connect"
    captions_id = f"{story_id}-captions"
    compose_id = f"{story_id}-compose"
    nodes.extend([
        node_from_definition(definitions["video.concatenate"], port_types, node_id=connect_id, label="생성 영상 연결", position={"x": 1120, "y": midpoint}, config=defaults(definitions["video.concatenate"])),
        node_from_definition(definitions["subtitle.layout"], port_types, node_id=captions_id, label="자막 표시 영역", position={"x": 650, "y": -520}, config={
            **defaults(definitions["subtitle.layout"]),
            "aspect_ratio": story_config.get("aspect_ratio", "9:16"),
            "frame_x": story_config.get("caption_frame_x", 0.06),
            "frame_y": story_config.get("caption_frame_y", 0.68),
            "frame_width": story_config.get("caption_frame_width", 0.88),
            "frame_height": story_config.get("caption_frame_height", 0.28),
            "align": story_config.get("caption_align", "center"),
            "font_family": story_config.get("caption_font_family", "Noto Sans CJK KR"),
            "font_size": story_config.get("caption_font_size", 58),
            "color": story_config.get("caption_color", "#F7F3E8"),
            "outline_color": story_config.get("caption_outline_color", "#000000"),
        }),
        node_from_definition(definitions["video.compose"], port_types, node_id=compose_id, label="영상·자막·음성 합성", position={"x": 1600, "y": midpoint}, config=defaults(definitions["video.compose"])),
    ])
    for image in image_sources:
        frame_id = f"{image['id']}-frame"
        edges.append({"id": f"edge-{frame_id}-connect", "source": frame_id, "target": connect_id, "sourceHandle": "output", "targetHandle": "input-Video-0", "type": "adaptive"})
    edges.extend([
        {"id": f"edge-{captions_id}", "source": subtitle_sources[0]["id"], "target": captions_id, "sourceHandle": "output", "targetHandle": "input-Subtitle-0", "type": "adaptive"},
        {"id": f"edge-{connect_id}-compose", "source": connect_id, "target": compose_id, "sourceHandle": "output", "targetHandle": "input-Video-0", "type": "adaptive"},
        {"id": f"edge-{captions_id}-compose", "source": captions_id, "target": compose_id, "sourceHandle": "output", "targetHandle": "input-CaptionLayout-1", "type": "adaptive"},
        {"id": f"edge-audio-{compose_id}", "source": audio_sources[0]["id"], "target": compose_id, "sourceHandle": "output", "targetHandle": "input-Audio-2", "type": "adaptive"},
    ])
    draft_contract = dict(canvas["draft_contract"])
    draft_contract["outputs"] = [
        {**output, "node_id": compose_id if output.get("node_id") == story_id else output.get("node_id")}
        for output in draft_contract.get("outputs", [])
    ]
    saved = request(args.api, f"/canvases/{args.canvas_id}", method="PUT", body={
        "name": canvas["name"],
        "nodes": nodes,
        "edges": edges,
        "expected_revision": canvas["revision"],
        "draft_contract": draft_contract,
    })
    print(json.dumps({
        "status": "migrated",
        "canvas_id": saved["id"],
        "backup_canvas_id": backup["id"],
        "revision_before": canvas["revision"],
        "revision_after": saved["revision"],
        "node_count_before": canvas["node_count"],
        "node_count_after": saved["node_count"],
        "edge_count_before": canvas["edge_count"],
        "edge_count_after": saved["edge_count"],
        "warnings": ["Scene duration defaults to 10 seconds; adjust each Image Motion Node to match narration timing."],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
