from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import uuid
import zipfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

from .config import MAX_IMAGE_DIMENSION, MAX_UPLOAD_BYTES, AppPaths


MIME_TO_EXTENSION = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
STORAGE_MARKER_NAME = ".novelai-lan-studio-storage"
STORAGE_LOGICAL_PREFIX = ("data", "assets")


class ImageValidationError(ValueError):
    pass


class StorageLocationError(ValueError):
    pass


class StorageUnavailableError(StorageLocationError):
    pass


class StorageBusyError(RuntimeError):
    pass


class StorageActivityGate:
    """Do not hold a thread lock over async work; reserve operations instead."""

    def __init__(self):
        self._lock = threading.Lock()
        self._active = 0
        self._moving = False

    @contextmanager
    def activity(self):
        with self._lock:
            if self._moving:
                raise StorageBusyError("이미지 저장 폴더를 이동 중입니다. 이동이 끝난 뒤 다시 시도해 주세요.")
            self._active += 1
        try:
            yield
        finally:
            with self._lock:
                self._active -= 1

    @contextmanager
    def migration(self):
        with self._lock:
            if self._moving or self._active:
                raise StorageBusyError("진행 중인 작업이 끝난 뒤 저장 폴더를 변경해 주세요.")
            self._moving = True
        try:
            yield
        finally:
            with self._lock:
                self._moving = False


@dataclass(frozen=True)
class PreparedStorageMigration:
    source_root: Path
    target_root: Path
    files: tuple[tuple[Path, int], ...]


