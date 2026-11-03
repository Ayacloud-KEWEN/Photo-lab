import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "./locales/en";
import fr from "./locales/fr";
import zhCN from "./locales/zh-CN";

/** Supported UI languages, in priority order (Chinese first). */
export const LANGUAGES = [
  { code: "zh-CN", label: "简体中文" },
  { code: "en", label: "English" },
  { code: "fr", label: "Français" },
] as const;

export type LanguageCode = (typeof LANGUAGES)[number]["code"];

const STORAGE_KEY = "lumen.language";
const DEFAULT_LANGUAGE: LanguageCode = "zh-CN";

function isLanguage(value: unknown): value is LanguageCode {
  return LANGUAGES.some((language) => language.code === value);
}

function savedLanguage(): LanguageCode {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return isLanguage(value) ? value : DEFAULT_LANGUAGE;
  } catch {
    return DEFAULT_LANGUAGE;
  }
}

export function setLanguage(code: LanguageCode): void {
  void i18n.changeLanguage(code);
  try {
    localStorage.setItem(STORAGE_KEY, code);
  } catch {
    // Preference simply won't persist.
  }
}

void i18n.use(initReactI18next).init({
  resources: {
    "zh-CN": { translation: zhCN },
    en: { translation: en },
    fr: { translation: fr },
  },
  lng: savedLanguage(),
  fallbackLng: DEFAULT_LANGUAGE,
  interpolation: { escapeValue: false },
});

i18n.on("languageChanged", (lng) => {
  document.documentElement.lang = lng;
});
document.documentElement.lang = i18n.language;

export default i18n;
