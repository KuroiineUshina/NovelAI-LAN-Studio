import type { GenerationParameters, QualityPresetSettings } from "./types";

const SAMPLER_LABELS: Record<string, string> = {
  k_dpmpp_2m: "DPM++ 2M",
  k_euler: "Euler",
  k_euler_ancestral: "Euler Ancestral",
  k_dpmpp_2s_ancestral: "DPM++ 2S Ancestral",
  k_dpmpp_2m_sde: "DPM++ 2M SDE",
  k_dpmpp_sde: "DPM++ SDE",
};

const SCHEDULE_LABELS: Record<string, string> = {
  karras: "Karras",
  exponential: "Exponential",
  polyexponential: "Polyexponential",
};

export function settingsFromParameters(parameters: Partial<GenerationParameters>): QualityPresetSettings {
  const settings: QualityPresetSettings = {};
  if (parameters.steps != null) settings.steps = parameters.steps;
  if (parameters.guidance != null) settings.guidance = parameters.guidance;
  if (parameters.guidance_rescale != null) settings.guidance_rescale = parameters.guidance_rescale;
  if (parameters.sampler) settings.sampler = parameters.sampler;
  if (parameters.noise_schedule) settings.noise_schedule = parameters.noise_schedule;
  return settings;
}

/** True when a setting the preset manages no longer matches the draft. */
export function settingsDiffer(settings: QualityPresetSettings | undefined, parameters: GenerationParameters): boolean {
  if (!settings) return false;
  return (Object.keys(settings) as Array<keyof QualityPresetSettings>).some((key) => settings[key] !== parameters[key]);
}

export function settingsChips(settings: QualityPresetSettings | undefined): string[] {
  if (!settings) return [];
  return [
    settings.steps != null ? `${settings.steps}스텝` : null,
    settings.guidance != null ? `가이던스 ${settings.guidance}` : null,
    settings.guidance_rescale != null ? `리스케일 ${settings.guidance_rescale}` : null,
    settings.sampler ? SAMPLER_LABELS[settings.sampler] ?? settings.sampler : null,
    settings.noise_schedule ? SCHEDULE_LABELS[settings.noise_schedule] ?? settings.noise_schedule : null,
  ].filter((chip): chip is string => Boolean(chip));
}
