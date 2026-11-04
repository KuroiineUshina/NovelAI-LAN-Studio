"""Explicit-only MCP tools that run NovelAI jobs and save the results into a local folder.

These sit beside the prompt-draft tools on purpose: the scene prompter flow never
generates, so every tool here spends Anlas only when a caller names it directly.
Jobs go through the normal queue but are hidden from the gallery, and both the
outputs and the uploaded inputs are removed from Studio once copied out.
"""

from __future__ import annotations

import asyncio
import io
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Literal

from mcp.types import ToolAnnotations
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .config import MAX_UPLOAD_BYTES, MODELS
from .schemas import GenerationRequest

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}
SPENDING = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True
)


def _output_directory(raw: str) -> Path:
    directory = Path(raw).expanduser()
    if not directory.is_absolute():
        raise ValueError("output_dir는 절대 경로여야 합니다.")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _input_file(raw: str, label: str) -> bytes:
    path = Path(raw).expanduser()
    if not path.is_absolute() or not path.is_file():
        raise ValueError(f"{label} 파일을 찾을 수 없습니다: {raw}")
    if path.stat().st_size > MAX_UPLOAD_BYTES:
        raise ValueError(f"{label} 파일은 최대 20MB까지 가능합니다.")
    return path.read_bytes()


def _unique_path(directory: Path, stem: str) -> Path:
    candidate = directory / f"{stem}.png"
    index = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{index}.png"
        index += 1
    return candidate


def _as_png(data: bytes) -> tuple[bytes, int, int, bool]:
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        has_alpha = image.mode in {"RGBA", "LA", "PA"} and image.getchannel("A").getextrema()[0] < 255
        if image.format == "PNG":
            return data, image.width, image.height, has_alpha
        converted = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        buffer = io.BytesIO()
        converted.save(buffer, "PNG")
        return buffer.getvalue(), image.width, image.height, has_alpha


