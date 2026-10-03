import ast
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.billing import (
    CostReadModel, ProviderCall, call_with_cost, execution_cost_scope,
    record_provider_result, run_cost_owner, summary,
)
from app.cost_pricing import calculate
from app.database import (
    CanvasNodeRunRecord, CanvasRunRecord, ExperimentRunRecord,
    ProviderCostObservation, ProviderCostRecord, SessionLocal,
)
from app.providers_lipsync import FalLipSyncService
from app.providers_performance import MediaProviderError


@pytest.fixture(autouse=True)
def pricing_snapshot_date(monkeypatch):
    from app import cost_pricing
    class SnapshotDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 2)
    monkeypatch.setattr(cost_pricing, "date", SnapshotDate)


def experiment(ident, run_id=None, node_run_id=None):
    with SessionLocal() as db:
        row = ExperimentRunRecord(id=ident, canvas_id="billing-test", node_id="node", node_key="image.describe",
            status="RUNNING", prompt="", model_alias="openai.chat.latest", exact_model_id="chat-latest",
            request_hash=uuid4().hex*2, billing_run_id=run_id, billing_node_run_id=node_run_id,
            cost_summary=summary("pending", unresolved=1))
        db.add(row)
        db.commit()


def response(ident="response-1", usage=None):
    return NS(id=ident, model="chat-latest", usage=usage or {"input_tokens": 1000,
        "input_tokens_details": {"cached_tokens": 200}, "output_tokens": 100}, output_text="answer")


def finish(ident, costs, status="SUCCEEDED"):
    value = costs.finish()
    with SessionLocal() as db:
        row = db.get(ExperimentRunRecord, ident)
        row.status, row.cost_summary, row.cost_usd = status, value, float(value["known_cost_usd"])
        db.commit()
    return value


def test_cached_input_and_image_usage_have_reproducible_decimal_prices():
    value, price, reason = calculate("openai", "chat-latest", "responses", response().usage, {}, today=date(2026, 10, 2))
    assert value == Decimal("0.0071") and reason is None
    assert sum(Decimal(line["amount_usd"]) for line in price["line_items"]) == value
    value, price, _ = calculate("openai", "gpt-image-2", "images.edit",
        {"input_tokens_details": {"text_tokens": 10, "image_tokens": 20}, "output_tokens": 100}, {}, today=date(2026, 10, 2))
    assert value == Decimal("0.00321")
    assert price["source"].startswith("https://developers.openai.com/")


@pytest.mark.parametrize("usage,context,day,reason", [
    ({}, {}, date(2026, 10, 2), "input_usage_missing_or_inconsistent"),
    ({"input_tokens": 1, "input_tokens_details": {"cached_tokens": 2}}, {}, date(2026, 10, 2), "input_usage_missing_or_inconsistent"),
    (response().usage, {"service_tier": "priority"}, date(2026, 10, 2), "service_tier_price_unavailable"),
    (response().usage, {"custom_endpoint": True}, date(2026, 10, 2), "custom_endpoint_price_unavailable"),
    (response().usage, {}, date(2026, 11, 1), "pricing_catalog_expired"),
])
def test_missing_or_stale_evidence_is_unknown_not_free(usage, context, day, reason):
    amount, _, actual_reason = calculate("openai", "chat-latest", "responses", usage, context, today=day)
    assert amount is None and actual_reason == reason


def test_google_thinking_and_regional_price_are_counted():
    usage = {"prompt_token_count": 1000, "cached_content_token_count": 100, "candidates_token_count": 50, "thoughts_token_count": 30}
    amount, _, _ = calculate("google", "gemini-3.6-flash", "generate_content", usage,
        {"channel": "vertex", "location": "us-central1"}, today=date(2026, 10, 2))
    assert amount == Decimal("0.00108075")


def test_video_prices_use_completed_outputs_and_validated_duration():
    context = {"channel": "vertex", "generate_audio": True, "duration_seconds": 8, "resolution": "1080p"}
    usage = {"videos": [{"duration_seconds": "8.04", "width": 1080, "height": 1920}] * 2}
    amount, _, _ = calculate("google", "veo-3.1-generate-001", "async_result", usage, context, today=date(2026, 10, 2))
    assert amount == Decimal("6.4")
    usage["videos"][0] = {"duration_seconds": "5", "width": 1080, "height": 1920}
    assert calculate("google", "veo-3.1-generate-001", "async_result", usage, context, today=date(2026, 10, 2))[0] is None


