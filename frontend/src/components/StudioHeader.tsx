import { useEffect, useRef } from "react";
import { ChartColumn, ChevronDown, Copy, Images, KeyRound, Moon, Settings, ShieldCheck, Sparkles, Sun, UsersRound } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { AppStatus, Tab } from "../types";

const NAVIGATION: Array<{ id: Tab; label: string; icon: LucideIcon }> = [
  { id: "generate", label: "생성", icon: Sparkles },
  { id: "gallery", label: "갤러리", icon: Images },
  { id: "presets", label: "인물", icon: UsersRound },
  { id: "stats", label: "통계", icon: ChartColumn },
  { id: "settings", label: "설정", icon: Settings },
];

interface Props {
  tab: Tab;
  onNavigate: (tab: Tab) => void;
  status: AppStatus;
  theme: "dark" | "light";
  onToggleTheme: () => void;
  notify: (message: string) => void;
}

export function StudioHeader({ tab, onNavigate, status, theme, onToggleTheme, notify }: Props) {
  const headerRef = useRef<HTMLElement>(null);
  const connectionRef = useRef<HTMLDetailsElement>(null);
  const pendingCount = status.admin_available
    ? status.pending_device_count + status.pending_api_profile_transfer_count
    : 0;

  useEffect(() => {
    const header = headerRef.current;
    if (!header) return;
    const measure = () => document.documentElement.style.setProperty("--header-height", `${header.getBoundingClientRect().height}px`);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(header);
    return () => {
      observer.disconnect();
      document.documentElement.style.removeProperty("--header-height");
    };
  }, []);

  useEffect(() => {
    const close = (restoreFocus = false) => {
      const details = connectionRef.current;
      if (!details?.open) return false;
      details.open = false;
      if (restoreFocus) details.querySelector("summary")?.focus();
      return true;
    };
    const outside = (event: PointerEvent) => {
      if (event.target instanceof Node && !connectionRef.current?.contains(event.target)) close();
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && close(true)) event.preventDefault();
    };
    const back = (event: Event) => {
      if (close(true)) event.preventDefault();
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    window.addEventListener("novelai-system-back", back);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
      window.removeEventListener("novelai-system-back", back);
    };
  }, []);

  const navigate = (next: Tab) => {
    if (connectionRef.current) connectionRef.current.open = false;
    onNavigate(next);
  };
  const copyAddress = async (address: string) => {
    try {
      await navigator.clipboard.writeText(address);
      notify("주소를 복사했어요");
    } catch {
      notify("복사하지 못했어요. 주소를 직접 선택해 주세요");
    }
  };

  return (
    <header className="studio-header" ref={headerRef}>
      <button type="button" className="header-brand" aria-label="NovelAI LAN Studio 생성 화면" onClick={() => navigate("generate")}>
        <img src="/app-icon.png" alt="" />
        <strong>LAN Studio</strong>
      </button>
      <nav className="header-nav" aria-label="주 메뉴">
        {NAVIGATION.map(({ id, label, icon: Icon }) => (
          <button type="button" key={id} onClick={() => navigate(id)} aria-current={tab === id ? "page" : undefined}>
            <Icon aria-hidden="true" strokeWidth={1.9} /><span>{label}</span>
          </button>
        ))}
      </nav>
      <div className="topbar-status">
        {!status.has_token ? (
          <button
            type="button"
            className="header-api-state"
            onClick={() => navigate("settings")}
            disabled={!status.admin_available}
            title="NovelAI API 토큰 필요"
          >
            <KeyRound aria-hidden="true" strokeWidth={1.9} />
            <span className="header-api-label">토큰 필요</span>
          </button>
        ) : null}
        <details className="header-connection" ref={connectionRef} onBlur={(event) => {
          if (event.relatedTarget instanceof Node && !event.currentTarget.contains(event.relatedTarget)) event.currentTarget.open = false;
        }}>
          <summary aria-label={`연결${pendingCount > 0 ? `, 승인 대기 ${pendingCount}건` : ""}`}>
            <ShieldCheck aria-hidden="true" strokeWidth={1.9} /><span className="header-connection-label">연결</span><ChevronDown aria-hidden="true" className="connection-chevron" />
            {pendingCount > 0 ? <span className="header-pending-count" aria-hidden="true">{pendingCount}</span> : null}
          </summary>
          <div className="header-connection-panel">
            <div className="connection-row">
              <span className="connection-row-title"><span className={status.lan_urls.length ? "live-dot" : "live-dot off"} aria-hidden="true" />LAN</span>
              {status.lan_urls[0]
                ? <button type="button" className="copy-address" onClick={() => void copyAddress(status.lan_urls[0])} aria-label={`LAN 주소 ${status.lan_urls[0]} 복사`}><span>{status.lan_urls[0]}</span><Copy aria-hidden="true" /></button>
                : <small>Windows 네트워크를 ‘개인’으로 바꿔 주세요</small>}
            </div>
            <div className="connection-row">
              <span className="connection-row-title"><span className={status.tailscale_urls.length ? "live-dot remote" : "live-dot off"} aria-hidden="true" />Tailscale</span>
              {status.tailscale_urls[0]
                ? <button type="button" className="copy-address" onClick={() => void copyAddress(status.tailscale_urls[0])} aria-label={`Tailscale 주소 ${status.tailscale_urls[0]} 복사`}><span>{status.tailscale_urls[0]}</span><Copy aria-hidden="true" /></button>
                : <small>연결되어 있지 않아요</small>}
            </div>
            {pendingCount > 0 ? <button type="button" className="button primary small block" onClick={() => navigate("settings")}>승인 대기 {pendingCount}건 보기</button> : null}
            <p className="header-security-notice">{status.security_notice}</p>
          </div>
        </details>
        <button type="button" className="icon-button" onClick={onToggleTheme} aria-label={theme === "dark" ? "라이트 모드로 전환" : "다크 모드로 전환"} title={theme === "dark" ? "라이트 모드" : "다크 모드"}>
          {theme === "dark" ? <Sun aria-hidden="true" strokeWidth={1.9} /> : <Moon aria-hidden="true" strokeWidth={1.9} />}
        </button>
      </div>
    </header>
  );
}
