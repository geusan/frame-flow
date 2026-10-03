from datetime import date
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app import cost_pricing
from app.billing import execution_cost_scope, run_cost_owner
from app.cost_pricing import calculate, MINIMAX_SOURCE
from app.database import ProviderCostRecord, SessionLocal
from app.providers_minimax import MiniMaxVideoService, reference_request
from app.providers_performance import MediaProviderError


@pytest.fixture(autouse=True)
def pricing_snapshot_date(monkeypatch):
    class SnapshotDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 2)
    monkeypatch.setattr(cost_pricing, "date", SnapshotDate)


def usage(*, resolution="2K", output=4, video=3, images=2, audio=3):
    return {"task_type": "generation", "resolution": resolution, "duration": output,
            "provider_usage": {"output_seconds": output, "input_seconds": video,
                               "total_seconds": output + video, "input_image_count": images,
                               "input_audio_seconds": audio, "total_tokens": 99999999}}


@pytest.mark.parametrize("resolution,output,video,images,audio,expected", [
    ("2K", 4, 3, 2, 3, "0.91"),
    ("768P", 4, 3, 2, 15, "0.56"),
    ("2K", 11, 10, 2, 10, "2.73"),
    ("2K", 9, 9, 2, 9, "2.34"),
    ("2K", 4, 0, 5, 15, "0.52"),
    ("2K", 4, 0, 6, 0, "0.56"),
    ("768P", 4, 0, 9, 0, "0.48"),
])
def test_h3_charges_both_video_directions_and_only_excess_images(resolution, output, video, images, audio, expected):
    measured = usage(resolution=resolution, output=output, video=video, images=images, audio=audio)
    # A returned file may include tail padding. Never substitute it for billed seconds.
    measured["duration"] = 4.459
    amount, pricing, reason = calculate("minimax", "MiniMax-H3", "async_result", measured, {})
    assert amount == Decimal(expected) and reason is None
    assert pricing["source"] == MINIMAX_SOURCE
    assert sum(Decimal(line["amount_usd"]) for line in pricing["line_items"]) == amount
    audio_line = next(line for line in pricing["line_items"] if line["unit"] == "reference_audio_seconds")
    assert Decimal(audio_line["amount_usd"]) == 0
    assert not any("tokens" in line["unit"] for line in pricing["line_items"])


@pytest.mark.parametrize("field", ["input_seconds", "output_seconds", "input_image_count"])
def test_h3_missing_billed_usage_is_not_replaced_by_request_defaults(field):
    measured = usage()
    measured["provider_usage"].pop(field)
    amount, _, reason = calculate("minimax", "MiniMax-H3", "video_generation", measured, {"duration_seconds": 4})
    assert amount is None and reason == "minimax_usage_missing_or_inconsistent"


@pytest.mark.parametrize("field,value", [("input_seconds", -1), ("input_image_count", 5.5), ("output_seconds", "NaN"), ("input_seconds", True), ("total_seconds", 999)])
def test_h3_rejects_invalid_or_conflicting_quantities(field, value):
    measured = usage(); measured["provider_usage"][field] = value
    assert calculate("minimax", "MiniMax-H3", "video_generation", measured, {})[0] is None


@pytest.mark.parametrize("model,resolution,task_type", [
    ("MiniMax-H3-Max", "2K", "generation"),
    ("MiniMax-H3", "1080P", "generation"),
    ("MiniMax-H3", "2K", "regeneration"),
    ("MiniMax-H3", "2K", "context_ir"),
])
def test_other_tariffs_are_not_silently_charged_as_h3_generation(model, resolution, task_type):
    measured = usage(resolution=resolution); measured["task_type"] = task_type
    assert calculate("minimax", model, "video_generation", measured, {})[0] is None


def test_old_receipt_can_use_its_recorded_generation_operation():
    measured = usage(); measured.pop("task_type")
    assert calculate("minimax", "MiniMax-H3", "video_generation", measured, {})[0] == Decimal("0.91")
    assert calculate("minimax", "MiniMax-H3", "async_result", measured, {})[0] is None
    assert calculate("minimax", "MiniMax-H3", "video_generation", measured, {"api_origin": "https://proxy.example"})[0] is None


def test_provider_receipt_is_calculated_before_download_and_resume_is_not_double_billed(client, monkeypatch):
    posts = []
    downloaded = False
    measured = usage()
    # Older tasks need not expose task_type; the saved submit operation is sufficient.
    measured.pop("task_type")
    def handle(request):
        if request.method == "POST":
            posts.append(request.url.path)
            return httpx.Response(200, json={"task_id": "minimax-cost-task"})
        if request.url.host == "api.minimax.io":
            return httpx.Response(200, json={"task": {"id": "minimax-cost-task", "model": "MiniMax-H3", "status": "succeeded",
                "resolution": measured["resolution"], "duration": measured["duration"], "usage": measured["provider_usage"],
                "content": {"url": "https://cdn.hailuoai.com/result.mp4"}}})
        assert "authorization" not in request.headers
        return httpx.Response(200 if downloaded else 500, content=b"video")
    monkeypatch.setattr("app.providers_minimax.validate_public_url", lambda url: url)
    service = MiniMaxVideoService(api_key="fake-secret", client=httpx.Client(transport=httpx.MockTransport(handle)), poll_interval=0)
    payload = reference_request(prompt="cost test", resolution="2K", duration=4, ratio="9:16", media=[("image", "image/png", b"image")])
    kwargs = {"timeout_seconds": 30, "remember": lambda _: None, "progress": lambda *_: None}
    with run_cost_owner("original-run", "original-node"), execution_cost_scope("original-exp", expects_provider=True) as original:
        with pytest.raises(MediaProviderError):
            service.generate(payload, resume_id=None, **kwargs)
    assert Decimal(original.finish()["amount_usd"]) == Decimal("0.91")
    downloaded = True
    with run_cost_owner("resume-run", "resume-node"), execution_cost_scope("resume-exp", expects_provider=True) as resumed:
        assert service.generate(payload, resume_id="minimax-cost-task", **kwargs).content == b"video"
    assert resumed.finish()["status"] == "no_charge" and len(posts) == 1
    with SessionLocal() as db:
        receipts = db.scalars(select(ProviderCostRecord).where(ProviderCostRecord.provider == "minimax")).all()
        assert len(receipts) == 1
        receipt = receipts[0]
        assert receipt.amount_usd == Decimal("0.91") and receipt.status == "calculated"
        assert receipt.run_id == "original-run" and receipt.pricing["source"] == MINIMAX_SOURCE
        assert "fake-secret" not in str(receipt.usage)
