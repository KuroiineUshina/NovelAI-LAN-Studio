import { useEffect, useState } from "react";
import { Check, Copy, FolderOpen, MonitorCog, Pencil, Plus, RefreshCw, Smartphone, Trash2, TriangleAlert, X } from "lucide-react";
import { api, errorMessage } from "../api";
import { APP_FONTS } from "../fonts";
import type { AppFontId } from "../fonts";
import type { AppStatus, ClaudeIntegrationStatus, DeviceApproval, DiscordWebhookTarget } from "../types";
import "../settings.css";

interface AutostartStatus {
  supported: boolean;
  enabled: boolean;
  registered: boolean;
  matches_current: boolean;
  message: string;
}

interface AdminSettings {
  has_token: boolean;
  data_directory: string;
  image_storage_directory: string;
  default_image_storage_directory: string;
  storage_warning: string | null;
  port: number;
  retention_hours: number;
  lan_urls: string[];
  tailscale_urls: string[];
  mobile_urls: string[];
  autostart: AutostartStatus;
  claude: ClaudeIntegrationStatus;
}

interface Props {
  status: AppStatus;
  reloadStatus: () => Promise<void>;
  notify: (message: string) => void;
  fontId: AppFontId;
  onFontChange: (fontId: AppFontId) => void;
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatRelativeTime(value: string | null | undefined): string {
  if (!value) return "없음";
  const date = new Date(value);
  const time = date.getTime();
  if (Number.isNaN(time)) return value;
  const seconds = Math.max(0, Math.round((Date.now() - time) / 1000));
  if (seconds < 60) return "방금 전";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}분 전`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}시간 전`;
  return date.toLocaleString();
}

function FontSettingRow({ fontId, onChange }: { fontId: AppFontId; onChange: (fontId: AppFontId) => void }) {
  const categories = ["기본", "고딕", "명조"] as const;
  return (
    <div className="list-item">
      <div className="list-item-content">
        <span className="list-item-title">글꼴</span>
        <span className="list-item-detail">내장 고딕 4종과 명조 4종 · SIL Open Font License 1.1</span>
      </div>
      <div className="list-item-actions">
        <select className="settings-select" aria-label="앱 글꼴" value={fontId} onChange={(event) => onChange(event.target.value as AppFontId)}>
          {categories.map((category) => (
            <optgroup label={category} key={category}>
              {APP_FONTS.filter((font) => font.category === category).map((font) => <option value={font.id} key={font.id}>{font.label}</option>)}
            </optgroup>
          ))}
        </select>
      </div>
    </div>
  );
}

