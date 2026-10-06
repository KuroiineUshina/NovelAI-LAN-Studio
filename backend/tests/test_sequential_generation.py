from __future__ import annotations

import asyncio
import base64
import json
import sqlite3

import httpx
import pytest
import respx

from backend.app.database import Database
from backend.app.schemas import GenerationRequest


def payload(repeat_count=3, seed=None, count=1):
    return {
        "mode": "txt2img", "model": "nai-diffusion-5-full", "repeat_count": repeat_count,
        "quality_prompt": "quality snapshot", "description_prompt": "quiet garden",
        "parameters": {"seed": seed, "count": count},
    }


def output(icon_bytes, seed=1, count=1):
    return httpx.Response(201, json={"images": [
        {"image": base64.b64encode(icon_bytes).decode(), "seed": seed + i} for i in range(count)
    ]})


@pytest.mark.parametrize("count", [0, -1, 101, 1.5, True, "3"])
def test_repeat_count_api_rejects_invalid(client, count):
    assert client.post("/api/jobs", json=payload(count)).status_code == 422


@pytest.mark.asyncio
@respx.mock
async def test_repeat_serial_requests_random_seeds_progress_and_images(client, app, icon_bytes, monkeypatch):
    state = app.state.services
    state.credentials.set_token("test-token")
    response = client.post("/api/jobs", json=payload(3, count=2))
    assert response.status_code == 202
    job = response.json()
    initial_seed = job["request"]["parameters"]["seed"]
    seeds = iter([111, 222])
    monkeypatch.setattr("backend.app.jobs.secrets.randbits", lambda _: next(seeds))
    requests = []
    in_flight = maximum = 0

    async def generate(request):
        nonlocal in_flight, maximum
        in_flight += 1
        maximum = max(maximum, in_flight)
        body = json.loads(request.content)
        requests.append(body)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return output(icon_bytes, body["parameters"]["seed"], 2)

    route = respx.post("https://image.novelai.net/ai/generate-image").mock(side_effect=generate)
    assert state.database.set_job_running(job["id"])
    await state.jobs._process(job["id"])
    current = state.database.get_job(job["id"])
    assert current["status"] == "succeeded"
    assert current["completed_requests"] == 3
    assert current["output_count"] == 6
    assert route.call_count == 3 and maximum == 1
    assert [r["parameters"]["seed"] for r in requests] == [initial_seed, 111, 222]
    assert len({r["input"] for r in requests}) == 1
    images = state.database.list_images(None, [], 1)["items"]
    assert len(images) == 6
    assert {image["settings"]["seed"] for image in images} == {initial_seed, 111, 222}


@pytest.mark.asyncio
@respx.mock
async def test_fixed_seed_is_preserved(client, app, icon_bytes):
    state = app.state.services
    state.credentials.set_token("test-token")
    job = client.post("/api/jobs", json=payload(3, seed=0)).json()
    route = respx.post("https://image.novelai.net/ai/generate-image").mock(return_value=output(icon_bytes))
    state.database.set_job_running(job["id"])
    await state.jobs._process(job["id"])
    assert [json.loads(call.request.content)["parameters"]["seed"] for call in route.calls] == [0, 0, 0]


