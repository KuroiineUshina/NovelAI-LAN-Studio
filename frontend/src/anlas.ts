import type { AnlasStatus, DirectorTool, GenerationMode, GenerationParameters } from "./types";

export const NORMAL_PIXEL_LIMIT = 1024 * 1024;
const MAX_ESTIMATED_UNIT_COST = 140;
const PIXEL_BASE_COST = 2.951823174884865e-6;
const PIXEL_STEP_COST = 5.753298233447344e-7;
const DIRECTOR_MAX_PIXELS = 3_145_728;
const CHARACTER_REFERENCE_COST = 5;
const VIBE_FREE_COUNT = 4;
const VIBE_EXTRA_COST = 2;

export interface AnlasEstimate {
  total: number | null;
  per_image: number | null;
  free_images: number;
  note: string;
}

interface EstimateInput {
  mode: GenerationMode;
  model: string;
  parameters: GenerationParameters;
  account: AnlasStatus | null;
  source_width?: number | null;
  source_height?: number | null;
  director_tool?: DirectorTool;
  character_reference_count?: number;
  vibe_count?: number;
}

function directorCost(tool: DirectorTool | undefined, width: number, height: number, account: AnlasStatus | null): AnlasEstimate {
  const sourcePixels = width * height;
  if (!Number.isFinite(sourcePixels) || sourcePixels <= 0) {
    return { total: null, per_image: null, free_images: 0, note: "원본을 고르면 계산해요" };
  }
  // Billed area is clamped to 1MP..3MP and priced like 28 steps.
  const pixels = Math.min(DIRECTOR_MAX_PIXELS, Math.max(NORMAL_PIXEL_LIMIT, sourcePixels));
  const base = Math.ceil(PIXEL_BASE_COST * pixels + PIXEL_STEP_COST * pixels * 28);
  const removal = tool === "bg-removal";
  const cost = removal ? base * 3 + 5 : base;
  const free = !removal && account?.active === true && account.tier >= 3 && sourcePixels <= NORMAL_PIXEL_LIMIT;
  return {
    total: free ? 0 : cost,
    per_image: cost,
    free_images: free ? 1 : 0,
    note: free ? "Opus 무료" : removal ? "배경 제거는 항상 유료" : "디렉터 도구 1회 기준",
  };
}

function upscaleCost(width: number, height: number): number | null {
  const pixels = width * height;
  if (!Number.isFinite(pixels) || pixels <= 0 || pixels > NORMAL_PIXEL_LIMIT) return null;
  return 1;
}

export function estimateAnlasCost({
  mode,
  model,
  parameters,
  account,
  source_width,
  source_height,
  director_tool,
  character_reference_count = 0,
  vibe_count = 0,
}: EstimateInput): AnlasEstimate {
  if (mode === "director") return directorCost(director_tool, source_width ?? 0, source_height ?? 0, account);
  if (mode === "upscale") {
    const total = upscaleCost(source_width ?? 0, source_height ?? 0);
    return {
      total,
      per_image: total,
      free_images: 0,
      note: total === null ? "원본을 고르면 계산해요" : "업스케일 1회 기준",
    };
  }

  const width = Number(parameters.width);
  const height = Number(parameters.height);
  const steps = Number(parameters.steps);
  const count = Math.max(1, Math.floor(Number(parameters.count) || 1));
  const pixels = width * height;
  if (!Number.isFinite(pixels) || pixels <= 0 || !Number.isFinite(steps) || steps <= 0) {
    return { total: null, per_image: null, free_images: 0, note: "크기와 단계를 확인해 주세요" };
  }

  const rawBase = Math.ceil(PIXEL_BASE_COST * pixels + PIXEL_STEP_COST * pixels * steps);
  const modelMultiplier = model.startsWith("nai-diffusion-5-") ? 1.5 : 1;
  const strengthMultiplier = mode === "img2img"
    ? Math.min(1, Math.max(0, Number(parameters.strength)))
    : 1;
  const perImage = Math.max(Math.ceil(rawBase * modelMultiplier * strengthMultiplier), 2);
  if (perImage > MAX_ESTIMATED_UNIT_COST) {
    return { total: null, per_image: null, free_images: 0, note: "계산할 수 없는 크기예요" };
  }

  const isV5 = model.startsWith("nai-diffusion-5-");
  const opusFreeEligible = mode === "txt2img"
    && account?.active === true
    && account.tier >= 3
    && pixels <= NORMAL_PIXEL_LIMIT
    && steps <= 28
    && (!isV5 || account.usage_is_negative !== true);
  const v5LimitExhausted = mode === "txt2img"
    && isV5
    && account?.active === true
    && account.tier >= 3
    && pixels <= NORMAL_PIXEL_LIMIT
    && steps <= 28
    && account.usage_is_negative === true;
  const freeImages = opusFreeEligible ? 1 : 0;
  const billedImages = Math.max(0, count - freeImages);
  // Reference surcharges are never covered by the Opus free generation.
  const referenceExtra = character_reference_count * CHARACTER_REFERENCE_COST
    + Math.max(0, vibe_count - VIBE_FREE_COUNT) * VIBE_EXTRA_COST;
  const total = perImage * billedImages + referenceExtra * count;
  const referenceNote = referenceExtra > 0 ? ` · 레퍼런스 +${(referenceExtra * count).toLocaleString()}` : "";

  return {
    total,
    per_image: perImage,
    free_images: freeImages,
    note: (v5LimitExhausted
      ? `V5 무료 한도 소진 · ${perImage.toLocaleString()} ANLAS × ${count}장`
      : freeImages > 0
      ? count === 1
        ? "Opus 무료"
        : `Opus 무료 1장 · 유료 ${billedImages}장`
      : `${perImage.toLocaleString()} ANLAS × ${count}장`) + referenceNote,
  };
}
