from fastapi.testclient import TestClient
import time


def import_reference(client: TestClient, suffix: str = "abc") -> str:
    inspect = client.post("/references/inspect", json={"urls": [f"https://youtube.com/watch?v={suffix}"]})
    assert inspect.status_code == 200
    response = client.post("/references/import", json={"metadata": inspect.json()[0], "rights_basis": "analysis_only"})
    assert response.status_code == 201
    return response.json()["reference_id"]


def create_format(client: TestClient) -> str:
    reference_ids = [import_reference(client, "a1"), import_reference(client, "b2")]
    reference_set = client.post("/reference-sets", json={"name": "Test set", "reference_ids": reference_ids})
    assert reference_set.status_code == 201
    result = client.post("/format-runs", json={"reference_set_id": reference_set.json()["id"], "name": "Test format"})
    assert result.status_code == 201
    return result.json()["id"]


def test_reference_deduplication_and_rights_isolation(client: TestClient):
    first_id = import_reference(client, "same-video")
    preview = client.post("/references/inspect", json={"urls": ["https://youtube.com/watch?v=same-video&utm_source=x"]}).json()[0]
    assert preview["duplicate_reference_id"] == first_id
    imported = client.post("/references/import", json={"metadata": preview, "rights_basis": "analysis_only", "allow_generation_input": True})
    assert imported.json()["deduplicated"] is True
    record = client.get("/references").json()[0]
    assert record["allow_generation_input"] is False


def test_format_variation_and_merge_preserve_lineage(client: TestClient):
    format_a = create_format(client)
    reference_id = import_reference(client, "c3")
    reference_set = client.post("/reference-sets", json={"name": "Second", "reference_ids": [reference_id]}).json()
    format_b = client.post("/format-runs", json={"reference_set_id": reference_set["id"], "name": "Second format"}).json()["id"]
    variants = client.post(f"/formats/{format_a}/variants", json={"count": 3, "distance": "medium", "variation_axes": ["visual_motion"]})
    assert variants.status_code == 201
    assert len(variants.json()) == 3
    merged = client.post("/formats/merge", json={"name": "Merged", "sources": [{"format_id": format_a, "weight": 0.7}, {"format_id": format_b, "weight": 0.3}]})
    assert merged.status_code == 201
    assert merged.json()["lineage"]["core.editing.median_shot_duration_ms"]["strategy"] == "weighted_average"


def test_generation_compile_budget_and_immutable_node_history(client: TestClient):
    format_id = create_format(client)
    over_budget = client.post("/generation-briefs", json={"topic": "Budget failure", "key_message": "x", "audience": "general", "format_id": format_id, "budget_limit_usd": 1})
    response = client.post("/generation-runs", json={"brief_id": over_budget.json()["id"], "dry_run": True})
    assert response.status_code == 422

    brief = client.post("/generation-briefs", json={"topic": "Roman roads", "key_message": "Old engineering survives", "audience": "history fans", "format_id": format_id, "budget_limit_usd": 5})
    run = client.post("/generation-runs", json={"brief_id": brief.json()["id"], "dry_run": True})
    assert run.status_code == 201
    payload = run.json()
    assert payload["execution_plan"]["checks"]["reference_isolation"] is True
    assert payload["execution_plan"]["expanded_jobs"] > 40
    assert len(payload["node_runs"]) == 12


def test_fork_reuses_upstream_without_overwriting(client: TestClient):
    format_id = create_format(client)
    brief = client.post("/generation-briefs", json={"topic": "Fork test", "key_message": "x", "audience": "general", "format_id": format_id, "budget_limit_usd": 5}).json()
    run = client.post("/generation-runs", json={"brief_id": brief["id"], "dry_run": True}).json()
    target = run["node_runs"][4]
    fork = client.post(f"/node-runs/{target['id']}/fork")
    assert fork.status_code == 201
    forked = client.get(f"/runs/{fork.json()['run_id']}").json()
    assert forked["execution_plan"]["forked_at_node"] == target["node_key"]
    assert forked["id"] != run["id"]


def test_run_waits_for_candidate_selection_then_resumes(client: TestClient):
    format_id = create_format(client)
    brief = client.post("/generation-briefs", json={"topic": "End to end", "key_message": "x", "audience": "general", "format_id": format_id, "budget_limit_usd": 5}).json()
    run = client.post("/generation-runs", json={"brief_id": brief["id"]}).json()
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        run = client.get(f"/runs/{run['id']}").json()
        if run["status"] == "WAITING_INPUT":
            break
        time.sleep(0.08)
    assert run["status"] == "WAITING_INPUT"
    candidate_node = next(node for node in run["node_runs"] if node["node_key"] == "candidate.select")
    selected = client.post(f"/node-runs/{candidate_node['id']}/select", json={"artifact_id": "art_candidate_02"})
    assert selected.status_code == 201
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        run = client.get(f"/runs/{run['id']}").json()
        if run["status"] == "SUCCEEDED":
            break
        time.sleep(0.08)
    assert run["status"] == "SUCCEEDED"
    assert run["progress"] == 100
    assert sum(len(node["output_artifact_ids"]) for node in run["node_runs"]) >= 10


def test_single_experiment_snapshots_inputs_caches_and_sets_baseline(client: TestClient):
    payload = {
        "canvas_id": "canvas_test",
        "node_id": "video_1",
        "node_key": "video.generate",
        "prompt": "A slow cinematic push-in on ancient stone",
        "model_alias": "video.fast",
        "parameters": {"resolution": "1080p", "aspect_ratio": "9:16", "seed": 42},
        "inputs": [{"node_id": "image_1", "type": "Image", "artifact_id": "art_image_1"}],
    }
    first = client.post("/experiments", json=payload)
    assert first.status_code == 201
    first_run = first.json()
    assert first_run["status"] == "SUCCEEDED"
    assert first_run["model_alias"] == "google.video.fast"
    assert first_run["exact_model_id"] == "veo-3.1-fast-generate-001"
    assert first_run["inputs"] == payload["inputs"]
    assert first_run["cache_hit"] is False
    assert len(first_run["output_artifact_ids"]) == 1

    second_run = client.post("/experiments", json=payload).json()
    assert second_run["id"] != first_run["id"]
    assert second_run["request_hash"] == first_run["request_hash"]
    assert second_run["cache_hit"] is True
    assert second_run["cached_from_id"] == first_run["id"]
    assert second_run["cost_usd"] == 0

    changed = client.post("/experiments", json={**payload, "model_alias": "video.quality"}).json()
    assert changed["request_hash"] != first_run["request_hash"]

    baseline = client.post(f"/experiments/{first_run['id']}/baseline")
    assert baseline.status_code == 200
    assert baseline.json()["is_baseline"] is True
    history = client.get("/experiments", params={"canvas_id": "canvas_test", "node_id": "video_1"})
    assert history.status_code == 200
    assert len(history.json()) == 3
    assert sum(item["is_baseline"] for item in history.json()) == 1
    invalid = client.post("/experiments", json={**payload, "model_alias": "text.quality"})
    assert invalid.status_code == 422
