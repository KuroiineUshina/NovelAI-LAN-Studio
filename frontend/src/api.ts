export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function parseError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string | Array<{ msg?: string }> };
    if (typeof payload.detail === "string") return payload.detail;
    if (Array.isArray(payload.detail)) return payload.detail.map((item) => item.msg ?? "입력 오류").join("\n");
  } catch {
    // Fall through to the status text.
  }
  return response.statusText || "요청하지 못했어요";
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/api/device-auth/")) {
      window.dispatchEvent(new Event("novelai-device-authorization-lost"));
    }
    throw new ApiError(await parseError(response), response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function uploadFile<T>(path: string, file: File, fields?: Record<string, string>): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  if (fields) Object.entries(fields).forEach(([key, value]) => form.append(key, value));
  return api<T>(path, { method: "POST", body: form });
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "알 수 없는 문제가 생겼어요";
}