@pytest.mark.asyncio
@respx.mock
async def test_failure_stops_remaining_rounds_without_retry(client, app, icon_bytes):
    state = app.state.services
    state.credentials.set_token("test-token")
    job = client.post("/api/jobs", json=payload(5)).json()
    route = respx.post("https://image.novelai.net/ai/generate-image").mock(side_effect=[
        output(icon_bytes), httpx.Response(500, json={"message":"test failure"}), output(icon_bytes),
    ])
    state.database.set_job_running(job["id"])
    await state.jobs._process(job["id"])
    current = state.database.get_job(job["id"])
    assert route.call_count == 2
    assert current["status"] == "failed"
    assert current["output_count"] == current["completed_requests"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_stop_during_in_flight_request_saves_result_then_stops(client, app, icon_bytes):
    state = app.state.services
    state.credentials.set_token("test-token")
    job = client.post("/api/jobs", json=payload(10)).json()
    entered, release = asyncio.Event(), asyncio.Event()

    async def generate(request):
        entered.set()
        await release.wait()
        return output(icon_bytes)

    route = respx.post("https://image.novelai.net/ai/generate-image").mock(side_effect=generate)
    state.database.set_job_running(job["id"])
    task = asyncio.create_task(state.jobs._process(job["id"]))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        stopped = client.post(f"/api/jobs/{job['id']}/cancel")
        assert stopped.status_code == 200 and stopped.json()["cancel_requested"]
        assert state.database.get_job(job["id"])["status"] == "running"
    finally:
        release.set()
        await asyncio.wait_for(task, 3)
    current = state.database.get_job(job["id"])
    assert route.call_count == 1
    assert current["status"] == "cancelled"
    assert current["output_count"] == current["completed_requests"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_cancelled_queue_entry_cannot_start(client, app):
    state = app.state.services
    job = client.post("/api/jobs", json=payload(4)).json()
    assert client.post(f"/api/jobs/{job['id']}/cancel").status_code == 200
    assert not state.database.set_job_running(job["id"])
    await state.jobs._process(job["id"])
    assert state.database.get_job(job["id"])["status"] == "cancelled"
    assert not respx.calls


def test_additive_schema_migration_and_restart_never_resumes(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE jobs(id TEXT PRIMARY KEY,mode TEXT,status TEXT,request_json TEXT,queue_position INTEGER,error_code TEXT,error_message TEXT,correlation_id TEXT,output_count INTEGER DEFAULT 0,created_at TEXT,started_at TEXT,finished_at TEXT)")
    db = Database(path)
    db.initialize()
    job = db.create_job(payload(10), "test")
    db.set_job_running(job["id"])
    db.update_job_progress(job["id"], 2, 2)
    db.initialize()
    current = db.get_job(job["id"])
    assert current["status"] == "interrupted"
    assert current["completed_requests"] == current["output_count"] == 2
    assert not current["cancel_requested"]


@pytest.mark.asyncio
@respx.mock
async def test_inpaint_mask_reused_until_all_rounds_complete(client, app, icon_bytes):
    state = app.state.services
    state.credentials.set_token("test-token")
    source = client.post("/api/uploads", files={"file":("source.png",icon_bytes,"image/png")}).json()
    mask = client.post("/api/masks", data={"source_asset_id":source["id"]}, files={"file":("mask.png",icon_bytes,"image/png")}).json()
    request = payload(3)
    request.update(mode="inpaint",source_asset_id=source["id"],mask_asset_id=mask["id"])
    job = client.post("/api/jobs", json=request).json()
    route = respx.post("https://image.novelai.net/ai/generate-image").mock(return_value=output(icon_bytes))
    state.database.set_job_running(job["id"])
    await state.jobs._process(job["id"])
    assert route.call_count == 3
    assert state.database.get_job(job["id"])["status"] == "succeeded"
    assert state.database.get_mask(mask["id"]) is None


@pytest.mark.asyncio
async def test_cancelled_ids_do_not_block_new_enqueue_and_active_limit_remains(app):
    state = app.state.services
    for index in range(15):
        job = state.database.create_job(payload(), f"test-{index}")
        await asyncio.wait_for(state.jobs.enqueue(job["id"]), 0.5)
        assert state.database.request_job_stop(job["id"])
    for index in range(10):
        job = state.database.create_job(payload(), f"active-{index}")
        await asyncio.wait_for(state.jobs.enqueue(job["id"]), 0.5)
    with pytest.raises(OverflowError):
        state.database.create_job(payload(), "too-many")


@pytest.mark.asyncio
@respx.mock
async def test_multiple_queued_sequences_keep_fifo_order(app, icon_bytes):
    state = app.state.services
    state.credentials.set_token("test-token")
    first_payload = payload(3, seed=10)
    second_payload = payload(2, seed=20)
    first = state.database.create_job(GenerationRequest.model_validate(first_payload).model_dump(), "first")
    second = state.database.create_job(GenerationRequest.model_validate(second_payload).model_dump(), "second")
    await state.jobs.enqueue(first["id"])
    await state.jobs.enqueue(second["id"])
    route = respx.post("https://image.novelai.net/ai/generate-image").mock(return_value=output(icon_bytes))
    await state.jobs.start()
    try:
        await asyncio.wait_for(state.jobs.queue.join(), 5)
    finally:
        await state.jobs.stop()
    assert [json.loads(call.request.content)["parameters"]["seed"] for call in route.calls] == [10, 10, 10, 20, 20]
    assert state.database.get_job(first["id"])["status"] == "succeeded"
    assert state.database.get_job(second["id"])["status"] == "succeeded"
