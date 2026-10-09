import { useState } from "react";
import { Plus, Upload, X } from "lucide-react";
import type {
  CharacterReference,
  ImageRecord,
  ModelSpec,
  ReferenceKind,
  UploadAsset,
  VibeReference,
} from "../types";

type SourceAsset = ImageRecord | UploadAsset;
export type ReferenceTab = "character" | "vibe";
export type CharacterReferenceItem = CharacterReference & { thumbnail_url: string };
export type VibeReferenceItem = VibeReference & { thumbnail_url: string };

export const MAX_CHARACTER_REFERENCES = 4;
export const MAX_VIBE_REFERENCES = 16;

const KINDS: Array<{ id: ReferenceKind; label: string }> = [
  { id: "character&style", label: "둘 다" },
  { id: "character", label: "캐릭터" },
  { id: "style", label: "스타일" },
];

interface Props {
  tab: ReferenceTab;
  onTabChange: (tab: ReferenceTab) => void;
  characterRefs: CharacterReferenceItem[];
  onCharacterRefsChange: (items: CharacterReferenceItem[]) => void;
  vibes: VibeReferenceItem[];
  onVibesChange: (items: VibeReferenceItem[]) => void;
  modelSpec: ModelSpec | undefined;
  models: ModelSpec[];
  onModelChange: (modelId: string) => void;
  sources: SourceAsset[];
  loadingSources: boolean;
  onOpenPicker: () => void;
  onUpload: (file: File) => Promise<SourceAsset | null>;
}

