"""Durable provider-call receipts, independent of media/output transactions.

Only usage, identifiers and price evidence belong here; never prompts, media,
credentials, full provider responses or signed download URLs.
"""
from __future__ import annotations

from .access import credential_scope_key

from contextlib import contextmanager
from contextvars import ContextVar
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError

from .cost_pricing import calculate, number
from .database import ExperimentRunRecord, ProviderCostObservation, ProviderCostRecord, SessionLocal
from .domain import utc_now

_enabled = ContextVar("cost_recording_enabled", default=False)
_owner = ContextVar("cost_recording_owner", default=(None, None))
_scope = ContextVar("cost_recording_scope", default=None)


@contextmanager
def request_cost_scope():
    token = _enabled.set(True)
    try:
        yield
    finally:
        _enabled.reset(token)


@contextmanager
def run_cost_owner(run_id: str, node_run_id: str):
    token = _owner.set((run_id, node_run_id))
    try:
        yield
    finally:
        _owner.reset(token)


def current_owner():
    return _owner.get()


def summary(status: str, *, known=Decimal(0), unresolved=0, calls=0, reason=None):
    return {"version": 1, "status": status, "currency": "USD", "known_cost_usd": str(known),
            "amount_usd": None if status in {"pending", "unreported", "partial", "legacy"} else str(known),
            "unresolved_calls": unresolved, "call_count": calls, "reason": reason}


def summarize_receipts(receipts):
    rows = list(receipts)
    known = sum((r.amount_usd or Decimal(0) for r in rows), Decimal(0))
    unresolved = sum(r.amount_usd is None for r in rows)
    if unresolved:
        status = "partial" if any(r.amount_usd is not None and r.amount_usd > 0 for r in rows) else "unreported"
    elif any(r.status == "calculated" for r in rows):
        status = "calculated"
    elif any(r.status == "recorded" for r in rows):
        status = "recorded"
    else:
        status = "no_charge"
    return summary(status, known=known, unresolved=unresolved, calls=len(rows))


def legacy_summary(cost=0):
    return summary("legacy", known=number(cost) or Decimal(0), reason="historical_cost_basis_unavailable")


def combine_summaries(items):
    items = list(items)
    known = sum((number(i.get("known_cost_usd")) or Decimal(0) for i in items), Decimal(0))
    unresolved = sum(int(i.get("unresolved_calls") or 0) for i in items)
    incomplete = any(i.get("status") in {"pending", "unreported", "partial", "legacy"} for i in items)
    if incomplete:
        status = "partial" if known else "unreported"
    elif any(i.get("status") == "calculated" for i in items):
        status = "calculated"
    elif any(i.get("status") == "recorded" for i in items):
        status = "recorded"
    else:
        status = "no_charge"
    return summary(status, known=known, unresolved=unresolved, calls=sum(i.get("call_count", 0) for i in items))


@dataclass
class ExecutionCostScope:
    experiment_id: str
    expects_provider: bool
    observed_ids: set[str] = field(default_factory=set)

    def finish(self):
        with SessionLocal() as db:
            owned = db.scalars(select(ProviderCostRecord).where(ProviderCostRecord.experiment_id == self.experiment_id)).all()
            if owned:
                return summarize_receipts(owned)
        if self.observed_ids:
            return summary("no_charge", reason="reused_provider_request")
        if self.expects_provider:
            return summary("unreported", unresolved=1, reason="provider_usage_not_reported")
        return summary("no_charge", reason="local_processing")


@contextmanager
def execution_cost_scope(experiment_id: str, *, expects_provider: bool):
    scope = ExecutionCostScope(experiment_id, expects_provider)
    token = _scope.set(scope)
    try:
        with request_cost_scope():
            yield scope
    finally:
        _scope.reset(token)


def _identifier(value):
    return value[:512] if isinstance(value, str) and value else None


def usage_dict(value: Any):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", exclude_none=True)
    elif hasattr(value, "__dict__") and not isinstance(value, type):
        value = vars(value)
    if isinstance(value, dict):
        return {str(k): usage_dict(v) for k, v in value.items() if v is not None and not str(k).startswith("_")}
    if isinstance(value, (list, tuple)):
        return [usage_dict(v) for v in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, (float, Decimal)):
        return str(value) if number(value) is not None else None
    return None


