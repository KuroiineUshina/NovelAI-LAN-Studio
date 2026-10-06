export type AppFontId =
  | "system"
  | "noto-sans-kr"
  | "nanum-gothic"
  | "gowun-dodum"
  | "ibm-plex-sans-kr"
  | "noto-serif-kr"
  | "nanum-myeongjo"
  | "gowun-batang"
  | "hahmlet";

export interface AppFontOption {
  id: AppFontId;
  label: string;
  category: "기본" | "고딕" | "명조";
}

export const APP_FONT_STORAGE_KEY = "novelai-lan-studio-font-v1";

export const APP_FONTS: AppFontOption[] = [
  { id: "system", label: "시스템 기본", category: "기본" },
  { id: "noto-sans-kr", label: "Noto Sans KR", category: "고딕" },
  { id: "nanum-gothic", label: "나눔고딕", category: "고딕" },
  { id: "gowun-dodum", label: "고운돋움", category: "고딕" },
  { id: "ibm-plex-sans-kr", label: "IBM Plex Sans KR", category: "고딕" },
  { id: "noto-serif-kr", label: "Noto Serif KR", category: "명조" },
  { id: "nanum-myeongjo", label: "나눔명조", category: "명조" },
  { id: "gowun-batang", label: "고운바탕", category: "명조" },
  { id: "hahmlet", label: "함렛", category: "명조" },
];

const APP_FONT_IDS = new Set<AppFontId>(APP_FONTS.map((font) => font.id));

export function isAppFontId(value: string | null): value is AppFontId {
  return Boolean(value && APP_FONT_IDS.has(value as AppFontId));
}

export function getInitialAppFont(): AppFontId {
  try {
    const stored = window.localStorage.getItem(APP_FONT_STORAGE_KEY);
    return isAppFontId(stored) ? stored : "system";
  } catch {
    return "system";
  }
}
