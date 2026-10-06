// Unfolded foldables (Galaxy Z Fold7 inner screen: 984×1092 CSS px at DPR 2) are touch screens
// close to square. They get their own layout via :root[data-device="fold"] (see fold.css).
export const FOLD_QUERY = "(pointer: coarse) and (min-width: 700px) and (max-width: 1200px) and (min-aspect-ratio: 3/4) and (max-aspect-ratio: 4/3)";

const LAYOUT_OVERRIDE_KEY = "novelai-lan-studio-layout-override";

// `?layout=fold` / `?layout=auto` lets a desktop browser preview the foldable layout.
function layoutOverride(): "fold" | null {
  try {
    const requested = new URLSearchParams(window.location.search).get("layout");
    if (requested === "fold") window.sessionStorage.setItem(LAYOUT_OVERRIDE_KEY, "fold");
    if (requested === "auto") window.sessionStorage.removeItem(LAYOUT_OVERRIDE_KEY);
    return window.sessionStorage.getItem(LAYOUT_OVERRIDE_KEY) === "fold" ? "fold" : null;
  } catch {
    return null;
  }
}

export function isFoldLayout(): boolean {
  if (typeof window === "undefined") return false;
  return layoutOverride() === "fold" || window.matchMedia(FOLD_QUERY).matches;
}

export function watchDeviceLayout(onChange: (fold: boolean) => void): () => void {
  const query = window.matchMedia(FOLD_QUERY);
  const update = () => onChange(isFoldLayout());
  update();
  query.addEventListener("change", update);
  window.addEventListener("resize", update);
  return () => {
    query.removeEventListener("change", update);
    window.removeEventListener("resize", update);
  };
}