def cost_payload(row):
    return {"id": row.id, "created_at": row.created_at.isoformat(), "experiment_id": row.experiment_id,
            "run_id": row.run_id, "node_run_id": row.node_run_id, "provider": row.provider,
            "operation": row.operation, "requested_model": row.requested_model, "model": row.model,
            "provider_request_id": row.provider_request_id, "status": row.status, "outcome": row.outcome,
            "amount_usd": str(row.amount_usd) if row.amount_usd is not None else None,
            "currency": "USD", "usage": row.usage, "pricing": row.pricing, "reason": row.reason}


def _observation(db, row):
    db.flush()
    db.add(ProviderCostObservation(id="costobs_" + uuid4().hex, cost_id=row.id, payload=cost_payload(row)))


def receipt_session():
    from .access import current_scope
    scope=current_scope()
    if scope and scope.adapters.cost_sessions:
        return scope.adapters.cost_sessions(scope.context)
    return SessionLocal()


class ProviderCall:
    def __init__(self, provider, operation, model, *, request_id=None, context=None):
        self.provider, self.operation, self.model = provider, operation, model
        self.context = context or {}
        self.id = None
        if not _enabled.get():
            return
        run_id, node_run_id = current_owner()
        scope = _scope.get()
        with receipt_session() as db:
            row = db.scalar(select(ProviderCostRecord).where(
                ProviderCostRecord.provider == provider, ProviderCostRecord.provider_request_id == request_id, ProviderCostRecord.credential_scope == credential_scope_key(),
            )) if request_id else None
            if row is None:
                row = ProviderCostRecord(id="cost_" + uuid4().hex,
                    experiment_id=scope.experiment_id if scope else None, run_id=run_id, node_run_id=node_run_id,
                    provider=provider, operation=operation, requested_model=model, model=model,
                    provider_request_id=request_id, credential_scope=credential_scope_key(), status="pending", outcome="pending", usage={}, pricing={},
                    reason="awaiting_provider_response")
                db.add(row)
                _observation(db, row)
                db.commit()  # Must commit BEFORE making a billable request.
            self.id = row.id
            self.operation = row.operation
        if scope:
            scope.observed_ids.add(self.id)

    def submitted(self, request_id):
        request_id = _identifier(request_id)
        if not self.id or not request_id:
            return
        for retry in range(2):
            try:
                with receipt_session() as db:
                    row = db.get(ProviderCostRecord, self.id)
                    existing = db.scalar(select(ProviderCostRecord).where(
                        ProviderCostRecord.provider == self.provider,
                        ProviderCostRecord.provider_request_id == request_id, ProviderCostRecord.credential_scope == credential_scope_key(),
                        ProviderCostRecord.id != self.id,
                    ))
                    if existing:
                        row.status, row.outcome, row.amount_usd = "no_charge", "linked", Decimal(0)
                        row.reason = "duplicate_receipt_reference"
                        row.usage = {"linked_cost_id": existing.id}
                        self.id = existing.id
                    else:
                        row.provider_request_id = request_id
                        row.reason = "awaiting_provider_usage"
                    _observation(db, row)
                    db.commit()
                if _scope.get():
                    _scope.get().observed_ids.add(self.id)
                return
            except IntegrityError:
                if retry:
                    raise

    def complete(self, *, usage=None, model=None, amount=None, pricing=None, status=None, reason=None):
        if not self.id:
            return
        actual_model = _identifier(model) or self.model
        clean_usage = usage_dict(usage or {})
        if amount is not None:
            amount = number(amount)
            if amount is None or not pricing:
                raise ValueError("A provider cost requires non-negative finite amount and price evidence")
            status = status or "recorded"
        else:
            amount, pricing, missing = calculate(self.provider, actual_model, self.operation, clean_usage, self.context)
            status, reason = ("calculated", None) if amount is not None else ("unreported", reason or missing)
        with receipt_session() as db:
            row = db.scalar(select(ProviderCostRecord).where(ProviderCostRecord.id == self.id).with_for_update())
            # A resumed task with less information cannot erase a prior receipt.
            if row.amount_usd is not None:
                return
            row.model, row.usage = actual_model, clean_usage
            row.pricing = {"observed_at": utc_now().isoformat(), **pricing} if pricing else {}
            row.status, row.outcome, row.amount_usd, row.reason = status, "completed", amount, reason
            _observation(db, row)
            db.commit()

    def failed(self, error):
        if not self.id:
            return
        status_code = getattr(error, "status_code", None) or getattr(getattr(error, "response", None), "status_code", None)
        rejected = status_code in {400, 401, 402, 403, 404, 413, 422, 429}
        with receipt_session() as db:
            row = db.get(ProviderCostRecord, self.id)
            if row.outcome == "completed":
                return
            row.outcome = "rejected" if rejected else "unknown"
            row.status = "no_charge" if rejected else "unreported"
            row.amount_usd = Decimal(0) if rejected else None
            row.reason = f"provider_http_{status_code}" if isinstance(status_code, int) else "provider_outcome_unknown"
            _observation(db, row)
            db.commit()


