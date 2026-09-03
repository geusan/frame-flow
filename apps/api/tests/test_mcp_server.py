from __future__ import annotations

import json
import time

import anyio
import pytest
from mcp import Client

from app.mcp_server import server
from app.nodes import node_registry


@pytest.fixture
def anyio_backend():
    return "asyncio"


def image_workflow_spec() -> dict:
    return {
        "name": "MCP image workflow",
        "description": "Generate a hero image from a runtime topic.",
        "tags": ["mcp", "image", "mcp"],
        "nodes": [
            {
                "ref": "topic",
                "type_key": "prompt.input",
                "contract_version": 1,
                "config": {"text": ""},
            },
            {
                "ref": "hero",
                "type_key": "image.generate",
                "contract_version": 1,
                "config": {
                    "resolution": "2K",
                    "aspect_ratio": "9:16",
                    "output_count": 1,
                    "quality": "medium",
                },
            },
        ],
        "edges": [
            {
                "source": {"node": "topic", "port": "prompt"},
                "target": {"node": "hero", "port": "prompt"},
            }
        ],
        "inputs": [
            {"key": "topic", "label": "Topic", "type": "prompt", "required": True}
        ],
        "bindings": [
            {"node": "topic", "field": "text", "kind": "input", "input_key": "topic"}
        ],
        "outputs": [
            {
                "key": "hero_image",
                "label": "Hero image",
                "node": "hero",
                "port": "image",
                "primary": True,
            }
        ],
    }


@pytest.mark.anyio
async def test_mcp_exposes_every_registered_node_contract(client):
    del client
    async with Client(server) as mcp_client:
        tools = await mcp_client.list_tools()
        tool_names = {tool.name for tool in tools.tools}
        assert {
            "frameflow.node_contracts.list",
            "frameflow.node_contracts.get",
            "frameflow.workflow_drafts.plan",
            "frameflow.workflow_drafts.create",
            "frameflow.workflow_drafts.get",
            "frameflow.workflow_drafts.update",
            "frameflow.workflow_drafts.validate",
            "frameflow.workflow_drafts.publish",
            "frameflow.workflows.run",
            "frameflow.runs.get",
            "frameflow.runs.cancel",
            "frameflow.runs.respond",
        } <= tool_names

        listed = await mcp_client.call_tool(
            "frameflow.node_contracts.list",
            {"lifecycle": "ALL", "limit": 500},
        )
        assert listed.is_error is False
        registered = {
            (definition.type_key, definition.contract_version)
            for definition in node_registry.list()
        }
        exposed = {
            (item["type_key"], item["contract_version"])
            for item in listed.structured_content["contracts"]
        }
        assert exposed == registered
        assert all(item["definition_digest"].startswith("sha256:") for item in listed.structured_content["contracts"])

        contract = await mcp_client.call_tool(
            "frameflow.node_contracts.get",
            {"type_key": "image.generate", "contract_version": 1},
        )
        assert contract.is_error is False
        assert contract.structured_content["ports"]["inputs"][0]["type"] == "prompt.text.v1"
        assert contract.structured_content["config_schema"]["additionalProperties"] is False

        resource = await mcp_client.read_resource(
            "frameflow://node-contracts/image.generate/1"
        )
        payload = json.loads(resource.contents[0].text)
        assert payload["type_key"] == "image.generate"
        assert payload["contract_version"] == 1


@pytest.mark.anyio
async def test_mcp_plan_rejects_unknown_ports_without_writing(client):
    async with Client(server) as mcp_client:
        spec = image_workflow_spec()
        spec["edges"][0]["target"]["port"] = "invented"
        result = await mcp_client.call_tool(
            "frameflow.workflow_drafts.plan",
            {"spec": spec},
        )
        assert result.is_error is True
        assert "unknown input port: hero.invented" in result.content[0].text
    assert client.get("/workflows").json() == []


@pytest.mark.anyio
async def test_mcp_can_round_trip_and_update_a_canonical_draft(client):
    async with Client(server) as mcp_client:
        created = await mcp_client.call_tool(
            "frameflow.workflow_drafts.create",
            {"spec": image_workflow_spec()},
        )
        workflow_id = created.structured_content["workflow_id"]
        current = await mcp_client.call_tool(
            "frameflow.workflow_drafts.get",
            {"workflow_id": workflow_id},
        )
        assert current.is_error is False
        assert current.structured_content["revision"] == 1
        spec = current.structured_content["spec"]
        hero = next(node for node in spec["nodes"] if node["ref"] == "hero")
        hero["config"]["aspect_ratio"] = "1:1"

        updated = await mcp_client.call_tool(
            "frameflow.workflow_drafts.update",
            {
                "workflow_id": workflow_id,
                "expected_revision": 1,
                "spec": spec,
            },
        )
        assert updated.is_error is False
        assert updated.structured_content["changed"] is True
        assert updated.structured_content["revision"] == 2
        assert next(
            node
            for node in updated.structured_content["spec"]["nodes"]
            if node["ref"] == "hero"
        )["config"]["aspect_ratio"] == "1:1"
        assert client.get(f"/workflows/{workflow_id}").json()["current_version_id"] is None

        conflict = await mcp_client.call_tool(
            "frameflow.workflow_drafts.update",
            {
                "workflow_id": workflow_id,
                "expected_revision": 1,
                "spec": spec,
            },
        )
        assert conflict.is_error is True
        assert "revision conflict" in conflict.content[0].text


