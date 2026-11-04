from __future__ import annotations

import sqlite3

from backend.app.database import Database


def test_quality_preset_round_trips_generation_settings(client):
    created = client.post(
        "/api/quality-presets",
        json={
            "name": "애니 고품질",
            "prompt": "masterpiece, best quality",
            "negative_prompt": "lowres",
            "settings": {"guidance": 5.5, "guidance_rescale": 0.2, "steps": 28, "sampler": "k_euler_ancestral", "noise_schedule": "karras"},
        },
    )
    assert created.status_code == 201
    preset = created.json()
    assert preset["settings"] == {
        "steps": 28,
        "guidance": 5.5,
        "guidance_rescale": 0.2,
        "sampler": "k_euler_ancestral",
        "noise_schedule": "karras",
    }
    assert "settings_json" not in preset

    updated = client.put(
        f"/api/quality-presets/{preset['id']}",
        json={"name": "애니 고품질", "prompt": "masterpiece", "settings": {"guidance": 6}},
    )
    assert updated.status_code == 200
    assert updated.json()["settings"] == {"guidance": 6.0}

    plain = client.post("/api/quality-presets", json={"name": "기본", "prompt": "best quality"}).json()
    assert plain["settings"] == {}
    listed = {item["name"]: item["settings"] for item in client.get("/api/quality-presets").json()["items"]}
    assert listed == {"애니 고품질": {"guidance": 6.0}, "기본": {}}


def test_quality_preset_rejects_out_of_range_settings(client):
    response = client.post(
        "/api/quality-presets",
        json={"name": "잘못", "prompt": "x", "settings": {"guidance": 99, "noise_schedule": "linear"}},
    )
    assert response.status_code == 422


def test_existing_quality_presets_gain_empty_settings(tmp_path):
    path = tmp_path / "old.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """CREATE TABLE quality_prompt_presets (
               id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, prompt TEXT NOT NULL,
               negative_prompt TEXT NOT NULL DEFAULT '', sort_order INTEGER NOT NULL DEFAULT 0,
               created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
           INSERT INTO quality_prompt_presets VALUES ('p1','옛 프리셋','masterpiece','',0,'2026-01-01','2026-01-01');"""
    )
    connection.close()
    database = Database(path)
    database.initialize()
    assert database.get_quality_prompt_preset("p1")["settings"] == {}
