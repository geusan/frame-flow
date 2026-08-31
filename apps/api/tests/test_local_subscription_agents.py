from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain import ExperimentRunRequest
from app.local_subscription_agents import (
    LocalAgentExecution,
    LocalAuthStatus,
    check_local_provider_auth,
    run_local_subscription_agent,
)
from app.nodes import node_registry
from app.nodes.contracts import NodeExecutionContext
from app.nodes.executors import local_subscription_agent as executor_module
from app.nodes.executors.local_subscription_agent import LocalSubscriptionAgentExecutor
from app import provider_settings as provider_settings_module


def completed(args, *, stdout: str = "", stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr=stderr)


def test_codex_auth_status_uses_chatgpt_session_without_api_key(monkeypatch):
    monkeypatch.setattr("app.local_subscription_agents._executable", lambda *_: "/usr/bin/codex")
    observed = {}

    def runner(args, **kwargs):
        observed.update({"args": args, "env": kwargs["env"]})
        return completed(args, stdout="Logged in using ChatGPT\n")

    status = check_local_provider_auth("openai", "chatgpt_oauth", {}, runner=runner)

    assert status and status.ready is True
    assert observed["args"] == ["/usr/bin/codex", "login", "status"]
    assert "OPENAI_API_KEY" not in observed["env"]


def test_claude_auth_status_injects_setup_token(monkeypatch):
    monkeypatch.setattr("app.local_subscription_agents._executable", lambda *_: "/usr/bin/claude")
    observed = {}

    def runner(args, **kwargs):
        observed.update({"args": args, "env": kwargs["env"]})
        return completed(args, stdout=json.dumps({"loggedIn": True, "email": "user@example.com", "subscriptionType": "pro"}))

    status = check_local_provider_auth(
        "claude",
        "setup_token",
        {"setup_token": "setup-token-test"},
        runner=runner,
    )

    assert status and status.ready is True
    assert status.plan == "pro"
    assert observed["args"] == ["/usr/bin/claude", "auth", "status", "--json"]
    assert observed["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "setup-token-test"
    assert "ANTHROPIC_API_KEY" not in observed["env"]


def test_codex_execution_is_ephemeral_read_only_and_returns_last_message(monkeypatch):
    monkeypatch.setattr("app.local_subscription_agents._executable", lambda *_: "/usr/bin/codex")
    observed = {}

    def runner(args, **kwargs):
        observed.update({"args": args, "input": kwargs["input"], "cwd": kwargs["cwd"]})
        output_path = Path(args[args.index("--output-last-message") + 1])
        output_path.write_text("Codex final response")
        return completed(args, stdout='{"type":"thread.started","thread_id":"thread_123"}\n')

    result = run_local_subscription_agent(
        model_alias="chatgpt.local.quality",
        prompt="Make a concise plan",
        instructions="Return only the plan.",
        timeout_seconds=60,
        runner=runner,
    )

    assert result.text == "Codex final response"
    assert result.provider_request_id == "thread_123"
    assert "--ephemeral" in observed["args"]
    assert observed["args"][observed["args"].index("--sandbox") + 1] == "read-only"
    assert observed["args"][observed["args"].index("--model") + 1] == "gpt-5.6-terra"
    assert "Return only the plan." in observed["input"]


def test_claude_execution_disables_tools_and_parses_result(monkeypatch):
    monkeypatch.setattr("app.local_subscription_agents._executable", lambda *_: "/usr/bin/claude")
    observed = {}

    def runner(args, **kwargs):
        observed.update({"args": args, "env": kwargs["env"], "input": kwargs["input"]})
        return completed(args, stdout=json.dumps({
            "type": "result",
            "subtype": "success",
            "result": "Claude final response",
            "session_id": "session_123",
            "total_cost_usd": 0.42,
        }))

    result = run_local_subscription_agent(
        model_alias="claude.local.sonnet",
        prompt="Rewrite this prompt",
        instructions="Return only the rewrite.",
        timeout_seconds=60,
        setup_token="setup-token-test",
        runner=runner,
    )

    assert result.text == "Claude final response"
    assert result.provider_request_id == "session_123"
    assert observed["args"][observed["args"].index("--tools") + 1] == ""
    assert observed["args"][observed["args"].index("--model") + 1] == "claude-sonnet-4-6"
    assert observed["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "setup-token-test"


def test_local_subscription_agent_executor_returns_text_artifact_contract(monkeypatch):
    definition = node_registry.get("agent.execute", 1)
    assert definition is not None
    provider_record = SimpleNamespace(configuration={"_auth_method": "chatgpt_oauth"}, secrets={})
    artifact = SimpleNamespace(id="artifact_text_1")
    monkeypatch.setattr(executor_module, "get_provider_record", lambda *_: provider_record)
    monkeypatch.setattr(executor_module, "provider_auth_method_key", lambda *_: "chatgpt_oauth")
    monkeypatch.setattr(executor_module, "provider_is_configured", lambda *_: True)
    monkeypatch.setattr(executor_module, "run_local_subscription_agent", lambda **_: LocalAgentExecution(
        text="Local agent result",
        provider_request_id="thread_1",
        client="codex-cli",
        metadata={"model": "gpt-5.6-terra"},
    ))
    monkeypatch.setattr(executor_module, "create_artifact", lambda *args, **kwargs: artifact)
    monkeypatch.setattr(executor_module, "artifact_content_url", lambda artifact_id: f"/artifacts/{artifact_id}/content")

    class FakeDb:
        def flush(self):
            return None

    payload = ExperimentRunRequest(
        canvas_id="canvas_1",
        node_id="agent_1",
        node_key="agent.execute",
        prompt="Connected prompt",
        model_alias="chatgpt.local.quality",
        parameters={},
        inputs=[],
    )
    context = NodeExecutionContext(
        db=FakeDb(),
        payload=payload,
        definition=definition,
        request_hash="digest",
        experiment_id="experiment_1",
    )

    result = LocalSubscriptionAgentExecutor().execute(
        context,
        {
            "model_alias": "chatgpt.local.quality",
            "instructions": "Return only the result.",
            "timeout_seconds": 300,
        },
        [],
    )

    assert result.output_artifact_ids == ["artifact_text_1"]
    assert result.provider_request_id == "thread_1"
    assert result.output["text"] == "Local agent result"
    assert result.metadata["schema_id"] == "agent.response.v1"


def test_claude_error_result_is_not_treated_as_success(monkeypatch):
    monkeypatch.setattr("app.local_subscription_agents._executable", lambda *_: "/usr/bin/claude")

    def runner(args, **kwargs):
        return completed(args, stdout=json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "usage limit"}))

    with pytest.raises(RuntimeError, match="usage limit"):
        run_local_subscription_agent(
            model_alias="claude.local.haiku",
            prompt="hello",
            instructions="answer",
            timeout_seconds=60,
            setup_token="token",
            runner=runner,
        )


