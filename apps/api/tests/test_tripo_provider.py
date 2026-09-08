from __future__ import annotations

import json
import struct

import httpx
import pytest

from app.character_motion.canonical_motion import BONE_NAMES
from app.character_motion.bone_maps import resolve_bone_map
from app.character_motion.providers import (
    AutoRigInput,
    ImageTo3DInput,
    ImageTo3DView,
    TripoAutoRigProvider,
    TripoImageTo3DProvider,
)
from app.character_motion.tripo import TripoClient, TripoProviderError, TripoUpload


def minimal_glb(*, rigged: bool = True, bone_names: list[str] | None = None) -> bytes:
    selected_bones = bone_names or list(BONE_NAMES)
    document = {
        "asset": {"version": "2.0", "generator": "Frameflow Tripo test"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [
            {"name": "Fixture", "mesh": 0, **({"skin": 0} if rigged else {})},
            *(
                [
                    {"name": name, **({"children": [index + 2]} if index + 1 < len(BONE_NAMES) else {})}
                    for index, name in enumerate(selected_bones)
                ]
                if rigged else []
            ),
        ],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "material": 0}]}],
        "accessors": [
            {"componentType": 5126, "count": 24, "type": "VEC3", "min": [-0.5, 0.0, -0.3], "max": [0.5, 1.8, 0.3]}
        ],
        "materials": [{"name": "Fixture"}],
        **({"skins": [{"joints": list(range(1, len(selected_bones) + 1)), "skeleton": 1}]} if rigged else {}),
    }
    body = json.dumps(document, separators=(",", ":")).encode()
    body += b" " * ((4 - len(body) % 4) % 4)
    return (
        struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(body))
        + struct.pack("<II", len(body), 0x4E4F534A)
        + body
    )


def test_tripo_multiview_provider_uploads_role_keyed_images_and_downloads_glb():
    requests: list[tuple[str, str, dict | None]] = []
    upload_count = 0
    poll_count = 0
    output_glb = minimal_glb(rigged=False)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal upload_count, poll_count
        path = request.url.path
        if request.method == "GET" and path.endswith("/account/balance"):
            assert request.headers["authorization"] == "Bearer test-key"
            return httpx.Response(200, json={"code": 0, "data": {"balance": 1000, "frozen": 0}})
        if request.method == "POST" and path.endswith("/files"):
            upload_count += 1
            assert request.headers["authorization"] == "Bearer test-key"
            assert request.headers["content-type"].startswith("multipart/form-data")
            requests.append((request.method, path, None))
            return httpx.Response(200, json={"code": 0, "data": {"file_token": f"file_{upload_count}"}})
        if request.method == "POST" and path.endswith("/generation/multiview-to-model"):
            payload = json.loads(request.content)
            requests.append((request.method, path, payload))
            return httpx.Response(200, json={"code": 0, "data": {"task_id": "95c3b441-8011-44de-950a-16f7746fbf81"}})
        if request.method == "GET" and path.endswith("/tasks/95c3b441-8011-44de-950a-16f7746fbf81"):
            poll_count += 1
            status = "running" if poll_count == 1 else "success"
            return httpx.Response(200, json={
                "code": 0,
                "data": {
                    "task_id": "95c3b441-8011-44de-950a-16f7746fbf81",
                    "type": "multiview_to_model",
                    "status": status,
                    "progress": 45 if status == "running" else 100,
                    "credits_consumed": 60,
                    "output": {"model_url": "https://tripo-data.rg1.data.tripo3d.com/output/model.glb"} if status == "success" else {},
                },
            })
        if request.method == "GET" and request.url.host == "tripo-data.rg1.data.tripo3d.com":
            assert "authorization" not in request.headers
            return httpx.Response(200, content=output_glb)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    client = TripoClient(
        api_key="test-key",
        http_client=http,
        poll_interval_seconds=0.1,
    )
    submitted: list[tuple[str, str]] = []
    progress: list[tuple[int, str]] = []
    result = TripoImageTo3DProvider(client).generate(ImageTo3DInput(
        image=b"",
        image_content_type="application/json",
        quality="detailed",
        seed=42,
        views=(
            ImageTo3DView("front", b"front", "image/png", "front.png"),
            ImageTo3DView("left", b"left", "image/png", "left.png"),
            ImageTo3DView("back", b"back", "image/jpeg", "back.jpg"),
            ImageTo3DView("right", b"right", "image/png", "right.png"),
        ),
        model_id="P1-20260311",
        face_limit=20_000,
        texture=True,
        pbr=True,
        texture_quality="detailed",
        export_uv=True,
        smart_low_poly=True,
        timeout_seconds=30,
        task_callback=lambda stage, task_id: submitted.append((stage, task_id)),
        progress_callback=lambda value, message: progress.append((value, message)),
    ))

    generation = next(payload for method, path, payload in requests if path.endswith("multiview-to-model"))
    assert generation == {
        "inputs": [
            {"front": "file_1"}, {"left": "file_2"}, {"back": "file_3"}, {"right": "file_4"},
        ],
        "model": "P1-20260311",
        "face_limit": 20_000,
        "texture": True,
        "pbr": True,
        "export_uv": True,
        "model_seed": 42,
        "texture_quality": "detailed",
    }
    assert result.glb == output_glb
    assert result.provider_request_id == "tripo:generate:95c3b441-8011-44de-950a-16f7746fbf81"
    assert result.metadata["credits_consumed"] == 60
    assert submitted == [
        ("generate", "pending"),
        ("generate", "95c3b441-8011-44de-950a-16f7746fbf81"),
    ]
    assert any("running" in message for _, message in progress)


