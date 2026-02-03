import { useState } from 'react';
import { Check, Copy } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useI18n } from '@/hooks/useI18n';

type ApiType = 'openai' | 'anthropic';
type CodeType = 'curl' | 'python' | 'javascript';

interface ApiExamplesProps {
  host: string;
  port: number;
  apiKey: string;
}

export function ApiExamples({ host, port, apiKey }: ApiExamplesProps) {
  const { t } = useI18n();
  const [apiType, setApiType] = useState<ApiType>('openai');
  const [codeType, setCodeType] = useState<CodeType>('curl');
  const [copied, setCopied] = useState(false);

  const baseUrl = `http://${host}:${port}`;
  const displayApiKey = apiKey || 'YOUR_API_KEY';

  const examples: Record<ApiType, Record<CodeType, string>> = {
    openai: {
      curl: `curl ${baseUrl}/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${displayApiKey}" \\
  -d '{
    "model": "claude-sonnet-4-5",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ]
  }'`,
      python: `from openai import OpenAI

client = OpenAI(
    base_url="${baseUrl}/v1",
    api_key="${displayApiKey}"
)

response = client.chat.completions.create(
    model="claude-sonnet-4-5",
    messages=[
        {"role": "user", "content": "Hello!"}
    ]
)

print(response.choices[0].message.content)`,
      javascript: `import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: '${baseUrl}/v1',
  apiKey: '${displayApiKey}',
});

const response = await client.chat.completions.create({
  model: 'claude-sonnet-4-5',
  messages: [
    { role: 'user', content: 'Hello!' }
  ],
});

console.log(response.choices[0].message.content);`,
    },
    anthropic: {
      curl: `curl ${baseUrl}/v1/messages \\
  -H "Content-Type: application/json" \\
  -H "x-api-key: ${displayApiKey}" \\
  -H "anthropic-version: 2023-06-01" \\
  -d '{
    "model": "claude-sonnet-4-5",
    "max_tokens": 1024,
    "messages": [
      {"role": "user", "content": "Hello!"}
    ]
  }'`,
      python: `import anthropic

client = anthropic.Anthropic(
    base_url="${baseUrl}/v1",
    api_key="${displayApiKey}"
)

message = client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=1024,
    messages=[
        {"role": "user", "content": "Hello!"}
    ]
)

print(message.content[0].text)`,
      javascript: `import Anthropic from '@anthropic-ai/sdk';

const client = new Anthropic({
  baseURL: '${baseUrl}/v1',
  apiKey: '${displayApiKey}',
});

const message = await client.messages.create({
  model: 'claude-sonnet-4-5',
  max_tokens: 1024,
  messages: [
    { role: 'user', content: 'Hello!' }
  ],
});

console.log(message.content[0].text);`,
    },
  };

  const currentCode = examples[apiType][codeType];

  const handleCopy = async () => {
    await navigator.clipboard.writeText(currentCode);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header with API type toggle */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-stone-600">{t('apiExamples')}</span>
        </div>
        <div className="flex items-center gap-1 bg-stone-100 rounded-full p-1">
          <button
            onClick={() => setApiType('openai')}
            className={`px-3 py-1 text-xs font-medium rounded-full transition-all ${apiType === 'openai'
              ? 'bg-white text-stone-900 shadow-sm'
              : 'text-stone-500 hover:text-stone-700'
              }`}
          >
            OpenAI
          </button>
          <button
            onClick={() => setApiType('anthropic')}
            className={`px-3 py-1 text-xs font-medium rounded-full transition-all ${apiType === 'anthropic'
              ? 'bg-white text-stone-900 shadow-sm'
              : 'text-stone-500 hover:text-stone-700'
              }`}
          >
            Anthropic
          </button>
        </div>
      </div>

      {/* Code type tabs */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1">
          {(['curl', 'python', 'javascript'] as CodeType[]).map((type) => (
            <button
              key={type}
              onClick={() => setCodeType(type)}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-all ${codeType === type
                ? 'bg-stone-800 text-white'
                : 'bg-stone-100 text-stone-600 hover:bg-stone-200'
                }`}
            >
              {type === 'curl' ? 'cURL' : type === 'python' ? 'Python' : 'JavaScript'}
            </button>
          ))}
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={handleCopy}
          className="h-7 px-2 text-xs gap-1.5"
        >
          {copied ? (
            <>
              <Check className="h-3.5 w-3.5 text-green-600" />
              <span className="text-green-600">{t('copied')}</span>
            </>
          ) : (
            <>
              <Copy className="h-3.5 w-3.5" />
              <span>{t('copy')}</span>
            </>
          )}
        </Button>
      </div>

      {/* Code block */}
      <div className="flex-1 bg-[#1e1e1e] rounded-xl overflow-hidden min-h-0">
        <pre className="h-full overflow-auto p-4 text-[11px] leading-relaxed text-stone-300 font-mono">
          <code>{currentCode}</code>
        </pre>
      </div>
    </div>
  );
}
