import { useState } from "react";
import { ClipboardCopy, ClipboardX } from "lucide-react";
import { api, ApiError, errorMessage } from "../api";
import { imageDownloadUrl } from "../imageDownload";

type MetadataMode = "preserve" | "remove";

interface AndroidCopyBridge {
  copyImage?: (url: string) => boolean;
}

function androidCopyBridge(): AndroidCopyBridge | null {
  const bridge = (window as typeof window & { NovelAIAndroid?: AndroidCopyBridge }).NovelAIAndroid;
  return bridge && typeof bridge.copyImage === "function" ? bridge : null;
}

async function copyWithBrowserClipboard(url: string): Promise<void> {
  if (!window.isSecureContext || !navigator.clipboard?.write || typeof ClipboardItem === "undefined") {
    throw new Error("이 브라우저에서는 이미지 복사를 쓸 수 없어요");
  }
  const blob = await fetch(url).then((response) => {
    if (!response.ok) throw new Error("이미지를 불러오지 못했어요");
    return response.blob();
  });
  await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
}

export function ImageCopyButtons({
  imageId,
  url,
  notify,
  buttonClassName = "detail-summary-action",
}: {
  imageId: string;
  url: string;
  notify: (message: string) => void;
  buttonClassName?: string;
}) {
  const [busy, setBusy] = useState<MetadataMode | null>(null);

  const copy = async (metadata: MetadataMode) => {
    if (busy) return;
    setBusy(metadata);
    const target = imageDownloadUrl(url, metadata);
    const done = metadata === "preserve" ? "생성정보 포함해서 복사했어요" : "생성정보 없이 복사했어요";
    try {
      const android = androidCopyBridge();
      if (android?.copyImage) {
        // The Android app copies the exact file bytes and shows its own result toast.
        if (!android.copyImage(new URL(target, window.location.href).href)) throw new Error("복사하지 못했어요");
        return;
      }
      try {
        // On the PC the app writes the Windows clipboard itself, so the original file survives.
        await api(`/api/images/${encodeURIComponent(imageId)}/clipboard?metadata=${metadata}`, { method: "POST" });
        notify(done);
        return;
      } catch (error) {
        if (!(error instanceof ApiError) || (error.status !== 401 && error.status !== 403)) throw error;
      }
      // Other devices: browsers re-encode copied images, so text metadata cannot be kept.
      await copyWithBrowserClipboard(target);
      notify(metadata === "preserve" ? "복사했어요. 브라우저에서는 생성정보가 빠질 수 있어요" : done);
    } catch (error) {
      notify(errorMessage(error));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="image-copy-buttons" role="group" aria-label="이미지 복사">
      <button
        type="button"
        className={buttonClassName}
        onClick={() => void copy("preserve")}
        disabled={busy !== null}
        aria-label="생성정보 포함 복사"
        title="생성정보 포함 복사"
      >
        <ClipboardCopy aria-hidden="true" strokeWidth={1.8} />
      </button>
      <button
        type="button"
        className={buttonClassName}
        onClick={() => void copy("remove")}
        disabled={busy !== null}
        aria-label="생성정보 제거 복사"
        title="생성정보 제거 복사"
      >
        <ClipboardX aria-hidden="true" strokeWidth={1.8} />
      </button>
    </div>
  );
}
