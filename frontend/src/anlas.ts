import type { AnlasStatus, GenerationMode, GenerationParameters } from "./types";

export const NORMAL_PIXEL_LIMIT = 1024 * 1024;
const MAX_ESTIMATED_UNIT_COST = 140;
const PIXEL_BASE_COST = 2.951823174884865e-6;
const PIXEL_STEP_COST = 5.753298233447344e-7;

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
}: EstimateInput): AnlasEstimate {
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
  const total = perImage * billedImages;

  return {
    total,
    per_image: perImage,
    free_images: freeImages,
    note: v5LimitExhausted
      ? `V5 무료 한도 소진 · ${perImage.toLocaleString()} ANLAS × ${count}장`
      : freeImages > 0
      ? count === 1
        ? "Opus 무료"
        : `Opus 무료 1장 · 유료 ${billedImages}장`
      : `${perImage.toLocaleString()} ANLAS × ${count}장`,
  };
}
