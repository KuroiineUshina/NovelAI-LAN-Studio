import { Download, ShieldCheck } from "lucide-react";
import { imageDownloadUrl } from "../imageDownload";

export function ImageDownloads({ url, compact = false }: { url: string; compact?: boolean }) {
  return <div className={`image-downloads${compact ? " compact" : ""}`} role="group" aria-label="이미지 다운로드">
    <a href={imageDownloadUrl(url, "preserve")} download aria-label="EXIF·생성정보 보존 다운로드" title="생성정보 포함 다운로드">
      <Download aria-hidden="true" strokeWidth={1.8} /><span>원본</span>
    </a>
    <a href={imageDownloadUrl(url, "remove")} download aria-label="EXIF·생성정보 제거 다운로드" title="생성정보 제거 다운로드">
      <ShieldCheck aria-hidden="true" strokeWidth={1.8} /><span>정보 제거</span>
    </a>
  </div>;
}
