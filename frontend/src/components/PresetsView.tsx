import { useEffect, useRef, useState } from "react";
import { ChevronLeft, Plus, Trash2, UserPlus, X } from "lucide-react";
import { api, errorMessage } from "../api";
import type { CharacterPreset } from "../types";
import "../library.css";

type PresetDraft = Pick<CharacterPreset, "name" | "tag_name" | "subject_type" | "prompt" | "negative_prompt" | "sort_order">;

const EMPTY: PresetDraft = {
  name: "",
  tag_name: "",
  subject_type: "girl",
  prompt: "",
  negative_prompt: "",
  sort_order: 0,
};

const PROMPT_LIMIT = 8_000;

const SUBJECTS: Array<{ value: PresetDraft["subject_type"]; label: string }> = [
  { value: "girl", label: "여자" },
  { value: "boy", label: "남자" },
  { value: "other", label: "기타" },
];

const subjectLabel = (value: PresetDraft["subject_type"]) => SUBJECTS.find((item) => item.value === value)?.label ?? value;

const isDesktop = () => typeof window !== "undefined" && window.matchMedia("(min-width: 768px)").matches;

interface Props {
  presets: CharacterPreset[];
  reload: () => Promise<void>;
  notify: (message: string) => void;
}

export function PresetsView({ presets, reload, notify }: Props) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<PresetDraft>(EMPTY);
  const [formOpen, setFormOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const autoSelected = useRef(false);

  const openNew = () => {
    setEditingId(null);
    setDraft({ ...EMPTY, sort_order: presets.length * 10 });
    setError("");
    setFormOpen(true);
  };

  const openEdit = (preset: CharacterPreset) => {
    setEditingId(preset.id);
    setDraft({
      name: preset.name,
      tag_name: preset.tag_name,
      subject_type: preset.subject_type,
      prompt: preset.prompt,
      negative_prompt: preset.negative_prompt,
      sort_order: preset.sort_order,
    });
    setError("");
    setFormOpen(true);
  };

  const closeForm = () => {
    setFormOpen(false);
    setEditingId(null);
    setError("");
  };

  // Desktop shows the editor beside the list, so open the first character once.
  useEffect(() => {
    if (autoSelected.current || formOpen || !presets.length) return;
    autoSelected.current = true;
    if (isDesktop()) openEdit(presets[0]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [presets]);

  const update = <K extends keyof PresetDraft>(key: K, value: PresetDraft[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
  };

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const saved = await api<CharacterPreset | undefined>(editingId ? `/api/presets/${editingId}` : "/api/presets", {
        method: editingId ? "PUT" : "POST",
        body: JSON.stringify(draft),
      });
      await reload();
      if (isDesktop() && saved?.id) {
        setEditingId(saved.id);
      } else {
        closeForm();
      }
      notify(editingId ? "수정했어요" : "추가했어요");
    } catch (saveError) {
      setError(errorMessage(saveError));
    } finally {
      setSaving(false);
    }
  };

  const remove = async (preset: CharacterPreset) => {
    if (!window.confirm(`${preset.name}을(를) 삭제할까요? 기존 이미지의 #${preset.tag_name} 태그는 남아요.`)) return;
    try {
      await api(`/api/presets/${preset.id}`, { method: "DELETE" });
      await reload();
      if (editingId === preset.id) closeForm();
      notify("삭제했어요");
    } catch (removeError) {
      setError(errorMessage(removeError));
    }
  };

  const editingPreset = editingId ? presets.find((preset) => preset.id === editingId) ?? null : null;

  return (
    <div className="page presets-view" data-editor-open={formOpen ? "true" : "false"}>
      <header className="page-header presets-header">
        <h1>인물</h1>
        <div className="page-actions">
          <button type="button" className="button secondary" onClick={openNew}><Plus aria-hidden="true" strokeWidth={2} />새 인물</button>
        </div>
      </header>

      {error && !formOpen ? <p className="error-message" role="alert">{error}</p> : null}

      {presets.length || formOpen ? (
        <div className="presets-layout">
          <nav className="presets-list-pane panel flush" aria-label="인물 목록">
            {presets.length ? (
              <ul className="list presets-list">
                {presets.map((preset) => (
                  <li key={preset.id}>
                    <button
                      type="button"
                      className="list-item presets-list-item"
                      aria-current={formOpen && editingId === preset.id ? "true" : undefined}
                      onClick={() => openEdit(preset)}
                    >
                      <span className="list-item-content">
                        <span className="list-item-title">{preset.name}</span>
                        <span className="list-item-detail">#{preset.tag_name}</span>
                      </span>
                      <span className={`badge presets-subject ${preset.subject_type}`}>{subjectLabel(preset.subject_type)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : <p className="empty-inline presets-list-empty">인물이 없어요</p>}
          </nav>

          <section className="presets-editor-pane panel">
            {formOpen ? (
              <form className="preset-form stack loose" aria-label="인물 프리셋 편집" onSubmit={save}>
                <div className="presets-editor-header">
                  <button type="button" className="icon-button presets-back" onClick={closeForm} aria-label="목록으로">
                    <ChevronLeft aria-hidden="true" strokeWidth={2} />
                  </button>
                  <h2 className="grow">{editingId ? (editingPreset?.name ?? draft.name) || "인물 편집" : "새 인물"}</h2>
                  <button type="button" className="icon-button presets-close" onClick={closeForm} aria-label="닫기">
                    <X aria-hidden="true" strokeWidth={1.8} />
                  </button>
                </div>

                <div className="presets-fields">
                  <label className="field">
                    <span className="field-label">이름</span>
                    <input autoFocus={!editingId} required maxLength={80} value={draft.name} onChange={(event) => update("name", event.target.value)} placeholder="아리아" />
                  </label>
                  <label className="field">
                    <span className="field-label">태그</span>
                    <span className="presets-tag-input">
                      <span aria-hidden="true">#</span>
                      <input required maxLength={80} value={draft.tag_name} onChange={(event) => update("tag_name", event.target.value)} placeholder="aria" />
                    </span>
                  </label>
                  <div className="field">
                    <span className="field-label" id="preset-subject-label">종류</span>
                    <div className="segmented block" role="radiogroup" aria-labelledby="preset-subject-label">
                      {SUBJECTS.map((subject) => (
                        <button
                          key={subject.value}
                          type="button"
                          role="radio"
                          aria-checked={draft.subject_type === subject.value}
                          onClick={() => update("subject_type", subject.value)}
                        >
                          {subject.label}
                        </button>
                      ))}
                    </div>
                  </div>
                  <label className="field">
                    <span className="field-label">순서</span>
                    <input type="number" min="-10000" max="10000" value={draft.sort_order} onChange={(event) => update("sort_order", Number(event.target.value))} />
                  </label>
                </div>

                <label className="field">
                  <span className="label-row">
                    <span className="field-label">프롬프트</span>
                    <span className="counter">{draft.prompt.length.toLocaleString()}/{PROMPT_LIMIT.toLocaleString()}</span>
                  </span>
                  <textarea className="presets-prompt" required rows={8} maxLength={PROMPT_LIMIT} value={draft.prompt} onChange={(event) => update("prompt", event.target.value)} placeholder="girl, silver hair, blue eyes, white coat" />
                </label>
                <label className="field">
                  <span className="label-row">
                    <span className="field-label">네거티브</span>
                    <span className="counter">{draft.negative_prompt.length.toLocaleString()}/{PROMPT_LIMIT.toLocaleString()}</span>
                  </span>
                  <textarea className="presets-negative" rows={4} maxLength={PROMPT_LIMIT} value={draft.negative_prompt} onChange={(event) => update("negative_prompt", event.target.value)} placeholder="제외할 요소" />
                </label>

                {error ? <p className="error-message" role="alert">{error}</p> : null}

                <div className="form-actions presets-actions">
                  {editingPreset ? (
                    <button type="button" className="button ghost presets-delete" onClick={() => void remove(editingPreset)}>
                      <Trash2 aria-hidden="true" strokeWidth={1.8} />삭제
                    </button>
                  ) : null}
                  <button type="submit" className="button primary" disabled={saving}>{saving ? "저장 중…" : "저장"}</button>
                </div>
              </form>
            ) : (
              <div className="empty-state presets-editor-empty">
                <strong>인물을 선택해 주세요</strong>
              </div>
            )}
          </section>
        </div>
      ) : (
        <div className="empty-state panel">
          <UserPlus aria-hidden="true" strokeWidth={1.7} />
          <strong>인물이 없어요</strong>
        </div>
      )}
    </div>
  );
}
