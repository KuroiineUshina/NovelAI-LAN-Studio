from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path

from backend.app.config import AppPaths
from backend.app.credentials import CredentialStore
from backend.app.database import Database, iso, utc_now
from backend.app.jobs import JobManager
from backend.app.storage import ImageStorage


def test_database_migrates_legacy_image_prompt_columns(tmp_path: Path):
    database_path = tmp_path / "legacy" / "data" / "app.db"
    database_path.parent.mkdir(parents=True)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """CREATE TABLE images (
               id TEXT PRIMARY KEY, job_id TEXT NOT NULL, parent_image_id TEXT,
               file_path TEXT NOT NULL, thumbnail_path TEXT, mime_type TEXT NOT NULL,
               width INTEGER NOT NULL, height INTEGER NOT NULL, mode TEXT NOT NULL,
               model TEXT NOT NULL, prompt TEXT NOT NULL, negative_prompt TEXT NOT NULL,
               settings_json TEXT NOT NULL, character_snapshot_json TEXT NOT NULL,
               seed INTEGER, created_at TEXT NOT NULL, expires_at TEXT,
               favorite_at TEXT, cleanup_error TEXT)"""
        )
        connection.execute(
            """INSERT INTO images
               (id,job_id,file_path,mime_type,width,height,mode,model,prompt,
                negative_prompt,settings_json,character_snapshot_json,created_at)
               VALUES('legacy-image','legacy-job','legacy.png','image/png',1,1,
                      'txt2img','nai-diffusion-5-full','saved legacy prompt','saved legacy negative',
                      '{}','[]','2026-01-01T00:00:00+00:00')"""
        )
        connection.commit()

    database = Database(database_path)
    database.initialize()
    image = database.get_image("legacy-image")
    assert image is not None
    assert image["quality_prompt"] == ""
    assert image["description_prompt"] == "saved legacy prompt"
    assert image["quality_negative_prompt"] == "saved legacy negative"
    assert image["description_negative_prompt"] == ""



LEGACY_STORY_SCHEMA = """
CREATE TABLE story_scenarios (
    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    data_json TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE story_player_profiles (
    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    profile TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE story_sessions (
    id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL REFERENCES story_scenarios(id),
    title TEXT NOT NULL, scenario_snapshot_json TEXT NOT NULL,
    player_profile_json TEXT NOT NULL, memory TEXT NOT NULL DEFAULT '',
    revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE story_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES story_sessions(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
    created_at TEXT NOT NULL, UNIQUE(session_id, sequence));
CREATE TABLE story_library_images (
    id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL REFERENCES story_scenarios(id) ON DELETE CASCADE,
    image_id TEXT NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE story_message_images (
    message_id TEXT PRIMARY KEY REFERENCES story_messages(id) ON DELETE CASCADE,
    image_id TEXT NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    library_image_id TEXT REFERENCES story_library_images(id) ON DELETE SET NULL,
    source TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX idx_story_sessions_updated ON story_sessions(updated_at DESC);
CREATE INDEX idx_story_messages_session_sequence ON story_messages(session_id, sequence);
CREATE INDEX idx_story_library_scenario_priority ON story_library_images(scenario_id);
INSERT INTO story_scenarios VALUES('scenario','Old story','{}',1,'t','t');
INSERT INTO story_player_profiles VALUES('player','Player','profile','t','t');
INSERT INTO story_sessions(id,scenario_id,title,scenario_snapshot_json,player_profile_json,created_at,updated_at)
    VALUES('session','scenario','Old session','{}','{}','t','t');
INSERT INTO story_messages VALUES('message','session',1,'assistant','A scene.','t');
INSERT INTO story_library_images VALUES('library','scenario','story-image','Scene','t','t');
INSERT INTO story_message_images VALUES('message','story-image','library','generated','t');
"""


