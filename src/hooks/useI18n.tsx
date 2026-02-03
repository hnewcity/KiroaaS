import { createContext, useContext, useState, ReactNode } from 'react';
import { Language, translations, TranslationKey } from '@/lib/i18n';

interface I18nContextType {
  lang: Language;
  setLang: (lang: Language) => void;
  t: (key: TranslationKey) => string;
}

const I18nContext = createContext<I18nContextType | null>(null);

const LANG_STORAGE_KEY = 'kiroaas-lang';

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Language>(() => {
    // Try to get from localStorage, default to system language or 'en'
    if (typeof window !== 'undefined') {
      const stored = localStorage.getItem(LANG_STORAGE_KEY);
      if (stored === 'zh' || stored === 'en') {
        return stored;
      }
      // Detect system language
      const systemLang = navigator.language.toLowerCase();
      if (systemLang.startsWith('zh')) {
        return 'zh';
      }
    }
    return 'en';
  });

  const setLang = (newLang: Language) => {
    setLangState(newLang);
    localStorage.setItem(LANG_STORAGE_KEY, newLang);
  };

  const t = (key: TranslationKey): string => {
    return translations[lang][key] || key;
  };

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