def remove_flat_background(
    data: bytes, tolerance: int = 24, background_color: tuple[int, int, int] | None = None
) -> bytes:
    """Make the flat backdrop connected to the image border transparent.

    Only regions touching the edge are removed, so white clothing inside the
    silhouette survives even when it matches the backdrop color.
    """
    with Image.open(io.BytesIO(data)) as source:
        rgb = source.convert("RGB")
    width, height = rgb.size
    if background_color is None:
        corners = [rgb.getpixel(point) for point in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1))]
        background_color = tuple(sorted(channel)[1] for channel in zip(*corners))  # type: ignore[assignment]
    difference = ImageChops.difference(rgb, Image.new("RGB", rgb.size, background_color))
    distance = difference.convert("L")
    # 255 where the pixel is close enough to the backdrop, 0 elsewhere.
    candidate = distance.point(lambda value: 255 if value <= tolerance else 0)
    for x in range(0, width, max(1, width // 64)):
        for y in (0, height - 1):
            if candidate.getpixel((x, y)) == 255:
                ImageDraw.floodfill(candidate, (x, y), 128)
    for y in range(0, height, max(1, height // 64)):
        for x in (0, width - 1):
            if candidate.getpixel((x, y)) == 255:
                ImageDraw.floodfill(candidate, (x, y), 128)
    alpha = candidate.point(lambda value: 0 if value == 128 else 255)
    alpha = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8))
    result = rgb.convert("RGBA")
    result.putalpha(alpha)
    buffer = io.BytesIO()
    result.save(buffer, "PNG")
    return buffer.getvalue()


def register_generation_tools(
    mcp_server: "FastMCP",
    services: Any,
    submit_job: Callable[[GenerationRequest], Awaitable[dict[str, Any]]],
    load_draft: Callable[[], Any],
) -> None:
    def register_upload(data: bytes, name: str) -> str:
        saved = services.storage.save_upload(data, name)
        services.database.create_upload(
            upload_id=saved["id"],
            file_path=saved["file_path"],
            thumbnail_path=saved["thumbnail_path"],
            original_name=saved["original_name"],
            mime_type=saved["mime_type"],
            width=saved["width"],
            height=saved["height"],
        )
        return saved["id"]

    def register_mask(data: bytes, source_id: str) -> str:
        saved = services.storage.save_mask(data, source_id)
        source = services.database.get_upload(source_id)
        if saved["width"] != source["width"] or saved["height"] != source["height"]:
            services.storage.delete_paths(saved["file_path"])
            raise ValueError("마스크 크기가 원본 이미지와 같아야 합니다.")
        services.database.create_mask(
            mask_id=saved["id"], file_path=saved["file_path"], source_asset_id=source_id
        )
        return saved["id"]

    async def remaining_anlas() -> int | None:
        try:
            status = await services.get_anlas_status(force=True)
        except Exception:
            return None
        return status.get("remaining_anlas") if status else None

    async def wait_for(job_id: str, timeout_seconds: int) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while True:
            job = await asyncio.to_thread(services.database.get_job, job_id)
            if job is None or job["status"] in TERMINAL_STATUSES or time.monotonic() >= deadline:
                return job or {"id": job_id, "status": "missing"}
            await asyncio.sleep(0.5)

    def save_outputs(job_id: str, directory: Path, prefix: str) -> list[dict[str, Any]]:
        files = []
        for index, image in enumerate(services.database.list_job_images(job_id), start=1):
            png, width, height, has_alpha = _as_png(services.storage.read(image["file_path"]))
            seed = image.get("seed")
            stem = f"{prefix}_{seed}" if seed is not None else f"{prefix}_{index:02d}"
            destination = _unique_path(directory, stem)
            destination.write_bytes(png)
            # The caller owns the copy now; keep Studio's gallery free of MCP output.
            services.storage.delete_paths(image["file_path"], image.get("thumbnail_path"))
            services.database.delete_image_record(image["id"])
            files.append(
                {
                    "path": str(destination),
                    "width": width,
                    "height": height,
                    "seed": seed,
                    "has_alpha": has_alpha,
                    "image_id": image["id"],
                }
            )
        return files

    def discard_inputs(job: dict[str, Any]) -> None:
        request = job.get("request") or {}
        asset_ids = [request.get("source_asset_id")] + [
            item.get("asset_id")
            for key in ("character_references", "vibe_references")
            for item in request.get(key) or []
        ]
        for asset_id in filter(None, asset_ids):
            upload = services.database.get_upload(asset_id)
            if upload:
                services.storage.delete_paths(upload["file_path"], upload.get("thumbnail_path"))
                services.database.delete_upload_record(asset_id)

    async def run_job(
        request: GenerationRequest, directory: Path, prefix: str, timeout_seconds: int
    ) -> dict[str, Any]:
        before = await remaining_anlas()
        job = await submit_job(request)
        finished = await wait_for(job["id"], timeout_seconds)
        result: dict[str, Any] = {
            "job_id": job["id"],
            "status": finished["status"],
            "model": request.model,
            "mode": request.mode,
        }
        if finished["status"] not in TERMINAL_STATUSES:
            result["message"] = (
                "시간 안에 끝나지 않았어요. collect_generation_outputs로 나중에 받아 가세요."
            )
            return result
        if finished["status"] != "succeeded":
            result["error_code"] = finished.get("error_code")
            result["error_message"] = finished.get("error_message")
        result["files"] = await asyncio.to_thread(save_outputs, job["id"], directory, prefix)
        await asyncio.to_thread(discard_inputs, finished)
        after = await remaining_anlas()
        result["anlas"] = {
            "before": before,
            "after": after,
            "spent": before - after if before is not None and after is not None else None,
        }
        return result

    @mcp_server.tool(
        name="generate_images",
        title="NovelAI 이미지 생성 후 폴더에 저장 (Anlas 소모 가능)",
        description=(
            "사용자가 이 도구로 그림을 뽑으라고 명시했을 때만 호출하세요. 장면 프롬프트 초안 작업"
            "(get_prompt_context·apply_description_prompts) 흐름에서는 절대 부르지 않습니다. "
            "공유 초안은 건드리지 않고, 넘긴 프롬프트로 바로 생성해 PNG를 output_dir에 저장한 뒤 "
            "(Studio 갤러리에는 남기지 않음) "
            "경로·seed·알파 여부·Anlas 변화량을 돌려줍니다. source_image_path가 있으면 img2img, "
            "mask_image_path(흰색=다시 그릴 부분, 원본과 같은 크기의 PNG)까지 있으면 인페인트입니다. "
            "character_reference_paths는 V4.5 모델 전용, vibe_image_paths는 V4/V4.5 전용이며 둘을 함께 "
            "쓸 수 없습니다. use_draft_quality가 true면 현재 초안의 품질 P·N을 앞에 붙입니다."
        ),
        annotations=SPENDING,
        structured_output=True,
    )
    async def mcp_generate_images(
        output_dir: str,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
        seed: int | None = None,
        count: int = 1,
        steps: int = 28,
        guidance: float = 5.0,
        model: str | None = None,
        use_draft_quality: bool = True,
        character_preset_ids: list[str] | None = None,
        source_image_path: str | None = None,
        mask_image_path: str | None = None,
        strength: float = 0.7,
        noise: float = 0.2,
        character_reference_paths: list[str] | None = None,
        character_reference_kind: Literal["character", "style", "character&style"] = "character&style",
        character_reference_strength: float = 1.0,
        character_reference_fidelity: float = 1.0,
        vibe_image_paths: list[str] | None = None,
        vibe_strength: float = 0.6,
        vibe_information_extracted: float = 1.0,
        filename_prefix: str = "nai",
        timeout_seconds: int = 600,
    ) -> dict[str, Any]:
        directory = _output_directory(output_dir)
        draft = load_draft()
        chosen_model = model or draft.model
        if chosen_model not in MODELS:
            raise ValueError(f"모르는 모델입니다: {chosen_model}")
        if mask_image_path and not source_image_path:
            raise ValueError("마스크를 쓰려면 source_image_path도 필요합니다.")
        source_id = (
            register_upload(_input_file(source_image_path, "원본"), Path(source_image_path).name)
            if source_image_path
            else None
        )
        mask_id = register_mask(_input_file(mask_image_path, "마스크"), source_id) if mask_image_path else None
        character_references = [
            {
                "asset_id": register_upload(_input_file(path, "캐릭터 레퍼런스"), Path(path).name),
                "kind": character_reference_kind,
                "strength": character_reference_strength,
                "fidelity": character_reference_fidelity,
            }
            for path in character_reference_paths or []
        ]
        vibe_references = [
            {
                "asset_id": register_upload(_input_file(path, "바이브"), Path(path).name),
                "strength": vibe_strength,
                "information_extracted": vibe_information_extracted,
            }
            for path in vibe_image_paths or []
        ]
        request = GenerationRequest.model_validate(
            {
                "mode": "inpaint" if mask_id else "img2img" if source_id else "txt2img",
                "model": chosen_model,
                "quality_prompt": draft.quality_prompt if use_draft_quality else "",
                "quality_negative_prompt": draft.quality_negative_prompt if use_draft_quality else "",
                "description_prompt": prompt,
                "description_negative_prompt": negative_prompt,
                "nsfw_enabled": False,
                "character_preset_ids": character_preset_ids or [],
                "source_asset_id": source_id,
                "mask_asset_id": mask_id,
                "character_references": character_references,
                "vibe_references": vibe_references,
                "parameters": {
                    **draft.parameters.model_dump(),
                    "width": width,
                    "height": height,
                    "seed": seed,
                    "count": count,
                    "steps": steps,
                    "guidance": guidance,
                    "strength": strength,
                    "noise": noise,
                },
            }
        )
        return await run_job(request, directory, filename_prefix, timeout_seconds)

    @mcp_server.tool(
        name="remove_background",
        title="배경 제거 후 투명 PNG로 저장",
        description=(
            "사용자가 배경 제거를 명시했을 때만 호출하세요. method='flat_color'는 PC에서 무료로 "
            "처리하며, 가장자리에 닿은 단색 배경(예: simple background, white background로 뽑은 그림)만 "
            "투명하게 만듭니다. method='novelai'는 NovelAI 디렉터 배경 제거를 써서 복잡한 배경도 "
            "지우지만 Opus여도 Anlas가 듭니다. 결과 PNG 경로와 실제 알파 여부를 돌려줍니다."
        ),
        annotations=SPENDING,
        structured_output=True,
    )
    async def mcp_remove_background(
        image_path: str,
        output_dir: str,
        method: Literal["flat_color", "novelai"],
        tolerance: int = 24,
        background_color: list[int] | None = None,
        filename_prefix: str | None = None,
        timeout_seconds: int = 600,
    ) -> dict[str, Any]:
        directory = _output_directory(output_dir)
        data = _input_file(image_path, "이미지")
        prefix = filename_prefix or f"{Path(image_path).stem}_nobg"
        if method == "flat_color":
            if not 0 <= tolerance <= 255:
                raise ValueError("tolerance는 0~255 사이여야 합니다.")
            color = tuple(background_color) if background_color else None
            if color is not None and (len(color) != 3 or not all(0 <= c <= 255 for c in color)):
                raise ValueError("background_color는 [R, G, B] 형식이어야 합니다.")
            png = await asyncio.to_thread(remove_flat_background, data, tolerance, color)
            destination = _unique_path(directory, prefix)
            destination.write_bytes(png)
            with Image.open(io.BytesIO(png)) as image:
                size = image.size
            return {
                "status": "succeeded",
                "method": method,
                "files": [{"path": str(destination), "width": size[0], "height": size[1], "has_alpha": True}],
                "anlas": {"spent": 0},
            }
        source_id = register_upload(data, Path(image_path).name)
        draft = load_draft()
        request = GenerationRequest.model_validate(
            {
                "mode": "director",
                "model": draft.model,
                "source_asset_id": source_id,
                "director": {"tool": "bg-removal"},
                "parameters": {**draft.parameters.model_dump(), "count": 1},
            }
        )
        result = await run_job(request, directory, prefix, timeout_seconds)
        result["method"] = method
        transparent = [item["path"] for item in result.get("files", []) if item["has_alpha"]]
        result["transparent_path"] = transparent[0] if transparent else None
        return result

    @mcp_server.tool(
        name="collect_generation_outputs",
        title="끝난 생성 작업 결과를 폴더에 저장",
        description=(
            "generate_images나 remove_background가 시간 안에 끝나지 않아 job_id만 돌려줬을 때, "
            "그 작업의 상태를 확인하고 끝났으면 PNG를 output_dir에 저장합니다. 새로 생성하지 않습니다."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
        ),
        structured_output=True,
    )
    async def mcp_collect_generation_outputs(
        job_id: str, output_dir: str, filename_prefix: str = "nai"
    ) -> dict[str, Any]:
        job = await asyncio.to_thread(services.database.get_job, job_id)
        if not job:
            raise ValueError("작업을 찾을 수 없습니다.")
        result: dict[str, Any] = {"job_id": job_id, "status": job["status"]}
        if job["status"] not in TERMINAL_STATUSES:
            return result
        if job["status"] != "succeeded":
            result["error_code"] = job.get("error_code")
            result["error_message"] = job.get("error_message")
        directory = _output_directory(output_dir)
        result["files"] = await asyncio.to_thread(save_outputs, job_id, directory, filename_prefix)
        await asyncio.to_thread(discard_inputs, job)
        return result
