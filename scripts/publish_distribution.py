from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.config import AppPaths  # noqa: E402
from backend.app.credentials import CredentialStore  # noqa: E402
from backend.app.database import Database  # noqa: E402
from backend.app.distribution import (  # noqa: E402
    DISCORD_SAFE_BATCH_BYTES,
    publish_distribution_files,
    split_file_for_discord,
)


VERSION = (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip()

ARTIFACT_NAMES = (
    "NovelAI-LAN-Studio.exe",
    f"NovelAI-LAN-Studio-Android-v{VERSION}.apk",
    "SHA256SUMS.txt",
)


def main() -> int:
    paths = AppPaths.from_environment()
    database = Database(paths.database)
    webhook_id = database.get_app_setting("distribution_webhook_id")
    if not webhook_id:
        print("Discord 배포 대상이 설정되지 않아 전송을 건너뜁니다.")
        return 0
    webhook = database.get_discord_webhook(webhook_id)
    webhook_url = CredentialStore().get_discord_webhook_url(webhook_id)
    if not webhook or not webhook_url:
        print("Discord 배포 대상의 자격 증명을 찾을 수 없습니다.", file=sys.stderr)
        return 2

    artifacts = [PROJECT_ROOT / "dist" / name for name in ARTIFACT_NAMES]
    missing = [path.name for path in artifacts if not path.is_file()]
    if missing:
        print(f"배포 파일이 없습니다: {', '.join(missing)}", file=sys.stderr)
        return 3

    try:
        exe_path, apk_path, checksum_path = artifacts
        with tempfile.TemporaryDirectory(prefix="novelai-distribution-") as temp_name:
            if exe_path.stat().st_size > DISCORD_SAFE_BATCH_BYTES:
                parts, join_script = split_file_for_discord(
                    exe_path, Path(temp_name)
                )
                delivery_files = [*parts, join_script, apk_path, checksum_path]
            else:
                delivery_files = artifacts
            published = asyncio.run(
                publish_distribution_files(webhook_url, delivery_files)
            )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 4
    print(f"Discord 배포 완료: {', '.join(published)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
