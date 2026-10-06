import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronLeft, ChevronRight, FolderDown, Heart, ImageOff, Pencil, Send, ShieldAlert, Trash2, X } from "lucide-react";
import { ImageDownloads } from "./ImageDownloads";
import { ImageCopyButtons } from "./ImageCopyButtons";
import { api, errorMessage } from "../api";
import type { DiscordWebhookTarget, ImageRecord, ImageReuseOptions, ImageTag } from "../types";
import { ZoomableGalleryImage } from "./ZoomableGalleryImage";
import "../gallery.css";

const DEFAULT_REUSE_OPTIONS: ImageReuseOptions = {
  quality_prompt: true,
  description_prompt: true,
  quality_negative_prompt: true,
  description_negative_prompt: true,
  nsfw_enabled: true,
  character_presets: true,
  model: true,
  dimensions: true,
  steps: true,
  guidance: true,
  guidance_rescale: true,
  sampler: true,
  quality: true,
  seed: true,
  count: true,
  strength_noise: true,
};

const REUSE_OPTION_LABELS: Array<{ key: keyof ImageReuseOptions; label: string }> = [
  { key: "quality_prompt", label: "품질 프롬프트" },
  { key: "description_prompt", label: "묘사 프롬프트" },
  { key: "quality_negative_prompt", label: "품질 네거티브" },
  { key: "description_negative_prompt", label: "묘사 네거티브" },
  { key: "nsfw_enabled", label: "NSFW 옵션" },
  { key: "character_presets", label: "인물 선택과 순서" },
  { key: "model", label: "모델" },
  { key: "dimensions", label: "이미지 크기" },
  { key: "steps", label: "단계" },
  { key: "guidance", label: "가이던스" },
  { key: "guidance_rescale", label: "Guidance Rescale" },
  { key: "sampler", label: "샘플러" },
  { key: "quality", label: "품질 태그" },
  { key: "seed", label: "시드" },
  { key: "count", label: "생성 수" },
  { key: "strength_noise", label: "Strength와 Noise" },
];

const WIDE_DETAIL_QUERY = "(min-width: 768px)";

