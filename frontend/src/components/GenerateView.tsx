import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowDown, ArrowLeftRight, ArrowUp, FolderPlus, RotateCw, Save, Trash2, Upload, X } from "lucide-react";
import "../generate.css";
import { api, errorMessage, uploadFile } from "../api";
import { estimateAnlasCost, NORMAL_PIXEL_LIMIT } from "../anlas";
import type {
  AnlasStatus,
  AppStatus,
  CharacterPreset,
  CharacterSet,
  DirectorInput,
  GenerationDraft,
  GenerationMode,
  GenerationRequest,
  ImageRecord,
  Job,
  QualityPromptPreset,
  UploadAsset,
} from "../types";
import { InpaintCanvas, type InpaintCanvasHandle } from "./InpaintCanvas";
import {
  ReferencePanel,
  type CharacterReferenceItem,
  type ReferenceTab,
  type VibeReferenceItem,
} from "./ReferencePanel";
import { DEFAULT_DIRECTOR, DirectorPanel } from "./DirectorPanel";
import { DEFAULT_GENERATION_PARAMETERS } from "../types";
import { parseRepeatCount } from "../sequentialGeneration";

const MODES: Array<{ id: GenerationMode; label: string; action: string }> = [
  { id: "txt2img", label: "새 이미지", action: "생성" },
  { id: "img2img", label: "변형", action: "변형" },
  { id: "inpaint", label: "인페인트", action: "인페인트" },
  { id: "upscale", label: "업스케일", action: "업스케일" },
  { id: "director", label: "디렉터", action: "적용" },
];

const SIZE_PRESET_GROUPS = [
  {
    id: "square",
    label: "1:1",
    description: "정사각형",
    presets: [
      { id: "small-square", label: "소형", ratio: "1:1", width: 640, height: 640 },
      { id: "normal-square", label: "기본", ratio: "1:1", width: 1024, height: 1024 },
      { id: "large-square", label: "대형", ratio: "1:1", width: 1472, height: 1472 },
    ],
  },
  {
    id: "portrait-classic",
    label: "2:3 계열",
    description: "일반 세로형",
    presets: [
      { id: "small-portrait", label: "소형", ratio: "2:3", width: 512, height: 768 },
      { id: "normal-portrait", label: "기본", ratio: "13:19", width: 832, height: 1216 },
      { id: "large-portrait", label: "대형", ratio: "2:3", width: 1024, height: 1536 },
    ],
  },
  {
    id: "portrait-wide",
    label: "9:16 계열",
    description: "긴 세로형",
    presets: [
      { id: "portrait-9x16", label: "정확한 9:16", ratio: "9:16", width: 576, height: 1024 },
      { id: "wallpaper-portrait", label: "배경화면", ratio: "17:30", width: 1088, height: 1920 },
    ],
  },
  {
    id: "galaxy-z-fold7-cover",
    label: "9:21",
    description: "Galaxy Z Fold7 외부 디스플레이",
    presets: [
      { id: "fold7-cover-portrait", label: "Fold7 외부", ratio: "9:21", width: 768, height: 1792 },
    ],
  },
  {
    id: "galaxy-z-fold7-main",
    label: "9:10",
    description: "Galaxy Z Fold7 내부 · 원본 82:91 근사",
    presets: [
      { id: "fold7-main-portrait", label: "Fold7 내부", ratio: "9:10 (≈82:91)", width: 1152, height: 1280 },
    ],
  },
  {
    id: "ipad-air4",
    label: "16:23",
    description: "iPad Air 4 · 원본 41:59 근사",
    presets: [
      { id: "ipad-air4-portrait", label: "iPad Air 4", ratio: "16:23 (≈41:59)", width: 1024, height: 1472 },
    ],
  },
  {
    id: "landscape-classic",
    label: "3:2 계열",
    description: "일반 가로형",
    presets: [
      { id: "small-landscape", label: "소형", ratio: "3:2", width: 768, height: 512 },
      { id: "normal-landscape", label: "기본", ratio: "19:13", width: 1216, height: 832 },
      { id: "large-landscape", label: "대형", ratio: "3:2", width: 1536, height: 1024 },
    ],
  },
  {
    id: "landscape-wide",
    label: "16:9 계열",
    description: "긴 가로형",
    presets: [
      { id: "landscape-16x9", label: "정확한 16:9", ratio: "16:9", width: 1024, height: 576 },
      { id: "wallpaper-landscape", label: "배경화면", ratio: "30:17", width: 1920, height: 1088 },
    ],
  },
] as const;

function formatLimitDuration(seconds: number | null): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return "충전 완료";
  const totalMinutes = Math.max(1, Math.ceil(seconds / 60));
  const days = Math.floor(totalMinutes / 1_440);
  const hours = Math.floor((totalMinutes % 1_440) / 60);
  const minutes = totalMinutes % 60;
  if (days > 0) return `${days}일 ${hours}시간`;
  if (hours > 0) return `${hours}시간 ${minutes}분`;
  return `${minutes}분`;
}

interface Props {
  status: AppStatus;
  presets: CharacterPreset[];
  characterSets: CharacterSet[];
  reloadCharacterSets: () => Promise<void>;
  qualityPresets: QualityPromptPreset[];
  reloadQualityPresets: () => Promise<void>;
  notify: (message: string) => void;
  generationDraft: GenerationDraft;
  onGenerationDraftChange: (draft: GenerationDraft) => void;
  syncStatus: "synced" | "saving" | "offline";
  initialSource: ImageRecord | null;
  onInitialSourceConsumed: () => void;
  onSubmitted: (message: string) => void;
}

type SourceAsset = ImageRecord | UploadAsset;

const REFERENCES_STORAGE_KEY = "novelai-lan-studio-references-v1";

interface StoredReferences {
  tab: ReferenceTab;
  character: CharacterReferenceItem[];
  vibe: VibeReferenceItem[];
  director: DirectorInput;
}

function loadStoredReferences(): StoredReferences {
  const fallback: StoredReferences = { tab: "character", character: [], vibe: [], director: DEFAULT_DIRECTOR };
  try {
    const raw = window.localStorage.getItem(REFERENCES_STORAGE_KEY);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<StoredReferences>;
    return {
      tab: parsed.tab === "vibe" ? "vibe" : "character",
      character: Array.isArray(parsed.character) ? parsed.character : [],
      vibe: Array.isArray(parsed.vibe) ? parsed.vibe : [],
      director: { ...DEFAULT_DIRECTOR, ...(parsed.director ?? {}) },
    };
  } catch {
    return fallback;
  }
}

