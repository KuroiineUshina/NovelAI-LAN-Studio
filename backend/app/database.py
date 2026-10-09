from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence



def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None = None) -> str:
    return (value or utc_now()).astimezone(timezone.utc).isoformat()


def normalize_tag(value: str) -> str:
    return " ".join(value.strip().lower().split())


SCHEMA = """
CREATE TABLE IF NOT EXISTS tags (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    normalized TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS character_presets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    tag_id TEXT NOT NULL REFERENCES tags(id),
    subject_type TEXT NOT NULL CHECK(subject_type IN ('girl', 'boy', 'other')),
    prompt TEXT NOT NULL,
    negative_prompt TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quality_prompt_presets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    prompt TEXT NOT NULL,
    negative_prompt TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS character_sets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS character_set_members (
    set_id TEXT NOT NULL REFERENCES character_sets(id) ON DELETE CASCADE,
    preset_id TEXT NOT NULL REFERENCES character_presets(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    PRIMARY KEY(set_id, preset_id)
);

CREATE TABLE IF NOT EXISTS discord_webhooks (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS uploads (
    id TEXT PRIMARY KEY,
    file_path TEXT NOT NULL,
    thumbnail_path TEXT,
    original_name TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    cleanup_error TEXT
);

CREATE TABLE IF NOT EXISTS masks (
    id TEXT PRIMARY KEY,
    file_path TEXT NOT NULL,
    source_asset_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    request_json TEXT NOT NULL,
    queue_position INTEGER,
    error_code TEXT,
    error_message TEXT,
    correlation_id TEXT,
    output_count INTEGER NOT NULL DEFAULT 0,
    completed_requests INTEGER NOT NULL DEFAULT 0,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS images (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    parent_image_id TEXT REFERENCES images(id) ON DELETE SET NULL,
    file_path TEXT NOT NULL,
    thumbnail_path TEXT,
    mime_type TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    mode TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt TEXT NOT NULL,
    quality_prompt TEXT NOT NULL DEFAULT '',
    description_prompt TEXT NOT NULL DEFAULT '',
    quality_negative_prompt TEXT NOT NULL DEFAULT '',
    description_negative_prompt TEXT NOT NULL DEFAULT '',
    negative_prompt TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    character_snapshot_json TEXT NOT NULL,
    seed INTEGER,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    favorite_at TEXT,
    cleanup_error TEXT
);

CREATE TABLE IF NOT EXISTS image_tags (
    image_id TEXT NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    tag_id TEXT NOT NULL REFERENCES tags(id),
    PRIMARY KEY(image_id, tag_id)
);

CREATE TABLE IF NOT EXISTS daily_statistics (
    local_date TEXT NOT NULL,
    mode TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(local_date, mode)
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS device_approvals (
    device_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    credential_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','approved','denied','revoked')),
    requested_at TEXT NOT NULL,
    decided_at TEXT,
    approved_at TEXT,
    last_seen_at TEXT,
    last_address TEXT,
    user_agent TEXT NOT NULL DEFAULT ''
);

-- Vibe Transfer encodings cost Anlas and are bound to one model + Information Extracted value.
CREATE TABLE IF NOT EXISTS vibe_encodings (
    cache_key TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    information_extracted REAL NOT NULL,
    data BLOB NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_images_created_at ON images(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_images_expires_at ON images(expires_at);
CREATE INDEX IF NOT EXISTS idx_images_favorite_at ON images(favorite_at);
CREATE INDEX IF NOT EXISTS idx_image_tags_tag_id ON image_tags(tag_id, image_id);
CREATE INDEX IF NOT EXISTS idx_uploads_expires_at ON uploads(expires_at);
CREATE INDEX IF NOT EXISTS idx_jobs_status_created_at ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_quality_prompt_presets_order ON quality_prompt_presets(sort_order, name);
CREATE INDEX IF NOT EXISTS idx_character_set_members_order ON character_set_members(set_id, position);
CREATE INDEX IF NOT EXISTS idx_discord_webhooks_name ON discord_webhooks(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_device_approvals_status_requested
    ON device_approvals(status, requested_at DESC);
"""

# Android standalone mode (and its PC-side API profile transfer) was removed on 2026-10-09.
REMOVED_STANDALONE_TABLES = ("api_profile_transfer_requests",)