def test_receipt_is_committed_before_provider_and_survives_later_rollback(client):
    experiment("exp-receipt")
    def sdk(**kwargs):
        with SessionLocal() as db:
            pending = db.scalar(select(ProviderCostRecord))
            assert pending.status == "pending" and pending.amount_usd is None
            assert pending.experiment_id == "exp-receipt"
        return response()
    with execution_cost_scope("exp-receipt", expects_provider=True) as costs:
        returned = call_with_cost("openai", "responses", sdk, model="chat-latest", input="SECRET PROMPT")
        assert returned.output_text == "answer"
    with SessionLocal() as db:
        db.get(ExperimentRunRecord, "exp-receipt").status = "SUCCEEDED"
        db.flush()
        db.rollback()  # Simulates output validation/storage failure after a paid response.
    value = finish("exp-receipt", costs, "FAILED")
    assert value["status"] == "calculated" and Decimal(value["amount_usd"]) == Decimal("0.0071")
    receipts = client.get("/costs?owner_id=exp-receipt").json()
    assert len(receipts) == 1 and "SECRET PROMPT" not in str(receipts)
    with SessionLocal() as db:
        assert len(db.scalars(select(ProviderCostObservation)).all()) >= 3


def test_provider_error_and_unknown_usage_are_not_zero(client):
    experiment("exp-uncertain")
    with execution_cost_scope("exp-uncertain", expects_provider=True) as costs:
        def timeout(**kwargs):
            raise TimeoutError("credential must not be saved")
        with pytest.raises(TimeoutError):
            call_with_cost("openai", "responses", timeout, model="chat-latest")
    value = finish("exp-uncertain", costs, "FAILED")
    assert value["amount_usd"] is None and value["unresolved_calls"] == 1
    receipt = client.get("/costs?owner_id=exp-uncertain").json()[0]
    assert receipt["reason"] == "provider_outcome_unknown"
    assert "credential" not in str(receipt)


def test_rejected_call_and_local_execution_have_explicit_zero(client):
    experiment("exp-rejected")
    with execution_cost_scope("exp-rejected", expects_provider=True) as costs:
        def rejected(**kwargs):
            response = httpx.Response(429, request=httpx.Request("POST", "https://example.test"))
            response.raise_for_status()
        with pytest.raises(httpx.HTTPStatusError):
            call_with_cost("openai", "responses", rejected, model="chat-latest")
    assert finish("exp-rejected", costs, "FAILED")["status"] == "no_charge"
    experiment("exp-local")
    with execution_cost_scope("exp-local", expects_provider=False) as costs:
        pass
    assert finish("exp-local", costs)["amount_usd"] == "0"


def test_composite_keeps_every_call_and_partial_totals(client):
    experiment("exp-composite")
    with execution_cost_scope("exp-composite", expects_provider=True) as costs:
        call_with_cost("openai", "responses", lambda **_: response("a"), model="chat-latest")
        call_with_cost("openai", "responses", lambda **_: response("b"), model="chat-latest")
        call_with_cost("openai", "audio.transcriptions", lambda **_: NS(id="c", duration=10), model="unknown-transcriber")
    value = finish("exp-composite", costs)
    assert value["status"] == "partial" and value["amount_usd"] is None
    assert Decimal(value["known_cost_usd"]) == Decimal("0.0142") and value["call_count"] == 3


