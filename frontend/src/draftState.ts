import type { ImageRecord } from "./types";

export function canAcceptRemoteDraft(remote: number, current: number, dirty: boolean, saving: boolean): boolean {
  return remote > current && !dirty && !saving;
}

export function removeDeletedPresetSelections(selected: string[], previouslyKnown: string[], nowKnown: string[]): string[] {
  const removed = new Set(previouslyKnown.filter((id) => !nowKnown.includes(id)));
  return selected.filter((id) => !removed.has(id));
}

export function outputSeed(image: Pick<ImageRecord, "seed" | "settings">): number | null {
  return image.seed ?? image.settings.seed ?? null;
}
