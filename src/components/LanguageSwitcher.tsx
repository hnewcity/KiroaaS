import { useI18n } from '@/hooks/useI18n';
import { Language } from '@/lib/i18n';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Globe } from 'lucide-react';

export type LanguageSwitcherVariant = 'default' | 'sidebar';

export interface LanguageSwitcherProps {
  variant?: LanguageSwitcherVariant;
}

const LANGUAGE_LABELS: Record<Language, string> = {
  zh: '中文',
  en: 'English',
  ru: 'Русский',
  es: 'Español',
  id: 'Bahasa Indonesia',
  pt: 'Português (Brasil)',
  ja: '日本語',
  ko: '한국어',
};

export function LanguageSwitcher({ variant = 'default' }: LanguageSwitcherProps) {
  const { lang, setLang } = useI18n();

  if (variant === 'sidebar') {
    return (
      <Select value={lang} onValueChange={(value) => setLang(value as Language)}>
        <SelectTrigger className="w-10 h-10 lg:w-full bg-[#1A1A1A] border-none text-stone-400 hover:text-white rounded-full p-0 lg:px-3 flex items-center justify-center lg:justify-between focus:ring-0 [&>span]:hidden lg:[&>span]:flex [&>svg.lucide-chevron-down]:hidden lg:[&>svg.lucide-chevron-down]:block">
          <Globe className="h-4 w-4 flex-shrink-0 lg:mr-2" />
          <span className="hidden lg:inline text-xs">{LANGUAGE_LABELS[lang] ?? lang}</span>
        </SelectTrigger>
        <SelectContent className="dark border-[#333] bg-[#1A1A1A] text-stone-300">
          <SelectItem value="en">English</SelectItem>
          <SelectItem value="zh">中文</SelectItem>
          <SelectItem value="ru">Русский</SelectItem>
          <SelectItem value="es">Español</SelectItem>
          <SelectItem value="id">Bahasa Indonesia</SelectItem>
          <SelectItem value="pt">Português (Brasil)</SelectItem>
          <SelectItem value="ja">日本語</SelectItem>
          <SelectItem value="ko">한국어</SelectItem>
        </SelectContent>
      </Select>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <Globe className="h-4 w-4 text-muted-foreground" />
      <Select value={lang} onValueChange={(value) => setLang(value as Language)}>
        <SelectTrigger className="w-[120px] h-8">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="en">English</SelectItem>
          <SelectItem value="zh">中文</SelectItem>
          <SelectItem value="ru">Русский</SelectItem>
          <SelectItem value="es">Español</SelectItem>
          <SelectItem value="id">Bahasa Indonesia</SelectItem>
          <SelectItem value="pt">Português (Brasil)</SelectItem>
          <SelectItem value="ja">日本語</SelectItem>
          <SelectItem value="ko">한국어</SelectItem>
        </SelectContent>
      </Select>
    </div>
  );
}