def call_with_cost(provider: str, operation: str, call: Callable, *, _cost_context=None, **kwargs):
    """SDK adapter preserving the original response and capturing usage before validation."""
    model = str(kwargs.get("model") or (_cost_context or {}).get("model") or "unspecified")
    context = dict(_cost_context or {})
    sdk_client = getattr(getattr(call, "__self__", None), "_client", None)
    base_url = getattr(sdk_client, "base_url", None)
    if provider == "openai" and base_url is not None and type(base_url).__module__ in {"httpx", "httpx._urls"}:
        context.setdefault("custom_endpoint", str(base_url).rstrip("/") != "https://api.openai.com/v1")
    context.setdefault("service_tier", kwargs.get("service_tier", "default"))
    charge = ProviderCall(provider, operation, model, context=context)
    try:
        response = call(**kwargs)
    except BaseException as error:
        charge.failed(error)
        raise
    headers = getattr(response, "headers", None) or getattr(getattr(response, "response", None), "headers", None) or getattr(getattr(response, "sdk_http_response", None), "headers", None)
    http_id = (headers.get("x-request-id") or headers.get("request-id") or headers.get("x-goog-request-id")) if isinstance(headers, dict) or hasattr(headers, "get") else None
    request_id = _identifier(getattr(response, "id", None)) or _identifier(getattr(response, "response_id", None)) or _identifier(getattr(response, "_request_id", None)) or _identifier(http_id)
    charge.submitted(request_id)
    usage = usage_dict(getattr(response, "usage", None) or getattr(response, "usage_metadata", None) or {})
    if not isinstance(usage, dict):
        usage = {}
    if _identifier(http_id):
        usage["http_request_id"] = http_id
    if operation == "audio.speech" and isinstance(kwargs.get("input"), str):
        usage["input_characters"] = len(kwargs["input"])
    if operation == "audio.transcriptions":
        duration = number(usage.get("seconds"))
        if duration is None:
            duration = number(getattr(response, "duration", None))
        if duration is not None:
            usage["audio_seconds"] = str(duration)
    if operation == "speech.recognize":
        duration = getattr(getattr(response, "metadata", None), "total_billed_duration", None)
        if duration is not None and hasattr(duration, "total_seconds"):
            usage["billed_audio_seconds"] = str(duration.total_seconds())
    response_tier = _identifier(getattr(response, "service_tier", None))
    if response_tier:
        charge.context["service_tier"] = response_tier
    response_model = _identifier(getattr(response, "model", None)) or _identifier(getattr(response, "model_version", None))
    ticks = number(usage.get("cost_in_usd_ticks")) if provider == "xai" else None
    if ticks is not None:
        charge.complete(usage=usage, model=response_model, amount=ticks / Decimal("10000000000"),
                        pricing={"source": "https://docs.x.ai/developers/cost-tracking", "basis": "provider_reported_charge", "ticks_per_usd": "10000000000"})
    else:
        charge.complete(usage=usage, model=response_model)
    return response