def test_agent_experiment_snapshots_the_manifest_selected_local_model(client, monkeypatch):
    monkeypatch.setattr(
        provider_settings_module,
        "check_local_provider_auth",
        lambda *args, **kwargs: LocalAuthStatus(True, "ready", "Codex ready"),
    )
    monkeypatch.setattr(executor_module, "run_local_subscription_agent", lambda **_: LocalAgentExecution(
        text="Subscription-backed result",
        provider_request_id="thread_snapshot",
        client="codex-cli",
        metadata={"model": "gpt-5.6-terra"},
    ))
    connected = client.put("/settings/providers/openai", json={
        "enabled": True,
        "auth_method": "chatgpt_oauth",
        "values": {},
    })
    assert connected.status_code == 200

    response = client.post("/experiments", json={
        "canvas_id": "canvas_local_agent",
        "node_id": "agent_1",
        "node_key": "agent.execute",
        "prompt": "Return a concise answer",
        "model_alias": "chatgpt.local.fast",
        "parameters": {
            "model_alias": "chatgpt.local.quality",
            "instructions": "Return only the answer.",
            "timeout_seconds": 300,
        },
        "inputs": [],
    })

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "SUCCEEDED"
    assert payload["model_alias"] == "chatgpt.local.quality"
    assert payload["exact_model_id"] == "gpt-5.6-terra"
    assert payload["output"]["text"] == "Subscription-backed result"
    model = next(item for item in client.get("/models").json() if item["logical_alias"] == "chatgpt.local.quality")
    assert model["provider"] == "ChatGPT Subscription"
    assert model["configured"] is True
