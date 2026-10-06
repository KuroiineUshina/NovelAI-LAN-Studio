import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import type { Statistics } from "../types";
import "../library.css";

const TILES: Array<{ key: keyof Pick<Statistics, "lifetime" | "today" | "last_7_days" | "temporary" | "favorites">; label: string }> = [
  { key: "lifetime", label: "전체" },
  { key: "today", label: "오늘" },
  { key: "last_7_days", label: "최근 7일" },
  { key: "temporary", label: "보관 중" },
  { key: "favorites", label: "즐겨찾기" },
];

interface Props {
  refreshSignal: number;
}

export function StatsView({ refreshSignal }: Props) {
  const [stats, setStats] = useState<Statistics | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    api<Statistics>("/api/stats")
      .then((result) => { if (active) { setStats(result); setError(""); } })
      .catch((loadError) => { if (active) setError(errorMessage(loadError)); });
    return () => { active = false; };
  }, [refreshSignal]);

  const max = Math.max(1, ...(stats?.daily.map((item) => item.count) ?? [1]));

  return (
    <div className="page narrow stats-view">
      <header className="page-header">
        <h1>통계</h1>
      </header>
      {error ? <p className="error-message" role="alert">{error}</p> : null}
      {!stats ? (
        <div className="stats-tiles" aria-busy="true">
          <span className="sr-only" role="status">불러오는 중…</span>
          {TILES.map((tile) => <div className="stats-tile skeleton" key={tile.key} aria-hidden="true" />)}
        </div>
      ) : (
        <>
          <section className="stats-tiles" aria-label="생성 수">
            {TILES.map((tile) => (
              <article className="stats-tile" key={tile.key}>
                <span className="stats-tile-label">{tile.label}</span>
                <strong className="stats-tile-value">{stats[tile.key].toLocaleString()}</strong>
              </article>
            ))}
          </section>
          <section className="panel stats-daily">
            <div className="panel-header">
              <h2>일별 생성</h2>
              <span className="counter">{stats.last_7_days.toLocaleString()}장</span>
            </div>
            <ol className="stats-bars" aria-label="최근 7일 일별 생성 수">
              {stats.daily.map((item) => {
                const date = new Date(`${item.date}T00:00:00`);
                return (
                  <li className="stats-bar-row" key={item.date}>
                    <span className="stats-bar-label">
                      <span>{date.toLocaleDateString(undefined, { weekday: "short" })}</span>
                      <small>{date.toLocaleDateString(undefined, { month: "numeric", day: "numeric" })}</small>
                    </span>
                    <span className="stats-bar-track" aria-hidden="true">
                      <span className="stats-bar-fill" style={{ width: `${Math.max(item.count ? 2 : 0, (item.count / max) * 100)}%` }} />
                    </span>
                    <span className="stats-bar-count">{item.count.toLocaleString()}</span>
                  </li>
                );
              })}
            </ol>
          </section>
        </>
      )}
    </div>
  );
}
