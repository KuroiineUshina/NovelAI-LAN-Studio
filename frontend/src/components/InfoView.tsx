import { useCallback, useEffect, useState } from "react";
import { ScanText, Upload, X } from "lucide-react";
import { api, errorMessage, uploadFile } from "../api";
import type { ImageInfo, QualityPresetSettings, QualityPromptPreset } from "../types";
import { settingsChips, settingsFromParameters } from "../qualityPresetSettings";
import { ImageInfoCard } from "./ImageInfoCard";
import "../info.css";

interface Loaded {
  info: ImageInfo;
  name: string;
  previewUrl: string;
}

function imageFile(items: ArrayLike<DataTransferItem | File> | null | undefined): File | null {
  if (!items) return null;
  for (const item of Array.from(items)) {
    const file = item instanceof File ? item : item.kind === "file" ? item.getAsFile() : null;
    if (file && file.type.startsWith("image/")) return file;
  }
  return null;
}

interface InfoViewProps {
  qualityPresets: QualityPromptPreset[];
  reloadQualityPresets: () => Promise<void>;
  notify: (message: string) => void;
}

interface PresetDraft {
  name: string;
  prompt: string;
  negative: string;
  settings: QualityPresetSettings;
  includeSettings: boolean;
}

export function InfoView({ qualityPresets, reloadQualityPresets, notify }: InfoViewProps) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [presetDraft, setPresetDraft] = useState<PresetDraft | null>(null);
  const [presetSaving, setPresetSaving] = useState(false);
  const [presetError, setPresetError] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);

  const read = useCallback(async (file: File) => {
    setBusy(true);
    setError("");
    try {
      const info = await uploadFile<ImageInfo>("/api/image-info", file);
      setLoaded({ info, name: file.name || "붙여 넣은 이미지", previewUrl: URL.createObjectURL(file) });
    } catch (readError) {
      setError(errorMessage(readError));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    const onPaste = (event: ClipboardEvent) => {
      const file = imageFile(event.clipboardData?.items);
      if (!file) return;
      event.preventDefault();
      void read(file);
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [read]);

  // Release each preview URL once it is replaced or the view closes.
  useEffect(() => {
    if (!loaded) return;
    return () => URL.revokeObjectURL(loaded.previewUrl);
  }, [loaded]);

  const openPresetSave = () => {
    const generation = loaded?.info.generation;
    if (!loaded || !generation) return;
    setPresetError("");
    const { sampler, noise_schedule: noiseSchedule, ...portable } = generation.parameters;
    // WebUI sampler names do not exist on NovelAI, so only NovelAI images carry them over.
    const settings = settingsFromParameters(
      generation.source === "novelai" ? { ...portable, sampler, noise_schedule: noiseSchedule } : portable,
    );
    setPresetDraft({
      name: loaded.name.replace(/\.[^.]+$/, "").slice(0, 80),
      prompt: generation.prompt,
      negative: generation.negative_prompt,
      settings,
      includeSettings: Object.keys(settings).length > 0,
    });
  };

  const savePreset = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!presetDraft) return;
    setPresetSaving(true);
    setPresetError("");
    try {
      const created = await api<QualityPromptPreset>("/api/quality-presets", {
        method: "POST",
        body: JSON.stringify({
          name: presetDraft.name.trim(),
          prompt: presetDraft.prompt.trim(),
          negative_prompt: presetDraft.negative.trim(),
          settings: presetDraft.includeSettings ? presetDraft.settings : {},
          sort_order: qualityPresets.length * 10,
        }),
      });
      await reloadQualityPresets();
      setPresetDraft(null);
      notify(`‘${created.name}’ 프리셋을 저장했어요`);
    } catch (saveError) {
      setPresetError(errorMessage(saveError));
    } finally {
      setPresetSaving(false);
    }
  };

  return (
    <div className="page narrow info-view">
      <header className="page-header">
        <h1>EXIF</h1>
      </header>
      {error ? <p className="error-message" role="alert">{error}</p> : null}

      <label
        className={`info-drop${dragging ? " dragging" : ""}${loaded ? " compact" : ""}`}
        onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          const file = imageFile(event.dataTransfer.files);
          if (file) void read(file);
        }}
        aria-busy={busy}
      >
        {busy ? <span className="spinner" aria-hidden="true" /> : loaded ? <Upload aria-hidden="true" /> : <ScanText aria-hidden="true" />}
        <strong>{loaded ? "다른 이미지" : "이미지 선택"}</strong>
        <small>끌어 놓기 · 붙여 넣기</small>
        <input
          type="file"
          accept="image/png,image/jpeg,image/webp"
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file) void read(file);
          }}
        />
      </label>

      {loaded ? (
        <div className="info-result">
          <figure className="info-preview">
            <img src={loaded.previewUrl} alt={loaded.name} />
            <figcaption className="caption">
              {loaded.info.image.width} × {loaded.info.image.height}{loaded.info.image.format ? ` · ${loaded.info.image.format}` : ""}
            </figcaption>
          </figure>
          <ImageInfoCard
            info={loaded.info}
            fileName={loaded.name}
            onClose={() => setLoaded(null)}
            onSaveQualityPreset={loaded.info.generation ? openPresetSave : undefined}
          />
        </div>
      ) : null}

      {presetDraft ? (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setPresetDraft(null)}>
          <form
            className="modal-form quality-preset-modal info-preset-modal"
            role="dialog"
            aria-modal="true"
            aria-label="품질 프롬프트 프리셋 저장"
            onMouseDown={(event) => event.stopPropagation()}
            onSubmit={(event) => void savePreset(event)}
          >
            <button type="button" className="icon-button modal-close" onClick={() => setPresetDraft(null)} aria-label="닫기"><X aria-hidden="true" /></button>
            <h2>품질 프리셋 저장</h2>
            <label className="field">
              <span className="field-label">이름</span>
              <input autoFocus required maxLength={80} value={presetDraft.name} onChange={(event) => setPresetDraft({ ...presetDraft, name: event.target.value })} />
            </label>
            <label className="field">
              <span className="field-label">포지티브</span>
              <textarea className="prompt-textarea" required value={presetDraft.prompt} onChange={(event) => setPresetDraft({ ...presetDraft, prompt: event.target.value })} rows={6} />
            </label>
            <label className="field">
              <span className="field-label">네거티브</span>
              <textarea className="prompt-textarea" value={presetDraft.negative} onChange={(event) => setPresetDraft({ ...presetDraft, negative: event.target.value })} rows={4} />
            </label>
            {Object.keys(presetDraft.settings).length ? (
              <>
                <label className="switch">
                  <input type="checkbox" checked={presetDraft.includeSettings} onChange={(event) => setPresetDraft({ ...presetDraft, includeSettings: event.target.checked })} />
                  <span className="switch-track" aria-hidden="true" />
                  <span className="switch-label"><strong>생성 설정 포함</strong></span>
                </label>
                {presetDraft.includeSettings ? (
                  <div className="image-info-chips">{settingsChips(presetDraft.settings).map((chip) => <span className="chip" key={chip}>{chip}</span>)}</div>
                ) : null}
              </>
            ) : null}
            {presetError ? <p className="error-message" role="alert">{presetError}</p> : null}
            <div className="form-actions">
              <button type="button" className="button secondary" onClick={() => setPresetDraft(null)}>취소</button>
              <button type="submit" className="button primary" disabled={presetSaving || !presetDraft.name.trim() || !presetDraft.prompt.trim()}>{presetSaving ? "저장 중…" : "저장"}</button>
            </div>
          </form>
        </div>
      ) : null}
    </div>
  );
}
