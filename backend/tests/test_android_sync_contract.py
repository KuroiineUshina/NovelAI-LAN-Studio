"""Exercise the exact Android conditional-update predicates with real SQLite."""
import re
import sqlite3
from pathlib import Path

SOURCE = (Path(__file__).parents[2] / "android/app/src/main/java/com/novelai/lanstudio/StandaloneDatabase.java").read_text(encoding="utf-8")


def selection(name):
    return re.search(rf'{name} = "([^"]+)";', SOURCE).group(1)


def test_image_upload_ack_cannot_clear_newer_favorite_change():
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE images(id TEXT PRIMARY KEY,file_path TEXT,favorite_at INTEGER,expires_at INTEGER,synced INTEGER)")
        db.execute("INSERT INTO images VALUES('image','favorites/image',123,NULL,0)")
        sql = "UPDATE images SET synced=1 WHERE " + selection("IMAGE_ACK_SELECTION")
        assert db.execute(sql, ("image", "temporary/image", None, "456")).rowcount == 0
        assert db.execute("SELECT synced FROM images").fetchone()[0] == 0
        assert db.execute(sql, ("image", "favorites/image", "123", None)).rowcount == 1
