import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage } from "./api";
import { GalleryView } from "./components/GalleryView";
import { GenerateView } from "./components/GenerateView";
import { JobsPanel } from "./components/JobsPanel";
import { PresetsView } from "./components/PresetsView";
import { SettingsView } from "./components/SettingsView";
import { StatsView } from "./components/StatsView";
import { DeviceApprovalView } from "./components/DeviceApprovalView";
import { StudioHeader } from "./components/StudioHeader";
import { APP_FONT_STORAGE_KEY, getInitialAppFont } from "./fonts";
import { watchDeviceLayout } from "./device";
import type { AppFontId } from "./fonts";
import { DEFAULT_GENERATION_PARAMETERS } from "./types";
import { canAcceptRemoteDraft, outputSeed, removeDeletedPresetSelections } from "./draftState";
import type { AppStatus, CharacterPreset, CharacterSet, GenerationDraft, GenerationDraftSyncEnvelope, ImageRecord, ImageReuseOptions, QualityPromptPreset, Tab } from "./types";

type Theme = "dark" | "light";
const THEME_STORAGE_KEY = "novelai-lan-studio-theme-v1";

function getInitialTheme(): Theme {
  try {
    return window.localStorage.getItem(THEME_STORAGE_KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

function getDraftClientId(): string {
  const storageKey = "novelai-lan-studio-draft-client-id";
  const createClientId = () => {
    const uuid = globalThis.crypto?.randomUUID?.();
    if (uuid) return `studio-${uuid}`;
    return `studio-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 14)}`;
  };
  try {
    const saved = window.localStorage.getItem(storageKey);
    if (saved) return saved;
    const created = createClientId();
    window.localStorage.setItem(storageKey, created);
    return created;
  } catch {
    return createClientId();
  }
}

export default function App() {
  const [tab, setTab] = useState<Tab>("generate");
  const [theme, setTheme] = useState<Theme>(getInitialTheme);
  const [fontId, setFontId] = useState<AppFontId>(getInitialAppFont);
  const [status, setStatus] = useState<AppStatus | null>(null);
  const [presets, setPresets] = useState<CharacterPreset[]>([]);
  const [characterSets, setCharacterSets] = useState<CharacterSet[]>([]);
  const [qualityPresets, setQualityPresets] = useState<QualityPromptPreset[]>([]);
  const [generationDraft, setGenerationDraft] = useState<GenerationDraft>({
    schema_version: 4,
    quality_prompt: "",
    description_prompt: "",
    quality_preset_id: null,
    quality_negative_prompt: "",
    description_negative_prompt: "",
    nsfw_enabled: false,
    character_preset_ids: [],
    model: "nai-diffusion-5-full",
    parameters: DEFAULT_GENERATION_PARAMETERS,
  });
  const [draftReady, setDraftReady] = useState(false);
  const [draftSyncState, setDraftSyncState] = useState<"synced" | "saving" | "offline">("synced");
  const [draftClientId] = useState(getDraftClientId);
  const [editSource, setEditSource] = useState<ImageRecord | null>(null);
  const [refreshSignal, setRefreshSignal] = useState(0);
  const [jobSignal, setJobSignal] = useState(0);
  const [toast, setToast] = useState("");
  const [bootError, setBootError] = useState("");
  const generationDraftRef = useRef(generationDraft);
  const presetsRef = useRef(presets);
  presetsRef.current = presets;
  const draftRevisionRef = useRef(0);
  const draftDirtyRef = useRef(false);
  const draftSaveInFlightRef = useRef(false);
  const draftSaveQueueRef = useRef<Promise<void>>(Promise.resolve());
  const tabRef = useRef<Tab>(tab);
  const tabHistoryRef = useRef<Tab[]>([]);
  generationDraftRef.current = generationDraft;
  tabRef.current = tab;

  const navigateToTab = useCallback((next: Tab) => {
    setTab((current) => {
      if (current === next) return current;
      tabHistoryRef.current.push(current);
      return next;
    });
  }, []);

  useEffect(() => {
    const target = window as typeof window & { NovelAIStudioBack?: () => boolean };
    target.NovelAIStudioBack = () => {
      const event = new Event("novelai-system-back", { cancelable: true });
      if (!window.dispatchEvent(event)) return true;
      const previous = tabHistoryRef.current.pop();
      if (previous) {
        setTab(previous);
        return true;
      }
      if (tabRef.current !== "generate") {
        setTab("generate");
        return true;
      }
      return false;
    };
    return () => {
      delete target.NovelAIStudioBack;
    };
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute(
      "content",
      theme === "light" ? "#f3eee4" : "#0e0f12",
    );
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      // Theme persistence is best effort in restricted WebViews.
    }
  }, [theme]);

  useEffect(() => watchDeviceLayout((fold) => {
    if (fold) document.documentElement.dataset.device = "fold";
    else delete document.documentElement.dataset.device;
  }), []);

  useEffect(() => {
    document.documentElement.dataset.font = fontId;
    try {
      window.localStorage.setItem(APP_FONT_STORAGE_KEY, fontId);
    } catch {
      // Device-local appearance persistence is best effort in restricted WebViews.
    }
  }, [fontId]);

  const reloadStatus = useCallback(async () => {
    const result = await api<AppStatus>("/api/status");
    setStatus(result);
  }, []);

  const changeGenerationDraft = useCallback((draft: GenerationDraft) => {
    draftDirtyRef.current = true;
    generationDraftRef.current = draft;
    setDraftSyncState("saving");
    setGenerationDraft(draft);
  }, []);

  const enqueueDraftSave = useCallback((draft: GenerationDraft) => {
    const serialized = JSON.stringify(draft);
    draftSaveQueueRef.current = draftSaveQueueRef.current
      .catch(() => undefined)
      .then(async () => {
        draftSaveInFlightRef.current = true;
        setDraftSyncState("saving");
        try {
          const result = await api<GenerationDraftSyncEnvelope>("/api/generation-draft/sync", {
            method: "PUT",
            body: JSON.stringify({ client_id: draftClientId, draft }),
          });
          draftRevisionRef.current = Math.max(draftRevisionRef.current, result.revision);
          if (JSON.stringify(generationDraftRef.current) === serialized) {
            draftDirtyRef.current = false;
            setDraftSyncState("synced");
          }
        } catch {
          setDraftSyncState("offline");
        } finally {
          draftSaveInFlightRef.current = false;
        }
      });
  }, [draftClientId]);

  const reloadCharacterSets = useCallback(async () => {
    const result = await api<{ items: CharacterSet[] }>("/api/character-sets");
    setCharacterSets(result.items);
  }, []);

  const reloadPresets = useCallback(async () => {
    const previouslyKnown = presetsRef.current.map((preset) => preset.id);
    const [result, setResult] = await Promise.all([
      api<{ items: CharacterPreset[] }>("/api/presets"),
      api<{ items: CharacterSet[] }>("/api/character-sets"),
    ]);
    setPresets(result.items);
    setCharacterSets(setResult.items);
    const validIds = new Set(result.items.map((preset) => preset.id));
    setGenerationDraft((current) => {
      const characterPresetIds = removeDeletedPresetSelections(current.character_preset_ids, previouslyKnown, [...validIds]);
      if (characterPresetIds.length === current.character_preset_ids.length) return current;
      const next = { ...current, character_preset_ids: characterPresetIds };
      generationDraftRef.current = next;
      draftDirtyRef.current = true;
      setDraftSyncState("saving");
      return next;
    });
  }, []);

  const reloadQualityPresets = useCallback(async () => {
    const result = await api<{ items: QualityPromptPreset[] }>("/api/quality-presets");
    setQualityPresets(result.items);
    const validIds = new Set(result.items.map((preset) => preset.id));
    setGenerationDraft((current) => {
      if (!current.quality_preset_id || validIds.has(current.quality_preset_id)) return current;
      const next = { ...current, quality_preset_id: null };
      generationDraftRef.current = next;
      draftDirtyRef.current = true;
      setDraftSyncState("saving");
      return next;
    });
  }, []);

  useEffect(() => {
    let active = true;
    const boot = async () => {
      try {
        const statusResult = await api<AppStatus>("/api/status");
        if (!active) return;
        setStatus(statusResult);
        if (statusResult.device_approval_required && !statusResult.device_authorized) return;
        const [presetResult, qualityPresetResult, characterSetResult, syncResult] = await Promise.all([
          api<{ items: CharacterPreset[] }>("/api/presets"),
          api<{ items: QualityPromptPreset[] }>("/api/quality-presets"),
          api<{ items: CharacterSet[] }>("/api/character-sets"),
          api<GenerationDraftSyncEnvelope>("/api/generation-draft/sync"),
        ]);
        if (!active) return;
        setPresets(presetResult.items);
        setQualityPresets(qualityPresetResult.items);
        setCharacterSets(characterSetResult.items);
        const validIds = new Set(presetResult.items.map((preset) => preset.id));
        const validQualityPresetIds = new Set(qualityPresetResult.items.map((preset) => preset.id));
        const characterPresetIds = syncResult.draft.character_preset_ids;
        if (characterPresetIds.some((id) => !validIds.has(id))) void reloadPresets();
        const qualityPresetId = syncResult.draft.quality_preset_id;
        const sanitizedDraft = {
          ...syncResult.draft,
          character_preset_ids: characterPresetIds,
          quality_preset_id: qualityPresetId,
        };
        draftRevisionRef.current = syncResult.revision;
        generationDraftRef.current = sanitizedDraft;
        draftDirtyRef.current = characterPresetIds.length !== syncResult.draft.character_preset_ids.length;
        setDraftSyncState(draftDirtyRef.current ? "saving" : "synced");
        setGenerationDraft(sanitizedDraft);
        setDraftReady(true);
        if (qualityPresetId && !validQualityPresetIds.has(qualityPresetId)) {
          void reloadQualityPresets();
        }
      } catch (error) {
        if (active) setBootError(errorMessage(error));
      }
    };
    void boot();
    return () => { active = false; };
  }, [reloadQualityPresets, reloadPresets]);

  useEffect(() => {
    if (!status?.admin_available) return;
    const timer = window.setInterval(() => {
      void reloadStatus().catch(() => undefined);
    }, 3_000);
    return () => window.clearInterval(timer);
  }, [reloadStatus, status?.admin_available]);

  useEffect(() => {
    const authorizationLost = () => {
      void reloadStatus().catch(() => undefined);
    };
    window.addEventListener("novelai-device-authorization-lost", authorizationLost);
    return () => window.removeEventListener("novelai-device-authorization-lost", authorizationLost);
  }, [reloadStatus]);

  useEffect(() => {
    if (!draftReady || !draftDirtyRef.current) return;
    const timer = window.setTimeout(() => {
      enqueueDraftSave(generationDraft);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [draftReady, enqueueDraftSave, generationDraft]);

  useEffect(() => {
    if (!draftReady) return;
    let active = true;
    const sync = async () => {
      if (draftDirtyRef.current) {
        if (!draftSaveInFlightRef.current) enqueueDraftSave(generationDraftRef.current);
        return;
      }
      if (draftSaveInFlightRef.current) return;
      try {
        const remote = await api<GenerationDraftSyncEnvelope>("/api/generation-draft/sync");
        if (!active || !canAcceptRemoteDraft(remote.revision, draftRevisionRef.current, draftDirtyRef.current, draftSaveInFlightRef.current)) return;
        const validIds = new Set(presets.map((preset) => preset.id));
        const validQualityPresetIds = new Set(qualityPresets.map((preset) => preset.id));
        const characterPresetIds = remote.draft.character_preset_ids;
        if (characterPresetIds.some((id) => !validIds.has(id))) await reloadPresets();
        const qualityPresetId = remote.draft.quality_preset_id;
        if (qualityPresetId && !validQualityPresetIds.has(qualityPresetId)) {
          await reloadQualityPresets();
        }
        if (!active || !canAcceptRemoteDraft(remote.revision, draftRevisionRef.current, draftDirtyRef.current, draftSaveInFlightRef.current)) return;
        const next = {
          ...remote.draft,
          character_preset_ids: characterPresetIds,
          quality_preset_id: qualityPresetId,
        };
        draftRevisionRef.current = remote.revision;
        draftDirtyRef.current = characterPresetIds.length !== remote.draft.character_preset_ids.length;
        generationDraftRef.current = next;
        setGenerationDraft(next);
        setDraftSyncState(draftDirtyRef.current ? "saving" : "synced");
      } catch {
        if (active) setDraftSyncState("offline");
      }
    };
    void sync();
    const timer = window.setInterval(() => void sync(), 1_500);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [draftReady, enqueueDraftSave, presets, qualityPresets, reloadQualityPresets, reloadPresets]);

  useEffect(() => {
    if (!draftReady) return;
    const flush = () => {
      if (!draftDirtyRef.current) return;
      void fetch("/api/generation-draft/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ client_id: draftClientId, draft: generationDraftRef.current }),
        keepalive: true,
      });
    };
    window.addEventListener("pagehide", flush);
    return () => window.removeEventListener("pagehide", flush);
  }, [draftClientId, draftReady]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 4200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const notify = useCallback((message: string) => setToast(message), []);
  const markChanged = useCallback(() => setRefreshSignal((value) => value + 1), []);

  const editImage = (image: ImageRecord) => {
    setEditSource(image);
    navigateToTab("generate");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const reuseImage = (image: ImageRecord, options: ImageReuseOptions) => {
    const current = generationDraftRef.current;
    const savedParameters = { ...DEFAULT_GENERATION_PARAMETERS, ...image.settings };
    const imageQualityPrompt = image.quality_prompt ?? "";
    const imageDescriptionPrompt = image.description_prompt ?? image.prompt;
    const imageHasNsfwPrefix = /^\s*nsfw\s*,\s*uncensored(?:\s*,|\s*$)/i.test(imageDescriptionPrompt);
    const imageNsfwEnabled = image.settings.nsfw_enabled === true || imageHasNsfwPrefix;
    const importedDescriptionPrompt = options.nsfw_enabled && imageHasNsfwPrefix
      ? imageDescriptionPrompt.replace(/^\s*nsfw\s*,\s*uncensored\s*,?\s*/i, "")
      : imageDescriptionPrompt;
    const parameters = { ...current.parameters };
    if (options.dimensions) {
      parameters.width = savedParameters.width;
      parameters.height = savedParameters.height;
    }
    if (options.steps) parameters.steps = savedParameters.steps;
    if (options.guidance) parameters.guidance = savedParameters.guidance;
    if (options.guidance_rescale) parameters.guidance_rescale = savedParameters.guidance_rescale;
    if (options.sampler) {
      parameters.sampler = savedParameters.sampler;
      parameters.noise_schedule = savedParameters.noise_schedule ?? "karras";
    }
    if (options.quality) parameters.quality = savedParameters.quality;
    if (options.seed) parameters.seed = outputSeed(image);
    if (options.count) parameters.count = savedParameters.count;
    if (options.strength_noise) {
      parameters.strength = savedParameters.strength;
      parameters.noise = savedParameters.noise;
    }

    const availablePresetIds = new Set(presets.map((preset) => preset.id));
    const snapshotPresetIds = image.character_snapshot.flatMap((item) => {
      const presetId = item.preset_id;
      return typeof presetId === "string" && availablePresetIds.has(presetId) ? [presetId] : [];
    });
    const imageTagIds = new Set(image.tags.map((tag) => tag.id));
    const tagMatchedPresetIds = presets
      .filter((preset) => imageTagIds.has(preset.tag_id))
      .map((preset) => preset.id);
    const importedPresetIds = Array.from(new Set([...snapshotPresetIds, ...tagMatchedPresetIds]));
    const baseModel = image.model.replace(/-inpainting$/, "");
    const importedModel = status?.models.some((item) => item.id === baseModel) ? baseModel : current.model;
    const matchingQualityPreset = qualityPresets.find(
      (preset) => preset.prompt.trim() === imageQualityPrompt.trim(),
    );

    changeGenerationDraft({
      ...current,
      quality_prompt: options.quality_prompt ? imageQualityPrompt : current.quality_prompt,
      description_prompt: options.description_prompt
        ? importedDescriptionPrompt
        : current.description_prompt,
      quality_preset_id: options.quality_prompt
        ? matchingQualityPreset?.id ?? null
        : current.quality_preset_id,
      quality_negative_prompt: options.quality_negative_prompt
        ? image.quality_negative_prompt ?? image.negative_prompt ?? ""
        : current.quality_negative_prompt,
      description_negative_prompt: options.description_negative_prompt
        ? image.description_negative_prompt ?? ""
        : current.description_negative_prompt,
      nsfw_enabled: options.nsfw_enabled ? imageNsfwEnabled : current.nsfw_enabled,
      character_preset_ids: options.character_presets ? importedPresetIds : current.character_preset_ids,
      model: options.model ? importedModel : current.model,
      parameters,
    });
    setEditSource(null);
    navigateToTab("generate");
    notify("프롬프트와 설정을 가져왔어요");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const submitNotice = (message: string) => {
    notify(message);
    setJobSignal((value) => value + 1);
  };

  if (bootError) {
    return (
      <main className="boot-screen">
        <img src="/app-icon.png" alt="" />
        <h1>스튜디오에 연결하지 못했어요</h1>
        <p>{bootError}</p>
        <button type="button" className="button primary" onClick={() => window.location.reload()}>다시 연결</button>
      </main>
    );
  }

  if (!status) {
    return <main className="boot-screen" aria-busy="true"><img src="/app-icon.png" alt="" /><div className="spinner" aria-hidden="true" /><p role="status">여는 중…</p></main>;
  }

  if (status.device_approval_required && !status.device_authorized) {
    return <DeviceApprovalView onAuthorized={() => window.location.reload()} />;
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#studio-content">본문으로 건너뛰기</a>
      <div className="app-content">
        <StudioHeader tab={tab} onNavigate={navigateToTab} status={status} theme={theme} onToggleTheme={() => setTheme((current) => current === "dark" ? "light" : "dark")} notify={notify} />

        <main className={tab === "generate" ? "page-content workbench-page" : "page-content"} id="studio-content" tabIndex={-1}>
          {tab === "generate" ? <GenerateView status={status} presets={presets} characterSets={characterSets} reloadCharacterSets={reloadCharacterSets} qualityPresets={qualityPresets} reloadQualityPresets={reloadQualityPresets} notify={notify} generationDraft={generationDraft} onGenerationDraftChange={changeGenerationDraft} syncStatus={draftSyncState} initialSource={editSource} onInitialSourceConsumed={() => setEditSource(null)} onSubmitted={submitNotice} /> : null}
          {tab === "gallery" ? <GalleryView refreshSignal={refreshSignal} onEdit={editImage} onReuse={reuseImage} onChanged={markChanged} notify={notify} /> : null}
          {tab === "presets" ? <PresetsView presets={presets} reload={reloadPresets} notify={notify} /> : null}
          {tab === "stats" ? <StatsView refreshSignal={refreshSignal} /> : null}
          {tab === "settings" ? <SettingsView status={status} reloadStatus={reloadStatus} notify={notify} fontId={fontId} onFontChange={setFontId} /> : null}
          <JobsPanel refreshSignal={jobSignal} onGalleryChanged={markChanged} />
        </main>
      </div>

      {toast ? <div className="toast" role="status">{toast}</div> : null}
    </div>
  );
}