def submit_sdk_with_cost(provider, operation, call, *, _cost_context=None, **kwargs):
    charge = ProviderCall(provider, operation, str(kwargs.get("model") or "unspecified"), context=_cost_context)
    try:
        response = call(**kwargs)
        charge.submitted(getattr(response, "name", None))
    except BaseException as error:
        charge.failed(error)
        raise
    if charge.id:
        with SessionLocal() as db:
            row = db.get(ProviderCostRecord, charge.id)
            row.usage = {"request_dimensions": dict(_cost_context or {})}
            _observation(db, row)
            db.commit()
    return response


def record_google_video_result(model, request_id, *, video_count):
    if not _enabled.get():
        return
    with SessionLocal() as db:
        row = db.scalar(select(ProviderCostRecord).where(ProviderCostRecord.provider == "google", ProviderCostRecord.provider_request_id == request_id, ProviderCostRecord.credential_scope == credential_scope_key()))
        context = dict((row.usage or {}).get("request_dimensions") or {}) if row else {}
        model = row.requested_model if row and model == "unspecified" else model
    # Provider output count is known at completion; requested count is not billable usage.
    usage = {"generated_video_count": video_count, "request_dimensions": context}
    record_provider_result("google", model, request_id, usage, context=context)


def record_google_video_media(model, request_id, videos):
    if not _enabled.get():
        return
    import json
    import subprocess
    import tempfile
    from pathlib import Path
    with SessionLocal() as db:
        row = db.scalar(select(ProviderCostRecord).where(ProviderCostRecord.provider == "google", ProviderCostRecord.provider_request_id == request_id, ProviderCostRecord.credential_scope == credential_scope_key()))
        context = dict((row.usage or {}).get("request_dimensions") or {}) if row else {}
    dimensions = []
    try:
        with tempfile.TemporaryDirectory(prefix="cost-video-") as folder:
            for index, video in enumerate(videos):
                path = Path(folder) / f"{index}.mp4"
                path.write_bytes(video.data)
                response = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)], capture_output=True, check=True, timeout=30)
                data = json.loads(response.stdout)
                stream = next(s for s in data["streams"] if s.get("codec_type") == "video")
                dimensions.append({"duration_seconds": str(data["format"]["duration"]), "width": stream["width"], "height": stream["height"]})
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, StopIteration):
        return  # The earlier provider receipt remains unreported, never a fabricated zero.
    usage = {"generated_video_count": len(videos), "videos": dimensions, "request_dimensions": context}
    record_provider_result("google", model, request_id, usage, context=context)


def submit_with_cost(provider, operation, model, call, *args, request_id_field="request_id", **kwargs):
    charge = ProviderCall(provider, operation, model)
    try:
        response = call(*args, **kwargs)
        response.raise_for_status()
        payload = response.json()
        request_id = payload.get(request_id_field) or (payload.get("data") or {}).get(request_id_field)
        charge.submitted(request_id)
    except BaseException as error:
        charge.failed(error)
        raise
    return response


def record_provider_result(provider, model, request_id, usage, *, amount=None, pricing=None, status=None, context=None):
    charge = ProviderCall(provider, "async_result", model, request_id=request_id, context=context)
    charge.complete(usage=usage, amount=amount, pricing=pricing, status=status)


def record_fal_result(response, model, request_id, client, headers):
    """Billable units come from fal, never from requested duration/output count."""
    if not _enabled.get():
        return
    units = number(response.headers.get("x-fal-billable-units"))
    usage = {"billable_units": str(units) if units is not None else None}
    price, amount = {}, None
    if units is not None:
        try:
            result = client.get("https://api.fal.ai/v1/models/pricing", headers=headers, params={"endpoint_id": model})
            result.raise_for_status()
            rate = next(p for p in result.json()["prices"] if p["endpoint_id"] == model and p["currency"] == "USD")
            unit_price = number(rate["unit_price"])
            if unit_price is not None:
                amount = units * unit_price
                price = {"source": "https://api.fal.ai/v1/models/pricing", "basis": "provider_usage_and_price",
                         "unit": rate["unit"], "unit_price_usd": str(unit_price), "quantity": str(units), "currency": "USD"}
        except Exception:
            # The submitted receipt remains visible even if the pricing API is unavailable.
            pass
    record_provider_result("fal", model, request_id, usage, amount=amount, pricing=price, status="calculated")


