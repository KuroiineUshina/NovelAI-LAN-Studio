export function imageDownloadUrl(url: string, metadata: "preserve" | "remove"): string {
  const parsed = new URL(url, "http://studio.local");
  parsed.searchParams.set("metadata", metadata);
  return url.startsWith("/") ? parsed.pathname + parsed.search + parsed.hash : parsed.href;
}