function Slider({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  return (
    <label className="reference-slider">
      <span>{label}</span>
      <input type="range" min="0" max="1" step="0.05" value={value} onChange={(event) => onChange(Number(event.target.value))} />
      <output>{value.toFixed(2)}</output>
    </label>
  );
}

export function ReferencePanel({
  tab,
  onTabChange,
  characterRefs,
  onCharacterRefsChange,
  vibes,
  onVibesChange,
  modelSpec,
  models,
  onModelChange,
  sources,
  loadingSources,
  onOpenPicker,
  onUpload,
}: Props) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const supported = tab === "character"
    ? Boolean(modelSpec?.supports_character_reference)
    : Boolean(modelSpec?.supports_vibe_transfer);
  const fallbackModel = models.find((item) => (
    tab === "character" ? item.supports_character_reference : item.supports_vibe_transfer
  ));
  const count = tab === "character" ? characterRefs.length : vibes.length;
  const limit = tab === "character" ? MAX_CHARACTER_REFERENCES : MAX_VIBE_REFERENCES;
  const otherCount = tab === "character" ? vibes.length : characterRefs.length;

  const add = (source: SourceAsset) => {
    if (tab === "character") {
      if (characterRefs.length >= MAX_CHARACTER_REFERENCES) return;
      onCharacterRefsChange([
        ...characterRefs,
        { asset_id: source.id, thumbnail_url: source.thumbnail_url, kind: "character&style", strength: 1, fidelity: 1 },
      ]);
    } else {
      if (vibes.length >= MAX_VIBE_REFERENCES) return;
      onVibesChange([
        ...vibes,
        { asset_id: source.id, thumbnail_url: source.thumbnail_url, strength: 0.6, information_extracted: 1 },
      ]);
    }
    setPickerOpen(false);
  };

  const togglePicker = () => {
    if (!pickerOpen) onOpenPicker();
    setPickerOpen(!pickerOpen);
  };

  return (
    <section className="panel reference-panel" aria-label="레퍼런스">
      <div className="panel-header">
        <h2>레퍼런스</h2>
        <div className="panel-actions">
          <div className="segmented reference-tabs" role="tablist" aria-label="레퍼런스 종류">
            <button type="button" role="tab" aria-selected={tab === "character"} onClick={() => onTabChange("character")}>
              캐릭터{characterRefs.length ? <small>{characterRefs.length}</small> : null}
            </button>
            <button type="button" role="tab" aria-selected={tab === "vibe"} onClick={() => onTabChange("vibe")}>
              바이브{vibes.length ? <small>{vibes.length}</small> : null}
            </button>
          </div>
          <button type="button" className="button small" onClick={togglePicker} disabled={count >= limit} aria-expanded={pickerOpen}>
            <Plus aria-hidden="true" />추가
          </button>
        </div>
      </div>

      {!supported ? (
        <div className="reference-unsupported">
          <span>{modelSpec?.label ?? "이 모델"}에서는 안 돼요</span>
          {fallbackModel ? (
            <button type="button" className="button small" onClick={() => onModelChange(fallbackModel.id)}>{fallbackModel.label}로 바꾸기</button>
          ) : null}
        </div>
      ) : null}
      {otherCount > 0 && count > 0 ? <p className="caption reference-note">한 번에 한 종류만 적용돼요</p> : null}

      {pickerOpen ? (
        <div className="reference-picker">
          <div className="source-grid">
            <label className="source-card reference-upload" title="업로드">
              <Upload aria-hidden="true" />
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                onChange={async (event) => {
                  const file = event.target.files?.[0];
                  event.target.value = "";
                  if (!file) return;
                  const uploaded = await onUpload(file);
                  if (uploaded) add(uploaded);
                }}
              />
            </label>
            {loadingSources && !sources.length ? Array.from({ length: 7 }, (_, index) => <span key={index} className="source-card skeleton" aria-hidden="true" />) : null}
            {sources.slice(0, 23).map((source) => (
              <button type="button" className="source-card" key={source.id} onClick={() => add(source)}>
                <img src={source.thumbnail_url} alt="" />
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {tab === "character" && characterRefs.length ? (
        <ul className="reference-list">
          {characterRefs.map((item, index) => {
            const update = (patch: Partial<CharacterReferenceItem>) => onCharacterRefsChange(
              characterRefs.map((ref, refIndex) => (refIndex === index ? { ...ref, ...patch } : ref)),
            );
            return (
              <li className="reference-item" key={`${item.asset_id}-${index}`}>
                <img src={item.thumbnail_url} alt="" />
                <div className="reference-controls">
                  <div className="segmented reference-kind" role="radiogroup" aria-label="참고할 부분">
                    {KINDS.map((kind) => (
                      <button type="button" role="radio" key={kind.id} aria-checked={item.kind === kind.id} onClick={() => update({ kind: kind.id })}>{kind.label}</button>
                    ))}
                  </div>
                  <Slider label="강도" value={item.strength} onChange={(strength) => update({ strength })} />
                  <Slider label="충실도" value={item.fidelity} onChange={(fidelity) => update({ fidelity })} />
                </div>
                <button type="button" className="icon-button small weak" aria-label="레퍼런스 빼기" onClick={() => onCharacterRefsChange(characterRefs.filter((_, refIndex) => refIndex !== index))}><X aria-hidden="true" /></button>
              </li>
            );
          })}
        </ul>
      ) : null}

      {tab === "vibe" && vibes.length ? (
        <ul className="reference-list">
          {vibes.map((item, index) => {
            const update = (patch: Partial<VibeReferenceItem>) => onVibesChange(
              vibes.map((ref, refIndex) => (refIndex === index ? { ...ref, ...patch } : ref)),
            );
            return (
              <li className="reference-item" key={`${item.asset_id}-${index}`}>
                <img src={item.thumbnail_url} alt="" />
                <div className="reference-controls">
                  <Slider label="강도" value={item.strength} onChange={(strength) => update({ strength })} />
                  <Slider label="정보량" value={item.information_extracted} onChange={(value) => update({ information_extracted: Math.max(0.05, value) })} />
                </div>
                <button type="button" className="icon-button small weak" aria-label="바이브 빼기" onClick={() => onVibesChange(vibes.filter((_, refIndex) => refIndex !== index))}><X aria-hidden="true" /></button>
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}