def experiment_cost_summary(record, db=None):
    if not record.cost_summary:
        return legacy_summary(record.cost_usd)
    if db is not None:
        receipts = db.scalars(select(ProviderCostRecord).where(ProviderCostRecord.experiment_id == record.id)).all()
        if receipts:
            return summarize_receipts(receipts)
    return record.cost_summary


class CostReadModel:
    """Batch projection over receipts; historical snapshots are never rewritten."""
    def __init__(self, db, run_id=None):
        query = select(ExperimentRunRecord).where(ExperimentRunRecord.cost_summary["version"].as_integer() == 1)
        costs = select(ProviderCostRecord)
        if run_id:
            query = query.where(ExperimentRunRecord.billing_run_id == run_id)
            costs = costs.where(ProviderCostRecord.run_id == run_id)
        self.experiments = db.scalars(query).all()
        self.receipts = db.scalars(costs).all()
        self.by_experiment = defaultdict(list)
        self.by_node = defaultdict(list)
        for cost in self.receipts:
            if cost.experiment_id:
                self.by_experiment[cost.experiment_id].append(cost)
        for experiment in self.experiments:
            if experiment.billing_node_run_id:
                self.by_node[experiment.billing_node_run_id].append(experiment)

    def experiment(self, record):
        receipts = self.by_experiment[record.id]
        return summarize_receipts(receipts) if receipts else record.cost_summary or legacy_summary(record.cost_usd)

    def node(self, node):
        experiments = self.by_node[node.id]
        if experiments:
            values = [self.experiment(e) for e in experiments]
            if node.attempt_count > len(experiments):
                values.append(legacy_summary())
            return combine_summaries(values)
        if not node.attempt_count:
            return summary("no_charge", reason="source_or_reused_artifact")
        return legacy_summary(node.cost_usd)

    def run(self, run):
        if not any(self.by_node[n.id] for n in run.node_runs):
            if all(not n.attempt_count for n in run.node_runs):
                return summary("no_charge", reason="source_or_reused_artifact") if run.status in {"SUCCEEDED", "FAILED", "CANCELED"} else summary("pending", reason="awaiting_execution")
            return legacy_summary(getattr(run, "actual_cost_usd", sum(n.cost_usd for n in run.node_runs)))
        return combine_summaries(self.node(node) for node in run.node_runs)

    def standalone_rows(self):
        rows = []
        for e in self.experiments:
            if e.billing_run_id:
                continue
            cost = self.experiment(e)
            rows.append({"id": e.id, "created_at": e.created_at, "run_type": "experiment", "name": e.node_key,
                         "status": e.status, "progress": 100 if e.status == "SUCCEEDED" else 0,
                         "cost_usd": float(cost["known_cost_usd"]), "cost_summary": cost,
                         "estimated_cost_usd": None, "nodes_done": int(e.status == "SUCCEEDED"), "nodes_total": 1,
                         "attempt_count": 1, "duration_ms": e.duration_ms})
        for c in self.receipts:
            if c.experiment_id or c.run_id or c.outcome == "linked":
                continue
            cost = summarize_receipts([c])
            completed = c.outcome == "completed"
            rows.append({"id": c.id, "created_at": c.created_at, "run_type": "provider", "name": f"{c.provider} · {c.operation}",
                         "status": "SUCCEEDED" if completed else "RUNNING" if c.outcome == "pending" else "FAILED",
                         "progress": 100 if completed else 0, "cost_usd": float(cost["known_cost_usd"]), "cost_summary": cost,
                         "estimated_cost_usd": None, "nodes_done": int(completed), "nodes_total": 1, "attempt_count": 1, "duration_ms": None})
        return rows


def list_costs(db, owner_id, limit, offset):
    query = select(ProviderCostRecord)
    if owner_id:
        query = query.where(or_(ProviderCostRecord.run_id == owner_id, ProviderCostRecord.experiment_id == owner_id,
                               ProviderCostRecord.node_run_id == owner_id, ProviderCostRecord.id == owner_id))
    return [cost_payload(row) for row in db.scalars(query.order_by(ProviderCostRecord.created_at).limit(limit).offset(offset))]
