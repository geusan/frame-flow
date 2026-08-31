from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .providers import model_id_for_alias


LOCAL_SUBSCRIPTION_AGENT_REVISION = "local-subscription-agent.v1"


@dataclass(frozen=True)
class LocalAuthStatus:
    ready: bool
    state: str
    message: str
    account: str | None = None
    plan: str | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "state": self.state,
            "message": self.message,
            "account": self.account,
            "plan": self.plan,
        }


@dataclass(frozen=True)
class LocalAgentExecution:
    text: str
    provider_request_id: str
    client: str
    metadata: dict[str, Any]


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def _executable(env_name: str, fallback: str) -> str | None:
    configured = os.getenv(env_name, "").strip() or fallback
    if os.path.isabs(configured):
        return configured if os.path.isfile(configured) and os.access(configured, os.X_OK) else None
    return shutil.which(configured)


def _command_env(*, setup_token: str = "", chatgpt_subscription: bool = False) -> dict[str, str]:
    env = dict(os.environ)
    if chatgpt_subscription:
        env.pop("OPENAI_API_KEY", None)
    if setup_token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = setup_token
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
    return env


def _run(
    runner: CommandRunner | None,
    args: list[str],
    *,
    timeout: int,
    env: Mapping[str, str],
    cwd: str | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    command_runner = runner or subprocess.run
    return command_runner(
        args,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
        env=dict(env),
        cwd=cwd,
    )


def check_local_provider_auth(
    provider: str,
    auth_method: str,
    values: Mapping[str, str],
    *,
    runner: CommandRunner | None = None,
) -> LocalAuthStatus | None:
    if provider == "openai" and auth_method == "chatgpt_oauth":
        executable = _executable("CODEX_EXECUTABLE", "codex")
        if not executable:
            return LocalAuthStatus(False, "missing_binary", "Codex CLI was not found on the execution host.")
        try:
            completed = _run(
                runner,
                [executable, "login", "status"],
                timeout=5,
                env=_command_env(chatgpt_subscription=True),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return LocalAuthStatus(False, "error", f"Could not check Codex login: {exc}")
        if completed.returncode != 0:
            return LocalAuthStatus(False, "not_authenticated", _tail(completed.stderr or completed.stdout) or "Run codex login --device-auth.")
        detail = _tail(completed.stdout) or "ChatGPT subscription is connected through Codex CLI."
        return LocalAuthStatus(True, "ready", detail)

    if provider == "claude" and auth_method == "setup_token":
        setup_token = str(values.get("setup_token") or "").strip()
        if not setup_token:
            return LocalAuthStatus(False, "not_authenticated", "Paste a token created by claude setup-token.")
        executable = _executable("CLAUDE_CODE_EXECUTABLE", "claude")
        if not executable:
            return LocalAuthStatus(False, "missing_binary", "Claude Code CLI was not found on the execution host.")
        try:
            completed = _run(
                runner,
                [executable, "auth", "status", "--json"],
                timeout=5,
                env=_command_env(setup_token=setup_token),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return LocalAuthStatus(False, "error", f"Could not check Claude Code login: {exc}")
        if completed.returncode != 0:
            return LocalAuthStatus(False, "not_authenticated", _tail(completed.stderr or completed.stdout) or "Claude Code login is required.")
        try:
            status = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return LocalAuthStatus(False, "error", "Claude Code returned an invalid authentication status.")
        if not status.get("loggedIn"):
            return LocalAuthStatus(False, "not_authenticated", "Claude Code is not logged in.")
        account = str(status.get("email") or "").strip() or None
        plan = str(status.get("subscriptionType") or "").strip() or None
        return LocalAuthStatus(True, "ready", "Claude Code subscription token is ready.", account=account, plan=plan)

    return None


def run_local_subscription_agent(
    *,
    model_alias: str,
    prompt: str,
    instructions: str,
    timeout_seconds: int,
    setup_token: str = "",
    runner: CommandRunner | None = None,
) -> LocalAgentExecution:
    exact_model = model_id_for_alias(model_alias)
    if not exact_model:
        raise ValueError(f"Local subscription model alias is not registered: {model_alias}")
    if model_alias.startswith("chatgpt.local."):
        return _run_codex(
            model=exact_model,
            prompt=prompt,
            instructions=instructions,
            timeout_seconds=timeout_seconds,
            runner=runner,
        )
    if model_alias.startswith("claude.local."):
        return _run_claude(
            model=exact_model,
            prompt=prompt,
            instructions=instructions,
            timeout_seconds=timeout_seconds,
            setup_token=setup_token,
            runner=runner,
        )
    raise ValueError(f"Unsupported local subscription model alias: {model_alias}")


def _run_codex(
    *,
    model: str,
    prompt: str,
    instructions: str,
    timeout_seconds: int,
    runner: CommandRunner | None,
) -> LocalAgentExecution:
    executable = _executable("CODEX_EXECUTABLE", "codex")
    if not executable:
        raise RuntimeError("Codex CLI was not found on the execution host")
    combined_prompt = f"{instructions.strip()}\n\nUser request:\n{prompt.strip()}".strip()
    with tempfile.TemporaryDirectory(prefix="frameflow-codex-") as work_dir:
        output_path = Path(work_dir) / "final.txt"
        args = [
            executable,
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "--json",
            "--model",
            model,
            "--output-last-message",
            str(output_path),
            "-",
        ]
        try:
            completed = _run(
                runner,
                args,
                timeout=timeout_seconds,
                env=_command_env(chatgpt_subscription=True),
                cwd=work_dir,
                input_text=combined_prompt,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Codex CLI timed out after {timeout_seconds} seconds") from exc
        if completed.returncode != 0:
            raise RuntimeError(f"Codex CLI failed: {_tail(completed.stderr or completed.stdout)}")
        text = output_path.read_text().strip() if output_path.exists() else _codex_final_text(completed.stdout)
        if not text:
            raise RuntimeError("Codex CLI returned no final response")
        thread_id = _codex_thread_id(completed.stdout)
        return LocalAgentExecution(
            text=text,
            provider_request_id=thread_id or "codex_local",
            client="codex-cli",
            metadata={"model": model, "thread_id": thread_id},
        )


def _run_claude(
    *,
    model: str,
    prompt: str,
    instructions: str,
    timeout_seconds: int,
    setup_token: str,
    runner: CommandRunner | None,
) -> LocalAgentExecution:
    executable = _executable("CLAUDE_CODE_EXECUTABLE", "claude")
    if not executable:
        raise RuntimeError("Claude Code CLI was not found on the execution host")
    with tempfile.TemporaryDirectory(prefix="frameflow-claude-") as work_dir:
        args = [
            executable,
            "--print",
            "--output-format",
            "json",
            "--input-format",
            "text",
            "--no-session-persistence",
            "--safe-mode",
            "--permission-mode",
            "dontAsk",
            "--tools",
            "",
            "--model",
            model,
            "--append-system-prompt",
            instructions.strip(),
        ]
        try:
            completed = _run(
                runner,
                args,
                timeout=timeout_seconds,
                env=_command_env(setup_token=setup_token),
                cwd=work_dir,
                input_text=prompt.strip(),
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Claude Code CLI timed out after {timeout_seconds} seconds") from exc
        if completed.returncode != 0:
            raise RuntimeError(f"Claude Code CLI failed: {_tail(completed.stderr or completed.stdout)}")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Claude Code CLI returned invalid JSON") from exc
        if payload.get("is_error") or str(payload.get("subtype") or "").startswith("error"):
            raise RuntimeError(f"Claude Code CLI failed: {_tail(str(payload.get('result') or 'unknown error'))}")
        text = str(payload.get("result") or "").strip()
        if not text:
            raise RuntimeError("Claude Code CLI returned no final response")
        session_id = str(payload.get("session_id") or "").strip()
        return LocalAgentExecution(
            text=text,
            provider_request_id=session_id or "claude_local",
            client="claude-code-cli",
            metadata={
                "model": model,
                "session_id": session_id or None,
                "reported_cost_usd": float(payload.get("total_cost_usd") or 0),
            },
        )


def _json_lines(raw: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def _codex_thread_id(raw: str) -> str:
    for event in _json_lines(raw):
        if event.get("type") == "thread.started":
            return str(event.get("thread_id") or event.get("id") or "").strip()
    return ""


def _codex_final_text(raw: str) -> str:
    messages: list[str] = []
    for event in _json_lines(raw):
        item = event.get("item")
        if event.get("type") != "item.completed" or not isinstance(item, dict):
            continue
        if item.get("type") == "agent_message" and item.get("text"):
            messages.append(str(item["text"]))
    return messages[-1].strip() if messages else ""


def _tail(value: str, limit: int = 600) -> str:
    normalized = " ".join(value.strip().split())
    return normalized[-limit:]