@pytest.mark.anyio
async def test_mcp_can_plan_create_publish_run_and_read_resources(client):
    async with Client(server) as mcp_client:
        spec = image_workflow_spec()
        planned = await mcp_client.call_tool(
            "frameflow.workflow_drafts.plan",
            {"spec": spec},
        )
        assert planned.is_error is False
        assert planned.structured_content["valid"] is True
        assert [node["type_key"] for node in planned.structured_content["resolved_nodes"]] == [
            "prompt.input",
            "image.generate",
        ]
        assert planned.structured_content["output_schema"]["outputs"][0]["port_key"] == "image"

        created = await mcp_client.call_tool(
            "frameflow.workflow_drafts.create",
            {"spec": spec},
        )
        assert created.is_error is False
        workflow_id = created.structured_content["workflow_id"]
        canvas_id = created.structured_content["draft_canvas_id"]
        assert created.structured_content["revision"] == 1

        canvas = client.get(f"/canvases/{canvas_id}")
        assert canvas.status_code == 200
        assert canvas.json()["storage_schema_version"] == "canvas.document.v1"
        assert canvas.json()["workflow_definition_id"] == workflow_id

        validated = await mcp_client.call_tool(
            "frameflow.workflow_drafts.validate",
            {"workflow_id": workflow_id},
        )
        assert validated.is_error is False
        assert validated.structured_content["content_hash"] == planned.structured_content["content_hash"]

        published = await mcp_client.call_tool(
            "frameflow.workflow_drafts.publish",
            {
                "workflow_id": workflow_id,
                "expected_revision": 1,
                "release_notes": "Created through MCP",
            },
        )
        assert published.is_error is False
        assert published.structured_content["version_number"] == 1
        assert published.structured_content["content_hash"] == planned.structured_content["content_hash"]

        version_resource = await mcp_client.read_resource(
            f"frameflow://workflows/{workflow_id}/versions/1"
        )
        version_payload = json.loads(version_resource.contents[0].text)
        assert version_payload["input_schema"]["inputs"][0]["key"] == "topic"
        assert version_payload["graph"]["nodes"][1]["definition_digest"].startswith("sha256:")

        started = await mcp_client.call_tool(
            "frameflow.workflows.run",
            {
                "workflow_id": workflow_id,
                "version": 1,
                "inputs": {"topic": "A cat cooking breakfast"},
            },
        )
        assert started.is_error is False
        run_id = started.structured_content["run_id"]
        assert started.structured_content["workflow_version"] == 1
        assert started.structured_content["inputs"] == {"topic": "A cat cooking breakfast"}

        deadline = time.monotonic() + 5
        state = started
        while time.monotonic() < deadline:
            state = await mcp_client.call_tool(
                "frameflow.runs.get",
                {"run_id": run_id},
            )
            if state.structured_content["status"] in {"SUCCEEDED", "FAILED", "CANCELED"}:
                break
            await anyio.sleep(0.03)
        assert state.structured_content["status"] == "SUCCEEDED"
        output = state.structured_content["outputs"]["hero_image"]
        assert output["primary"] is True
        assert output["port_key"] == "image"
        assert output["artifacts"][0]["type"] == "Image"

        run_resource = await mcp_client.read_resource(f"frameflow://runs/{run_id}")
        run_payload = json.loads(run_resource.contents[0].text)
        assert run_payload["status"] == "SUCCEEDED"
        artifact_uri = run_payload["outputs"]["hero_image"]["artifacts"][0]["resource_uri"]
        artifact_resource = await mcp_client.read_resource(artifact_uri)
        artifact_payload = json.loads(artifact_resource.contents[0].text)
        assert artifact_payload["type"] == "Image"
        assert artifact_payload["content_url"].endswith(f"/artifacts/{artifact_payload['artifact_id']}/content")

        artifacts = await mcp_client.call_tool(
            "frameflow.artifacts.list",
            {"types": ["Image"], "query": artifact_payload["artifact_id"], "limit": 10},
        )
        assert artifacts.is_error is False
        assert [item["artifact_id"] for item in artifacts.structured_content["artifacts"]] == [
            artifact_payload["artifact_id"]
        ]

        models = await mcp_client.call_tool(
            "frameflow.models.list",
            {"type_key": "image.generate", "contract_version": 1},
        )
        assert models.is_error is False
        assert {item["logical_alias"] for item in models.structured_content["models"]} >= {
            "google.image.fast",
            "openai.image.default",
        }