# Storyteller was removed on 2026-10-06. Drop its tables from older databases,
# children before parents. Images those rows pointed at stay in `images`.
REMOVED_STORY_INDEXES = (
    "idx_story_library_scenario_priority",
    "idx_story_messages_session_sequence",
    "idx_story_sessions_updated",
)
REMOVED_STORY_TABLES = (
    "story_message_images",
    "story_library_images",
    "story_messages",
    "story_sessions",
    "story_player_profiles",
    "story_scenarios",
)


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._write_lock = threading.RLock()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._write_lock, self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(SCHEMA)
            for index_name in REMOVED_STORY_INDEXES:
                connection.execute(f"DROP INDEX IF EXISTS {index_name}")
            for table_name in REMOVED_STORY_TABLES:
                connection.execute(f"DROP TABLE IF EXISTS {table_name}")
            for table_name in REMOVED_STANDALONE_TABLES:
                connection.execute(f"DROP TABLE IF EXISTS {table_name}")
            connection.execute("DELETE FROM app_settings WHERE key='server_id'")
            job_columns = {row["name"] for row in connection.execute("PRAGMA table_info(jobs)")}
            if "completed_requests" not in job_columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN completed_requests INTEGER NOT NULL DEFAULT 0")
            if "cancel_requested" not in job_columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0")
            preset_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(quality_prompt_presets)").fetchall()
            }
            if "negative_prompt" not in preset_columns:
                connection.execute(
                    "ALTER TABLE quality_prompt_presets ADD COLUMN negative_prompt TEXT NOT NULL DEFAULT ''"
                )
            image_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(images)").fetchall()
            }
            if "quality_prompt" not in image_columns:
                connection.execute(
                    "ALTER TABLE images ADD COLUMN quality_prompt TEXT NOT NULL DEFAULT ''"
                )
            if "description_prompt" not in image_columns:
                connection.execute(
                    "ALTER TABLE images ADD COLUMN description_prompt TEXT NOT NULL DEFAULT ''"
                )
                connection.execute(
                    "UPDATE images SET description_prompt=prompt WHERE description_prompt=''"
                )
            if "quality_negative_prompt" not in image_columns:
                connection.execute(
                    "ALTER TABLE images ADD COLUMN quality_negative_prompt TEXT NOT NULL DEFAULT ''"
                )
                connection.execute(
                    "UPDATE images SET quality_negative_prompt=negative_prompt "
                    "WHERE quality_negative_prompt=''"
                )
            if "description_negative_prompt" not in image_columns:
                connection.execute(
                    "ALTER TABLE images ADD COLUMN description_negative_prompt TEXT NOT NULL DEFAULT ''"
                )
            now = iso()
            connection.execute(
                """UPDATE jobs SET status='interrupted', error_code='APP_RESTART',
                   error_message='앱 재시작으로 자동 재개하지 않았습니다.', finished_at=?
                   WHERE status IN ('queued', 'running')""",
                (now,),
            )
            connection.commit()

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row else None

    def list_presets(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT p.*, t.name AS tag_name FROM character_presets p
                   JOIN tags t ON t.id=p.tag_id
                   ORDER BY p.sort_order, p.name COLLATE NOCASE"""
            ).fetchall()
        return [dict(row) for row in rows]

    def get_presets(self, preset_ids: Sequence[str]) -> list[dict[str, Any]]:
        if not preset_ids:
            return []
        placeholders = ",".join("?" for _ in preset_ids)
        with self.connect() as connection:
            rows = connection.execute(
                f"""SELECT p.*, t.name AS tag_name FROM character_presets p
                    JOIN tags t ON t.id=p.tag_id WHERE p.id IN ({placeholders})""",
                tuple(preset_ids),
            ).fetchall()
        by_id = {row["id"]: dict(row) for row in rows}
        return [by_id[item] for item in preset_ids if item in by_id]

    def existing_tag_ids(self, tag_ids: Sequence[str]) -> list[str]:
        if not tag_ids:
            return []
        placeholders = ",".join("?" for _ in tag_ids)
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT id FROM tags WHERE id IN ({placeholders})", tuple(tag_ids)
            ).fetchall()
        existing = {row["id"] for row in rows}
        return [tag_id for tag_id in tag_ids if tag_id in existing]

    def create_preset(self, data: dict[str, Any]) -> dict[str, Any]:
        now = iso()
        preset_id = str(uuid.uuid4())
        tag_id = str(uuid.uuid4())
        normalized = normalize_tag(data["tag_name"])
        with self._write_lock, self.connect() as connection:
            try:
                existing = connection.execute(
                    "SELECT id FROM tags WHERE normalized=?", (normalized,)
                ).fetchone()
                if existing:
                    tag_id = existing["id"]
                else:
                    connection.execute(
                        "INSERT INTO tags(id,name,normalized,created_at) VALUES(?,?,?,?)",
                        (tag_id, data["tag_name"], normalized, now),
                    )
                connection.execute(
                    """INSERT INTO character_presets
                       (id,name,tag_id,subject_type,prompt,negative_prompt,sort_order,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        preset_id,
                        data["name"],
                        tag_id,
                        data["subject_type"],
                        data["prompt"],
                        data["negative_prompt"],
                        data["sort_order"],
                        now,
                        now,
                    ),
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                raise ValueError("같은 이름의 프리셋 또는 태그가 이미 있습니다.") from exc
        return self.get_presets([preset_id])[0]

    def update_preset(self, preset_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        normalized = normalize_tag(data["tag_name"])
        with self._write_lock, self.connect() as connection:
            current = connection.execute(
                "SELECT tag_id FROM character_presets WHERE id=?", (preset_id,)
            ).fetchone()
            if not current:
                return None
            conflict = connection.execute(
                "SELECT id FROM tags WHERE normalized=? AND id<>?",
                (normalized, current["tag_id"]),
            ).fetchone()
            if conflict:
                raise ValueError("같은 이름의 태그가 이미 있습니다.")
            try:
                connection.execute(
                    "UPDATE tags SET name=?, normalized=? WHERE id=?",
                    (data["tag_name"], normalized, current["tag_id"]),
                )
                connection.execute(
                    """UPDATE character_presets SET name=?,subject_type=?,prompt=?,negative_prompt=?,
                       sort_order=?,updated_at=? WHERE id=?""",
                    (
                        data["name"],
                        data["subject_type"],
                        data["prompt"],
                        data["negative_prompt"],
                        data["sort_order"],
                        iso(),
                        preset_id,
                    ),
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                raise ValueError("같은 이름의 프리셋이 이미 있습니다.") from exc
        rows = self.get_presets([preset_id])
        return rows[0] if rows else None

    def delete_preset(self, preset_id: str) -> bool:
        with self._write_lock, self.connect() as connection:
            cursor = connection.execute("DELETE FROM character_presets WHERE id=?", (preset_id,))
            connection.execute(
                """DELETE FROM character_sets WHERE (
                       SELECT COUNT(*) FROM character_set_members m WHERE m.set_id=character_sets.id
                   ) < 2"""
            )
            connection.commit()
            return cursor.rowcount > 0

    @staticmethod
    def _validate_character_set_members(
        connection: sqlite3.Connection, preset_ids: Sequence[str]
    ) -> None:
        if len(preset_ids) < 2:
            raise ValueError("인물 세트에는 서로 다른 인물이 2명 이상 필요합니다.")
        if len(preset_ids) > 22:
            raise ValueError("인물 세트에는 최대 22명까지 저장할 수 있습니다.")
        if len(set(preset_ids)) != len(preset_ids):
            raise ValueError("인물 세트에 같은 인물을 중복으로 넣을 수 없습니다.")
        placeholders = ",".join("?" for _ in preset_ids)
        count = connection.execute(
            f"SELECT COUNT(*) FROM character_presets WHERE id IN ({placeholders})",
            tuple(preset_ids),
        ).fetchone()[0]
        if count != len(preset_ids):
            raise ValueError("선택한 인물 프리셋 중 일부가 없습니다.")

    def _decorate_character_set(
        self, connection: sqlite3.Connection, row: sqlite3.Row
    ) -> dict[str, Any]:
        item = dict(row)
        members = connection.execute(
            """SELECT p.id,p.name,p.tag_id,t.name AS tag_name,m.position
               FROM character_set_members m
               JOIN character_presets p ON p.id=m.preset_id
               JOIN tags t ON t.id=p.tag_id
               WHERE m.set_id=? ORDER BY m.position""",
            (item["id"],),
        ).fetchall()
        item["members"] = [dict(member) for member in members]
        item["preset_ids"] = [member["id"] for member in members]
        return item

    def list_character_sets(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM character_sets ORDER BY name COLLATE NOCASE"
            ).fetchall()
            return [self._decorate_character_set(connection, row) for row in rows]

    def get_character_set(self, set_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM character_sets WHERE id=?", (set_id,)
            ).fetchone()
            return self._decorate_character_set(connection, row) if row else None

    def create_character_set(self, data: dict[str, Any]) -> dict[str, Any]:
        set_id = str(uuid.uuid4())
        now = iso()
        preset_ids = data["preset_ids"]
        with self._write_lock, self.connect() as connection:
            self._validate_character_set_members(connection, preset_ids)
            try:
                connection.execute(
                    "INSERT INTO character_sets(id,name,created_at,updated_at) VALUES(?,?,?,?)",
                    (set_id, data["name"], now, now),
                )
                connection.executemany(
                    "INSERT INTO character_set_members(set_id,preset_id,position) VALUES(?,?,?)",
                    [(set_id, preset_id, index) for index, preset_id in enumerate(preset_ids)],
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                raise ValueError("같은 이름의 인물 세트가 이미 있습니다.") from exc
        return self.get_character_set(set_id)  # type: ignore[return-value]

    def update_character_set(
        self, set_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        preset_ids = data["preset_ids"]
        with self._write_lock, self.connect() as connection:
            if not connection.execute(
                "SELECT 1 FROM character_sets WHERE id=?", (set_id,)
            ).fetchone():
                return None
            self._validate_character_set_members(connection, preset_ids)
            try:
                connection.execute(
                    "UPDATE character_sets SET name=?,updated_at=? WHERE id=?",
                    (data["name"], iso(), set_id),
                )
                connection.execute(
                    "DELETE FROM character_set_members WHERE set_id=?", (set_id,)
                )
                connection.executemany(
                    "INSERT INTO character_set_members(set_id,preset_id,position) VALUES(?,?,?)",
                    [(set_id, preset_id, index) for index, preset_id in enumerate(preset_ids)],
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                raise ValueError("같은 이름의 인물 세트가 이미 있습니다.") from exc
        return self.get_character_set(set_id)

    def delete_character_set(self, set_id: str) -> bool:
        with self._write_lock, self.connect() as connection:
            cursor = connection.execute("DELETE FROM character_sets WHERE id=?", (set_id,))
            connection.commit()
            return cursor.rowcount > 0

    def list_discord_webhooks(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM discord_webhooks ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_discord_webhook(self, webhook_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM discord_webhooks WHERE id=?", (webhook_id,)
            ).fetchone()
        return self._row(row)

    def create_discord_webhook(self, name: str) -> dict[str, Any]:
        webhook_id = str(uuid.uuid4())
        now = iso()
        with self._write_lock, self.connect() as connection:
            try:
                connection.execute(
                    "INSERT INTO discord_webhooks(id,name,created_at,updated_at) VALUES(?,?,?,?)",
                    (webhook_id, name, now, now),
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                raise ValueError("같은 이름의 Discord 웹훅이 이미 있습니다.") from exc
        return self.get_discord_webhook(webhook_id)  # type: ignore[return-value]

    def update_discord_webhook(
        self, webhook_id: str, name: str
    ) -> dict[str, Any] | None:
        with self._write_lock, self.connect() as connection:
            try:
                cursor = connection.execute(
                    "UPDATE discord_webhooks SET name=?,updated_at=? WHERE id=?",
                    (name, iso(), webhook_id),
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                raise ValueError("같은 이름의 Discord 웹훅이 이미 있습니다.") from exc
        if cursor.rowcount == 0:
            return None
        return self.get_discord_webhook(webhook_id)

    def delete_discord_webhook(self, webhook_id: str) -> bool:
        with self._write_lock, self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM discord_webhooks WHERE id=?", (webhook_id,)
            )
            connection.commit()
            return cursor.rowcount > 0

    @staticmethod
    def _public_device(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        item = dict(row)
        item.pop("credential_hash", None)
        return item

    def request_device_approval(
        self,
        device_id: str,
        display_name: str,
        credential_hash: str,
        remote_address: str,
        user_agent: str,
    ) -> dict[str, Any]:
        now = iso()
        with self._write_lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO device_approvals
                   (device_id,display_name,credential_hash,status,requested_at,
                    decided_at,approved_at,last_seen_at,last_address,user_agent)
                   VALUES(?,?,?,'pending',?,NULL,NULL,NULL,?,?)
                   ON CONFLICT(device_id) DO UPDATE SET
                     display_name=excluded.display_name,
                     credential_hash=excluded.credential_hash,
                     status='pending',
                     requested_at=excluded.requested_at,
                     decided_at=NULL,
                     approved_at=NULL,
                     last_seen_at=NULL,
                     last_address=excluded.last_address,
                     user_agent=excluded.user_agent""",
                (
                    device_id,
                    display_name,
                    credential_hash,
                    now,
                    remote_address,
                    user_agent[:500],
                ),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM device_approvals WHERE device_id=?", (device_id,)
            ).fetchone()
        return self._public_device(row)  # type: ignore[return-value]

    def get_device_approval(self, device_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM device_approvals WHERE device_id=?", (device_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_device_approvals(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM device_approvals
                   WHERE status IN ('pending','approved')
                   ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END,
                            requested_at DESC"""
            ).fetchall()
        return [self._public_device(row) for row in rows]  # type: ignore[misc]

    def count_pending_device_approvals(self, requested_after: str) -> int:
        with self.connect() as connection:
            return int(
                connection.execute(
                    """SELECT COUNT(*) FROM device_approvals
                       WHERE status='pending' AND requested_at>=?""",
                    (requested_after,),
                ).fetchone()[0]
            )

    def decide_device_approval(
        self,
        device_id: str,
        status: str,
        requested_after: str | None = None,
    ) -> dict[str, Any] | None:
        if status not in {"approved", "denied"}:
            raise ValueError("invalid device decision")
        now = iso()
        conditions = "device_id=? AND status='pending'"
        params: list[Any] = [device_id]
        if requested_after is not None:
            conditions += " AND requested_at>=?"
            params.append(requested_after)
        with self._write_lock, self.connect() as connection:
            cursor = connection.execute(
                f"""UPDATE device_approvals
                    SET status=?,decided_at=?,approved_at=?
                    WHERE {conditions}""",
                (
                    status,
                    now,
                    now if status == "approved" else None,
                    *params,
                ),
            )
            connection.commit()
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                "SELECT * FROM device_approvals WHERE device_id=?", (device_id,)
            ).fetchone()
        return self._public_device(row)

    def revoke_device_approval(self, device_id: str) -> bool:
        with self._write_lock, self.connect() as connection:
            cursor = connection.execute(
                """UPDATE device_approvals
                   SET status='revoked',decided_at=?
                   WHERE device_id=? AND status='approved'""",
                (iso(), device_id),
            )
            connection.commit()
            return cursor.rowcount > 0

    def touch_device_approval(
        self, device_id: str, remote_address: str, user_agent: str
    ) -> None:
        with self._write_lock, self.connect() as connection:
            connection.execute(
                """UPDATE device_approvals
                   SET last_seen_at=?,last_address=?,user_agent=?
                   WHERE device_id=? AND status='approved'""",
                (iso(), remote_address, user_agent[:500], device_id),
            )
            connection.commit()

    def list_quality_prompt_presets(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM quality_prompt_presets
                   ORDER BY sort_order, name COLLATE NOCASE"""
            ).fetchall()
        return [dict(row) for row in rows]

    def get_quality_prompt_preset(self, preset_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM quality_prompt_presets WHERE id=?", (preset_id,)
            ).fetchone()
        return self._row(row)

    def create_quality_prompt_preset(self, data: dict[str, Any]) -> dict[str, Any]:
        preset_id = str(uuid.uuid4())
        now = iso()
        with self._write_lock, self.connect() as connection:
            try:
                connection.execute(
                    """INSERT INTO quality_prompt_presets
                       (id,name,prompt,negative_prompt,sort_order,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?)""",
                    (
                        preset_id,
                        data["name"],
                        data["prompt"],
                        data.get("negative_prompt", ""),
                        data["sort_order"],
                        now,
                        now,
                    ),
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                raise ValueError("같은 이름의 품질 프롬프트 프리셋이 이미 있습니다.") from exc
        return self.get_quality_prompt_preset(preset_id)  # type: ignore[return-value]

    def update_quality_prompt_preset(
        self, preset_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        with self._write_lock, self.connect() as connection:
            try:
                cursor = connection.execute(
                    """UPDATE quality_prompt_presets
                       SET name=?,prompt=?,negative_prompt=?,sort_order=?,updated_at=? WHERE id=?""",
                    (
                        data["name"],
                        data["prompt"],
                        data.get("negative_prompt", ""),
                        data["sort_order"],
                        iso(),
                        preset_id,
                    ),
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                raise ValueError("같은 이름의 품질 프롬프트 프리셋이 이미 있습니다.") from exc
        if cursor.rowcount == 0:
            return None
        return self.get_quality_prompt_preset(preset_id)

    def delete_quality_prompt_preset(self, preset_id: str) -> bool:
        with self._write_lock, self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM quality_prompt_presets WHERE id=?", (preset_id,)
            )
            connection.commit()
            return cursor.rowcount > 0

    def create_job(self, request_data: dict[str, Any], correlation_id: str) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        now = iso()
        with self._write_lock, self.connect() as connection:
            active = connection.execute(
                "SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')"
            ).fetchone()[0]
            if active >= 10:
                raise OverflowError("생성 대기열이 가득 찼습니다.")
            position = connection.execute(
                "SELECT COUNT(*) FROM jobs WHERE status='queued'"
            ).fetchone()[0] + 1
            connection.execute(
                """INSERT INTO jobs(id,mode,status,request_json,queue_position,correlation_id,created_at)
                   VALUES(?,?, 'queued', ?,?,?,?)""",
                (job_id, request_data["mode"], json.dumps(request_data, ensure_ascii=False), position, correlation_id, now),
            )
            connection.commit()
        return self.get_job(job_id)  # type: ignore[return-value]

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        result = self._row(row)
        if result:
            result["request"] = json.loads(result.pop("request_json"))
        return result

    def list_jobs(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY CASE WHEN status IN ('queued','running') THEN 0 ELSE 1 END, created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["request"] = json.loads(item.pop("request_json"))
            result.append(item)
        return result

    def active_job_count(self) -> int:
        with self.connect() as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')"
                ).fetchone()[0]
            )

    def set_job_running(self, job_id: str) -> bool:
        with self._write_lock, self.connect() as connection:
            cursor = connection.execute(
                "UPDATE jobs SET status='running',started_at=?,queue_position=NULL WHERE id=? AND status='queued'",
                (iso(), job_id),
            )
            connection.execute(
                """WITH ranked AS (SELECT id, ROW_NUMBER() OVER (ORDER BY created_at) AS n
                   FROM jobs WHERE status='queued')
                   UPDATE jobs SET queue_position=(SELECT n FROM ranked WHERE ranked.id=jobs.id)
                   WHERE status='queued'"""
            )
            connection.commit()
            return cursor.rowcount > 0

    def update_job_progress(self, job_id: str, output_count: int, completed_requests: int) -> None:
        with self._write_lock, self.connect() as connection:
            connection.execute(
                "UPDATE jobs SET output_count=?,completed_requests=? WHERE id=?",
                (output_count, completed_requests, job_id),
            )
            connection.commit()

    def request_job_stop(self, job_id: str) -> bool:
        """Cancel a queued job, or stop remaining rounds after the in-flight call."""
        with self._write_lock, self.connect() as connection:
            row = connection.execute("SELECT status,request_json FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                return False
            if row["status"] == "queued":
                connection.execute(
                    "UPDATE jobs SET status='cancelled',cancel_requested=1,finished_at=?,queue_position=NULL WHERE id=?",
                    (iso(), job_id),
                )
            elif row["status"] == "running" and json.loads(row["request_json"]).get("repeat_count", 1) > 1:
                connection.execute("UPDATE jobs SET cancel_requested=1 WHERE id=?", (job_id,))
            else:
                return False
            connection.commit()
            return True

    def finish_job(
        self,
        job_id: str,
        status: str,
        output_count: int = 0,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        with self._write_lock, self.connect() as connection:
            connection.execute(
                """UPDATE jobs SET status=?,output_count=?,error_code=?,error_message=?,finished_at=?
                   WHERE id=?""",
                (status, output_count, error_code, error_message, iso(), job_id),
            )
            connection.commit()

    def cancel_queued_job(self, job_id: str) -> bool:
        with self._write_lock, self.connect() as connection:
            cursor = connection.execute(
                """UPDATE jobs SET status='cancelled',finished_at=?,queue_position=NULL
                   WHERE id=? AND status='queued'""",
                (iso(), job_id),
            )
            connection.commit()
            return cursor.rowcount > 0

    def create_upload(
        self,
        upload_id: str,
        file_path: str,
        thumbnail_path: str | None,
        original_name: str,
        mime_type: str,
        width: int,
        height: int,
    ) -> dict[str, Any]:
        created = utc_now()
        with self._write_lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO uploads
                   (id,file_path,thumbnail_path,original_name,mime_type,width,height,created_at,expires_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    upload_id,
                    file_path,
                    thumbnail_path,
                    original_name,
                    mime_type,
                    width,
                    height,
                    iso(created),
                    iso(created + timedelta(hours=168)),
                ),
            )
            connection.commit()
        return self.get_upload(upload_id)  # type: ignore[return-value]

    def get_vibe_encoding(self, cache_key: str) -> bytes | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT data FROM vibe_encodings WHERE cache_key=?", (cache_key,)
            ).fetchone()
        return bytes(row["data"]) if row else None

    def save_vibe_encoding(
        self, cache_key: str, model: str, information_extracted: float, data: bytes
    ) -> None:
        with self._write_lock, self.connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO vibe_encodings
                   (cache_key,model,information_extracted,data,created_at) VALUES(?,?,?,?,?)""",
                (cache_key, model, information_extracted, data, iso()),
            )
            connection.commit()

    def get_upload(self, upload_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            return self._row(connection.execute("SELECT * FROM uploads WHERE id=?", (upload_id,)).fetchone())

    def list_uploads(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM uploads ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]

    def create_mask(self, mask_id: str, file_path: str, source_asset_id: str) -> None:
        with self._write_lock, self.connect() as connection:
            connection.execute(
                "INSERT INTO masks(id,file_path,source_asset_id,created_at) VALUES(?,?,?,?)",
                (mask_id, file_path, source_asset_id, iso()),
            )
            connection.commit()

    def get_mask(self, mask_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            return self._row(connection.execute("SELECT * FROM masks WHERE id=?", (mask_id,)).fetchone())

    def delete_mask(self, mask_id: str) -> dict[str, Any] | None:
        with self._write_lock, self.connect() as connection:
            row = connection.execute("SELECT * FROM masks WHERE id=?", (mask_id,)).fetchone()
            connection.execute("DELETE FROM masks WHERE id=?", (mask_id,))
            connection.commit()
        return self._row(row)

    def orphan_masks(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT m.* FROM masks m WHERE NOT EXISTS (
                   SELECT 1 FROM jobs j WHERE j.status IN ('queued','running')
                   AND json_extract(j.request_json,'$.mask_asset_id')=m.id
                   )"""
            ).fetchall()
        return [dict(row) for row in rows]

    def create_image(self, data: dict[str, Any], tag_ids: Sequence[str]) -> dict[str, Any]:
        image_id = data["id"]
        with self._write_lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO images
                   (id,job_id,parent_image_id,file_path,thumbnail_path,mime_type,width,height,mode,model,
                    prompt,quality_prompt,description_prompt,quality_negative_prompt,
                    description_negative_prompt,negative_prompt,settings_json,
                    character_snapshot_json,seed,created_at,expires_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    image_id,
                    data["job_id"],
                    data.get("parent_image_id"),
                    data["file_path"],
                    data.get("thumbnail_path"),
                    data["mime_type"],
                    data["width"],
                    data["height"],
                    data["mode"],
                    data["model"],
                    data["prompt"],
                    data.get("quality_prompt", ""),
                    data.get("description_prompt", data["prompt"]),
                    data.get("quality_negative_prompt", data.get("negative_prompt", "")),
                    data.get("description_negative_prompt", ""),
                    data["negative_prompt"],
                    json.dumps(data["settings"], ensure_ascii=False),
                    json.dumps(data["character_snapshot"], ensure_ascii=False),
                    data.get("seed"),
                    data["created_at"],
                    data["expires_at"],
                ),
            )
            connection.executemany(
                "INSERT OR IGNORE INTO image_tags(image_id,tag_id) VALUES(?,?)",
                [(image_id, tag_id) for tag_id in tag_ids],
            )
            local_date = datetime.fromisoformat(data["created_at"]).astimezone().date().isoformat()
            connection.execute(
                """INSERT INTO daily_statistics(local_date,mode,count) VALUES(?,?,1)
                   ON CONFLICT(local_date,mode) DO UPDATE SET count=count+1""",
                (local_date, data["mode"]),
            )
            connection.commit()
        return self.get_image(image_id)  # type: ignore[return-value]

    def _decorate_image(self, connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        tags = connection.execute(
            """SELECT t.id,t.name FROM image_tags it JOIN tags t ON t.id=it.tag_id
               WHERE it.image_id=? ORDER BY t.name COLLATE NOCASE""",
            (item["id"],),
        ).fetchall()
        item["tags"] = [dict(tag) for tag in tags]
        item["settings"] = json.loads(item.pop("settings_json"))
        item["character_snapshot"] = json.loads(item.pop("character_snapshot_json"))
        return item

    def get_image(self, image_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM images WHERE id=?", (image_id,)).fetchone()
            return self._decorate_image(connection, row) if row else None

    def list_images(
        self,
        favorite: bool | None,
        tag_ids: Sequence[str],
        page: int,
        nsfw: bool | None = None,
        page_size: int = 50,
    ) -> dict[str, Any]:
        conditions: list[str] = []
        params: list[Any] = []
        if favorite is True:
            conditions.append("i.favorite_at IS NOT NULL")
        elif favorite is False:
            conditions.append("i.favorite_at IS NULL")
        for tag_id in tag_ids:
            conditions.append("EXISTS (SELECT 1 FROM image_tags f WHERE f.image_id=i.id AND f.tag_id=?)")
            params.append(tag_id)
        if nsfw is not None:
            conditions.append(
                "COALESCE(json_extract(i.settings_json,'$.nsfw_enabled'),0)=?"
            )
            params.append(1 if nsfw else 0)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        offset = max(page - 1, 0) * page_size
        with self.connect() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM images i {where}", tuple(params)
            ).fetchone()[0]
            rows = connection.execute(
                f"SELECT i.* FROM images i {where} ORDER BY i.created_at DESC LIMIT ? OFFSET ?",
                (*params, page_size, offset),
            ).fetchall()
            items = [self._decorate_image(connection, row) for row in rows]
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def favorite_tag_counts(self, nsfw: bool | None = None) -> list[dict[str, Any]]:
        nsfw_condition = ""
        params: tuple[Any, ...] = ()
        if nsfw is not None:
            nsfw_condition = (
                " AND COALESCE(json_extract(i.settings_json,'$.nsfw_enabled'),0)=?"
            )
            params = (1 if nsfw else 0,)
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT t.id,t.name,COUNT(*) AS count FROM tags t
                   JOIN image_tags it ON it.tag_id=t.id JOIN images i ON i.id=it.image_id
                   WHERE i.favorite_at IS NOT NULL"""
                + nsfw_condition
                + """ GROUP BY t.id,t.name
                   ORDER BY t.name COLLATE NOCASE""",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def set_favorite_paths(
        self, image_id: str, favorite: bool, file_path: str, thumbnail_path: str | None
    ) -> dict[str, Any] | None:
        now = utc_now()
        with self._write_lock, self.connect() as connection:
            current = connection.execute("SELECT id FROM images WHERE id=?", (image_id,)).fetchone()
            if not current:
                return None
            if favorite:
                connection.execute(
                    """UPDATE images SET favorite_at=?,expires_at=NULL,file_path=?,thumbnail_path=?,cleanup_error=NULL
                       WHERE id=?""",
                    (iso(now), file_path, thumbnail_path, image_id),
                )
            else:
                connection.execute(
                    """UPDATE images SET favorite_at=NULL,expires_at=?,file_path=?,thumbnail_path=?,cleanup_error=NULL
                       WHERE id=?""",
                    (iso(now + timedelta(hours=168)), file_path, thumbnail_path, image_id),
                )
            connection.commit()
        return self.get_image(image_id)

    def delete_image_record(self, image_id: str) -> bool:
        with self._write_lock, self.connect() as connection:
            cursor = connection.execute("DELETE FROM images WHERE id=?", (image_id,))
            connection.commit()
            return cursor.rowcount > 0

    def expired_images(self, now_value: datetime | None = None) -> list[dict[str, Any]]:
        cutoff = iso(now_value)
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT i.* FROM images i WHERE i.favorite_at IS NULL AND i.expires_at<=?
                   AND NOT EXISTS (
                     SELECT 1 FROM jobs j WHERE j.status='running' AND
                     json_extract(j.request_json,'$.source_asset_id')=i.id
                   )""",
                (cutoff,),
            ).fetchall()
        return [dict(row) for row in rows]

    def expired_uploads(self, now_value: datetime | None = None) -> list[dict[str, Any]]:
        cutoff = iso(now_value)
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT u.* FROM uploads u WHERE u.expires_at<=?
                   AND NOT EXISTS (
                     SELECT 1 FROM jobs j WHERE j.status='running' AND
                     json_extract(j.request_json,'$.source_asset_id')=u.id
                   )""",
                (cutoff,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_upload_record(self, upload_id: str) -> bool:
        with self._write_lock, self.connect() as connection:
            cursor = connection.execute("DELETE FROM uploads WHERE id=?", (upload_id,))
            connection.commit()
            return cursor.rowcount > 0

    def mark_cleanup_error(self, table: str, item_id: str, message: str) -> None:
        if table not in {"images", "uploads"}:
            raise ValueError("invalid cleanup table")
        with self._write_lock, self.connect() as connection:
            connection.execute(
                f"UPDATE {table} SET cleanup_error=? WHERE id=?", (message[:500], item_id)
            )
            connection.commit()

    def statistics(self) -> dict[str, Any]:
        today = datetime.now().astimezone().date()
        start = today - timedelta(days=6)
        with self.connect() as connection:
            total = connection.execute("SELECT COALESCE(SUM(count),0) FROM daily_statistics").fetchone()[0]
            today_count = connection.execute(
                "SELECT COALESCE(SUM(count),0) FROM daily_statistics WHERE local_date=?",
                (today.isoformat(),),
            ).fetchone()[0]
            recent_total = connection.execute(
                "SELECT COALESCE(SUM(count),0) FROM daily_statistics WHERE local_date>=?",
                (start.isoformat(),),
            ).fetchone()[0]
            temporary = connection.execute(
                "SELECT COUNT(*) FROM images i WHERE i.favorite_at IS NULL"
            ).fetchone()[0]
            favorites = connection.execute(
                "SELECT COUNT(*) FROM images i WHERE i.favorite_at IS NOT NULL"
            ).fetchone()[0]
            rows = connection.execute(
                """SELECT local_date,SUM(count) AS count FROM daily_statistics
                   WHERE local_date>=? GROUP BY local_date ORDER BY local_date""",
                (start.isoformat(),),
            ).fetchall()
        by_date = {row["local_date"]: row["count"] for row in rows}
        daily = []
        for index in range(7):
            day = start + timedelta(days=index)
            daily.append({"date": day.isoformat(), "count": by_date.get(day.isoformat(), 0)})
        return {
            "lifetime": total,
            "today": today_count,
            "last_7_days": recent_total,
            "temporary": temporary,
            "favorites": favorites,
            "daily": daily,
        }

    def get_app_setting(self, key: str) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value FROM app_settings WHERE key=?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def set_app_setting(self, key: str, value: str) -> None:
        with self._write_lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO app_settings(key,value) VALUES(?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (key, value),
            )
            connection.commit()

    def set_app_settings(self, values: dict[str, str]) -> None:
        with self._write_lock, self.connect() as connection:
            connection.executemany(
                """INSERT INTO app_settings(key,value) VALUES(?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                list(values.items()),
            )
            connection.commit()

    def latest_generation_draft(self) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT request_json FROM jobs ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        try:
            request = json.loads(row["request_json"])
        except (TypeError, json.JSONDecodeError):
            return None
        selected_ids = list(request.get("character_preset_ids") or [])
        if not selected_ids:
            selected_ids = self.latest_nonempty_character_preset_ids()
        return {
            "quality_prompt": str(request.get("quality_prompt") or ""),
            "description_prompt": str(
                request.get("description_prompt") or request.get("prompt") or ""
            ),
            "quality_preset_id": request.get("quality_preset_id"),
            "quality_negative_prompt": str(
                request.get("quality_negative_prompt")
                or request.get("negative_prompt")
                or ""
            ),
            "description_negative_prompt": str(
                request.get("description_negative_prompt") or ""
            ),
            "nsfw_enabled": bool(request.get("nsfw_enabled")),
            "character_preset_ids": selected_ids,
            "model": str(request.get("model") or "nai-diffusion-5-full"),
            "parameters": request.get("parameters") or {},
        }

    def latest_nonempty_character_preset_ids(self) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT request_json FROM jobs ORDER BY created_at DESC"
            ).fetchall()
        for row in rows:
            try:
                request = json.loads(row["request_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            selected = request.get("character_preset_ids") or []
            if isinstance(selected, list) and selected:
                return [str(item) for item in selected]
        return []

    def all_favorites(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT i.* FROM images i WHERE i.favorite_at IS NOT NULL
                   ORDER BY i.created_at DESC"""
            ).fetchall()
            return [self._decorate_image(connection, row) for row in rows]