export function GenerateView({
  status,
  presets,
  characterSets,
  reloadCharacterSets,
  qualityPresets,
  reloadQualityPresets,
  notify,
  generationDraft,
  onGenerationDraftChange,
  syncStatus,
  initialSource,
  onInitialSourceConsumed,
  onSubmitted,
}: Props) {
  const [mode, setMode] = useState<GenerationMode>("txt2img");
  const [sources, setSources] = useState<SourceAsset[]>([]);
  const [selectedSource, setSelectedSource] = useState<SourceAsset | null>(null);
  const [loadingSources, setLoadingSources] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [repeatCountInput, setRepeatCountInput] = useState("1");
  const repeatCount = parseRepeatCount(repeatCountInput);
  const submitInFlightRef = useRef(false);
  const [error, setError] = useState("");
  const [promptTab, setPromptTab] = useState<"quality" | "description" | "nsfw">("description");
  const [advanced, setAdvanced] = useState(false);
  const [anlasStatus, setAnlasStatus] = useState<AnlasStatus | null>(null);
  const [anlasLoading, setAnlasLoading] = useState(false);
  const [anlasError, setAnlasError] = useState("");
  const [qualityPresetModalOpen, setQualityPresetModalOpen] = useState(false);
  const [qualityPresetName, setQualityPresetName] = useState("");
  const [qualityPresetSaving, setQualityPresetSaving] = useState(false);
  const [qualityPresetError, setQualityPresetError] = useState("");
  const [characterSetModalOpen, setCharacterSetModalOpen] = useState(false);
  const [characterSetName, setCharacterSetName] = useState("");
  const [characterSetSaving, setCharacterSetSaving] = useState(false);
  const [characterSetError, setCharacterSetError] = useState("");
  const maskRef = useRef<InpaintCanvasHandle>(null);
  const [storedReferences] = useState(loadStoredReferences);
  const [referenceTab, setReferenceTab] = useState<ReferenceTab>(storedReferences.tab);
  const [characterRefs, setCharacterRefs] = useState<CharacterReferenceItem[]>(storedReferences.character);
  const [vibes, setVibes] = useState<VibeReferenceItem[]>(storedReferences.vibe);
  const [director, setDirector] = useState<DirectorInput>(storedReferences.director);
  const usesReferences = mode === "txt2img" || mode === "img2img" || mode === "inpaint";
  const usesPrompt = mode !== "upscale" && mode !== "director";
  const qualityPrompt = generationDraft.quality_prompt;
  const descriptionPrompt = generationDraft.description_prompt;
  const qualityNegativePrompt = generationDraft.quality_negative_prompt;
  const descriptionNegativePrompt = generationDraft.description_negative_prompt;
  const nsfwPrompt = generationDraft.nsfw_prompt ?? "";
  const selectedPresetIds = generationDraft.character_preset_ids;
  const model = generationDraft.model;
  const parameters = generationDraft.parameters;
  const selectedQualityPreset = qualityPresets.find(
    (preset) => preset.id === generationDraft.quality_preset_id,
  );
  const qualityPresetChanged = Boolean(
    selectedQualityPreset
    && (
      selectedQualityPreset.prompt !== qualityPrompt
      || (Boolean(selectedQualityPreset.negative_prompt) && selectedQualityPreset.negative_prompt !== qualityNegativePrompt)
    ),
  );

  const refreshAnlas = useCallback(async (force = false) => {
    if (!status.has_token) {
      setAnlasStatus(null);
      setAnlasError("");
      return;
    }
    setAnlasLoading(true);
    try {
      const result = await api<AnlasStatus>(`/api/anlas${force ? "?refresh=true" : ""}`);
      setAnlasStatus(result);
      setAnlasError("");
    } catch (balanceError) {
      setAnlasError(errorMessage(balanceError));
    } finally {
      setAnlasLoading(false);
    }
  }, [status.has_token]);

  useEffect(() => {
    void refreshAnlas();
    if (!status.has_token) return;
    const timer = window.setInterval(() => void refreshAnlas(true), 30_000);
    return () => window.clearInterval(timer);
  }, [refreshAnlas, status.has_token]);

  const loadSources = useCallback(async () => {
    setLoadingSources(true);
    try {
      const [images, uploads] = await Promise.all([
        api<{ items: ImageRecord[] }>("/api/images?page=1"),
        api<{ items: UploadAsset[] }>("/api/uploads"),
      ]);
      setSources([...images.items, ...uploads.items]);
    } catch (loadError) {
      setError(errorMessage(loadError));
    } finally {
      setLoadingSources(false);
    }
  }, []);

  useEffect(() => {
    if (mode !== "txt2img") void loadSources();
  }, [loadSources, mode]);

  useEffect(() => {
    if (!initialSource) return;
    setMode("img2img");
    setSelectedSource(initialSource);
    const inherited = presets
      .filter((preset) => initialSource.tags.some((tag) => tag.id === preset.tag_id))
      .map((preset) => preset.id);
    const sourceQualityPrompt = initialSource.quality_prompt ?? "";
    const sourceDescriptionPrompt = initialSource.description_prompt ?? initialSource.prompt;
    const sourceQualityNegativePrompt = initialSource.quality_negative_prompt
      ?? initialSource.negative_prompt
      ?? "";
    const sourceDescriptionNegativePrompt = initialSource.description_negative_prompt ?? "";
    const matchingQualityPreset = qualityPresets.find(
      (preset) => preset.prompt.trim() === sourceQualityPrompt.trim(),
    );
    onGenerationDraftChange({
      ...generationDraft,
      quality_prompt: sourceQualityPrompt,
      description_prompt: sourceDescriptionPrompt,
      quality_preset_id: matchingQualityPreset?.id ?? null,
      quality_negative_prompt: sourceQualityNegativePrompt,
      description_negative_prompt: sourceDescriptionNegativePrompt,
      nsfw_enabled: initialSource.settings.nsfw_enabled === true,
      character_preset_ids: inherited,
      model: status.models.some((item) => item.id === initialSource.model)
        ? initialSource.model
        : generationDraft.model,
      parameters: {
        ...DEFAULT_GENERATION_PARAMETERS,
        ...initialSource.settings,
        count: 1,
      },
    });
    onInitialSourceConsumed();
  }, [generationDraft, initialSource, onGenerationDraftChange, onInitialSourceConsumed, presets, qualityPresets, status.models]);

  const selectedPresets = useMemo(() => {
    const map = new Map(presets.map((preset) => [preset.id, preset]));
    return selectedPresetIds.flatMap((id) => {
      const preset = map.get(id);
      return preset ? [preset] : [];
    });
  }, [presets, selectedPresetIds]);

  const modelSpec = status.models.find((item) => item.id === model) ?? status.models[0];

  useEffect(() => {
    try {
      window.localStorage.setItem(REFERENCES_STORAGE_KEY, JSON.stringify({
        tab: referenceTab,
        character: characterRefs,
        vibe: vibes,
        director,
      } satisfies StoredReferences));
    } catch {
      // Storage can be unavailable (private mode); references just won't persist.
    }
  }, [characterRefs, director, referenceTab, vibes]);

  // Only the active reference kind is sent, and only when the model supports it.
  const activeCharacterRefs = usesReferences && referenceTab === "character" && modelSpec?.supports_character_reference
    ? characterRefs
    : [];
  const activeVibes = usesReferences && referenceTab === "vibe" && modelSpec?.supports_vibe_transfer ? vibes : [];
  const anlasEstimate = useMemo(() => estimateAnlasCost({
    mode,
    model,
    parameters,
    account: anlasStatus,
    source_width: selectedSource?.width,
    source_height: selectedSource?.height,
    director_tool: director.tool,
    character_reference_count: activeCharacterRefs.length,
    vibe_count: activeVibes.length,
  }), [activeCharacterRefs.length, activeVibes.length, anlasStatus, director.tool, mode, model, parameters, selectedSource?.height, selectedSource?.width]);
  const totalEstimate = anlasEstimate.total === null || repeatCount === null ? null : anlasEstimate.total * repeatCount;
  const estimatedCostLabel = totalEstimate === null
    ? "—"
    : `${totalEstimate.toLocaleString()} ANLAS`;
  const remainingAnlasLabel = anlasLoading && !anlasStatus
    ? "조회 중…"
    : anlasStatus?.remaining_anlas == null
      ? status.has_token ? "조회 실패" : "토큰 필요"
      : `${anlasStatus.remaining_anlas.toLocaleString()} ANLAS`;
  const insufficientAnlas = totalEstimate !== null
    && anlasStatus?.remaining_anlas !== null
    && anlasStatus?.remaining_anlas !== undefined
    && totalEstimate > anlasStatus.remaining_anlas;
  const rawUsagePercent = anlasStatus?.usage_percent;
  const usageLimitPercent = anlasStatus?.usage_is_negative
    ? 0
    : rawUsagePercent == null
      ? 0
      : Math.min(100, Math.max(0, rawUsagePercent));
  const usageLimitLabel = anlasLoading && !anlasStatus
    ? "조회 중…"
    : anlasStatus?.tier !== 3
      ? "Opus 전용"
      : anlasStatus.usage_is_negative
        ? "소진됨"
        : rawUsagePercent == null
          ? "정보 없음"
          : `${usageLimitPercent}%`;
  const rechargeSecondsPerPercent = (
    anlasStatus?.usage_time_until_next_percent != null
    && Number.isFinite(anlasStatus.usage_time_until_next_percent)
    && anlasStatus.usage_time_until_next_percent > 0
  ) ? anlasStatus.usage_time_until_next_percent : null;
  const fullRechargeSeconds = rechargeSecondsPerPercent == null
    ? null
    : rechargeSecondsPerPercent * Math.max(0, 100 - usageLimitPercent);
  const usageLimitNote = anlasStatus?.tier !== 3
    ? ""
    : anlasStatus.usage_is_negative
      ? "Anlas 차감 중"
      : usageLimitPercent >= 100
        ? "가득 참"
        : rechargeSecondsPerPercent == null || fullRechargeSeconds == null
          ? ""
          : `완충까지 ${formatLimitDuration(fullRechargeSeconds)}`;

  const togglePreset = (presetId: string) => {
    const next = selectedPresetIds.includes(presetId)
      ? selectedPresetIds.filter((id) => id !== presetId)
      : [...selectedPresetIds, presetId];
    onGenerationDraftChange({ ...generationDraft, character_preset_ids: next });
  };

  const movePreset = (index: number, direction: -1 | 1) => {
    const next = [...selectedPresetIds];
    const target = index + direction;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    onGenerationDraftChange({ ...generationDraft, character_preset_ids: next });
  };

  const characterSetIsActive = (characterSet: CharacterSet) => (
    characterSet.preset_ids.length === selectedPresetIds.length
    && characterSet.preset_ids.every((id, index) => id === selectedPresetIds[index])
  );

  const applyCharacterSet = (characterSet: CharacterSet) => {
    if (characterSet.preset_ids.length > (modelSpec?.max_characters ?? 0)) {
      setError(
        `${modelSpec?.label}은 인물을 ${modelSpec?.max_characters}명까지 넣을 수 있어요. V5 모델로 바꿔 주세요`,
      );
      return;
    }
    setError("");
    onGenerationDraftChange({
      ...generationDraft,
      character_preset_ids: [...characterSet.preset_ids],
    });
    notify(`‘${characterSet.name}’ 세트를 적용했어요`);
  };

  const openCharacterSetSave = () => {
    if (selectedPresetIds.length < 2) {
      setError("인물을 2명 이상 골라 주세요");
      return;
    }
    setCharacterSetName("");
    setCharacterSetError("");
    setCharacterSetModalOpen(true);
  };

  const createCharacterSet = async (event: React.FormEvent) => {
    event.preventDefault();
    setCharacterSetSaving(true);
    setCharacterSetError("");
    try {
      const created = await api<CharacterSet>("/api/character-sets", {
        method: "POST",
        body: JSON.stringify({
          name: characterSetName.trim(),
          preset_ids: selectedPresetIds,
        }),
      });
      await reloadCharacterSets();
      setCharacterSetModalOpen(false);
      notify(`‘${created.name}’ 세트를 저장했어요`);
    } catch (saveError) {
      setCharacterSetError(errorMessage(saveError));
    } finally {
      setCharacterSetSaving(false);
    }
  };

  const deleteCharacterSet = async (characterSet: CharacterSet) => {
    if (!window.confirm(`‘${characterSet.name}’ 세트를 삭제할까요?`)) return;
    setError("");
    try {
      await api(`/api/character-sets/${characterSet.id}`, { method: "DELETE" });
      await reloadCharacterSets();
      notify(`‘${characterSet.name}’ 세트를 삭제했어요`);
    } catch (deleteError) {
      setError(errorMessage(deleteError));
    }
  };

  const chooseSource = (source: SourceAsset) => {
    setSelectedSource(source);
    if ("tags" in source) {
      onGenerationDraftChange({
        ...generationDraft,
        character_preset_ids: presets
          .filter((preset) => source.tags.some((tag) => tag.id === preset.tag_id))
          .map((preset) => preset.id),
      });
    } else {
      onGenerationDraftChange({ ...generationDraft, character_preset_ids: [] });
    }
  };

  const uploadReference = async (file: File): Promise<SourceAsset | null> => {
    setError("");
    try {
      const uploaded = await uploadFile<UploadAsset>("/api/uploads", file);
      setSources((current) => [uploaded, ...current]);
      return uploaded;
    } catch (uploadError) {
      setError(errorMessage(uploadError));
      return null;
    }
  };

  const handleUpload = async (file: File | undefined) => {
    if (!file) return;
    setError("");
    try {
      const uploaded = await uploadFile<UploadAsset>("/api/uploads", file);
      setSources((current) => [uploaded, ...current]);
      setSelectedSource(uploaded);
    } catch (uploadError) {
      setError(errorMessage(uploadError));
    }
  };

  const updateNumber = (field: keyof GenerationDraft["parameters"], value: number | null) => {
    onGenerationDraftChange({
      ...generationDraft,
      parameters: { ...parameters, [field]: value },
    });
  };

  const selectQualityPreset = (presetId: string) => {
    if (!presetId) {
      onGenerationDraftChange({ ...generationDraft, quality_preset_id: null });
      return;
    }
    const preset = qualityPresets.find((item) => item.id === presetId);
    if (!preset) return;
    onGenerationDraftChange({
      ...generationDraft,
      quality_prompt: preset.prompt,
      // Presets saved before negatives were supported leave the current negative alone.
      quality_negative_prompt: preset.negative_prompt || generationDraft.quality_negative_prompt,
      quality_preset_id: preset.id,
    });
  };

  const openQualityPresetSave = () => {
    if (!qualityPrompt.trim()) {
      setError("품질 프롬프트를 먼저 입력해 주세요");
      return;
    }
    setQualityPresetName("");
    setQualityPresetError("");
    setQualityPresetModalOpen(true);
  };

  const createQualityPreset = async (event: React.FormEvent) => {
    event.preventDefault();
    setQualityPresetSaving(true);
    setQualityPresetError("");
    try {
      const created = await api<QualityPromptPreset>("/api/quality-presets", {
        method: "POST",
        body: JSON.stringify({
          name: qualityPresetName.trim(),
          prompt: qualityPrompt.trim(),
          negative_prompt: qualityNegativePrompt.trim(),
          sort_order: qualityPresets.length * 10,
        }),
      });
      onGenerationDraftChange({ ...generationDraft, quality_preset_id: created.id });
      await reloadQualityPresets();
      setQualityPresetModalOpen(false);
      notify(`‘${created.name}’ 프리셋을 저장했어요`);
    } catch (saveError) {
      setQualityPresetError(errorMessage(saveError));
    } finally {
      setQualityPresetSaving(false);
    }
  };

  const updateQualityPreset = async () => {
    if (!selectedQualityPreset || !qualityPrompt.trim()) return;
    setError("");
    try {
      await api<QualityPromptPreset>(`/api/quality-presets/${selectedQualityPreset.id}`, {
        method: "PUT",
        body: JSON.stringify({
          name: selectedQualityPreset.name,
          prompt: qualityPrompt.trim(),
          negative_prompt: qualityNegativePrompt.trim(),
          sort_order: selectedQualityPreset.sort_order,
        }),
      });
      await reloadQualityPresets();
      notify(`‘${selectedQualityPreset.name}’ 프리셋을 덮어썼어요`);
    } catch (updateError) {
      setError(errorMessage(updateError));
    }
  };

  const deleteQualityPreset = async () => {
    if (!selectedQualityPreset) return;
    if (!window.confirm(`‘${selectedQualityPreset.name}’ 프리셋을 삭제할까요?`)) return;
    setError("");
    try {
      await api(`/api/quality-presets/${selectedQualityPreset.id}`, { method: "DELETE" });
      onGenerationDraftChange({ ...generationDraft, quality_preset_id: null });
      await reloadQualityPresets();
      notify("프리셋을 삭제했어요");
    } catch (deleteError) {
      setError(errorMessage(deleteError));
    }
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (submitInFlightRef.current) return;
    setError("");
    if (repeatCount === null) {
      setError("연속 횟수는 1~100 사이로 입력해 주세요");
      return;
    }
    if (!status.has_token) {
      setError("설정에서 NovelAI 토큰을 먼저 등록해 주세요");
      return;
    }
    if (mode !== "txt2img" && !selectedSource) {
      setError("원본 이미지를 골라 주세요");
      return;
    }
    if (selectedPresetIds.length > (modelSpec?.max_characters ?? 0)) {
      setError(`${modelSpec?.label}은 인물을 ${modelSpec?.max_characters}명까지 넣을 수 있어요`);
      return;
    }
    if (usesPrompt && !descriptionPrompt.trim()) {
      setPromptTab("description");
      setError("묘사 프롬프트를 입력해 주세요");
      return;
    }
    submitInFlightRef.current = true;
    setSubmitting(true);
    try {
      let maskId: string | null = null;
      if (mode === "inpaint") {
        if (!maskRef.current?.hasMask()) throw new Error("바꿀 영역을 칠해 주세요");
        const maskBlob = await maskRef.current.exportMask();
        const maskFile = new File([maskBlob], "inpaint-mask.png", { type: "image/png" });
        const mask = await uploadFile<{ id: string }>("/api/masks", maskFile, {
          source_asset_id: selectedSource?.id ?? "",
        });
        maskId = mask.id;
      }
      const body: GenerationRequest = {
        mode,
        repeat_count: repeatCount,
        model,
        quality_prompt: usesPrompt ? qualityPrompt.trim() : "",
        description_prompt: usesPrompt ? descriptionPrompt.trim() : "",
        quality_negative_prompt: usesPrompt ? qualityNegativePrompt.trim() : "",
        description_negative_prompt: usesPrompt ? descriptionNegativePrompt.trim() : "",
        nsfw_enabled: usesPrompt ? generationDraft.nsfw_enabled : false,
        nsfw_prompt: usesPrompt && generationDraft.nsfw_enabled ? nsfwPrompt.trim() : "",
        character_preset_ids: selectedPresetIds,
        source_asset_id: selectedSource?.id ?? null,
        mask_asset_id: maskId,
        character_references: activeCharacterRefs.map(({ asset_id, kind, strength, fidelity }) => ({ asset_id, kind, strength, fidelity })),
        vibe_references: activeVibes.map(({ asset_id, strength, information_extracted }) => ({ asset_id, strength, information_extracted })),
        director: mode === "director" ? director : null,
        parameters: { ...parameters, count: usesPrompt ? parameters.count : 1 },
      };
      await api<Job>("/api/jobs", { method: "POST", body: JSON.stringify(body) });
      onSubmitted(repeatCount > 1 ? `${repeatCount}회 연속 생성을 시작했어요` : "생성을 시작했어요");
      window.setTimeout(() => void refreshAnlas(true), 15_000);
    } catch (submitError) {
      setError(errorMessage(submitError));
    } finally {
      submitInFlightRef.current = false;
      setSubmitting(false);
    }
  };

  const handleGenerationShortcut = (event: React.KeyboardEvent<HTMLFormElement>) => {
    if (
      event.key !== "Enter"
      || !event.ctrlKey
      || event.repeat
      || event.nativeEvent.isComposing
      || submitInFlightRef.current
    ) return;
    event.preventDefault();
    event.currentTarget.requestSubmit();
  };

  const outputCount = (usesPrompt ? parameters.count : 1) * (repeatCount ?? 1);
  const activeMode = MODES.find((item) => item.id === mode) ?? MODES[0];

  return (
    <div className="generation-view">
      <form className="generate-form" onSubmit={submit} onKeyDown={handleGenerationShortcut} onInvalidCapture={(event) => {
        event.preventDefault();
        setError("입력값을 확인해 주세요");
        const field = event.target as HTMLElement;
        // Closed settings/disclosures must reveal an invalid field before focus.
        let parent = field.parentElement;
        while (parent) { if (parent instanceof HTMLDetailsElement) parent.open = true; parent = parent.parentElement; }
        requestAnimationFrame(() => field.focus());
      }}>
        <div className="generate-layout">
          <div className="generate-main" role="region" aria-label="장면 설정" tabIndex={-1}>
            <div className="generate-toolbar">
              <div className="segmented generate-modes" role="radiogroup" aria-label="생성 방식">
                {MODES.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    role="radio"
                    aria-checked={mode === item.id}
                    onClick={() => {
                      setMode(item.id);
                      if (item.id === "upscale" || item.id === "director") {
                        onGenerationDraftChange({
                          ...generationDraft,
                          parameters: { ...parameters, count: 1 },
                        });
                      }
                    }}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
              <span className={`draft-sync-state ${syncStatus}`} role="status" title={syncStatus === "offline" ? "입력은 이 기기에 보관돼요" : undefined}>
                {syncStatus === "synced" ? "저장됨" : syncStatus === "saving" ? "저장 중…" : "오프라인"}
              </span>
            </div>

            {mode !== "txt2img" ? (
              <section className="panel source-panel" aria-label="원본 선택">
                <div className="panel-header">
                  <h2>원본 선택</h2>
                  <div className="panel-actions">
                    {selectedSource ? <button type="button" className="button small" onClick={() => setSelectedSource(null)}>다른 이미지</button> : null}
                    <label className="button small file-button">
                      <Upload aria-hidden="true" />업로드
                      <input type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => void handleUpload(event.target.files?.[0])} />
                    </label>
                  </div>
                </div>
                {selectedSource ? (
                  <div className="selected-source">
                    <img src={selectedSource.thumbnail_url} alt="선택된 편집 원본" />
                    <div>
                      <strong>{"original_name" in selectedSource ? selectedSource.original_name : `생성 이미지 ${selectedSource.id.slice(0, 8)}`}</strong>
                      <span className="caption">{selectedSource.width} × {selectedSource.height}</span>
                    </div>
                  </div>
                ) : (
                  <div className="source-grid">
                    {loadingSources && !sources.length ? Array.from({ length: 8 }, (_, index) => <span key={index} className="source-card skeleton" aria-hidden="true" />) : null}
                    {sources.slice(0, 16).map((source) => (
                      <button type="button" className="source-card" key={source.id} onClick={() => chooseSource(source)}>
                        <img src={source.thumbnail_url} alt={"original_name" in source ? source.original_name : "생성 이미지"} />
                      </button>
                    ))}
                    {!loadingSources && !sources.length ? <p className="empty-inline">이미지가 없어요. 파일을 올려 주세요</p> : null}
                  </div>
                )}
              </section>
            ) : null}

            {mode === "inpaint" && selectedSource ? <InpaintCanvas ref={maskRef} sourceUrl={selectedSource.content_url} /> : null}

            {mode === "director" ? <DirectorPanel value={director} onChange={setDirector} /> : null}

            {usesPrompt ? (
              <section className="panel prompt-panel" aria-label="프롬프트">
                <div className="prompt-panel-head">
                  <div className="tabs prompt-tabs" role="tablist" aria-label="프롬프트 종류">
                    <button
                      type="button"
                      role="tab"
                      aria-selected={promptTab === "description"}
                      aria-controls="description-prompt-panel"
                      onClick={() => setPromptTab("description")}
                    >
                      묘사
                    </button>
                    <button
                      type="button"
                      role="tab"
                      aria-selected={promptTab === "quality"}
                      aria-controls="quality-prompt-panel"
                      onClick={() => setPromptTab("quality")}
                    >
                      품질{selectedQualityPreset ? <small className="prompt-tab-meta">{selectedQualityPreset.name}{qualityPresetChanged ? " · 수정됨" : ""}</small> : null}
                    </button>
                    <button
                      type="button"
                      role="tab"
                      aria-selected={promptTab === "nsfw"}
                      aria-controls="nsfw-prompt-panel"
                      onClick={() => setPromptTab("nsfw")}
                    >
                      NSFW{nsfwPrompt.trim() && !generationDraft.nsfw_enabled ? <small className="prompt-tab-meta">꺼짐</small> : null}
                    </button>
                  </div>
                  <label className="switch nsfw-switch">
                    <input
                      type="checkbox"
                      checked={generationDraft.nsfw_enabled}
                      onChange={(event) => onGenerationDraftChange({ ...generationDraft, nsfw_enabled: event.target.checked })}
                    />
                    <span className="switch-track" aria-hidden="true" />
                    <span className="switch-label"><strong>NSFW</strong></span>
                  </label>
                </div>

                {promptTab === "nsfw" ? (
                  <div id="nsfw-prompt-panel" className={`prompt-fields nsfw-prompt-fields${generationDraft.nsfw_enabled ? "" : " inactive"}`} role="tabpanel">
                    <label className="field">
                      <span className="label-row"><strong>포지티브</strong><small className="counter">{nsfwPrompt.length.toLocaleString()}</small></span>
                      <textarea className="prompt-textarea" value={nsfwPrompt} onChange={(event) => onGenerationDraftChange({ ...generationDraft, nsfw_prompt: event.target.value })} rows={6} />
                    </label>
                  </div>
                ) : promptTab === "quality" ? (
                  <div id="quality-prompt-panel" className="prompt-fields" role="tabpanel">
                    <div className="quality-preset-bar">
                      <select
                        aria-label="품질 프롬프트 프리셋"
                        value={generationDraft.quality_preset_id ?? ""}
                        onChange={(event) => selectQualityPreset(event.target.value)}
                      >
                        <option value="">프리셋 없음</option>
                        {qualityPresets.map((preset) => (
                          <option key={preset.id} value={preset.id}>{preset.name}</option>
                        ))}
                      </select>
                      {selectedQualityPreset ? (
                        <button type="button" className="button small" disabled={!qualityPresetChanged} onClick={() => void updateQualityPreset()}>덮어쓰기</button>
                      ) : null}
                      <button type="button" className="icon-button weak" onClick={openQualityPresetSave} aria-label="새 프리셋으로 저장" title="새 프리셋으로 저장"><Save aria-hidden="true" /></button>
                      {selectedQualityPreset ? (
                        <button type="button" className="icon-button weak danger" onClick={() => void deleteQualityPreset()} aria-label="프리셋 삭제" title="프리셋 삭제"><Trash2 aria-hidden="true" /></button>
                      ) : null}
                    </div>
                    <label className="field">
                      <span className="label-row"><strong>포지티브</strong><small className="counter">{qualityPrompt.length.toLocaleString()}</small></span>
                      <textarea className="prompt-textarea" value={qualityPrompt} onChange={(event) => onGenerationDraftChange({ ...generationDraft, quality_prompt: event.target.value })} rows={6} placeholder="masterpiece, best quality, artist:…" />
                    </label>
                    <label className="field">
                      <span className="label-row"><strong>네거티브</strong><small className="counter">{qualityNegativePrompt.length.toLocaleString()}</small></span>
                      <textarea className="prompt-textarea" value={qualityNegativePrompt} onChange={(event) => onGenerationDraftChange({ ...generationDraft, quality_negative_prompt: event.target.value })} rows={6} placeholder="lowres, worst quality, bad anatomy…" />
                    </label>
                  </div>
                ) : (
                  <div id="description-prompt-panel" className="prompt-fields" role="tabpanel">
                    <label className="field">
                      <span className="label-row"><strong>포지티브</strong><small className="counter">{descriptionPrompt.length.toLocaleString()}</small></span>
                      <textarea className="prompt-textarea main-prompt" value={descriptionPrompt} onChange={(event) => onGenerationDraftChange({ ...generationDraft, description_prompt: event.target.value })} rows={9} placeholder="장면, 구도, 표정, 의상, 배경" required />
                    </label>
                    <details className="disclosure negative-disclosure" open={descriptionNegativePrompt.length > 0 || undefined}>
                      <summary>네거티브 <small>{descriptionNegativePrompt ? descriptionNegativePrompt : "없음"}</small></summary>
                      <textarea className="prompt-textarea" aria-label="묘사 네거티브" value={descriptionNegativePrompt} onChange={(event) => onGenerationDraftChange({ ...generationDraft, description_negative_prompt: event.target.value })} rows={4} placeholder="빼고 싶은 동작, 구도, 배경" />
                    </details>
                  </div>
                )}
              </section>
            ) : null}

            {usesReferences ? (
              <ReferencePanel
                tab={referenceTab}
                onTabChange={setReferenceTab}
                characterRefs={characterRefs}
                onCharacterRefsChange={setCharacterRefs}
                vibes={vibes}
                onVibesChange={setVibes}
                modelSpec={modelSpec}
                models={status.models}
                onModelChange={(modelId) => onGenerationDraftChange({ ...generationDraft, model: modelId })}
                sources={sources}
                loadingSources={loadingSources}
                onOpenPicker={() => { if (!sources.length) void loadSources(); }}
                onUpload={uploadReference}
              />
            ) : null}
          </div>

          <aside className="generate-aside" aria-label="인물과 이미지 설정">
            <section className="panel character-panel" aria-label="등장인물">
              <div className="panel-header">
                <h2>인물 <span className="counter">{selectedPresetIds.length}/{modelSpec?.max_characters ?? 0}</span></h2>
                <div className="panel-actions">
                  <button
                    type="button"
                    className="icon-button small"
                    onClick={openCharacterSetSave}
                    disabled={selectedPresetIds.length < 2}
                    aria-label="선택한 인물을 세트로 저장"
                    title="세트로 저장"
                  >
                    <FolderPlus aria-hidden="true" />
                  </button>
                </div>
              </div>
              {presets.length ? (
                <div className="chip-group character-chips">
                  {presets.map((preset) => {
                    const order = selectedPresetIds.indexOf(preset.id);
                    return (
                      <button
                        type="button"
                        key={preset.id}
                        className="chip"
                        onClick={() => togglePreset(preset.id)}
                        aria-pressed={order >= 0}
                        title={`#${preset.tag_name}`}
                      >
                        {order >= 0 && selectedPresetIds.length > 1 ? <span className="chip-order" aria-hidden="true">{order + 1}</span> : null}
                        {preset.name}
                      </button>
                    );
                  })}
                </div>
              ) : <p className="empty-inline">인물 탭에서 먼저 추가해 주세요</p>}
              {selectedPresets.length > 1 ? (
                <ol className="character-order" aria-label="인물 순서">
                  {selectedPresets.map((preset, index) => (
                    <li key={preset.id}>
                      <span className="character-order-index">{index + 1}</span>
                      <strong>{preset.name}</strong>
                      <button type="button" className="icon-button small" aria-label={`${preset.name} 위로`} onClick={() => movePreset(index, -1)} disabled={index === 0}><ArrowUp aria-hidden="true" /></button>
                      <button type="button" className="icon-button small" aria-label={`${preset.name} 아래로`} onClick={() => movePreset(index, 1)} disabled={index === selectedPresets.length - 1}><ArrowDown aria-hidden="true" /></button>
                    </li>
                  ))}
                </ol>
              ) : null}
              {characterSets.length ? (
                <div className="character-sets">
                  <span className="caption">세트</span>
                  <div className="chip-group">
                    {characterSets.map((characterSet) => (
                      <span className="character-set" key={characterSet.id}>
                        <button
                          type="button"
                          className="chip"
                          onClick={() => applyCharacterSet(characterSet)}
                          aria-pressed={characterSetIsActive(characterSet)}
                          title={characterSet.members.map((member) => member.name).join(" · ")}
                        >
                          {characterSet.name}
                        </button>
                        <button
                          type="button"
                          className="character-set-delete"
                          onClick={() => void deleteCharacterSet(characterSet)}
                          aria-label={`인물 세트 ${characterSet.name} 삭제`}
                        >
                          <X aria-hidden="true" />
                        </button>
                      </span>
                    ))}
                  </div>
                </div>
              ) : null}
            </section>

            <section className="panel image-settings-panel" aria-label="이미지 설정">
              <div className="panel-header">
                <h2>이미지</h2>
                <select className="model-select" aria-label="모델" value={model} onChange={(event) => onGenerationDraftChange({ ...generationDraft, model: event.target.value })}>
                  {status.models.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                </select>
              </div>
              {usesPrompt ? (
                <div className="stack">
                  <div className="dimension-row">
                    <label className="field"><span className="field-label">가로</span><input type="number" min="64" max="8192" step="64" value={parameters.width} onChange={(event) => updateNumber("width", Number(event.target.value))} /></label>
                    <button
                      type="button"
                      className="icon-button weak dimension-swap"
                      aria-label="가로·세로 바꾸기"
                      title="가로·세로 바꾸기"
                      onClick={() => onGenerationDraftChange({
                        ...generationDraft,
                        parameters: {
                          ...parameters,
                          width: parameters.height,
                          height: parameters.width,
                        },
                      })}
                    >
                      <ArrowLeftRight aria-hidden="true" />
                    </button>
                    <label className="field"><span className="field-label">세로</span><input type="number" min="64" max="8192" step="64" value={parameters.height} onChange={(event) => updateNumber("height", Number(event.target.value))} /></label>
                  </div>
                  <details className="disclosure size-preset-disclosure">
                    <summary>크기 프리셋</summary>
                    <div className="size-preset-groups">
                      {SIZE_PRESET_GROUPS.map((group) => (
                        <section className="size-preset-group" key={group.id} aria-labelledby={`size-preset-${group.id}`}>
                          <h3 id={`size-preset-${group.id}`}>{group.label}<small>{group.description}</small></h3>
                          <div className="size-preset-grid">
                            {group.presets.map((preset) => {
                              const selected = parameters.width === preset.width && parameters.height === preset.height;
                              const paidBySize = preset.width * preset.height > NORMAL_PIXEL_LIMIT;
                              return (
                                <button
                                  type="button"
                                  key={preset.id}
                                  className={`size-preset${selected ? " selected" : ""}${paidBySize ? " paid-size" : ""}`}
                                  aria-pressed={selected}
                                  aria-label={`${preset.label} ${preset.width} × ${preset.height}${paidBySize ? ", 해상도 기준 Anlas 사용" : ""}`}
                                  title={paidBySize ? "해상도 기준 Anlas 사용" : preset.ratio}
                                  onClick={() => onGenerationDraftChange({
                                    ...generationDraft,
                                    parameters: {
                                      ...parameters,
                                      width: preset.width,
                                      height: preset.height,
                                    },
                                  })}
                                >
                                  <span>{preset.label}</span>
                                  <strong>{preset.width}×{preset.height}</strong>
                                </button>
                              );
                            })}
                          </div>
                        </section>
                      ))}
                    </div>
                  </details>
                  <div className="field">
                    <span className="field-label">장수</span>
                    <div className="segmented block" role="radiogroup" aria-label="생성 수">
                      {[1, 2, 3, 4].map((count) => (
                        <button type="button" role="radio" key={count} aria-checked={parameters.count === count} onClick={() => updateNumber("count", count)}>{count}</button>
                      ))}
                    </div>
                  </div>
                  <details className="disclosure advanced-disclosure" open={advanced} onToggle={(event) => setAdvanced(event.currentTarget.open)}>
                    <summary>고급 <small>{parameters.steps}단계 · 가이던스 {parameters.guidance}{parameters.seed !== null ? ` · 시드 ${parameters.seed}` : ""}</small></summary>
                    <div className="advanced-grid">
                      <label className="field"><span className="field-label">단계</span><input type="number" min="1" max="50" value={parameters.steps} onChange={(event) => updateNumber("steps", Number(event.target.value))} /></label>
                      <label className="field"><span className="field-label">가이던스</span><input type="number" min="0.1" max="20" step="0.1" value={parameters.guidance} onChange={(event) => updateNumber("guidance", Number(event.target.value))} /></label>
                      <label className="field"><span className="field-label">리스케일</span><input type="number" min="0" max="1" step="0.01" value={parameters.guidance_rescale} onChange={(event) => updateNumber("guidance_rescale", Number(event.target.value))} /></label>
                      <label className="field"><span className="field-label">샘플러</span><select value={parameters.sampler} onChange={(event) => onGenerationDraftChange({ ...generationDraft, parameters: { ...parameters, sampler: event.target.value } })}><option value="k_dpmpp_2m">DPM++ 2M</option><option value="k_euler">Euler</option><option value="k_euler_ancestral">Euler Ancestral</option><option value="k_dpmpp_2s_ancestral">DPM++ 2S Ancestral</option><option value="k_dpmpp_2m_sde">DPM++ 2M SDE</option><option value="k_dpmpp_sde">DPM++ SDE</option></select></label>
                      <label className="field"><span className="field-label">노이즈 스케줄</span><select value={parameters.noise_schedule ?? "karras"} onChange={(event) => onGenerationDraftChange({ ...generationDraft, parameters: { ...parameters, noise_schedule: event.target.value as GenerationDraft["parameters"]["noise_schedule"] } })}><option value="karras">Karras</option><option value="exponential">Exponential</option><option value="polyexponential">Polyexponential</option></select></label>
                      <label className="field span-2"><span className="field-label">시드</span><input type="number" min="0" max="4294967295" placeholder="랜덤" value={parameters.seed ?? ""} onChange={(event) => updateNumber("seed", event.target.value ? Number(event.target.value) : null)} /></label>
                      {mode === "img2img" || mode === "inpaint" ? (
                        <>
                          <label className="field span-2"><span className="label-row"><strong>강도</strong><small className="counter">{parameters.strength.toFixed(2)}</small></span><input type="range" min="0" max="1" step="0.01" value={parameters.strength} onChange={(event) => updateNumber("strength", Number(event.target.value))} /></label>
                          <label className="field span-2"><span className="label-row"><strong>노이즈</strong><small className="counter">{parameters.noise.toFixed(2)}</small></span><input type="range" min="0" max="1" step="0.01" value={parameters.noise} onChange={(event) => updateNumber("noise", Number(event.target.value))} /></label>
                        </>
                      ) : null}
                      <label className="switch span-2">
                        <input type="checkbox" checked={parameters.quality} onChange={(event) => onGenerationDraftChange({ ...generationDraft, parameters: { ...parameters, quality: event.target.checked } })} />
                        <span className="switch-track" aria-hidden="true" />
                        <span className="switch-label"><strong>NovelAI 품질 태그</strong></span>
                      </label>
                    </div>
                  </details>
                </div>
              ) : null}
            </section>
          </aside>
        </div>

        <div className="generation-action-bar" role="region" aria-label="생성 실행 및 ANLAS 정보">
          <div className="generation-action-inner">
            <dl className="anlas-metrics">
              <div className="anlas-metric">
                <dt>{(repeatCount ?? 1) > 1 ? "예상 총 소모" : "예상 소모"}</dt>
                <dd><strong>{estimatedCostLabel}</strong>{anlasEstimate.note ? <small>{anlasEstimate.note}</small> : null}</dd>
              </div>
              <div className={insufficientAnlas ? "anlas-metric insufficient" : "anlas-metric"}>
                <dt>잔액</dt>
                <dd><strong>{remainingAnlasLabel}</strong>{anlasStatus?.tier_name ? <small>{anlasStatus.tier_name}</small> : null}</dd>
              </div>
              <div className={anlasStatus?.usage_is_negative ? "anlas-metric opus-limit-metric exhausted" : "anlas-metric opus-limit-metric"}>
                <dt>V5 무료 한도</dt>
                <dd>
                  <strong>{usageLimitLabel}</strong>
                  {usageLimitNote ? <small>{usageLimitNote}</small> : null}
                  <span
                    className="opus-limit-track"
                    role="progressbar"
                    aria-label="Opus V5 무료 생성 한도"
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={usageLimitPercent}
                  >
                    <i style={{ width: `${usageLimitPercent}%` }} />
                  </span>
                </dd>
              </div>
              <button
                type="button"
                className="icon-button small anlas-refresh"
                onClick={() => void refreshAnlas(true)}
                disabled={anlasLoading || !status.has_token}
                aria-label="ANLAS 잔액 새로고침"
                title="잔액 새로고침"
              >
                <RotateCw aria-hidden="true" className={anlasLoading ? "spin" : undefined} />
              </button>
            </dl>
            <div className="generation-submit-controls">
              {error ? <p className="action-message critical" role="alert">{error}</p> : anlasError ? <p className="action-message warning" role="status">잔액을 불러오지 못했어요</p> : null}
              <label className="repeat-count-control" title="연속 생성 횟수 (1~100)">
                <span>연속</span>
                <input type="number" min={1} max={100} step={1} required value={repeatCountInput} onChange={(event) => setRepeatCountInput(event.target.value)} disabled={submitting} aria-label="연속 생성 횟수" aria-describedby="sequence-help" />
              </label>
              <button className="button primary large generate-submit" disabled={submitting} type="submit" title="Ctrl+Enter로 생성">
                <span>{submitting ? "보내는 중…" : (repeatCount ?? 1) > 1 ? `${repeatCount}회 ${activeMode.action}` : activeMode.action}</span>
                <kbd aria-hidden="true">Ctrl ↵</kbd>
              </button>
            </div>
            <span id="sequence-help" className="sr-only">
              {(repeatCount ?? 1) > 1 ? `총 ${outputCount}장, 실패하면 남은 회차는 멈춰요` : "1~100회까지 이어서 생성할 수 있어요"}
            </span>
          </div>
        </div>
      </form>

      {qualityPresetModalOpen ? (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setQualityPresetModalOpen(false)}>
          <form
            className="modal-form quality-preset-modal"
            role="dialog"
            aria-modal="true"
            aria-label="품질 프롬프트 프리셋 저장"
            onMouseDown={(event) => event.stopPropagation()}
            onSubmit={(event) => void createQualityPreset(event)}
          >
            <button type="button" className="icon-button modal-close" onClick={() => setQualityPresetModalOpen(false)} aria-label="닫기"><X aria-hidden="true" /></button>
            <h2>품질 프리셋 저장</h2>
            <label className="field">
              <span className="field-label">이름</span>
              <input autoFocus required maxLength={80} value={qualityPresetName} onChange={(event) => setQualityPresetName(event.target.value)} placeholder="예: 애니 고품질" />
            </label>
            <p className="preset-preview">{qualityPrompt.trim()}</p>
            {qualityNegativePrompt.trim() ? <p className="preset-preview negative"><span className="caption">네거티브</span>{qualityNegativePrompt.trim()}</p> : null}
            {qualityPresetError ? <p className="error-message" role="alert">{qualityPresetError}</p> : null}
            <div className="form-actions">
              <button type="button" className="button secondary" onClick={() => setQualityPresetModalOpen(false)}>취소</button>
              <button type="submit" className="button primary" disabled={qualityPresetSaving || !qualityPresetName.trim()}>{qualityPresetSaving ? "저장 중…" : "저장"}</button>
            </div>
          </form>
        </div>
      ) : null}

      {characterSetModalOpen ? (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setCharacterSetModalOpen(false)}>
          <form
            className="modal-form character-set-modal"
            role="dialog"
            aria-modal="true"
            aria-label="인물 세트 저장"
            onMouseDown={(event) => event.stopPropagation()}
            onSubmit={(event) => void createCharacterSet(event)}
          >
            <button type="button" className="icon-button modal-close" onClick={() => setCharacterSetModalOpen(false)} aria-label="닫기"><X aria-hidden="true" /></button>
            <h2>인물 세트 저장</h2>
            <label className="field">
              <span className="field-label">이름</span>
              <input autoFocus required maxLength={80} value={characterSetName} onChange={(event) => setCharacterSetName(event.target.value)} placeholder="예: 하린·도윤" />
            </label>
            <ol className="character-order">
              {selectedPresets.map((preset, index) => (
                <li key={preset.id}><span className="character-order-index">{index + 1}</span><strong>{preset.name}</strong><small className="caption">#{preset.tag_name}</small></li>
              ))}
            </ol>
            {characterSetError ? <p className="error-message" role="alert">{characterSetError}</p> : null}
            <div className="form-actions">
              <button type="button" className="button secondary" onClick={() => setCharacterSetModalOpen(false)}>취소</button>
              <button type="submit" className="button primary" disabled={characterSetSaving || !characterSetName.trim()}>{characterSetSaving ? "저장 중…" : "저장"}</button>
            </div>
          </form>
        </div>
      ) : null}
    </div>
  );
}