class ImageStorage:
    def __init__(self, paths: AppPaths, root: Path | None = None, *, initialize: bool = True):
        self.paths = paths
        self.paths.ensure()
        self.root = (root or self.paths.assets).expanduser().resolve()
        if self.root.parent == self.root:
            raise StorageLocationError("드라이브 루트는 이미지 저장 폴더로 사용할 수 없습니다.")
        self.temporary = self.root / "temporary"
        self.favorites = self.root / "favorites"
        self.uploads = self.root / "uploads"
        self.thumbnails = self.root / "thumbnails"
        self.masks = self.root / "masks"
        if not initialize:
            return
        for path in (
            self.temporary,
            self.favorites,
            self.uploads,
            self.thumbnails / "temporary",
            self.thumbnails / "favorites",
            self.thumbnails / "uploads",
            self.masks,
        ):
            path.mkdir(parents=True, exist_ok=True)
        if self.root != self.paths.assets.resolve():
            (self.root / STORAGE_MARKER_NAME).touch(exist_ok=True)

    @property
    def available(self) -> bool:
        return self.root.is_dir()

    def ensure_available(self) -> None:
        if not self.available:
            raise StorageUnavailableError("지정된 이미지 저장 폴더에 접근할 수 없습니다. 드라이브 연결과 폴더 접근 권한을 확인해 주세요.")

    def relative(self, path: Path) -> str:
        logical = path.resolve().relative_to(self.root).as_posix()
        return "/".join((*STORAGE_LOGICAL_PREFIX, logical))

    def absolute(self, relative: str) -> Path:
        self.ensure_available()
        logical = PurePosixPath(relative)
        parts = logical.parts
        if logical.is_absolute() or ".." in parts:
            raise ValueError("올바르지 않은 이미지 저장 경로입니다.")
        if parts[:2] == STORAGE_LOGICAL_PREFIX:
            parts = parts[2:]
        if not parts:
            raise ValueError("비어 있는 이미지 저장 경로입니다.")
        candidate = self.root.joinpath(*parts).resolve()
        root = self.root.resolve()
        if root != candidate and root not in candidate.parents:
            raise ValueError("저장 경로가 이미지 저장 폴더를 벗어났습니다.")
        return candidate

    @staticmethod
    def normalize_root(directory: str | Path) -> Path:
        raw = str(directory).strip()
        if not raw:
            raise StorageLocationError("이미지 저장 폴더를 입력해 주세요.")
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            raise StorageLocationError("이미지 저장 폴더는 절대 경로로 입력해 주세요.")
        resolved = candidate.resolve(strict=False)
        if resolved.parent == resolved:
            raise StorageLocationError("드라이브 루트는 이미지 저장 폴더로 사용할 수 없습니다.")
        return resolved

    @staticmethod
    def _manifest(root: Path) -> tuple[tuple[Path, int], ...]:
        if not root.exists():
            return ()
        if not root.is_dir() or root.is_symlink():
            raise StorageLocationError("이미지 저장 경로는 일반 폴더여야 합니다.")
        files: list[tuple[Path, int]] = []
        for item in root.rglob("*"):
            if item.is_symlink():
                raise StorageLocationError("심볼릭 링크가 포함된 폴더는 사용할 수 없습니다.")
            if item.is_file() and item.name != STORAGE_MARKER_NAME:
                files.append((item.relative_to(root), item.stat().st_size))
        return tuple(sorted(files, key=lambda entry: entry[0].as_posix()))

    @staticmethod
    def _remove_empty_location(root: Path) -> None:
        if not root.exists():
            return
        files = ImageStorage._manifest(root)
        if files:
            raise StorageLocationError("선택한 폴더가 비어 있지 않습니다. 빈 폴더를 선택해 주세요.")
        (root / STORAGE_MARKER_NAME).unlink(missing_ok=True)
        directories = sorted(
            (item for item in root.rglob("*") if item.is_dir()),
            key=lambda item: len(item.parts),
            reverse=True,
        )
        for directory in directories:
            directory.rmdir()
        root.rmdir()

    def prepare_migration(self, directory: str | Path) -> PreparedStorageMigration | None:
        self.ensure_available()
        source = self.root.resolve()
        target = self.normalize_root(directory)
        if target == source:
            return None
        if source in target.parents or target in source.parents:
            raise StorageLocationError("현재 저장 폴더와 서로 포함되는 경로는 선택할 수 없습니다.")
        if target.exists():
            self._manifest(target)
            if self._manifest(target):
                raise StorageLocationError("선택한 폴더가 비어 있지 않습니다. 빈 폴더를 선택해 주세요.")

        target.parent.mkdir(parents=True, exist_ok=True)
        files = self._manifest(source)
        required_bytes = sum(size for _, size in files)
        free_bytes = shutil.disk_usage(target.parent).free
        if free_bytes < required_bytes + 16 * 1024 * 1024:
            raise StorageLocationError("선택한 드라이브의 여유 공간이 부족합니다.")

        staging = target.parent / f".{target.name}.novelai-migrate-{uuid.uuid4().hex}"
        try:
            if source.exists():
                shutil.copytree(source, staging)
            else:
                staging.mkdir(parents=True)
            (staging / STORAGE_MARKER_NAME).touch(exist_ok=True)
            for relative, size in files:
                copied = staging / relative
                if not copied.is_file() or copied.stat().st_size != size:
                    raise OSError(f"복사 검증 실패: {relative.as_posix()}")
            if target.exists():
                self._remove_empty_location(target)
            os.replace(staging, target)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            raise
        return PreparedStorageMigration(source, target, files)

    @staticmethod
    def _remove_migrated_files(root: Path, files: tuple[tuple[Path, int], ...]) -> str | None:
        issues: list[str] = []
        for relative, expected_size in files:
            path = root / relative
            try:
                if not path.exists():
                    continue
                if not path.is_file() or path.stat().st_size != expected_size:
                    issues.append(relative.as_posix())
                    continue
                path.unlink()
            except OSError:
                issues.append(relative.as_posix())
        try:
            (root / STORAGE_MARKER_NAME).unlink(missing_ok=True)
        except OSError:
            issues.append(STORAGE_MARKER_NAME)
        if root.exists():
            directories = sorted(
                (item for item in root.rglob("*") if item.is_dir()),
                key=lambda item: len(item.parts),
                reverse=True,
            )
            for directory in directories:
                try:
                    directory.rmdir()
                except OSError:
                    pass
            try:
                root.rmdir()
            except OSError:
                pass
        if root.exists():
            issues.append("남은 파일")
        if not issues:
            return None
        return "이전 저장 폴더 일부를 정리하지 못했습니다. 파일은 새 폴더에 정상 복사되었습니다."

    @classmethod
    def rollback_migration(cls, migration: PreparedStorageMigration) -> None:
        cls._remove_migrated_files(migration.target_root, migration.files)

    @classmethod
    def finalize_migration(cls, migration: PreparedStorageMigration) -> str | None:
        return cls._remove_migrated_files(migration.source_root, migration.files)

    @staticmethod
    def _atomic_write(destination: Path, data: bytes) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".part", dir=destination.parent
        )
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, destination)
        except Exception:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise

    @staticmethod
    def inspect(data: bytes, *, upload: bool = False) -> tuple[str, int, int]:
        if upload and len(data) > MAX_UPLOAD_BYTES:
            raise ImageValidationError("업로드 파일은 최대 20MB까지 가능합니다.")
        try:
            with Image.open(io.BytesIO(data)) as image:
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
                format_name = (image.format or "").upper()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ImageValidationError("정상적인 이미지 파일이 아닙니다.") from exc
        if width < 1 or height < 1 or width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
            raise ImageValidationError("이미지 크기는 최대 8192×8192까지 가능합니다.")
        mime = {
            "PNG": "image/png",
            "JPEG": "image/jpeg",
            "WEBP": "image/webp",
        }.get(format_name)
        if not mime:
            raise ImageValidationError("PNG, JPEG, WebP 이미지만 사용할 수 있습니다.")
        return mime, width, height

    def _thumbnail(self, data: bytes, destination: Path) -> None:
        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((640, 640), Image.Resampling.LANCZOS)
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA")
            buffer = io.BytesIO()
            image.save(buffer, "WEBP", quality=82, method=4)
        self._atomic_write(destination, buffer.getvalue())

    def save_upload(self, data: bytes, original_name: str) -> dict[str, Any]:
        self.ensure_available()
        mime, width, height = self.inspect(data, upload=True)
        upload_id = str(uuid.uuid4())
        extension = MIME_TO_EXTENSION[mime]
        destination = self.uploads / f"{upload_id}{extension}"
        thumbnail = self.thumbnails / "uploads" / f"{upload_id}.webp"
        self._atomic_write(destination, data)
        try:
            self._thumbnail(data, thumbnail)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return {
            "id": upload_id,
            "file_path": self.relative(destination),
            "thumbnail_path": self.relative(thumbnail),
            "original_name": original_name,
            "mime_type": mime,
            "width": width,
            "height": height,
        }

    def save_mask(self, data: bytes, source_asset_id: str) -> dict[str, Any]:
        self.ensure_available()
        mime, width, height = self.inspect(data, upload=True)
        if mime != "image/png":
            raise ImageValidationError("인페인트 마스크는 PNG 형식이어야 합니다.")
        mask_id = str(uuid.uuid4())
        destination = self.masks / f"{mask_id}.png"
        self._atomic_write(destination, data)
        return {
            "id": mask_id,
            "file_path": self.relative(destination),
            "source_asset_id": source_asset_id,
            "width": width,
            "height": height,
        }

    def save_generated(self, data: bytes, image_id: str) -> dict[str, Any]:
        self.ensure_available()
        mime, width, height = self.inspect(data)
        extension = MIME_TO_EXTENSION[mime]
        destination = self.temporary / f"{image_id}{extension}"
        thumbnail = self.thumbnails / "temporary" / f"{image_id}.webp"
        self._atomic_write(destination, data)
        try:
            self._thumbnail(data, thumbnail)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return {
            "file_path": self.relative(destination),
            "thumbnail_path": self.relative(thumbnail),
            "mime_type": mime,
            "width": width,
            "height": height,
        }

    def move_favorite(self, image: dict[str, Any], favorite: bool) -> tuple[str, str | None]:
        current = self.absolute(image["file_path"])
        extension = current.suffix.lower()
        destination_root = self.favorites if favorite else self.temporary
        destination = destination_root / f"{image['id']}{extension}"

        current_thumb = self.absolute(image["thumbnail_path"]) if image.get("thumbnail_path") else None
        thumb_group = "favorites" if favorite else "temporary"
        destination_thumb = (
            self.thumbnails / thumb_group / f"{image['id']}.webp"
            if current_thumb
            else None
        )

        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination_thumb:
            destination_thumb.parent.mkdir(parents=True, exist_ok=True)

        moved_main = False
        try:
            if current != destination:
                os.replace(current, destination)
                moved_main = True
            if current_thumb and destination_thumb and current_thumb != destination_thumb:
                os.replace(current_thumb, destination_thumb)
        except Exception:
            if moved_main and destination.exists() and not current.exists():
                os.replace(destination, current)
            raise

        return self.relative(destination), self.relative(destination_thumb) if destination_thumb else None

    def delete_paths(self, *relative_paths: str | None) -> None:
        for relative in relative_paths:
            if not relative:
                continue
            path = self.absolute(relative)
            path.unlink(missing_ok=True)

    def read(self, relative: str) -> bytes:
        return self.absolute(relative).read_bytes()

    def build_favorites_zip(self, favorites: list[dict[str, Any]]) -> Path:
        handle, name = tempfile.mkstemp(prefix="novelai-favorites-", suffix=".zip")
        os.close(handle)
        destination = Path(name)
        manifest: list[dict[str, Any]] = []
        try:
            with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for index, image in enumerate(favorites, start=1):
                    source = self.absolute(image["file_path"])
                    extension = source.suffix.lower()
                    archive_name = f"images/{index:04d}_{image['id']}{extension}"
                    archive.write(source, archive_name)
                    manifest.append(
                        {
                            "file": archive_name,
                            "id": image["id"],
                            "created_at": image["created_at"],
                            "favorite_at": image["favorite_at"],
                            "mode": image["mode"],
                            "model": image["model"],
                            "prompt": image["prompt"],
                            "quality_prompt": image.get("quality_prompt", ""),
                            "description_prompt": image.get(
                                "description_prompt", image["prompt"]
                            ),
                            "negative_prompt": image["negative_prompt"],
                            "seed": image["seed"],
                            "tags": [tag["name"] for tag in image["tags"]],
                            "settings": image["settings"],
                        }
                    )
                archive.writestr(
                    "manifest.json",
                    json.dumps({"version": 2, "images": manifest}, ensure_ascii=False, indent=2),
                )
            return destination
        except Exception:
            destination.unlink(missing_ok=True)
            raise

    def copy_into_root(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