function useWideDetailLayout(): boolean {
  const [wide, setWide] = useState(() => typeof window !== "undefined" && window.matchMedia(WIDE_DETAIL_QUERY).matches);
  useEffect(() => {
    const query = window.matchMedia(WIDE_DETAIL_QUERY);
    const update = () => setWide(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return wide;
}

function expiryLabel(expiresAt: string | null): string {
  if (!expiresAt) return "영구 보관";
  const milliseconds = new Date(expiresAt).getTime() - Date.now();
  if (milliseconds <= 0) return "정리 대기";
  const hours = Math.ceil(milliseconds / 3_600_000);
  if (hours < 24) return `${hours}시간 남음`;
  return `${Math.ceil(hours / 24)}일 남음`;
}

interface Props {
  refreshSignal: number;
  onEdit: (image: ImageRecord) => void;
  onReuse: (image: ImageRecord, options: ImageReuseOptions) => void;
  onChanged: () => void;
  notify: (message: string) => void;
}

type DetailMotion = "previous" | "next" | null;
type GalleryFolder = "temporary" | "favorites";

export function GalleryView({ refreshSignal, onEdit, onReuse, onChanged, notify }: Props) {
  const [folder, setFolder] = useState<GalleryFolder>("temporary");
  const [nsfwOnly, setNsfwOnly] = useState(false);
  const [items, setItems] = useState<ImageRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [tags, setTags] = useState<ImageTag[]>([]);
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [detail, setDetail] = useState<ImageRecord | null>(null);
  const [detailExpanded, setDetailExpanded] = useState(false);
  const [detailMotion, setDetailMotion] = useState<DetailMotion>(null);
  const [zoomed, setZoomed] = useState(false);
  const [reuseTarget, setReuseTarget] = useState<ImageRecord | null>(null);
  const [reuseOptions, setReuseOptions] = useState<ImageReuseOptions>({ ...DEFAULT_REUSE_OPTIONS });
  const [webhooks, setWebhooks] = useState<DiscordWebhookTarget[]>([]);
  const [discordTarget, setDiscordTarget] = useState<ImageRecord | null>(null);
  const [selectedWebhookId, setSelectedWebhookId] = useState("");
  const [includeDiscordTags, setIncludeDiscordTags] = useState(true);
  const [includeDiscordMetadata, setIncludeDiscordMetadata] = useState(false);
  const [discordBusy, setDiscordBusy] = useState(false);
  const [discordError, setDiscordError] = useState("");
  const [detailNavigating, setDetailNavigating] = useState(false);
  const [enteringImageIds, setEnteringImageIds] = useState<Set<string>>(() => new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const wideDetail = useWideDetailLayout();
  const skipPageLoad = useRef<number | null>(null);
  const loadedImagePath = useRef<string | null>(null);
  const loadRequestId = useRef(0);
  const touchStart = useRef<{ x: number; y: number } | null>(null);
  const detailInfoRef = useRef<HTMLDivElement>(null);
  const knownImageIds = useRef<Set<string>>(new Set());
  const enterAnimationTimer = useRef<number | null>(null);

  const imagePath = useCallback((targetPage: number) => {
    const params = new URLSearchParams({ favorite: String(folder === "favorites"), page: String(targetPage) });
    if (nsfwOnly) params.set("nsfw", "true");
    selectedTags.forEach((tag) => params.append("tag", tag));
    return `/api/images?${params.toString()}`;
  }, [folder, nsfwOnly, selectedTags]);

  const favoriteTagsPath = useCallback(() => {
    const params = new URLSearchParams();
    if (nsfwOnly) params.set("nsfw", "true");
    const query = params.toString();
    return `/api/images/favorite-tags${query ? `?${query}` : ""}`;
  }, [nsfwOnly]);

  const load = useCallback(async () => {
    const path = imagePath(page);
    const backgroundRefresh = loadedImagePath.current === path;
    const requestId = ++loadRequestId.current;
    if (!backgroundRefresh) setLoading(true);
    try {
      const [images, tagResponse, webhookResponse] = await Promise.all([
        api<{ items: ImageRecord[]; total: number }>(path),
        api<{ items: ImageTag[] }>(favoriteTagsPath()),
        api<{ items: DiscordWebhookTarget[] }>("/api/webhooks"),
      ]);
      if (requestId !== loadRequestId.current) return;
      const nextIds = new Set(images.items.map((image) => image.id));
      const entering = new Set(
        images.items
          .filter((image) => !knownImageIds.current.has(image.id))
          .map((image) => image.id),
      );
      knownImageIds.current = nextIds;
      setEnteringImageIds(entering);
      if (enterAnimationTimer.current !== null) window.clearTimeout(enterAnimationTimer.current);
      if (entering.size) {
        enterAnimationTimer.current = window.setTimeout(() => {
          setEnteringImageIds(new Set());
          enterAnimationTimer.current = null;
        }, 1_000);
      }
      setItems(images.items);
      setTotal(images.total);
      setTags(tagResponse.items);
      setWebhooks(webhookResponse.items);
      loadedImagePath.current = path;
      setError("");
    } catch (loadError) {
      if (requestId === loadRequestId.current) setError(errorMessage(loadError));
    } finally {
      if (!backgroundRefresh && requestId === loadRequestId.current) setLoading(false);
    }
  }, [favoriteTagsPath, imagePath, page]);

  useEffect(() => {
    if (skipPageLoad.current === page) {
      skipPageLoad.current = null;
      return;
    }
    void load();
  }, [load, refreshSignal]);

  useEffect(() => () => {
    if (enterAnimationTimer.current !== null) window.clearTimeout(enterAnimationTimer.current);
  }, []);

  const openFolder = (nextFolder: GalleryFolder) => {
    setFolder(nextFolder);
    setSelectedTags([]);
    setPage(1);
  };

  const toggleNsfwOnly = () => {
    setNsfwOnly((current) => !current);
    setPage(1);
  };

  const toggleFavorite = async (image: ImageRecord) => {
    try {
      await api<ImageRecord>(`/api/images/${image.id}/favorite`, {
        method: "PATCH",
        body: JSON.stringify({ favorite: !image.favorite_at }),
      });
      const currentIndex = items.findIndex((item) => item.id === image.id);
      const isCurrentDetail = detail?.id === image.id;
      setItems((current) => current.filter((item) => item.id !== image.id));
      setTotal((current) => Math.max(0, current - 1));

      if (isCurrentDetail && currentIndex >= 0) {
        if (currentIndex > 0) {
          setDetailMotion("previous");
          setDetail(items[currentIndex - 1]);
        } else if (page > 1) {
          setDetailNavigating(true);
          try {
            const targetPage = page - 1;
            const response = await api<{ items: ImageRecord[]; total: number }>(imagePath(targetPage));
            const previous = response.items[response.items.length - 1] ?? null;
            skipPageLoad.current = targetPage;
            loadedImagePath.current = imagePath(targetPage);
            setItems(response.items);
            setTotal(response.total);
            setPage(targetPage);
            if (previous) {
              setDetailMotion("previous");
              setDetail(previous);
            }
          } catch (navigationError) {
            setError(errorMessage(navigationError));
          } finally {
            setDetailNavigating(false);
          }
        } else {
          const next = items[1] ?? null;
          if (next) {
            setDetailMotion("next");
            setDetail(next);
          } else {
            closeDetail();
          }
        }
      }

      void api<{ items: ImageTag[] }>(favoriteTagsPath())
        .then((response) => setTags(response.items))
        .catch(() => undefined);
      notify(image.favorite_at ? "즐겨찾기를 해제했어요. 7일 뒤 자동으로 정리돼요" : "즐겨찾기에 저장했어요");
    } catch (actionError) {
      setError(errorMessage(actionError));
    }
  };

  const deleteImage = async (image: ImageRecord) => {
    if (!window.confirm("이 이미지를 영구 삭제할까요? 되돌릴 수 없어요.")) return;
    try {
      await api(`/api/images/${image.id}`, { method: "DELETE" });
      setDetail(null);
      notify("이미지를 삭제했어요");
      await load();
      onChanged();
    } catch (actionError) {
      setError(errorMessage(actionError));
    }
  };

  const toggleTag = (tagId: string) => {
    setSelectedTags((current) => current.includes(tagId) ? current.filter((id) => id !== tagId) : [...current, tagId]);
    setPage(1);
  };

  const openDetail = (image: ImageRecord) => {
    setZoomed(false);
    setDetailExpanded(false);
    setDetailMotion(null);
    setDetail(image);
  };

  const closeDetail = useCallback(() => {
    setZoomed(false);
    setDetailExpanded(false);
    setDetailMotion(null);
    setDetail(null);
  }, []);

  const toggleDetailExpanded = () => {
    const next = !detailExpanded;
    setDetailExpanded(next);
    if (next) {
      window.setTimeout(() => {
        detailInfoRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 260);
    }
  };

  const openReuse = (image: ImageRecord) => {
    setReuseOptions({ ...DEFAULT_REUSE_OPTIONS });
    setReuseTarget(image);
    closeDetail();
  };

  const closeReuse = useCallback(() => setReuseTarget(null), []);

  const openDiscordSend = (image: ImageRecord) => {
    setDiscordTarget(image);
    setSelectedWebhookId(webhooks[0]?.id ?? "");
    setIncludeDiscordTags(true);
    setIncludeDiscordMetadata(false);
    setDiscordError("");
    closeDetail();
  };

  const closeDiscordSend = useCallback(() => {
    if (discordBusy) return;
    setDiscordTarget(null);
    setDiscordError("");
  }, [discordBusy]);

  const sendToDiscord = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!discordTarget || !selectedWebhookId) return;
    setDiscordBusy(true);
    setDiscordError("");
    try {
      const result = await api<{ webhook_name: string }>(
        `/api/images/${discordTarget.id}/discord`,
        {
          method: "POST",
          body: JSON.stringify({
            webhook_id: selectedWebhookId,
            include_tags: includeDiscordTags,
            include_metadata: includeDiscordMetadata,
          }),
        },
      );
      setDiscordTarget(null);
      notify(`‘${result.webhook_name}’(으)로 보냈어요`);
    } catch (sendError) {
      setDiscordError(errorMessage(sendError));
    } finally {
      setDiscordBusy(false);
    }
  };

  const setAllReuseOptions = (selected: boolean) => {
    setReuseOptions(Object.fromEntries(
      REUSE_OPTION_LABELS.map((option) => [option.key, selected]),
    ) as unknown as ImageReuseOptions);
  };

  const navigateDetail = useCallback(async (direction: -1 | 1) => {
    if (!detail || detailNavigating || total <= 1) return;
    const currentIndex = items.findIndex((image) => image.id === detail.id);
    if (currentIndex < 0) return;
    const targetIndex = currentIndex + direction;
    if (targetIndex >= 0 && targetIndex < items.length) {
      setDetailMotion(direction > 0 ? "next" : "previous");
      setDetail(items[targetIndex]);
      return;
    }

    const targetPage = page + direction;
    const lastPage = Math.max(1, Math.ceil(total / 50));
    if (targetPage < 1 || targetPage > lastPage) return;
    setDetailNavigating(true);
    try {
      const response = await api<{ items: ImageRecord[]; total: number }>(imagePath(targetPage));
      if (!response.items.length) return;
      skipPageLoad.current = targetPage;
      setItems(response.items);
      setTotal(response.total);
      loadedImagePath.current = imagePath(targetPage);
      setPage(targetPage);
      setDetailMotion(direction > 0 ? "next" : "previous");
      setDetail(direction > 0 ? response.items[0] : response.items[response.items.length - 1]);
    } catch (navigationError) {
      setError(errorMessage(navigationError));
    } finally {
      setDetailNavigating(false);
    }
  }, [detail, detailNavigating, imagePath, items, page, total]);

  const handleTouchStart = (event: React.TouchEvent) => {
    const touch = event.changedTouches[0];
    touchStart.current = { x: touch.clientX, y: touch.clientY };
  };

  const handleTouchEnd = (event: React.TouchEvent) => {
    const start = touchStart.current;
    touchStart.current = null;
    if (!start) return;
    const touch = event.changedTouches[0];
    const deltaX = touch.clientX - start.x;
    const deltaY = touch.clientY - start.y;
    if (deltaY > 95 && Math.abs(deltaY) > Math.abs(deltaX) * 1.12) {
      closeDetail();
      return;
    }
    if (Math.abs(deltaX) < 55 || Math.abs(deltaX) <= Math.abs(deltaY) * 1.15) return;
    void navigateDetail(deltaX < 0 ? 1 : -1);
  };

  const detailIndex = detail ? items.findIndex((image) => image.id === detail.id) : -1;
  const globalDetailIndex = detailIndex >= 0 ? (page - 1) * 50 + detailIndex : -1;
  const hasPreviousDetail = globalDetailIndex > 0;
  const hasNextDetail = globalDetailIndex >= 0 && globalDetailIndex < total - 1;

  useEffect(() => {
    if (!detail) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        if (zoomed) {
          setZoomed(false);
        }
        else closeDetail();
      } else if (event.key === "ArrowLeft" && hasPreviousDetail) {
        event.preventDefault();
        void navigateDetail(-1);
      } else if (event.key === "ArrowRight" && hasNextDetail) {
        event.preventDefault();
        void navigateDetail(1);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [closeDetail, detail, hasNextDetail, hasPreviousDetail, navigateDetail, zoomed]);

  useEffect(() => {
    if (!detail && !reuseTarget && !discordTarget) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previousOverflow; };
  }, [detail, discordTarget, reuseTarget]);

  useEffect(() => {
    if (!reuseTarget) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      closeReuse();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [closeReuse, reuseTarget]);

  useEffect(() => {
    if (!discordTarget) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || discordBusy) return;
      event.preventDefault();
      closeDiscordSend();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [closeDiscordSend, discordBusy, discordTarget]);

  const lastPage = Math.max(1, Math.ceil(total / 50));
  const detailInfoOpen = wideDetail || detailExpanded;

  return (
    <div className="page wide gallery-view">
      <header className="page-header gallery-header">
        <div className="gallery-title">
          <h1>갤러리</h1>
          {loading && !total ? null : <span className="counter">{total.toLocaleString()}장</span>}
        </div>
        <div className="page-actions">
          <div className="segmented" role="tablist" aria-label="갤러리 종류">
            <button type="button" role="tab" aria-selected={folder === "temporary"} onClick={() => openFolder("temporary")}>임시 보관</button>
            <button type="button" role="tab" aria-selected={folder === "favorites"} onClick={() => openFolder("favorites")}>즐겨찾기</button>
          </div>
          <button
            type="button"
            className="chip gallery-nsfw-toggle"
            onClick={toggleNsfwOnly}
            role="switch"
            aria-checked={nsfwOnly}
            aria-label="NSFW만 보기"
            title="NSFW만 보기"
          >
            <ShieldAlert aria-hidden="true" strokeWidth={1.9} />
            NSFW
          </button>
          {folder === "favorites" && total > 0 ? (
            <a className="button secondary small" href="/api/favorites/export"><FolderDown aria-hidden="true" strokeWidth={1.8} />ZIP 다운로드</a>
          ) : null}
        </div>
      </header>

      {folder === "favorites" && tags.length ? (
        <div className="chip-group gallery-tag-filter" role="group" aria-label="태그 필터">
          {tags.map((tag) => (
            <button type="button" key={tag.id} className="chip" onClick={() => toggleTag(tag.id)} aria-pressed={selectedTags.includes(tag.id)}>
              #{tag.name} <small>{tag.count}</small>
            </button>
          ))}
          {selectedTags.length ? <button type="button" className="text-button" onClick={() => setSelectedTags([])}>필터 해제</button> : null}
        </div>
      ) : null}

      {error ? <p className="error-message" role="alert">{error}</p> : null}
      {loading && !items.length ? (
        <div className="image-grid-skeleton" role="status">
          <span className="sr-only">불러오는 중…</span>
          {Array.from({ length: 12 }, (_, index) => <div className="skeleton" key={index} aria-hidden="true" />)}
        </div>
      ) : null}
      {!loading && !items.length ? (
        <div className="empty-state">
          <ImageOff aria-hidden="true" strokeWidth={1.7} />
          <strong>{folder === "favorites" ? "조건에 맞는 즐겨찾기가 없어요" : "아직 이미지가 없어요"}</strong>
        </div>
      ) : null}

      <section className="image-grid" aria-busy={loading} aria-label="이미지 목록">
        {items.map((image, index) => (
          <article
            className={enteringImageIds.has(image.id) ? "image-card image-card-enter" : "image-card"}
            key={image.id}
            style={enteringImageIds.has(image.id) ? { animationDelay: `${Math.min(index, 8) * 45}ms` } : undefined}
          >
            <button type="button" className="image-open" onClick={() => openDetail(image)} aria-label="이미지 상세 보기">
              <img src={image.thumbnail_url} alt={image.tags.length ? image.tags.map((tag) => tag.name).join(", ") : "NovelAI 생성 이미지"} loading="lazy" />
            </button>
            {image.settings.nsfw_enabled ? <span className="image-card-flag">NSFW</span> : null}
            <div className="image-card-info" aria-hidden="true">
              <span>{image.width}×{image.height} · {expiryLabel(image.expires_at)}</span>
              {image.tags.length ? <span className="image-card-tags">{image.tags.map((tag) => `#${tag.name}`).join(" ")}</span> : null}
            </div>
            <div className="image-card-actions">
              <ImageDownloads url={image.download_url} compact />
              <button type="button" className={image.favorite_at ? "image-card-action active" : "image-card-action"} onClick={() => void toggleFavorite(image)} aria-label={image.favorite_at ? "즐겨찾기 해제" : "즐겨찾기"} title={image.favorite_at ? "즐겨찾기 해제" : "즐겨찾기"}>
                <Heart aria-hidden="true" strokeWidth={1.9} fill={image.favorite_at ? "currentColor" : "none"} />
              </button>
            </div>
          </article>
        ))}
      </section>

      {total > 50 ? (
        <nav className="gallery-pagination" aria-label="갤러리 페이지">
          <button type="button" className="icon-button weak" disabled={page === 1} onClick={() => setPage((value) => Math.max(1, value - 1))} aria-label="이전 페이지"><ChevronLeft aria-hidden="true" strokeWidth={1.8} /></button>
          <span className="counter">{page} / {lastPage}</span>
          <button type="button" className="icon-button weak" disabled={page >= lastPage} onClick={() => setPage((value) => value + 1)} aria-label="다음 페이지"><ChevronRight aria-hidden="true" strokeWidth={1.8} /></button>
        </nav>
      ) : null}

      {detail ? (
        <>
          <div className={zoomed ? "gallery-lightbox hidden-for-zoom" : "gallery-lightbox"} role="presentation" aria-hidden={zoomed || undefined} onMouseDown={closeDetail}>
            <section className="detail-modal" role="dialog" aria-modal="true" aria-label="이미지 상세" onMouseDown={(event) => event.stopPropagation()}>
              <div className="detail-stage">
                <div
                  key={detail.id}
                  className={detailMotion ? `detail-image-shell navigate-${detailMotion}` : "detail-image-shell"}
                  onTouchStart={handleTouchStart}
                  onTouchEnd={handleTouchEnd}
                  onMouseDown={(event) => { if (event.target === event.currentTarget) closeDetail(); }}
                >
                  <button type="button" className="detail-image" onClick={() => setZoomed(true)} aria-label="이미지 전체화면 보기">
                    <img src={detail.content_url} alt="선택한 생성 이미지" />
                  </button>
                </div>
                <button type="button" className="detail-close" onClick={closeDetail} aria-label="상세 이미지 닫기"><X aria-hidden="true" strokeWidth={1.8} /></button>
                <span className="detail-position">{globalDetailIndex + 1} / {total}</span>
                <button type="button" className="detail-nav previous" onClick={() => void navigateDetail(-1)} disabled={!hasPreviousDetail || detailNavigating} aria-label="이전 이미지"><ChevronLeft aria-hidden="true" strokeWidth={1.8} /></button>
                <button type="button" className="detail-nav next" onClick={() => void navigateDetail(1)} disabled={!hasNextDetail || detailNavigating} aria-label="다음 이미지"><ChevronRight aria-hidden="true" strokeWidth={1.8} /></button>
              </div>
              <div className="detail-copy" ref={detailInfoRef}>
                <div className="detail-summary">
                  <div className="detail-summary-title">
                    <span className="badge">{detail.mode}</span>
                    <h2>{new Date(detail.created_at).toLocaleString()}</h2>
                  </div>
                  <div className="detail-summary-actions">
                    <button
                      type="button"
                      className={detail.favorite_at ? "detail-summary-action detail-summary-favorite active" : "detail-summary-action detail-summary-favorite"}
                      onClick={() => void toggleFavorite(detail)}
                      aria-label={detail.favorite_at ? "즐겨찾기 해제" : "즐겨찾기에 저장"}
                      title={detail.favorite_at ? "즐겨찾기 해제" : "즐겨찾기에 저장"}
                    >
                      <Heart aria-hidden="true" strokeWidth={1.9} fill={detail.favorite_at ? "currentColor" : "none"} />
                    </button>
                    <button
                      type="button"
                      className="detail-summary-action detail-summary-discord"
                      onClick={() => openDiscordSend(detail)}
                      aria-label="Discord 웹훅으로 전송"
                      title="Discord 웹훅으로 전송"
                    >
                      <Send aria-hidden="true" strokeWidth={1.8} />
                    </button>
                    <ImageDownloads url={detail.download_url} compact />
                    <ImageCopyButtons imageId={detail.id} url={detail.download_url} notify={notify} />
                  </div>
                </div>
                <div className="detail-actions">
                  <button type="button" className="button primary" onClick={() => openReuse(detail)}>프롬프트·설정 가져오기</button>
                  <button type="button" className="button secondary" onClick={() => { onEdit(detail); closeDetail(); }}><Pencil aria-hidden="true" strokeWidth={1.8} />편집</button>
                  <button type="button" className="button danger" onClick={() => void deleteImage(detail)} aria-label="영구 삭제" title="영구 삭제"><Trash2 aria-hidden="true" strokeWidth={1.8} /></button>
                </div>
                {!wideDetail ? (
                  <button
                    type="button"
                    className="detail-disclosure"
                    aria-expanded={detailExpanded}
                    aria-controls="image-detail-information"
                    onClick={toggleDetailExpanded}
                  >
                    {detailExpanded ? "상세 정보 접기" : "상세 정보"}
                    <ChevronDown className="disclosure-icon" aria-hidden="true" strokeWidth={1.8} />
                  </button>
                ) : null}
                <div id="image-detail-information" className={detailInfoOpen ? "detail-info expanded" : "detail-info"} aria-hidden={!detailInfoOpen}>
                  <div className="detail-info-inner">
                    {detail.tags.length ? <div className="detail-tags">{detail.tags.map((tag) => <span className="badge" key={tag.id}>#{tag.name}</span>)}</div> : null}
                    <dl className="detail-metadata">
                      <div><dt>모델</dt><dd>{detail.model}</dd></div>
                      <div><dt>크기</dt><dd>{detail.width}×{detail.height}</dd></div>
                      <div><dt>시드</dt><dd>{detail.seed ?? "없음"}</dd></div>
                      <div><dt>보관</dt><dd>{expiryLabel(detail.expires_at)}</dd></div>
                    </dl>
                    <div className="detail-prompts">
                      <div className="detail-prompt"><strong>품질 프롬프트</strong><p>{detail.quality_prompt || "없음"}</p></div>
                      <div className="detail-prompt"><strong>묘사 프롬프트</strong><p>{detail.description_prompt || detail.prompt || "없음"}</p></div>
                      {detail.quality_negative_prompt ? <div className="detail-prompt"><strong>품질 네거티브</strong><p>{detail.quality_negative_prompt}</p></div> : null}
                      {detail.description_negative_prompt ? <div className="detail-prompt"><strong>묘사 네거티브</strong><p>{detail.description_negative_prompt}</p></div> : null}
                    </div>
                  </div>
                </div>
              </div>
            </section>
          </div>

          {zoomed ? (
            <ZoomableGalleryImage
              src={detail.content_url}
              alt="확대한 생성 이미지"
              motion={detailMotion}
              position={globalDetailIndex + 1}
              total={total}
              canPrevious={hasPreviousDetail}
              canNext={hasNextDetail}
              navigating={detailNavigating}
              onNavigate={(direction) => void navigateDetail(direction)}
              onExitZoom={() => setZoomed(false)}
              onSwipeClose={closeDetail}
            />
          ) : null}
        </>
      ) : null}

      {reuseTarget ? (
        <div className="modal-backdrop" role="presentation" onMouseDown={closeReuse}>
          <form
            className="modal-form gallery-reuse-dialog"
            role="dialog"
            aria-modal="true"
            aria-label="프롬프트와 생성 설정 가져오기"
            onMouseDown={(event) => event.stopPropagation()}
            onSubmit={(event) => {
              event.preventDefault();
              onReuse(reuseTarget, reuseOptions);
              closeReuse();
            }}
          >
            <button type="button" className="icon-button modal-close" onClick={closeReuse} aria-label="닫기"><X aria-hidden="true" strokeWidth={1.8} /></button>
            <div className="stack tight">
              <h2>가져올 항목</h2>
              <p className="caption">{new Date(reuseTarget.created_at).toLocaleString()} · {reuseTarget.model} · {reuseTarget.width}×{reuseTarget.height}</p>
            </div>
            <div className="row">
              <button type="button" className="text-button" onClick={() => setAllReuseOptions(true)}>모두 선택</button>
              <button type="button" className="text-button" onClick={() => setAllReuseOptions(false)}>모두 해제</button>
            </div>
            <div className="gallery-reuse-options">
              {REUSE_OPTION_LABELS.map((option) => (
                <label className="check" key={option.key}>
                  <input
                    type="checkbox"
                    checked={reuseOptions[option.key]}
                    onChange={(event) => setReuseOptions((current) => ({ ...current, [option.key]: event.target.checked }))}
                  />
                  <span>{option.label}</span>
                </label>
              ))}
            </div>
            <div className="form-actions">
              <button type="button" className="button secondary" onClick={closeReuse}>취소</button>
              <button type="submit" className="button primary" disabled={!Object.values(reuseOptions).some(Boolean)}>가져오기</button>
            </div>
          </form>
        </div>
      ) : null}

      {discordTarget ? (
        <div className="modal-backdrop" role="presentation" onMouseDown={closeDiscordSend}>
          <form
            className="modal-form gallery-discord-dialog"
            role="dialog"
            aria-modal="true"
            aria-label="Discord 웹훅으로 이미지 전송"
            onMouseDown={(event) => event.stopPropagation()}
            onSubmit={(event) => void sendToDiscord(event)}
          >
            <button type="button" className="icon-button modal-close" onClick={closeDiscordSend} disabled={discordBusy} aria-label="닫기"><X aria-hidden="true" strokeWidth={1.8} /></button>
            <div className="stack tight">
              <h2>Discord로 보내기</h2>
              <p className="caption">{new Date(discordTarget.created_at).toLocaleString()} · {discordTarget.width}×{discordTarget.height} · {discordTarget.mime_type}</p>
            </div>
            {webhooks.length ? (
              <label className="field">
                <span className="field-label">웹훅</span>
                <select required value={selectedWebhookId} onChange={(event) => setSelectedWebhookId(event.target.value)}>
                  {webhooks.map((webhook) => <option key={webhook.id} value={webhook.id}>{webhook.name}</option>)}
                </select>
              </label>
            ) : (
              <p className="error-message">저장된 웹훅이 없어요. PC의 설정에서 먼저 추가해 주세요.</p>
            )}
            <div className="stack tight">
              <label className="switch">
                <input type="checkbox" checked={includeDiscordTags} onChange={(event) => setIncludeDiscordTags(event.target.checked)} />
                <span className="switch-track" aria-hidden="true" />
                <span className="switch-label"><strong>인물 태그 포함</strong></span>
              </label>
              <label className="switch">
                <input type="checkbox" checked={includeDiscordMetadata} onChange={(event) => setIncludeDiscordMetadata(event.target.checked)} />
                <span className="switch-track" aria-hidden="true" />
                <span className="switch-label"><strong>프롬프트·설정 JSON 첨부</strong></span>
              </label>
            </div>
            {discordError ? <p className="error-message" role="alert">{discordError}</p> : null}
            <div className="form-actions">
              <button type="button" className="button secondary" onClick={closeDiscordSend} disabled={discordBusy}>취소</button>
              <button type="submit" className="button primary" disabled={discordBusy || !selectedWebhookId}>
                <Send aria-hidden="true" strokeWidth={1.8} />
                {discordBusy ? "보내는 중…" : "보내기"}
              </button>
            </div>
          </form>
        </div>
      ) : null}
    </div>
  );
}
