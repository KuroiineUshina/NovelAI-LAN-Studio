import { useState } from "react";
import { Check, Copy, X } from "lucide-react";
import type { ImageInfo } from "../types";

interface ImageInfoCardProps {
  info: ImageInfo;
  fileName: string;
  onClose: () => void;
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // LAN pages over plain http have no async clipboard; fall back to a hidden textarea.
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="icon-button weak"
      aria-label={label}
      title={label}
      onClick={() => void copyText(text).then((ok) => {
        if (!ok) return;
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1200);
      })}
    >
      {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
    </button>
  );
}

function exposure(seconds: number): string {
  return seconds >= 1 ? `${seconds}초` : `1/${Math.round(1 / seconds)}초`;
}

export function ImageInfoCard({ info, fileName, onClose }: ImageInfoCardProps) {
  const generation = info.generation;
  const camera = info.camera;
  const params = generation?.parameters ?? {};
  const badge = generation ? (generation.source === "novelai" ? "NovelAI" : "WebUI") : camera ? "카메라" : null;

  const settingChips = generation
    ? [
        params.width && params.height ? `${params.width} × ${params.height}` : null,
        params.steps ? `${params.steps}스텝` : null,
        params.guidance != null ? `가이던스 ${params.guidance}` : null,
        params.guidance_rescale ? `리스케일 ${params.guidance_rescale}` : null,
        params.seed != null ? `시드 ${params.seed}` : null,
        params.sampler ?? null,
        params.noise_schedule ?? null,
        generation.model_label,
      ].filter((chip): chip is string => Boolean(chip))
    : [];

  const cameraChips = camera
    ? [
        [camera.make, camera.model].filter(Boolean).join(" ") || null,
        camera.lens ?? null,
        camera.taken_at ?? camera.modified_at ?? null,
        camera.exposure_time ? exposure(camera.exposure_time) : null,
        camera.f_number ? `f/${camera.f_number}` : null,
        camera.iso ? `ISO ${camera.iso}` : null,
        camera.focal_length ? `${camera.focal_length}mm` : null,
        camera.software ?? null,
        camera.has_location ? "위치 정보 있음" : null,
      ].filter((chip): chip is string => Boolean(chip))
    : [];

  return (
    <section className="image-info-card" aria-label="이미지 정보">
      <header className="image-info-head">
        {badge ? <span className="image-info-badge">{badge}</span> : null}
        <small className="image-info-name">{fileName}</small>
        <button type="button" className="icon-button weak" onClick={onClose} aria-label="닫기" title="닫기"><X aria-hidden="true" /></button>
      </header>

      {generation ? (
        <>
          <div className="image-info-block">
            <span className="label-row"><strong>포지티브</strong><CopyButton text={generation.prompt} label="포지티브 복사" /></span>
            <p className="image-info-text">{generation.prompt || "없음"}</p>
          </div>
          {generation.negative_prompt ? (
            <div className="image-info-block">
              <span className="label-row"><strong>네거티브</strong><CopyButton text={generation.negative_prompt} label="네거티브 복사" /></span>
              <p className="image-info-text">{generation.negative_prompt}</p>
            </div>
          ) : null}
          {generation.characters.map((character, index) => (
            <div className="image-info-block" key={index}>
              <span className="label-row"><strong>인물 {index + 1}</strong><CopyButton text={character.prompt} label={`인물 ${index + 1} 복사`} /></span>
              <p className="image-info-text">{character.prompt}</p>
              {character.negative_prompt ? <p className="image-info-text negative">{character.negative_prompt}</p> : null}
            </div>
          ))}
          {settingChips.length ? (
            <div className="image-info-chips">{settingChips.map((chip) => <span className="chip" key={chip}>{chip}</span>)}</div>
          ) : null}
        </>
      ) : null}

      {cameraChips.length ? (
        <div className="image-info-chips">{cameraChips.map((chip) => <span className="chip" key={chip}>{chip}</span>)}</div>
      ) : null}

      {!generation && !cameraChips.length ? <p className="caption">정보가 없어요</p> : null}
    </section>
  );
}
