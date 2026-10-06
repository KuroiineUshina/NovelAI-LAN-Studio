import { useEffect, useMemo, useState } from "react";
import { Check, Laptop, ShieldCheck, Smartphone, TriangleAlert } from "lucide-react";
import { api, errorMessage } from "../api";
import "../settings.css";

const DEVICE_ID_KEY = "novelai-lan-studio-device-id";
const DEVICE_NAME_KEY = "novelai-lan-studio-device-name";
const PAIRING_SECRET_KEY = "novelai-lan-studio-pairing-secret";

type ApprovalState = "idle" | "requesting" | "waiting" | "approved" | "denied" | "expired";

interface Props {
  onAuthorized: () => void;
}

interface PollResponse {
  status: "pending" | "approved" | "denied" | "expired";
  device_id: string;
  display_name?: string;
}

function randomHex(bytes: number): string {
  const values = new Uint8Array(bytes);
  globalThis.crypto.getRandomValues(values);
  return Array.from(values, (value) => value.toString(16).padStart(2, "0")).join("");
}

function loadOrCreateDeviceId(): string {
  const existing = window.localStorage.getItem(DEVICE_ID_KEY);
  if (existing) return existing;
  const uuid = globalThis.crypto.randomUUID?.() ?? `${Date.now().toString(36)}-${randomHex(16)}`;
  const created = `mobile-${uuid}`;
  window.localStorage.setItem(DEVICE_ID_KEY, created);
  return created;
}

function suggestedDeviceName(): string {
  const saved = window.localStorage.getItem(DEVICE_NAME_KEY);
  if (saved) return saved;
  const userAgent = navigator.userAgent;
  if (/iPad/i.test(userAgent) || (/Macintosh/i.test(userAgent) && navigator.maxTouchPoints > 1)) return "iPad";
  if (/Android/i.test(userAgent)) return "Android 모바일";
  if (/iPhone/i.test(userAgent)) return "iPhone";
  return "모바일 브라우저";
}

export function DeviceApprovalView({ onAuthorized }: Props) {
  const deviceId = useMemo(loadOrCreateDeviceId, []);
  const [deviceName, setDeviceName] = useState(suggestedDeviceName);
  const [pairingSecret, setPairingSecret] = useState(
    () => window.localStorage.getItem(PAIRING_SECRET_KEY) ?? "",
  );
  const [state, setState] = useState<ApprovalState>(pairingSecret ? "waiting" : "idle");
  const [error, setError] = useState("");

  const requestApproval = async () => {
    const normalizedName = deviceName.trim();
    if (!normalizedName) return;
    const secret = randomHex(32);
    setState("requesting");
    setError("");
    try {
      await api("/api/device-auth/request", {
        method: "POST",
        body: JSON.stringify({
          device_id: deviceId,
          display_name: normalizedName,
          pairing_secret: secret,
        }),
      });
      window.localStorage.setItem(DEVICE_NAME_KEY, normalizedName);
      window.localStorage.setItem(PAIRING_SECRET_KEY, secret);
      setPairingSecret(secret);
      setState("waiting");
    } catch (requestError) {
      setState("idle");
      setError(errorMessage(requestError));
    }
  };

  useEffect(() => {
    if (state !== "waiting" || !pairingSecret) return;
    let active = true;
    let timer = 0;
    const poll = async () => {
      try {
        const result = await api<PollResponse>("/api/device-auth/poll", {
          method: "POST",
          body: JSON.stringify({ device_id: deviceId, pairing_secret: pairingSecret }),
        });
        if (!active) return;
        if (result.status === "approved") {
          window.localStorage.removeItem(PAIRING_SECRET_KEY);
          setState("approved");
          window.setTimeout(onAuthorized, 450);
          return;
        }
        if (result.status === "denied") {
          window.localStorage.removeItem(PAIRING_SECRET_KEY);
          setPairingSecret("");
          setState("denied");
          return;
        }
        if (result.status === "expired") {
          window.localStorage.removeItem(PAIRING_SECRET_KEY);
          setPairingSecret("");
          setState("expired");
          return;
        }
        timer = window.setTimeout(() => void poll(), 2_000);
      } catch (pollError) {
        if (!active) return;
        setError(errorMessage(pollError));
        timer = window.setTimeout(() => void poll(), 3_000);
      }
    };
    void poll();
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [deviceId, onAuthorized, pairingSecret, state]);

  const needsRequest = state === "idle" || state === "denied" || state === "expired";

  return (
    <main className="device-approval-screen">
      <section className="device-approval-card" aria-live="polite">
        <span className={state === "approved" ? "device-approval-icon approved" : "device-approval-icon"} aria-hidden="true">
          {state === "approved" ? <Check /> : <Smartphone />}
        </span>
        <h1>{state === "approved" ? "연결됐어요" : "PC 승인이 필요해요"}</h1>

        {needsRequest ? (
          <form
            className="device-approval-form"
            onSubmit={(event) => {
              event.preventDefault();
              void requestApproval();
            }}
          >
            {state === "denied" ? <div className="callout warning"><TriangleAlert aria-hidden="true" /><span>PC에서 요청을 거절했어요</span></div> : null}
            {state === "expired" ? <div className="callout warning"><TriangleAlert aria-hidden="true" /><span>요청이 만료됐어요. 다시 요청해 주세요</span></div> : null}
            <label className="field">
              <span className="field-label">기기 이름</span>
              <input
                maxLength={80}
                value={deviceName}
                onChange={(event) => setDeviceName(event.target.value)}
                placeholder="예: 내 Galaxy Fold"
              />
            </label>
            <button type="submit" className="button primary large block" disabled={!deviceName.trim()}>
              <ShieldCheck aria-hidden="true" />승인 요청
            </button>
          </form>
        ) : null}

        {state === "requesting" ? (
          <div className="device-waiting">
            <div className="spinner" aria-hidden="true" />
            <strong>요청을 보내는 중…</strong>
          </div>
        ) : null}
        {state === "waiting" ? (
          <div className="device-waiting">
            <div className="spinner" aria-hidden="true" />
            <strong>PC 승인을 기다리는 중…</strong>
            <span><Laptop aria-hidden="true" />PC의 설정 → 연결 기기에서 승인해 주세요</span>
          </div>
        ) : null}
        {state === "approved" ? <div className="device-waiting"><strong>스튜디오를 여는 중…</strong></div> : null}
        {error ? <p className="error-message" role="alert">{error}</p> : null}
        <small className="device-id-hint">기기 ID {deviceId.slice(-12)}</small>
      </section>
    </main>
  );
}