def test_fal_resume_keeps_original_price_and_does_not_charge_twice(client, monkeypatch):
    posts = []
    download_ok = False
    def handle(request):
        if request.method == "POST":
            posts.append(request.url.path)
            return httpx.Response(200, json={"request_id": "same-task"})
        if request.url.path.endswith("/status"):
            return httpx.Response(200, json={"status": "COMPLETED"})
        if request.url.host == "queue.fal.run":
            return httpx.Response(200, json={"video": {"url": "https://v3.fal.media/result.mp4"}}, headers={"x-fal-billable-units": "0.05"})
        if request.url.host == "api.fal.ai":
            return httpx.Response(200, json={"prices": [{"endpoint_id": "fal-ai/sync-lipsync/v2/pro", "unit_price": 99 if download_ok else 5, "unit": "minutes", "currency": "USD"}]})
        return httpx.Response(200 if download_ok else 500, content=b"video")
    service = FalLipSyncService(api_key="test", client=httpx.Client(transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(service, "_upload", lambda *_: "https://v3.fal.media/input.mp4")
    kwargs = dict(video=b"v", audio=b"a", audio_content_type="audio/wav", timeout_seconds=30, remember=lambda _: None, progress=lambda *_: None)
    experiment("exp-first", "run-first", "node-first")
    with run_cost_owner("run-first", "node-first"), execution_cost_scope("exp-first", expects_provider=True) as first:
        with pytest.raises(MediaProviderError):
            service.synchronize(**kwargs, resume_id=None)
    assert Decimal(finish("exp-first", first, "FAILED")["amount_usd"]) == Decimal("0.25")
    download_ok = True
    experiment("exp-resume", "run-resume", "node-resume")
    with run_cost_owner("run-resume", "node-resume"), execution_cost_scope("exp-resume", expects_provider=True) as resumed:
        service.synchronize(**kwargs, resume_id="same-task")
    assert finish("exp-resume", resumed)["status"] == "no_charge" and len(posts) == 1
    with SessionLocal() as db:
        rows = db.scalars(select(ProviderCostRecord)).all()
        assert len(rows) == 1 and rows[0].run_id == "run-first"
        assert rows[0].amount_usd == Decimal("0.25") and rows[0].pricing["unit_price_usd"] == "5"


def test_cost_context_is_isolated_between_threads(client):
    for ident in ("one", "two"):
        experiment("exp-"+ident, "run-"+ident, "node-"+ident)
    def execute(ident):
        with run_cost_owner("run-"+ident, "node-"+ident), execution_cost_scope("exp-"+ident, expects_provider=True) as costs:
            call_with_cost("openai", "responses", lambda **_: response(ident), model="chat-latest")
        finish("exp-"+ident, costs)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(execute, ("one", "two")))
    with SessionLocal() as db:
        for receipt in db.scalars(select(ProviderCostRecord)):
            assert receipt.experiment_id.removeprefix("exp-") == receipt.run_id.removeprefix("run-") == receipt.provider_request_id


def test_run_aggregation_includes_failed_attempt_and_standalone_calls(client):
    with SessionLocal() as db:
        db.add(CanvasRunRecord(id="run-one", canvas_id="canvas", name="Tracked", status="FAILED"))
        db.add(CanvasNodeRunRecord(id="node-one", run_id="run-one", canvas_node_id="node", node_key="image.describe", ordinal=0, status="FAILED", attempt_count=1))
        db.commit()
    experiment("exp-paid", "run-one", "node-one")
    with run_cost_owner("run-one", "node-one"), execution_cost_scope("exp-paid", expects_provider=True) as costs:
        call_with_cost("openai", "responses", lambda **_: response("paid"), model="chat-latest")
    finish("exp-paid", costs, "FAILED")
    experiment("exp-alone")
    with execution_cost_scope("exp-alone", expects_provider=True) as costs:
        call_with_cost("openai", "responses", lambda **_: response("alone"), model="chat-latest")
    finish("exp-alone", costs)
    rows = client.get("/workflow-runs").json()
    assert {r["id"] for r in rows} == {"run-one", "exp-alone"}
    assert all(Decimal(r["cost_summary"]["amount_usd"]) == Decimal("0.0071") for r in rows)
    assert client.get("/canvas-runs/run-one").json()["cost_summary"]["status"] == "calculated"


def test_uninstrumented_provider_cannot_silently_report_free(client):
    experiment("exp-uninstrumented")
    with execution_cost_scope("exp-uninstrumented", expects_provider=True) as costs:
        pass
    value = finish("exp-uninstrumented", costs)
    assert value["status"] == "unreported" and value["amount_usd"] is None


def test_billable_sdk_calls_use_the_common_meter():
    forbidden = (".responses.create", ".chat.completions.create", ".images.generate", ".images.edit",
                 ".audio.speech.create", ".audio.transcriptions.create", ".models.generate_content",
                 ".models.generate_videos", ".interactions.create", ".recognize")
    bypasses = []
    for path in (Path(__file__).parents[1] / "app").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and ast.unparse(node.func).endswith(forbidden):
                bypasses.append(f"{path.name}:{node.lineno}")
    assert not bypasses, f"Billable SDK calls bypass usage recording: {bypasses}"


def test_xai_reported_ticks_take_precedence_over_model_price(client):
    experiment("exp-ticks")
    with execution_cost_scope("exp-ticks", expects_provider=True) as costs:
        call_with_cost("xai", "responses", lambda **_: NS(id="ticks", usage={"cost_in_usd_ticks": 37756000}), model="grok-4.6")
    value = finish("exp-ticks", costs)
    assert value["status"] == "recorded"
    assert Decimal(value["amount_usd"]) == Decimal("0.0037756")


def test_binary_speech_keeps_real_http_request_id_and_character_usage(client):
    from openai._legacy_response import HttpxBinaryResponseContent
    experiment("exp-speech")
    binary = HttpxBinaryResponseContent(httpx.Response(200, content=b"RIFF", headers={"x-request-id": "speech-http-id"}))
    with execution_cost_scope("exp-speech", expects_provider=True) as costs:
        call_with_cost("openai", "audio.speech", lambda **_: binary, model="tts-1", input="hello")
    assert Decimal(finish("exp-speech", costs)["amount_usd"]) == Decimal("0.000075")
    row = client.get("/costs?owner_id=exp-speech").json()[0]
    assert row["provider_request_id"] == "speech-http-id"
    assert row["usage"]["input_characters"] == 5


def test_google_tts_and_whisper_use_measured_units():
    amount, _, _ = calculate("google", "gemini-2.5-pro-tts", "generate_content",
        {"prompt_token_count": 120, "candidates_token_count": 250}, {"channel": "vertex"}, today=date(2026, 10, 2))
    assert amount == Decimal("0.00512")
    amount, price, _ = calculate("openai", "whisper-1", "audio.transcriptions", {"audio_seconds": "10.1"}, {}, today=date(2026, 10, 2))
    assert amount == Decimal("0.00101") and price["line_items"][0]["quantity"] == "10.1"


def test_api_records_sdk_usage_even_on_failure_and_cache_does_not_call_provider(client, monkeypatch):
    from app.providers_openai import OpenAIGenerationServices, OpenAIProviderConfig
    calls = []
    def sdk(**kwargs):
        calls.append(kwargs)
        value = response(f"real-response-{len(calls)}")
        if "fail" in kwargs["input"]:
            value.output_text = ""
        return value
    service = OpenAIGenerationServices(OpenAIProviderConfig("fake"), NS(responses=NS(create=sdk)))
    monkeypatch.setenv("GENERATION_PROVIDER_MODE", "live")
    monkeypatch.setattr("app.nodes.executors.text_generation.get_openai_generation_services", lambda: service)
    payload = {"canvas_id": "billing-canvas", "node_id": "text", "node_key": "llm.assistant", "node_contract_version": 2,
               "prompt": "hello", "model_alias": "openai.chat.latest", "parameters": {"provider": "openai"}, "inputs": []}
    first = client.post("/experiments", json=payload).json()
    assert first["status"] == "SUCCEEDED", first.get("error")
    assert Decimal(first["cost_summary"]["amount_usd"]) == Decimal("0.0071")
    second = client.post("/experiments", json=payload).json()
    assert second["cache_hit"] and second["cost_summary"]["status"] == "no_charge"
    assert len(calls) == 1
    failed = client.post("/experiments", json={**payload, "prompt": "fail after provider response"}).json()
    assert failed["status"] == "FAILED"
    assert Decimal(failed["cost_summary"]["amount_usd"]) == Decimal("0.0071")
    assert len(client.get("/costs").json()) == 2


def test_later_receipt_resolution_updates_projection_without_rewriting_run_snapshot(client):
    experiment("exp-original")
    with execution_cost_scope("exp-original", expects_provider=True) as original:
        charge = ProviderCall("fal", "generation", "model", request_id="resumable")
    assert finish("exp-original", original, "FAILED")["status"] == "unreported"
    experiment("exp-later")
    with execution_cost_scope("exp-later", expects_provider=True) as resumed:
        record_provider_result("fal", "model", "resumable", {"billable_units": 2}, amount="0.5", pricing={"basis": "provider_reported_charge", "source": "provider receipt"})
    assert finish("exp-later", resumed)["status"] == "no_charge"
    rows = client.get("/experiments?canvas_id=billing-test").json()
    first = next(r for r in rows if r["id"] == "exp-original")
    assert first["cost_summary"]["status"] == "recorded" and first["cost_usd"] == 0.5
    with SessionLocal() as db:
        assert db.get(ExperimentRunRecord, "exp-original").cost_summary["status"] == "unreported"
