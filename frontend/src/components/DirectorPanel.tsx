import type { DirectorInput, DirectorTool } from "../types";

export const DEFAULT_DIRECTOR: DirectorInput = { tool: "emotion", emotion: "happy", prompt: "", level: 0 };

const TOOLS: Array<{ id: DirectorTool; label: string }> = [
  { id: "emotion", label: "표정" },
  { id: "colorize", label: "채색" },
  { id: "lineart", label: "선화" },
  { id: "sketch", label: "스케치" },
  { id: "bg-removal", label: "배경 제거" },
  { id: "declutter", label: "정리" },
  { id: "declutter-keep-bubbles", label: "정리 · 말풍선 유지" },
];

const EMOTIONS: Array<[string, string]> = [
  ["neutral", "무표정"], ["happy", "기쁨"], ["laughing", "웃음"], ["smug", "의기양양"],
  ["playful", "장난"], ["excited", "신남"], ["love", "사랑"], ["shy", "수줍음"],
  ["embarrassed", "당황"], ["surprised", "놀람"], ["confused", "혼란"], ["thinking", "생각"],
  ["determined", "결의"], ["nervous", "긴장"], ["worried", "걱정"], ["scared", "겁먹음"],
  ["sad", "슬픔"], ["hurt", "상처"], ["tired", "피곤"], ["bored", "지루함"],
  ["irritated", "짜증"], ["angry", "화남"], ["disgusted", "혐오"], ["aroused", "달아오름"],
];

const LEVELS = ["최대", "강", "중", "약", "더 약", "최약"];

interface Props {
  value: DirectorInput;
  onChange: (value: DirectorInput) => void;
}

export function DirectorPanel({ value, onChange }: Props) {
  const update = (patch: Partial<DirectorInput>) => onChange({ ...value, ...patch });
  const usesLevel = value.tool === "emotion" || value.tool === "colorize";
  return (
    <section className="panel director-panel" aria-label="디렉터 도구">
      <div className="chip-group director-tools" role="radiogroup" aria-label="도구">
        {TOOLS.map((tool) => (
          <button type="button" role="radio" key={tool.id} className="chip" aria-checked={value.tool === tool.id} aria-pressed={value.tool === tool.id} onClick={() => update({ tool: tool.id })}>
            {tool.label}
          </button>
        ))}
      </div>

      {value.tool === "emotion" ? (
        <>
          <div className="chip-group director-emotions" role="radiogroup" aria-label="표정">
            {EMOTIONS.map(([id, label]) => (
              <button type="button" role="radio" key={id} className="chip" aria-checked={value.emotion === id} aria-pressed={value.emotion === id} onClick={() => update({ emotion: id })}>
                {label}
              </button>
            ))}
          </div>
          <label className="field">
            <span className="field-label">추가 태그</span>
            <input value={value.prompt} maxLength={2000} onChange={(event) => update({ prompt: event.target.value })} placeholder="blush, tears" />
          </label>
        </>
      ) : null}

      {value.tool === "colorize" ? (
        <label className="field">
          <span className="field-label">채색 프롬프트</span>
          <textarea className="prompt-textarea" rows={3} value={value.prompt} maxLength={2000} onChange={(event) => update({ prompt: event.target.value })} placeholder="pink hair, blue eyes, white sweater" />
        </label>
      ) : null}

      {usesLevel ? (
        <div className="field">
          <span className="field-label">세기</span>
          <div className="segmented block" role="radiogroup" aria-label="세기">
            {LEVELS.map((label, level) => (
              <button type="button" role="radio" key={label} aria-checked={value.level === level} onClick={() => update({ level })}>{label}</button>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