def test_startup_drops_removed_story_tables_but_keeps_their_images(tmp_path: Path):
    database_path = tmp_path / "story" / "data" / "app.db"
    database = Database(database_path)
    database.initialize()
    job = database.create_job({"mode": "txt2img", "parameters": {}}, "STORY1")
    database.create_image(
        {
            "id": "story-image",
            "job_id": job["id"],
            "parent_image_id": None,
            "file_path": "story.png",
            "thumbnail_path": None,
            "mime_type": "image/png",
            "width": 1,
            "height": 1,
            "mode": "txt2img",
            "model": "nai-diffusion-5-full",
            "prompt": "scene",
            "negative_prompt": "",
            "settings": {"story_message_id": "message"},
            "character_snapshot": [],
            "seed": None,
            "created_at": iso(),
            "expires_at": None,
        },
        [],
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(LEGACY_STORY_SCHEMA)

    Database(database_path).initialize()

    with sqlite3.connect(database_path) as connection:
        leftovers = connection.execute(
            "SELECT type, name FROM sqlite_master WHERE name LIKE '%story%'"
        ).fetchall()
        images = connection.execute("SELECT id FROM images").fetchall()
    assert leftovers == []
    assert images == [("story-image",)]
    assert database.get_image("story-image") is not None
    assert [item["id"] for item in database.list_images(None, [], 1)["items"]] == [
        "story-image"
    ]
    # Running the startup migration again on an already-clean database is a no-op.
    Database(database_path).initialize()
    assert database.get_image("story-image") is not None


def create_saved_image(
    database: Database,
    storage: ImageStorage,
    icon_bytes: bytes,
    tag_ids: list[str],
    mode: str = "txt2img",
    nsfw_enabled: bool | None = None,
):
    job = database.create_job(
        {"mode": mode, "parameters": {}, "character_snapshot": []}, "ABC123"
    )
    saved = storage.save_generated(icon_bytes, f"image-{job['id']}")
    created = utc_now()
    return database.create_image(
        {
            "id": f"image-{job['id']}",
            "job_id": job["id"],
            "parent_image_id": None,
            **saved,
            "mode": mode,
            "model": "nai-diffusion-5-full",
            "prompt": "test",
            "negative_prompt": "",
            "settings": (
                {"nsfw_enabled": nsfw_enabled}
                if nsfw_enabled is not None
                else {}
            ),
            "character_snapshot": [],
            "seed": 42,
            "created_at": iso(created),
            "expires_at": iso(created + timedelta(hours=168)),
        },
        tag_ids,
    )


def test_favorite_transition_unfavorite_and_cleanup(tmp_path: Path, icon_bytes: bytes):
    paths = AppPaths(tmp_path / "app")
    paths.ensure()
    database = Database(paths.database)
    database.initialize()
    storage = ImageStorage(paths)
    preset = database.create_preset(
        {
            "name": "아리아",
            "tag_name": "aria",
            "subject_type": "girl",
            "prompt": "girl",
            "negative_prompt": "",
            "sort_order": 0,
        }
    )
    image = create_saved_image(database, storage, icon_bytes, [preset["tag_id"]])

    new_path, new_thumb = storage.move_favorite(image, True)
    favorite = database.set_favorite_paths(image["id"], True, new_path, new_thumb)
    assert favorite is not None
    assert favorite["favorite_at"] is not None
    assert favorite["expires_at"] is None
    assert "favorites" in favorite["file_path"]

    temp_path, temp_thumb = storage.move_favorite(favorite, False)
    temporary = database.set_favorite_paths(image["id"], False, temp_path, temp_thumb)
    assert temporary is not None
    expiry = __import__("datetime").datetime.fromisoformat(temporary["expires_at"])
    assert timedelta(hours=167, minutes=59) < expiry - utc_now() <= timedelta(hours=168)

    with database.connect() as connection:
        connection.execute(
            "UPDATE images SET expires_at=? WHERE id=?",
            (iso(utc_now() - timedelta(seconds=1)), image["id"]),
        )
        connection.commit()
    manager = JobManager(database, storage, CredentialStore())
    assert manager.cleanup_once()["images"] == 1
    assert database.get_image(image["id"]) is None
    assert database.statistics()["lifetime"] == 1


def test_tag_rename_and_preset_delete_preserve_image_tag(tmp_path: Path, icon_bytes: bytes):
    paths = AppPaths(tmp_path / "app")
    paths.ensure()
    database = Database(paths.database)
    database.initialize()
    storage = ImageStorage(paths)
    data = {
        "name": "카이",
        "tag_name": "kai",
        "subject_type": "boy",
        "prompt": "boy",
        "negative_prompt": "",
        "sort_order": 0,
    }
    preset = database.create_preset(data)
    image = create_saved_image(database, storage, icon_bytes, [preset["tag_id"]])

    updated = database.update_preset(preset["id"], {**data, "tag_name": "kai-main"})
    assert updated and updated["tag_name"] == "kai-main"
    assert database.get_image(image["id"])["tags"][0]["name"] == "kai-main"

    assert database.delete_preset(preset["id"])
    assert database.get_image(image["id"])["tags"][0]["name"] == "kai-main"


def test_favorite_tag_filter_uses_and_semantics(tmp_path: Path, icon_bytes: bytes):
    paths = AppPaths(tmp_path / "app")
    paths.ensure()
    database = Database(paths.database)
    database.initialize()
    storage = ImageStorage(paths)
    first = database.create_preset({"name": "A", "tag_name": "a", "subject_type": "girl", "prompt": "a", "negative_prompt": "", "sort_order": 0})
    second = database.create_preset({"name": "B", "tag_name": "b", "subject_type": "boy", "prompt": "b", "negative_prompt": "", "sort_order": 1})
    both = create_saved_image(database, storage, icon_bytes, [first["tag_id"], second["tag_id"]])
    only_first = create_saved_image(database, storage, icon_bytes, [first["tag_id"]])
    for image in (both, only_first):
        path, thumb = storage.move_favorite(image, True)
        database.set_favorite_paths(image["id"], True, path, thumb)

    result = database.list_images(True, [first["tag_id"], second["tag_id"]], 1)
    assert result["total"] == 1
    assert result["items"][0]["id"] == both["id"]


def test_nsfw_filter_combines_with_folder_tags_and_tag_counts(
    tmp_path: Path, icon_bytes: bytes
):
    paths = AppPaths(tmp_path / "app")
    paths.ensure()
    database = Database(paths.database)
    database.initialize()
    storage = ImageStorage(paths)
    preset = database.create_preset(
        {
            "name": "A",
            "tag_name": "a",
            "subject_type": "girl",
            "prompt": "a",
            "negative_prompt": "",
            "sort_order": 0,
        }
    )
    nsfw = create_saved_image(
        database,
        storage,
        icon_bytes,
        [preset["tag_id"]],
        nsfw_enabled=True,
    )
    general = create_saved_image(
        database,
        storage,
        icon_bytes,
        [preset["tag_id"]],
        nsfw_enabled=False,
    )
    legacy_without_flag = create_saved_image(
        database, storage, icon_bytes, [preset["tag_id"]]
    )
    for image in (nsfw, general, legacy_without_flag):
        path, thumb = storage.move_favorite(image, True)
        database.set_favorite_paths(image["id"], True, path, thumb)

    nsfw_result = database.list_images(
        True, [preset["tag_id"]], 1, nsfw=True
    )
    general_result = database.list_images(
        True, [preset["tag_id"]], 1, nsfw=False
    )

    assert nsfw_result["total"] == 1
    assert nsfw_result["items"][0]["id"] == nsfw["id"]
    assert general_result["total"] == 2
    assert {item["id"] for item in general_result["items"]} == {
        general["id"],
        legacy_without_flag["id"],
    }
    assert database.favorite_tag_counts(nsfw=True) == [
        {"id": preset["tag_id"], "name": "a", "count": 1}
    ]
    assert database.favorite_tag_counts(nsfw=False) == [
        {"id": preset["tag_id"], "name": "a", "count": 2}
    ]