export function SettingsView({ status, reloadStatus, notify, fontId, onFontChange }: Props) {
  const [settings, setSettings] = useState<AdminSettings | null>(null);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [connection, setConnection] = useState("");
  const [webhooks, setWebhooks] = useState<DiscordWebhookTarget[]>([]);
  const [webhookName, setWebhookName] = useState("");
  const [webhookUrl, setWebhookUrl] = useState("");
  const [editingWebhookId, setEditingWebhookId] = useState<string | null>(null);
  const [webhookDialogOpen, setWebhookDialogOpen] = useState(false);
  const [webhookBusy, setWebhookBusy] = useState(false);
  const [webhookError, setWebhookError] = useState("");
  const [devices, setDevices] = useState<DeviceApproval[]>([]);
  const [deviceBusyId, setDeviceBusyId] = useState<string | null>(null);
  const [deviceError, setDeviceError] = useState("");
  const [claude, setClaude] = useState<ClaudeIntegrationStatus | null>(null);
  const [claudeChecking, setClaudeChecking] = useState(false);
  const [claudeInstalling, setClaudeInstalling] = useState(false);
  const [claudeError, setClaudeError] = useState("");
  const [autostartBusy, setAutostartBusy] = useState(false);
  const [autostartError, setAutostartError] = useState("");
  const [storageDirectory, setStorageDirectory] = useState("");
  const [storageBusy, setStorageBusy] = useState(false);
  const [storageError, setStorageError] = useState("");

  const changeFont = (next: AppFontId) => {
    onFontChange(next);
    notify("이 기기의 글꼴을 바꿨어요");
  };

  const reloadWebhooks = async () => {
    const result = await api<{ items: DiscordWebhookTarget[] }>("/api/admin/webhooks");
    setWebhooks(result.items);
  };

  const reloadDevices = async () => {
    const result = await api<{ items: DeviceApproval[] }>("/api/admin/devices");
    setDevices(result.items);
  };

  useEffect(() => {
    if (!status.admin_available) return;
    Promise.all([
      api<AdminSettings>("/api/admin/settings"),
      api<{ items: DiscordWebhookTarget[] }>("/api/admin/webhooks"),
      api<{ items: DeviceApproval[] }>("/api/admin/devices"),
    ])
      .then(([settingsResult, webhookResult, deviceResult]) => {
        setSettings(settingsResult);
        setStorageDirectory(settingsResult.image_storage_directory);
        setClaude(settingsResult.claude);
        setWebhooks(webhookResult.items);
        setDevices(deviceResult.items);
      })
      .catch((loadError) => setError(errorMessage(loadError)));
  }, [status.admin_available, status.has_token]);

  useEffect(() => {
    if (!status.admin_available) return;
    const timer = window.setInterval(() => {
      void api<ClaudeIntegrationStatus>("/api/admin/claude/status")
        .then(setClaude)
        .catch(() => undefined);
    }, 5_000);
    return () => window.clearInterval(timer);
  }, [status.admin_available]);

  useEffect(() => {
    if (!status.admin_available) return;
    const timer = window.setInterval(() => {
      void reloadDevices().catch(() => undefined);
    }, 2_000);
    return () => window.clearInterval(timer);
  }, [status.admin_available]);

  useEffect(() => {
    if (!webhookDialogOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setWebhookDialogOpen(false);
        setEditingWebhookId(null);
        setWebhookName("");
        setWebhookUrl("");
        setWebhookError("");
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [webhookDialogOpen]);

  if (!status.admin_available) {
    return (
      <div className="page narrow settings-view">
        <header className="page-header"><h1>설정</h1></header>
        <section className="panel">
          <div className="panel-header"><h2>일반</h2></div>
          <div className="list"><FontSettingRow fontId={fontId} onChange={changeFont} /></div>
        </section>
        <section className="panel">
          <div className="empty-state">
            <MonitorCog aria-hidden="true" strokeWidth={1.7} />
            <strong>나머지 설정은 PC에서 열어 주세요</strong>
          </div>
        </section>
      </div>
    );
  }

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/api/admin/settings/token", { method: "PUT", body: JSON.stringify({ token }) });
      setToken("");
      await reloadStatus();
      notify("API 토큰을 저장했어요");
    } catch (saveError) {
      setError(errorMessage(saveError));
    } finally {
      setBusy(false);
    }
  };

  const test = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await api<{ active: boolean; tier: number }>("/api/admin/settings/token/test", { method: "POST" });
      setConnection(`연결됨 · 구독 ${result.active ? "활성" : "비활성"} · 티어 ${result.tier ?? "확인 안 됨"}`);
    } catch (testError) {
      setConnection("");
      setError(errorMessage(testError));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!window.confirm("저장된 NovelAI API 토큰을 삭제할까요?")) return;
    setBusy(true);
    try {
      await api("/api/admin/settings/token", { method: "DELETE" });
      await reloadStatus();
      setConnection("");
      notify("API 토큰을 삭제했어요");
    } catch (removeError) {
      setError(errorMessage(removeError));
    } finally {
      setBusy(false);
    }
  };

  const cleanup = async () => {
    setBusy(true);
    try {
      const result = await api<{ images: number; uploads: number }>("/api/admin/cleanup", { method: "POST" });
      notify(`이미지 ${result.images}장, 업로드 ${result.uploads}개를 정리했어요`);
    } catch (cleanupError) {
      setStorageError(errorMessage(cleanupError));
    } finally {
      setBusy(false);
    }
  };

  const updateAutostart = async (enabled: boolean) => {
    setAutostartBusy(true);
    setAutostartError("");
    try {
      const result = await api<AutostartStatus>("/api/admin/settings/autostart", {
        method: "PUT",
        body: JSON.stringify({ enabled }),
      });
      setSettings((current) => current ? { ...current, autostart: result } : current);
      notify(enabled ? "자동 실행을 켰어요" : "자동 실행을 껐어요");
    } catch (autostartUpdateError) {
      setAutostartError(errorMessage(autostartUpdateError));
    } finally {
      setAutostartBusy(false);
    }
  };

  const applyStorageDirectory = async (directory: string) => {
    const normalized = directory.trim();
    if (!normalized || storageBusy) return;
    if (normalized === settings?.image_storage_directory && !settings?.storage_warning) {
      notify("이미 사용 중인 폴더예요");
      return;
    }
    if (!window.confirm(`이미지 저장 폴더를 바꿀까요?\n\n${normalized}\n\n기존 파일을 모두 복사·확인한 뒤 이전 폴더를 정리해요.`)) return;
    setStorageBusy(true);
    setStorageError("");
    try {
      const result = await api<{
        image_storage_directory: string;
        default_image_storage_directory: string;
        storage_warning: string | null;
        moved: boolean;
      }>("/api/admin/settings/image-storage", {
        method: "PUT",
        body: JSON.stringify({ directory: normalized }),
      });
      setSettings((current) => current ? {
        ...current,
        image_storage_directory: result.image_storage_directory,
        default_image_storage_directory: result.default_image_storage_directory,
        storage_warning: result.storage_warning,
      } : current);
      setStorageDirectory(result.image_storage_directory);
      notify(result.storage_warning ?? (result.moved ? "폴더를 바꾸고 파일을 옮겼어요" : "이미 적용된 폴더예요"));
    } catch (storageUpdateError) {
      setStorageError(errorMessage(storageUpdateError));
    } finally {
      setStorageBusy(false);
    }
  };

  const recheckClaude = async () => {
    setClaudeChecking(true);
    setClaudeError("");
    try {
      setClaude(await api<ClaudeIntegrationStatus>("/api/admin/claude/status"));
    } catch (checkError) {
      setClaudeError(errorMessage(checkError));
    } finally {
      setClaudeChecking(false);
    }
  };

  const installClaudeSkill = async () => {
    const updating = Boolean(claude?.skill_installed);
    setClaudeInstalling(true);
    setClaudeError("");
    try {
      const result = await api<ClaudeIntegrationStatus>("/api/admin/claude/skill", { method: "POST" });
      setClaude(result);
      notify(updating ? "프롬프트 스킬을 업데이트했어요" : "프롬프트 스킬을 설치했어요");
    } catch (installError) {
      setClaudeError(errorMessage(installError));
    } finally {
      setClaudeInstalling(false);
    }
  };

  const copyRegisterCommand = async () => {
    if (!claude?.register_command) return;
    try {
      await navigator.clipboard.writeText(claude.register_command);
      notify("명령어를 복사했어요");
    } catch {
      setClaudeError("복사하지 못했어요. 명령어를 직접 선택해 복사해 주세요");
    }
  };

  const resetWebhookForm = () => {
    setWebhookDialogOpen(false);
    setEditingWebhookId(null);
    setWebhookName("");
    setWebhookUrl("");
    setWebhookError("");
  };

  const addWebhook = () => {
    setEditingWebhookId(null);
    setWebhookName("");
    setWebhookUrl("");
    setWebhookError("");
    setWebhookDialogOpen(true);
  };

  const editWebhook = (webhook: DiscordWebhookTarget) => {
    setEditingWebhookId(webhook.id);
    setWebhookName(webhook.name);
    setWebhookUrl("");
    setWebhookError("");
    setWebhookDialogOpen(true);
  };

  const saveWebhook = async (event: React.FormEvent) => {
    event.preventDefault();
    setWebhookBusy(true);
    setWebhookError("");
    try {
      const path = editingWebhookId
        ? `/api/admin/webhooks/${editingWebhookId}`
        : "/api/admin/webhooks";
      await api<DiscordWebhookTarget>(path, {
        method: editingWebhookId ? "PUT" : "POST",
        body: JSON.stringify({
          name: webhookName.trim(),
          url: webhookUrl.trim(),
        }),
      });
      const savedName = webhookName.trim();
      const edited = Boolean(editingWebhookId);
      resetWebhookForm();
      await reloadWebhooks();
      notify(`웹훅 ‘${savedName}’을 ${edited ? "수정" : "저장"}했어요`);
    } catch (saveError) {
      setWebhookError(errorMessage(saveError));
    } finally {
      setWebhookBusy(false);
    }
  };

  const removeWebhook = async (webhook: DiscordWebhookTarget) => {
    if (!window.confirm(`Discord 웹훅 ‘${webhook.name}’을 삭제할까요?`)) return;
    setWebhookBusy(true);
    setWebhookError("");
    try {
      await api(`/api/admin/webhooks/${webhook.id}`, { method: "DELETE" });
      if (editingWebhookId === webhook.id) resetWebhookForm();
      await reloadWebhooks();
      notify(`웹훅 ‘${webhook.name}’을 삭제했어요`);
    } catch (removeError) {
      setWebhookError(errorMessage(removeError));
    } finally {
      setWebhookBusy(false);
    }
  };

  const decideDevice = async (device: DeviceApproval, decision: "approve" | "deny") => {
    setDeviceBusyId(device.device_id);
    setDeviceError("");
    try {
      await api(`/api/admin/devices/${device.device_id}/${decision}`, { method: "POST" });
      await Promise.all([reloadDevices(), reloadStatus()]);
      notify(
        decision === "approve"
          ? `‘${device.display_name}’ 연결을 승인했어요`
          : `‘${device.display_name}’ 연결을 거절했어요`,
      );
    } catch (decisionError) {
      setDeviceError(errorMessage(decisionError));
    } finally {
      setDeviceBusyId(null);
    }
  };

  const revokeDevice = async (device: DeviceApproval) => {
    if (!window.confirm(`‘${device.display_name}’ 기기의 자동 로그인을 해제할까요?`)) return;
    setDeviceBusyId(device.device_id);
    setDeviceError("");
    try {
      await api(`/api/admin/devices/${device.device_id}`, { method: "DELETE" });
      await Promise.all([reloadDevices(), reloadStatus()]);
      notify(`‘${device.display_name}’ 승인을 해제했어요`);
    } catch (revokeError) {
      setDeviceError(errorMessage(revokeError));
    } finally {
      setDeviceBusyId(null);
    }
  };

  const pendingDevices = devices.filter((device) => device.status === "pending" || device.status === "expired");
  const approvedDevices = devices.filter((device) => device.status === "approved");
  const skillLabel = !claude ? "" : !claude.skill_installed ? "설치 필요" : claude.skill_up_to_date ? "설치됨" : "업데이트 있음";
  const claudeDot = !claude ? "off" : claude.state === "ready" ? "" : "warning";

  return (
    <div className="page narrow settings-view">
      <header className="page-header"><h1>설정</h1></header>

      <section className="panel">
        <div className="panel-header"><h2>일반</h2></div>
        <div className="list">
          <FontSettingRow fontId={fontId} onChange={changeFont} />
          <div className="list-item">
            <label className="switch settings-switch">
              <input
                type="checkbox"
                role="switch"
                checked={settings?.autostart.enabled ?? false}
                disabled={autostartBusy || !settings?.autostart.supported}
                onChange={(event) => void updateAutostart(event.target.checked)}
                aria-label="Windows 시작 시 자동 실행"
              />
              <span className="switch-track" aria-hidden="true" />
              <span className="switch-label">
                <strong>Windows 시작 시 자동 실행</strong>
                <small>{settings?.autostart.message ?? "불러오는 중…"}</small>
              </span>
            </label>
          </div>
        </div>
        {autostartError ? <p className="error-message" role="alert">{autostartError}</p> : null}
      </section>

      <form className="panel" onSubmit={save}>
        <div className="panel-header"><h2>NovelAI</h2></div>
        <div className="list">
          <div className="list-item">
            <div className="list-item-content">
              <span className="list-item-title">API 토큰</span>
              <span className="list-item-detail">{status.has_token ? "저장됨" : "없음"}</span>
              {connection ? <span className="list-item-detail settings-success">{connection}</span> : null}
            </div>
            {status.has_token ? (
              <div className="list-item-actions">
                <button type="button" className="button secondary small" onClick={() => void test()} disabled={busy}>연결 테스트</button>
                <button type="button" className="icon-button danger" onClick={() => void remove()} disabled={busy} aria-label="API 토큰 삭제"><Trash2 aria-hidden="true" /></button>
              </div>
            ) : null}
          </div>
        </div>
        <div className="settings-inline-form">
          <input type="password" autoComplete="off" minLength={8} value={token} onChange={(event) => setToken(event.target.value)} placeholder={status.has_token ? "새 Persistent API Token" : "Persistent API Token 붙여넣기"} aria-label="새 토큰" required />
          <button className="button primary" type="submit" disabled={busy}>{status.has_token ? "토큰 교체" : "토큰 저장"}</button>
        </div>
        <p className="caption settings-note">토큰은 Windows 자격 증명 관리자에 안전하게 보관돼요</p>
        {error ? <p className="error-message" role="alert">{error}</p> : null}
      </form>

      <section className="panel">
        <div className="panel-header">
          <h2>Claude</h2>
          <div className="panel-actions">
            <button type="button" className="icon-button" onClick={() => void recheckClaude()} disabled={claudeChecking} aria-label="다시 확인" title="다시 확인">
              <RefreshCw aria-hidden="true" strokeWidth={1.8} className={claudeChecking ? "spin" : undefined} />
            </button>
          </div>
        </div>
        <p className="settings-summary"><span className={`live-dot ${claudeDot}`} aria-hidden="true" />{claude?.message ?? "불러오는 중…"}</p>
        <div className="list">
          <div className="list-item">
            <div className="list-item-content">
              <span className="list-item-title">MCP 연결</span>
              <span className="list-item-detail">{claude?.mcp_registered ? (claude.mcp_server_name ?? claude.mcp_url) : claude?.mcp_url ?? ""}</span>
            </div>
            {claude ? <div className="list-item-actions"><span className={claude.mcp_registered ? "badge positive" : "badge warning"}>{claude.mcp_registered ? "등록됨" : "등록 필요"}</span></div> : null}
          </div>
          {claude && !claude.mcp_registered && claude.register_command ? (
            <div className="settings-command">
              <code className="mono">{claude.register_command}</code>
              <button type="button" className="icon-button small" onClick={() => void copyRegisterCommand()} aria-label="등록 명령어 복사" title="복사"><Copy aria-hidden="true" /></button>
            </div>
          ) : null}
          <div className="list-item">
            <div className="list-item-content">
              <span className="list-item-title">프롬프트 스킬</span>
              <span className="list-item-detail">{claude?.skill_name ?? ""}</span>
            </div>
            {claude ? (
              <div className="list-item-actions">
                <span className={claude.skill_installed && claude.skill_up_to_date ? "badge positive" : "badge warning"}>{skillLabel}</span>
                {!claude.skill_installed || !claude.skill_up_to_date ? (
                  <button type="button" className="button secondary small" onClick={() => void installClaudeSkill()} disabled={claudeInstalling}>
                    {claudeInstalling ? "설치 중…" : claude.skill_installed ? "업데이트" : "설치"}
                  </button>
                ) : null}
              </div>
            ) : null}
          </div>
          <div className="list-item">
            <div className="list-item-content">
              <span className="list-item-title">최근 요청</span>
              <span className="list-item-detail" title={formatDateTime(claude?.last_mcp_activity_at)}>{claude ? formatRelativeTime(claude.last_mcp_activity_at) : ""}</span>
            </div>
          </div>
        </div>
        {claudeError ? <p className="error-message" role="alert">{claudeError}</p> : null}
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>연결 기기</h2>
          {pendingDevices.length ? <div className="panel-actions"><span className="badge warning">대기 {pendingDevices.length}</span></div> : null}
        </div>
        <div className="list">
          {pendingDevices.map((device) => (
            <div className="list-item" key={device.device_id}>
              <span className="settings-row-icon pending" aria-hidden="true"><Smartphone /></span>
              <div className="list-item-content">
                <span className="list-item-title">{device.display_name}</span>
                <span className="list-item-detail">{device.last_address || "주소 확인 안 됨"} · {formatDateTime(device.requested_at)}</span>
                <span className="list-item-detail">{device.status === "expired" ? "만료됨 · 모바일에서 다시 요청해 주세요" : device.user_agent}</span>
              </div>
              <div className="list-item-actions">
                <button type="button" className="icon-button weak settings-approve" disabled={device.status === "expired" || deviceBusyId === device.device_id} onClick={() => void decideDevice(device, "approve")} aria-label={`${device.display_name} 승인`}><Check aria-hidden="true" /></button>
                <button type="button" className="icon-button weak danger" disabled={deviceBusyId === device.device_id} onClick={() => void decideDevice(device, "deny")} aria-label={`${device.display_name} 거절`}><X aria-hidden="true" /></button>
              </div>
            </div>
          ))}
          {approvedDevices.map((device) => (
            <div className="list-item" key={device.device_id}>
              <span className="settings-row-icon" aria-hidden="true"><Smartphone /></span>
              <div className="list-item-content">
                <span className="list-item-title">{device.display_name}</span>
                <span className="list-item-detail">{device.last_address || "주소 확인 안 됨"} · 최근 접속 {device.last_seen_at ? formatDateTime(device.last_seen_at) : "없음"}</span>
              </div>
              <div className="list-item-actions">
                <button type="button" className="button ghost small" disabled={deviceBusyId === device.device_id} onClick={() => void revokeDevice(device)}>승인 해제</button>
              </div>
            </div>
          ))}
          {!pendingDevices.length && !approvedDevices.length ? <p className="empty-inline settings-empty">연결된 기기가 없어요</p> : null}
        </div>
        {deviceError ? <p className="error-message" role="alert">{deviceError}</p> : null}
      </section>

      <section className="panel">
        <div className="panel-header"><h2>저장 공간</h2></div>
        <div className="list">
          <details className="disclosure settings-row-disclosure">
            <summary>
              <span className="list-item-content">
                <span className="list-item-title">이미지 저장 폴더</span>
                <span className="list-item-detail mono">{settings?.image_storage_directory ?? "불러오는 중…"}</span>
              </span>
            </summary>
            <div className="settings-disclosure-body">
              <input
                type="text"
                value={storageDirectory}
                disabled={storageBusy}
                onChange={(event) => setStorageDirectory(event.target.value)}
                placeholder="빈 폴더의 전체 경로 (예: D:\NovelAI Images)"
                aria-label="새 이미지 저장 폴더"
                spellCheck={false}
              />
              <p className="caption">임시 이미지·즐겨찾기·썸네일·편집 파일도 함께 옮겨져요</p>
              <div className="row wrap settings-button-row">
                <button
                  type="button"
                  className="button secondary small"
                  disabled={storageBusy || !settings}
                  onClick={() => {
                    if (!settings) return;
                    setStorageDirectory(settings.default_image_storage_directory);
                    void applyStorageDirectory(settings.default_image_storage_directory);
                  }}
                >
                  기본 폴더로
                </button>
                <button type="button" className="button primary small" disabled={storageBusy || !storageDirectory.trim()} onClick={() => void applyStorageDirectory(storageDirectory)}>
                  <FolderOpen aria-hidden="true" strokeWidth={1.8} />
                  {storageBusy ? "옮기는 중…" : "폴더 변경"}
                </button>
              </div>
            </div>
          </details>
          <div className="list-item">
            <div className="list-item-content">
              <span className="list-item-title">자동 정리</span>
              <span className="list-item-detail">{settings?.retention_hours ?? 168}시간 지난 임시 파일</span>
            </div>
            <div className="list-item-actions">
              <button type="button" className="button secondary small" onClick={() => void cleanup()} disabled={busy}>지금 정리</button>
            </div>
          </div>
          <div className="list-item">
            <div className="list-item-content">
              <span className="list-item-title">앱 데이터</span>
              <span className="list-item-detail mono">{settings?.data_directory ?? "불러오는 중…"}</span>
            </div>
          </div>
        </div>
        {settings?.storage_warning ? <div className="callout warning settings-callout" role="status"><TriangleAlert aria-hidden="true" /><span>{settings.storage_warning}</span></div> : null}
        {storageError ? <p className="error-message" role="alert">{storageError}</p> : null}
      </section>

      <section className="panel">
        <div className="panel-header"><h2>네트워크</h2></div>
        <div className="list">
          <div className="list-item">
            <div className="list-item-content">
              <span className="list-item-title">LAN</span>
              <span className="list-item-detail mono">{settings?.lan_urls.join(", ") || "개인 네트워크 주소 없음"}</span>
            </div>
          </div>
          <div className="list-item">
            <div className="list-item-content">
              <span className="list-item-title">Tailscale</span>
              <span className="list-item-detail mono">{settings?.tailscale_urls.join(", ") || "연결 안 됨 · 연결 후 앱을 다시 시작해 주세요"}</span>
            </div>
          </div>
          <div className="list-item">
            <div className="list-item-content">
              <span className="list-item-title">포트</span>
              <span className="list-item-detail mono">{settings?.port ?? 8787}</span>
            </div>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Discord 웹훅</h2>
          <div className="panel-actions">
            <button type="button" className="button secondary small" onClick={addWebhook}><Plus aria-hidden="true" strokeWidth={1.8} />추가</button>
          </div>
        </div>
        <div className="list" aria-label="저장된 Discord 웹훅">
          {webhooks.map((webhook) => (
            <div className="list-item" key={webhook.id}>
              <div className="list-item-content">
                <span className="list-item-title">{webhook.name}</span>
                <span className={webhook.configured ? "list-item-detail" : "list-item-detail settings-warning-text"}>{webhook.configured ? "주소 저장됨" : "주소를 다시 저장해 주세요"}</span>
              </div>
              <div className="list-item-actions">
                <button type="button" className="icon-button" onClick={() => editWebhook(webhook)} aria-label={`${webhook.name} 수정`}><Pencil aria-hidden="true" strokeWidth={1.8} /></button>
                <button type="button" className="icon-button danger" onClick={() => void removeWebhook(webhook)} disabled={webhookBusy} aria-label={`${webhook.name} 삭제`}><Trash2 aria-hidden="true" strokeWidth={1.8} /></button>
              </div>
            </div>
          ))}
          {!webhooks.length ? <p className="empty-inline settings-empty">저장된 웹훅이 없어요</p> : null}
        </div>
        {webhookError && !webhookDialogOpen ? <p className="error-message" role="alert">{webhookError}</p> : null}
      </section>

      {webhookDialogOpen ? (
        <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) resetWebhookForm(); }}>
          <form className="modal-form settings-webhook-dialog" role="dialog" aria-modal="true" aria-labelledby="settings-webhook-title" onSubmit={(event) => void saveWebhook(event)}>
            <h2 id="settings-webhook-title">{editingWebhookId ? "웹훅 수정" : "웹훅 추가"}</h2>
            <button type="button" className="icon-button modal-close" onClick={resetWebhookForm} aria-label="닫기"><X aria-hidden="true" /></button>
            <label className="field">
              <span className="field-label">이름</span>
              <input required autoFocus maxLength={80} value={webhookName} onChange={(event) => setWebhookName(event.target.value)} placeholder="예: 개인 작업 채널" />
            </label>
            <label className="field">
              <span className="field-label">웹훅 URL</span>
              <input
                type="password"
                autoComplete="off"
                required={!editingWebhookId}
                value={webhookUrl}
                onChange={(event) => setWebhookUrl(event.target.value)}
                placeholder={editingWebhookId ? "비워 두면 기존 주소 유지" : "https://discord.com/api/webhooks/…"}
              />
              <span className="field-description">주소는 Windows 자격 증명 관리자에 보관돼요</span>
            </label>
            {webhookError ? <p className="error-message" role="alert">{webhookError}</p> : null}
            <div className="form-actions">
              <button type="button" className="button secondary" onClick={resetWebhookForm}>취소</button>
              <button type="submit" className="button primary" disabled={webhookBusy || !webhookName.trim() || (!editingWebhookId && !webhookUrl.trim())}>
                {webhookBusy ? "저장 중…" : editingWebhookId ? "수정" : "추가"}
              </button>
            </div>
          </form>
        </div>
      ) : null}
    </div>
  );
}
