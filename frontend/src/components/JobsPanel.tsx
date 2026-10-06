import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { api, errorMessage } from "../api";
import type { Job } from "../types";
import { sequenceProgress } from "../sequentialGeneration";
import "../library.css";

const STATUS: Record<Job["status"], string> = {
  queued: "대기 중",
  running: "생성 중",
  succeeded: "완료",
  failed: "실패",
  cancelled: "취소됨",
  interrupted: "중단됨",
};

const STATUS_TONE: Record<Job["status"], string> = {
  queued: "",
  running: "brand",
  succeeded: "positive",
  failed: "critical",
  cancelled: "",
  interrupted: "warning",
};

interface Props {
  refreshSignal: number;
  onGalleryChanged: () => void;
}

export function JobsPanel({ refreshSignal, onGalleryChanged }: Props) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState("");
  const successfulJobIds = useRef<Set<string> | null>(null);
  const previousOutputs = useRef<Map<string, number> | null>(null);
  const [cancellingIds, setCancellingIds] = useState<string[]>([]);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const response = await api<{ items: Job[] }>("/api/jobs?limit=12");
        if (!active) return;
        setJobs(response.items);
        setError("");
        const completed = new Set(
          response.items.filter((job) => job.status === "succeeded").map((job) => job.id),
        );
        if (
          successfulJobIds.current !== null
          && ([...completed].some((jobId) => !successfulJobIds.current?.has(jobId))
            || response.items.some((job) => job.output_count > (previousOutputs.current?.get(job.id) ?? 0)))
        ) {
          onGalleryChanged();
        }
        successfulJobIds.current = completed;
        previousOutputs.current = new Map(response.items.map((job) => [job.id, job.output_count]));
      } catch (loadError) {
        if (active) setError(errorMessage(loadError));
      }
    };
    void load();
    const timer = window.setInterval(load, 2000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [onGalleryChanged, refreshSignal]);

  const cancel = async (jobId: string) => {
    setCancellingIds((ids) => [...ids, jobId]);
    try {
      await api(`/api/jobs/${jobId}/cancel`, { method: "POST" });
      const response = await api<{ items: Job[] }>("/api/jobs?limit=12");
      setJobs(response.items);
    } catch (cancelError) {
      setError(errorMessage(cancelError));
    } finally {
      setCancellingIds((ids) => ids.filter((id) => id !== jobId));
    }
  };

  const running = jobs.filter((job) => job.status === "running");
  const queued = jobs.filter((job) => job.status === "queued");
  const visible = [
    ...running,
    ...queued,
    ...jobs.filter((job) => !["running", "queued", "succeeded"].includes(job.status)).slice(0, 3),
  ];
  if (!visible.length && !error) return null;

  const activeCount = running.length + queued.length;
  const hasFailure = visible.some((job) => job.status === "failed" || job.status === "interrupted");
  const summary = activeCount
    ? `${running.length ? "생성 중" : "대기 중"} ${activeCount}`
    : visible.length ? `최근 작업 ${visible.length}` : "연결 오류";
  const dotTone = error || hasFailure ? "critical" : "off";

  return (
    <aside className="jobs-panel" data-expanded={expanded ? "true" : "false"} aria-label="생성 대기열" aria-live="polite">
      {expanded ? (
        <div className="jobs-card" id="jobs-panel-list">
          <div className="jobs-card-header">
            <h2>대기열</h2>
            <span className="counter">{summary}</span>
            <button type="button" className="icon-button small" onClick={() => setExpanded(false)} aria-expanded="true" aria-controls="jobs-panel-list" aria-label="대기열 접기">
              <ChevronDown aria-hidden="true" strokeWidth={2} />
            </button>
          </div>
          {error ? <p className="error-message jobs-error" title={error}>{error}</p> : null}
          <ul className="jobs-list">
            {visible.map((job) => {
              const progress = sequenceProgress(job);
              const live = job.status === "running" || job.status === "queued";
              const errorText = job.error_message ? `${job.error_message} · ID ${job.correlation_id}` : "";
              return (
                <li className={`jobs-item ${job.status}`} key={job.id}>
                  <div className="jobs-item-main">
                    <span className={`badge ${STATUS_TONE[job.status]}`}>{STATUS[job.status]}</span>
                    <span className="jobs-item-meta">{job.request.mode} · {new Date(job.created_at).toLocaleTimeString()}</span>
                    {job.status === "queued" || (job.status === "running" && progress.total > 1) ? (
                      <button
                        type="button"
                        className="button ghost small jobs-cancel"
                        disabled={!!job.cancel_requested || cancellingIds.includes(job.id)}
                        onClick={() => void cancel(job.id)}
                      >
                        {job.status === "queued" ? "취소" : job.cancel_requested ? "중단 예약됨" : "남은 생성 중단"}
                      </button>
                    ) : null}
                  </div>
                  {progress.total > 1 ? (
                    <div className="jobs-progress">
                      <span className="jobs-progress-track" aria-hidden="true">
                        <span className="jobs-progress-fill" style={{ width: `${(progress.completed / progress.total) * 100}%` }} />
                      </span>
                      <span className="jobs-progress-text">
                        {progress.completed}/{progress.total}회 · {job.output_count}장
                        {live ? ` · 남은 ${progress.remaining}회` : ""}
                        {job.status === "running" && job.cancel_requested ? " · 이번 요청 후 중단" : ""}
                      </span>
                    </div>
                  ) : null}
                  {errorText ? <p className="jobs-item-error" title={errorText}>{errorText}</p> : null}
                </li>
              );
            })}
          </ul>
        </div>
      ) : (
        <button type="button" className="jobs-pill" onClick={() => setExpanded(true)} aria-expanded="false" aria-label={`대기열 펼치기, ${summary}`}>
          {activeCount ? <span className="spinner" aria-hidden="true" /> : <span className={`live-dot ${dotTone}`} aria-hidden="true" />}
          <span>{summary}</span>
        </button>
      )}
    </aside>
  );
}
