import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { getTranslation, Language, TranslationKey } from '@/lib/i18n';
import { updateTrayLanguage } from '@/lib/tauri';

interface I18nContextType {
  lang: Language;
  setLang: (lang: Language) => void;
  t: (key: TranslationKey) => string;
}

const I18nContext = createContext<I18nContextType | null>(null);

const LANG_STORAGE_KEY = 'kiroaas-lang';

function isSupportedLanguage(value: string | null): value is Language {
  return (
    value === 'zh' ||
    value === 'en' ||
    value === 'ru' ||
    value === 'es' ||
    value === 'id' ||
    value === 'pt' ||
    value === 'ja' ||
    value === 'ko'
  );
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Language>(() => {
    // Try to get from localStorage, default to system language or 'en'
    if (typeof window !== 'undefined') {
      const stored = localStorage.getItem(LANG_STORAGE_KEY);
      if (isSupportedLanguage(stored)) {
        return stored;
      }
      // Detect system language
      const systemLang = navigator.language.toLowerCase();

      const primary = systemLang.split('-')[0];
      if (primary === 'zh') return 'zh';
      if (primary === 'ru') return 'ru';
      if (primary === 'es') return 'es';
      if (primary === 'id') return 'id';
      if (primary === 'pt') return 'pt';
      if (primary === 'ja') return 'ja';
      if (primary === 'ko') return 'ko';
    }
    return 'en';
  });

  const setLang = (newLang: Language) => {
    setLangState(newLang);
    localStorage.setItem(LANG_STORAGE_KEY, newLang);
  };

  const t = (key: TranslationKey): string => {
    return getTranslation(lang, key);
  };

  useEffect(() => {
    updateTrayLanguage({
      startServerLabel: getTranslation(lang, 'startServer'),
      stopServerLabel: getTranslation(lang, 'stopServer'),
      restartServerLabel: getTranslation(lang, 'restartServer'),
      showWindowLabel: getTranslation(lang, 'trayShowWindow'),
      hideWindowLabel: getTranslation(lang, 'trayHideWindow'),
      quitLabel: getTranslation(lang, 'trayQuit'),
    }).catch(() => {});
  }, [lang]);

  return (
    <I18nContext.Provider value={{ lang, setLang, t }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n() {
  const context = useContext(I18nContext);
  if (!context) {
    throw new Error('useI18n must be used within an I18nProvider');
  }
  return context;
}
