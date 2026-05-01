export type LanguageOption = { code: string; label: string };

// ISO 639-1 language codes (two-letter) + common extras used by ASR engines.
// UI-only: server still accepts arbitrary strings, but the Settings form restricts input.
export const LANGUAGE_OPTIONS: LanguageOption[] = [
  { code: "auto", label: "auto (автоопределение)" },
  // Common
  { code: "en", label: "en (English)" },
  { code: "ru", label: "ru (Русский)" },
  { code: "uk", label: "uk (Українська)" },
  { code: "be", label: "be (Беларуская)" },
  { code: "de", label: "de (Deutsch)" },
  { code: "fr", label: "fr (Français)" },
  { code: "es", label: "es (Español)" },
  { code: "it", label: "it (Italiano)" },
  { code: "pt", label: "pt (Português)" },
  { code: "tr", label: "tr (Türkçe)" },
  { code: "pl", label: "pl (Polski)" },
  { code: "cs", label: "cs (Čeština)" },
  { code: "sk", label: "sk (Slovenčina)" },
  { code: "bg", label: "bg (Български)" },
  { code: "sr", label: "sr (Српски)" },
  { code: "hr", label: "hr (Hrvatski)" },
  { code: "hu", label: "hu (Magyar)" },
  { code: "ro", label: "ro (Română)" },
  { code: "nl", label: "nl (Nederlands)" },
  { code: "sv", label: "sv (Svenska)" },
  { code: "no", label: "no (Norsk)" },
  { code: "da", label: "da (Dansk)" },
  { code: "fi", label: "fi (Suomi)" },
  { code: "et", label: "et (Eesti)" },
  { code: "lv", label: "lv (Latviešu)" },
  { code: "lt", label: "lt (Lietuvių)" },
  { code: "el", label: "el (Ελληνικά)" },
  { code: "he", label: "he (עברית)" },
  { code: "ar", label: "ar (العربية)" },
  { code: "fa", label: "fa (فارسی)" },
  { code: "hi", label: "hi (हिन्दी)" },
  { code: "ur", label: "ur (اردو)" },
  { code: "bn", label: "bn (বাংলা)" },
  { code: "ta", label: "ta (தமிழ்)" },
  { code: "te", label: "te (తెలుగు)" },
  { code: "ml", label: "ml (മലയാളം)" },
  { code: "kn", label: "kn (ಕನ್ನಡ)" },
  { code: "mr", label: "mr (मराठी)" },
  { code: "gu", label: "gu (ગુજરાતી)" },
  { code: "pa", label: "pa (ਪੰਜਾਬੀ)" },
  { code: "id", label: "id (Bahasa Indonesia)" },
  { code: "ms", label: "ms (Bahasa Melayu)" },
  { code: "vi", label: "vi (Tiếng Việt)" },
  { code: "th", label: "th (ไทย)" },
  { code: "zh", label: "zh (中文)" },
  { code: "ja", label: "ja (日本語)" },
  { code: "ko", label: "ko (한국어)" },
];

export function normalizeLanguageCode(raw: string | null | undefined): string {
  const v = (raw ?? "").trim();
  if (!v) return "auto";
  const lower = v.toLowerCase();
  return lower;
}

