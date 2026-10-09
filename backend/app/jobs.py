from __future__ import annotations

import asyncio
import copy
import hashlib
import logging
import secrets
import string
import uuid
from datetime import timedelta
from typing import Any

from .credentials import CredentialStore, CredentialStoreError
from .database import Database, iso, utc_now
from .novelai import NovelAIClient, NovelAIError, letterbox_reference
from .storage import ImageStorage, StorageActivityGate, StorageBusyError, StorageLocationError


logger = logging.getLogger(__name__)


def correlation_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(6))


class JobManager:
    def __init__(
        self,
        database: Database,
        storage: ImageStorage,
        credentials: CredentialStore,
        novelai_base_url: str | None = None,
        storage_gate: StorageActivityGate | None = None,
    ):
        self.database = database
        self.storage = storage
        self.credentials = credentials
        self.novelai_base_url = novelai_base_url
        self.storage_gate = storage_gate or StorageActivityGate()
        # Database.create_job limits active jobs to 10. Cancelled IDs may remain
        # until the long-running sequence ends; they must not block new POSTs.
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._cleanup_worker: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._worker = asyncio.create_task(self._run(), name="novelai-job-worker")
        self._cleanup_worker = asyncio.create_task(self._run_cleanup(), name="asset-cleanup-worker")
        await asyncio.to_thread(self.cleanup_once)

    async def stop(self) -> None:
        for task in (self._worker, self._cleanup_worker):
            if task:
                task.cancel()
        for task in (self._worker, self._cleanup_worker):
            if task:
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def enqueue(self, job_id: str) -> None:
        self.queue.put_nowait(job_id)

    async def _run(self) -> None:
        while True:
            job_id = await self.queue.get()
            try:
                job = await asyncio.to_thread(self.database.get_job, job_id)
                if not job or job["status"] != "queued":
                    continue
                if not await asyncio.to_thread(self.database.set_job_running, job_id):
                    continue
                await self._process(job_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Unhandled generation worker error for job %s", job_id)
                latest = await asyncio.to_thread(self.database.get_job, job_id)
                await asyncio.to_thread(
                    self.database.finish_job,
                    job_id,
                    "failed",
                    latest["output_count"] if latest else 0,
                    "INTERNAL",
                    "앱 내부 오류가 발생했습니다.",
                )
            finally:
                self.queue.task_done()

    def _resolve_source(self, asset_id: str | None) -> tuple[bytes | None, str | None]:
        if not asset_id:
            return None, None
        image = self.database.get_image(asset_id)
        if image:
            return self.storage.read(image["file_path"]), image["id"]
        upload = self.database.get_upload(asset_id)
        if upload:
            return self.storage.read(upload["file_path"]), None
        raise NovelAIError("SOURCE_MISSING", "원본 이미지가 없거나 보관 기간이 만료되었습니다.")

    def _resolve_reference(self, asset_id: str) -> bytes:
        try:
            image, _ = self._resolve_source(asset_id)
        except NovelAIError as exc:
            raise NovelAIError(
                "REFERENCE_MISSING", "레퍼런스 이미지가 없거나 보관 기간이 만료되었습니다."
            ) from exc
        return image or b""

    async def _prepare_references(
        self, client: NovelAIClient, request_data: dict[str, Any], correlation: str
    ) -> tuple[list[tuple[bytes, float]], list[dict[str, Any]]]:
        model = request_data["model"]
        vibes: list[tuple[bytes, float]] = []
        for item in request_data.get("vibe_references") or []:
            image = await asyncio.to_thread(self._resolve_reference, item["asset_id"])
            information_extracted = round(float(item.get("information_extracted", 1.0)), 4)
            cache_key = f"{hashlib.sha256(image).hexdigest()}:{model}:{information_extracted}"
            encoding = await asyncio.to_thread(self.database.get_vibe_encoding, cache_key)
            if encoding is None:
                # Each encode costs Anlas, so it is cached per image, model and IE value.
                encoding = await client.encode_vibe(image, information_extracted, model, correlation)
                await asyncio.to_thread(
                    self.database.save_vibe_encoding, cache_key, model, information_extracted, encoding
                )
            vibes.append((encoding, float(item.get("strength", 0.6))))
        references: list[dict[str, Any]] = []
        for item in request_data.get("character_references") or []:
            image = await asyncio.to_thread(self._resolve_reference, item["asset_id"])
            references.append(
                {
                    "image": await asyncio.to_thread(letterbox_reference, image),
                    "kind": item.get("kind") or "character&style",
                    "strength": float(item.get("strength", 1.0)),
                    "fidelity": float(item.get("fidelity", 1.0)),
                }
            )
        return vibes, references

    async def _process(self, job_id: str) -> None:
        with self.storage_gate.activity():
            await self._process_active(job_id)

    async def _process_active(self, job_id: str) -> None:
        job = await asyncio.to_thread(self.database.get_job, job_id)
        if not job or job["status"] not in {"queued", "running"}:
            return
        request_data = job["request"]
        mask_id = request_data.get("mask_asset_id")
        saved_count = 0
        try:
            self.storage.ensure_available()
            try:
                token = self.credentials.get_token()
            except CredentialStoreError as exc:
                raise NovelAIError("CREDENTIAL_STORE", str(exc)) from exc
            if not token:
                raise NovelAIError("TOKEN_MISSING", "PC 설정에서 NovelAI API 토큰을 먼저 등록해 주세요.")

            source, parent_image_id = await asyncio.to_thread(
                self._resolve_source, request_data.get("source_asset_id")
            )
            mask: bytes | None = None
            if mask_id:
                mask_record = await asyncio.to_thread(self.database.get_mask, mask_id)
                if not mask_record:
                    raise NovelAIError("MASK_MISSING", "인페인트 마스크가 없습니다.")
                if mask_record["source_asset_id"] != request_data.get("source_asset_id"):
                    raise NovelAIError("MASK_SOURCE_MISMATCH", "마스크와 원본 이미지가 일치하지 않습니다.")
                mask = await asyncio.to_thread(self.storage.read, mask_record["file_path"])

            client = NovelAIClient(token, self.novelai_base_url) if self.novelai_base_url else NovelAIClient(token)
            vibes, character_references = await self._prepare_references(
                client, request_data, job["correlation_id"]
            )
            repeat_count = request_data.get("repeat_count", 1)
            if not isinstance(repeat_count, int) or not 1 <= repeat_count <= 100:
                raise NovelAIError("REPEAT_COUNT", "연속 생성은 1~100회까지 가능합니다.")
            random_seed_each_request = request_data.get(
                "random_seed_each_request", request_data["parameters"].get("seed") is None
            )
            for request_index in range(repeat_count):
                current = await asyncio.to_thread(self.database.get_job, job_id)
                if not current or current["status"] == "cancelled" or current.get("cancel_requested"):
                    await asyncio.to_thread(self.database.finish_job, job_id, "cancelled", saved_count)
                    return
                # Freeze the submitted prompts/characters/options; randomize only random seeds.
                request_data = copy.deepcopy(job["request"])
                if random_seed_each_request and (request_index > 0 or request_data["parameters"].get("seed") is None):
                    request_data["parameters"]["seed"] = secrets.randbits(32)
                outputs = await client.generate(
                    request_data,
                    job["correlation_id"],
                    source=source,
                    mask=mask,
                    vibes=vibes,
                    character_references=character_references,
                )

                characters = request_data.get("character_snapshot") or []
                tag_ids = [item["tag_id"] for item in characters]
                quality_prompt = request_data.get("quality_prompt", "")
                description_prompt = request_data.get(
                    "description_prompt", request_data.get("prompt", "")
                )
                legacy_prompt = NovelAIClient.compose_prompt(
                    quality_prompt, description_prompt, False
                )
                legacy_prompt = NovelAIClient.compose_subject_count_prompt(
                    legacy_prompt, characters
                )
                quality_negative_prompt = request_data.get(
                    "quality_negative_prompt", request_data.get("negative_prompt", "")
                )
                description_negative_prompt = request_data.get(
                    "description_negative_prompt", ""
                )
                combined_negative_prompt = NovelAIClient.compose_negative_prompt(
                    quality_negative_prompt,
                    description_negative_prompt,
                )
                for output in outputs:
                    image_id = str(uuid.uuid4())
                    created = utc_now()
                    saved = await asyncio.to_thread(self.storage.save_generated, output.data, image_id)
                    record = {
                        "id": image_id,
                        "job_id": job_id,
                        "parent_image_id": parent_image_id,
                        **saved,
                        "mode": request_data["mode"],
                        "model": request_data["model"],
                        "prompt": legacy_prompt,
                        "quality_prompt": quality_prompt,
                        "description_prompt": description_prompt,
                        "quality_negative_prompt": quality_negative_prompt,
                        "description_negative_prompt": description_negative_prompt,
                        "negative_prompt": combined_negative_prompt,
                        "settings": {
                            **request_data["parameters"],
                            "nsfw_enabled": bool(request_data.get("nsfw_enabled")),
                            **(
                                {"nsfw_prompt": request_data["nsfw_prompt"]}
                                if request_data.get("nsfw_enabled") and request_data.get("nsfw_prompt")
                                else {}
                            ),
                            **{
                                key: request_data[key]
                                for key in ("vibe_references", "character_references", "director")
                                if request_data.get(key)
                            },
                        },
                        "character_snapshot": characters,
                        "seed": output.seed,
                        "created_at": iso(created),
                        "expires_at": iso(created + timedelta(hours=168)),
                    }
                    try:
                        await asyncio.to_thread(self.database.create_image, record, tag_ids)
                    except Exception:
                        await asyncio.to_thread(
                            self.storage.delete_paths, saved["file_path"], saved["thumbnail_path"]
                        )
                        raise
                    saved_count += 1
                    await asyncio.to_thread(self.database.update_job_progress, job_id, saved_count, request_index)
                await asyncio.to_thread(self.database.update_job_progress, job_id, saved_count, request_index + 1)
            await asyncio.to_thread(self.database.finish_job, job_id, "succeeded", saved_count)
        except NovelAIError as exc:
            await asyncio.to_thread(
                self.database.finish_job, job_id, "failed", saved_count, exc.code, str(exc)
            )
        except (OSError, StorageLocationError) as exc:
            logger.exception("File operation failed for job %s", job_id)
            await asyncio.to_thread(
                self.database.finish_job,
                job_id,
                "failed",
                saved_count,
                "STORAGE",
                f"이미지 저장 중 오류가 발생했습니다: {exc}",
            )
        finally:
            if mask_id:
                mask_record = await asyncio.to_thread(self.database.delete_mask, mask_id)
                if mask_record:
                    try:
                        await asyncio.to_thread(self.storage.delete_paths, mask_record["file_path"])
                    except (OSError, StorageLocationError):
                        logger.warning("Could not delete mask %s", mask_id)

    async def _run_cleanup(self) -> None:
        while True:
            await asyncio.sleep(3600)
            await asyncio.to_thread(self.cleanup_once)

    def cleanup_once(self) -> dict[str, int]:
        if not self.storage.available:
            return {"images": 0, "uploads": 0, "masks": 0}
        try:
            with self.storage_gate.activity():
                return self._cleanup_once_active()
        except StorageBusyError:
            return {"images": 0, "uploads": 0, "masks": 0}

    def _cleanup_once_active(self) -> dict[str, int]:
        removed_images = 0
        removed_uploads = 0
        removed_masks = 0
        for image in self.database.expired_images():
            try:
                self.storage.delete_paths(image.get("file_path"), image.get("thumbnail_path"))
                self.database.delete_image_record(image["id"])
                removed_images += 1
            except (OSError, StorageLocationError) as exc:
                self.database.mark_cleanup_error("images", image["id"], str(exc))
        for upload in self.database.expired_uploads():
            try:
                self.storage.delete_paths(upload.get("file_path"), upload.get("thumbnail_path"))
                self.database.delete_upload_record(upload["id"])
                removed_uploads += 1
            except (OSError, StorageLocationError) as exc:
                self.database.mark_cleanup_error("uploads", upload["id"], str(exc))
        for mask in self.database.orphan_masks():
            try:
                self.storage.delete_paths(mask.get("file_path"))
                self.database.delete_mask(mask["id"])
                removed_masks += 1
            except (OSError, StorageLocationError):
                logger.warning("Could not clean orphan mask %s", mask["id"])
        return {"images": removed_images, "uploads": removed_uploads, "masks": removed_masks}
