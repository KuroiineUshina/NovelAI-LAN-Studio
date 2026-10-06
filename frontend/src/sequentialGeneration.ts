export function parseRepeatCount(value: string): number | null {
  if (!value.trim()) return null;
  const count = Number(value);
  return Number.isInteger(count) && count >= 1 && count <= 100 ? count : null;
}

export function sequenceProgress(job: {
  request: { repeat_count?: number };
  completed_requests?: number;
}) {
  const total = job.request.repeat_count ?? 1;
  const completed = Math.min(total, Math.max(0, job.completed_requests ?? 0));
  return { total, completed, remaining: total - completed };
}