def test_tripo_auto_rig_runs_check_and_requests_mixamo_glb():
    requests: list[tuple[str, dict]] = []
    output_glb = minimal_glb(rigged=True, bone_names=list(resolve_bone_map("mixamo").values()))

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path.endswith("/files"):
            return httpx.Response(200, json={"code": 0, "data": {"file_token": "file_model_123"}})
        if request.method == "POST" and path.endswith("/animations/rig-check"):
            payload = json.loads(request.content)
            requests.append(("rig-check", payload))
            return httpx.Response(200, json={"code": 0, "data": {"task_id": "task_check_123"}})
        if request.method == "POST" and path.endswith("/animations/rig"):
            payload = json.loads(request.content)
            requests.append(("rig", payload))
            return httpx.Response(200, json={"code": 0, "data": {"task_id": "task_rig_123"}})
        if request.method == "GET" and path.endswith("/tasks/task_check_123"):
            return httpx.Response(200, json={"code": 0, "data": {
                "task_id": "task_check_123", "type": "rig_check", "status": "success", "progress": 100,
                "output": {"riggable": True, "rig_type": "biped"},
            }})
        if request.method == "GET" and path.endswith("/tasks/task_rig_123"):
            return httpx.Response(200, json={"code": 0, "data": {
                "task_id": "task_rig_123", "type": "rig", "status": "success", "progress": 100,
                "credits_consumed": 30,
                "output": {"model_url": "https://cdn.tripo3d.ai/output/rigged.glb"},
            }})
        if request.method == "GET" and request.url.host == "cdn.tripo3d.ai":
            assert "authorization" not in request.headers
            return httpx.Response(200, content=output_glb)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    http = httpx.Client(
        transport=httpx.MockTransport(handler),
    )
    submitted: list[tuple[str, str]] = []
    result = TripoAutoRigProvider(TripoClient(
        api_key="test-key", http_client=http, poll_interval_seconds=0.1,
    )).rig(AutoRigInput(
        glb=minimal_glb(rigged=False),
        rig_profile="mixamo",
        model_id="v1.0-20240301",
        rig_type="biped",
        run_rig_check=True,
        timeout_seconds=30,
        task_callback=lambda stage, task_id: submitted.append((stage, task_id)),
    ))

    assert requests == [
        ("rig-check", {"input": "file_model_123"}),
        ("rig", {
            "input": "file_model_123",
            "model": "v1.0-20240301",
            "rig_type": "biped",
            "spec": "mixamo",
            "out_format": "glb",
        }),
    ]
    assert submitted == [
        ("rig_check", "pending"),
        ("rig_check", "task_check_123"),
        ("rig", "pending"),
        ("rig", "task_rig_123"),
    ]
    assert result.provider_request_id == "tripo:rig:task_rig_123"
    assert result.skeleton_metadata["rig_check"]["riggable"] is True
    assert result.skeleton_metadata["credits_consumed"] == 30


def test_tripo_errors_are_actionable_and_classified(monkeypatch):
    monkeypatch.delenv("TRIPO_API_KEY", raising=False)
    with pytest.raises(TripoProviderError, match="Enable Tripo in Settings") as missing:
        TripoClient()
    assert missing.value.retryable is False

    def unauthorized(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"code": 1001, "message": "invalid token"})

    client = TripoClient(
        api_key="secret-that-must-not-leak",
        http_client=httpx.Client(transport=httpx.MockTransport(unauthorized)),
    )
    with pytest.raises(TripoProviderError, match="authentication failed") as auth:
        client.upload_file(TripoUpload("front", b"image", "image/png", "front.png"))
    assert auth.value.retryable is False
    assert "secret-that-must-not-leak" not in str(auth.value)

    def insufficient(_: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={
            "code": 2010,
            "message": "Insufficient credits",
            "suggestion": "Please top up your account",
            "request_id": "req_credit_test",
        })

    credit_client = TripoClient(
        api_key="valid-test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(insufficient)),
    )
    with pytest.raises(TripoProviderError, match="credits are insufficient") as credits:
        credit_client.upload_file(TripoUpload("front", b"image", "image/png", "front.png"))
    assert credits.value.retryable is False
    assert "req_credit_test" in str(credits.value)


def test_tripo_multiview_preflight_stops_before_upload_when_balance_is_too_low():
    requests: list[str] = []

    def low_balance(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path.endswith("/account/balance"):
            return httpx.Response(200, json={"code": 0, "data": {"balance": 0, "frozen": 0}})
        raise AssertionError("Image upload must not start when Tripo balance is insufficient")

    client = TripoClient(
        api_key="valid-test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(low_balance)),
    )
    with pytest.raises(TripoProviderError, match="requires about 60 credits") as error:
        client.generate_multiview(
            (
                TripoUpload("front", b"front", "image/png", "front.png"),
                TripoUpload("left", b"left", "image/png", "left.png"),
            ),
            model="P1-20260311",
            face_limit=20_000,
            texture=True,
            pbr=True,
            texture_quality="detailed",
            export_uv=True,
            smart_low_poly=True,
            seed=0,
            timeout_seconds=30,
        )
    assert error.value.retryable is False
    assert requests == ["/v3/account/balance"]


def test_tripo_account_balance_uses_bearer_authentication():
    def balance(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v3/account/balance"
        assert request.headers["authorization"] == "Bearer valid-test-key"
        return httpx.Response(200, json={"code": 0, "data": {"balance": 4321.5, "frozen": 12}})

    client = TripoClient(
        api_key="valid-test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(balance)),
    )
    assert client.account_balance() == {"balance": 4321.5, "frozen": 12.0}


def test_tripo_rejects_unsafe_download_urls():
    client = TripoClient(
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x"))),
    )
    with pytest.raises(TripoProviderError, match="unsafe model download URL"):
        client.download_model("http://127.0.0.1/internal.glb")
