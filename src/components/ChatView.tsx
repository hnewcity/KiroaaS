import { useState, useRef, useEffect } from 'react';
import { Send, Loader2, Trash2, Bot, ImagePlus, X, Sparkles } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useI18n } from '@/hooks/useI18n';

interface MessageContent {
  type: 'text' | 'image_url';
  text?: string;
  image_url?: { url: string };
}

interface Message {
  role: 'user' | 'assistant';
  content: string | MessageContent[];
}

interface ChatViewProps {
  host: string;
  port: number;
  apiKey: string;
  isRunning: boolean;
}

export function ChatView({ host, port, apiKey, isRunning }: ChatViewProps) {
  const { t } = useI18n();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [images, setImages] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [model, setModel] = useState('claude-sonnet-4-5');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleImageUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;

    Array.from(files).forEach(file => {
      if (file.type.startsWith('image/')) {
        const reader = new FileReader();
        reader.onload = (event) => {
          const base64 = event.target?.result as string;
          setImages(prev => [...prev, base64]);
        };
        reader.readAsDataURL(file);
      }
    });

    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const removeImage = (index: number) => {
    setImages(prev => prev.filter((_, i) => i !== index));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if ((!input.trim() && images.length === 0) || isLoading || !isRunning) return;

    // Build message content
    let userContent: string | MessageContent[];
    if (images.length > 0) {
      userContent = [];
      images.forEach(img => {
        (userContent as MessageContent[]).push({
          type: 'image_url',
          image_url: { url: img }
        });
      });
      if (input.trim()) {
        (userContent as MessageContent[]).push({
          type: 'text',
          text: input.trim()
        });
      }
    } else {
      userContent = input.trim();
    }

    const userMessage: Message = { role: 'user', content: userContent };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setImages([]);
    setIsLoading(true);

    try {
      const response = await fetch(`http://${host}:${port}/v1/chat/completions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${apiKey}`,
        },
        body: JSON.stringify({
          model,
          messages: [...messages, userMessage].map(m => ({
            role: m.role,
            content: m.content,
          })),
          stream: true,
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error('No reader available');

      const decoder = new TextDecoder();
      let assistantContent = '';
      let messageAdded = false;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6);
            if (data === '[DONE]') continue;

            try {
              const parsed = JSON.parse(data);
              const content = parsed.choices?.[0]?.delta?.content || '';
              if (content) {
                assistantContent += content;
                if (!messageAdded) {
                  setMessages(prev => [...prev, { role: 'assistant', content: assistantContent }]);
                  messageAdded = true;
                } else {
                  setMessages(prev => {
                    const newMessages = [...prev];
                    newMessages[newMessages.length - 1] = {
                      role: 'assistant',
                      content: assistantContent,
                    };
                    return newMessages;
                  });
                }
              }
            } catch {
              // Skip invalid JSON
            }
          }
        }
      }
    } catch (error) {
      console.error('Chat error:', error);
      setMessages(prev => [
        ...prev,
        {
          role: 'assistant',
          content: t('chatError') + ': ' + (error instanceof Error ? error.message : 'Unknown error'),
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const clearChat = () => {
    setMessages([]);
    setImages([]);
  };

  const getMessageText = (content: string | MessageContent[]): string => {
    if (typeof content === 'string') return content;
    const textPart = content.find(c => c.type === 'text');
    return textPart?.text || '';
  };

  const getMessageImages = (content: string | MessageContent[]): string[] => {
    if (typeof content === 'string') return [];
    return content
      .filter(c => c.type === 'image_url')
      .map(c => c.image_url?.url || '')
      .filter(Boolean);
  };

  const models = [
    'claude-sonnet-4-5',
    'claude-opus-4-5',
    'claude-haiku-4-5',
  ];

  return (
    <div className="flex flex-col h-full">
      {/* Header: clear button only */}
      {messages.length > 0 && (
        <div className="flex items-center justify-end px-4 py-2">
          <button
            type="button"
            onClick={clearChat}
            className="text-xs text-stone-400 hover:text-stone-600 transition-colors flex items-center gap-1 px-3 py-1.5 rounded-full hover:bg-white/50"
          >
            <Trash2 className="h-3 w-3" />
            {t('clear')}
          </button>
        </div>
      )}

      {/* Messages Area */}
      <div className={`flex-1 px-4 ${messages.length > 0 ? 'overflow-y-auto' : 'flex items-center justify-center'}`}>
        {!isRunning ? (
          <div className="text-center text-stone-400">
            <div className="w-20 h-20 mx-auto mb-4 rounded-full bg-stone-200/50 flex items-center justify-center">
              <Bot className="h-10 w-10 opacity-40" />
            </div>
            <p className="font-semibold text-stone-500">{t('chatServerOffline')}</p>
            <p className="text-sm mt-1">{t('chatServerOfflineDesc')}</p>
          </div>
        ) : messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full">
            <div className="text-center max-w-lg mx-auto">
              <p className="text-4xl font-bold text-stone-300 tracking-tight mb-2">{t('chatWelcome')}</p>
              <p className="text-sm text-stone-400">{t('chatWelcomeDesc')}</p>
            </div>
          </div>
        ) : (
          <div className="space-y-6 max-w-3xl mx-auto w-full py-4">
            {messages.map((message, index) => {
              const messageImages = getMessageImages(message.content);
              const messageText = getMessageText(message.content);

              return (
                <div key={index}>
                  {message.role === 'user' ? (
                    <div className="flex justify-end">
                      <div className="max-w-[85%] rounded-2xl px-4 py-3 bg-stone-800 text-white">
                        {messageImages.length > 0 && (
                          <div className="flex flex-wrap gap-2 mb-2">
                            {messageImages.map((img, imgIndex) => (
                              <img
                                key={imgIndex}
                                src={img}
                                alt=""
                                className="max-w-[200px] max-h-[150px] rounded-lg object-cover"
                              />
                            ))}
                          </div>
                        )}
                        {messageText && (
                          <p className="text-sm whitespace-pre-wrap break-words leading-relaxed">{messageText}</p>
                        )}
                      </div>
                    </div>
                  ) : (
                    <div className="text-stone-700 prose prose-sm prose-stone max-w-none prose-p:my-2 prose-headings:my-3 prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5 prose-pre:bg-stone-100 prose-pre:text-stone-800 prose-code:text-stone-700 prose-code:bg-stone-100 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:before:content-none prose-code:after:content-none">
                      <ReactMarkdown>{messageText}</ReactMarkdown>
                    </div>
                  )}
                </div>
              );
            })}
            {isLoading && (messages.length === 0 || messages[messages.length - 1]?.role === 'user') && (
              <div className="text-stone-400">
                <Loader2 className="h-4 w-4 animate-spin" />
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input Area */}
      <div className="p-4">
        <div className="max-w-3xl mx-auto">
          {/* Image Preview */}
          {images.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-2 p-2 bg-white rounded-xl shadow-sm">
              {images.map((img, index) => (
                <div key={index} className="relative group">
                  <img
                    src={img}
                    alt=""
                    className="h-16 w-16 object-cover rounded-lg"
                  />
                  <button
                    type="button"
                    onClick={() => removeImage(index)}
                    className="absolute -top-1 -right-1 w-5 h-5 bg-stone-800 text-white rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </div>
          )}

          <form onSubmit={handleSubmit} className="flex flex-col bg-white rounded-[24px] p-3 shadow-sm gap-2">
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              multiple
              onChange={handleImageUpload}
              className="hidden"
            />
            {/* Top row: model selector */}
            <div className="px-1">
              <Select value={model} onValueChange={setModel} disabled={!isRunning}>
                <SelectTrigger className="w-auto h-7 bg-stone-100 border-none text-stone-500 hover:bg-stone-200 rounded-full px-3 text-xs font-medium focus:ring-0 gap-1">
                  <Sparkles className="h-3 w-3" />
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="rounded-xl" side="top">
                  {models.map((m) => (
                    <SelectItem key={m} value={m} className="text-xs">
                      {m}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {/* Bottom row: textarea and buttons */}
            <div className="flex items-end gap-2">
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={isRunning ? t('chatPlaceholder') : t('chatServerOffline')}
                disabled={!isRunning || isLoading}
                rows={1}
                className="flex-1 resize-none bg-transparent border-0 px-2 py-1 text-sm focus:outline-none disabled:opacity-50 disabled:cursor-not-allowed placeholder:text-stone-400"
                style={{ minHeight: '36px', maxHeight: '150px' }}
              />
              <div className="flex items-center gap-1 flex-shrink-0">
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={!isRunning || isLoading}
                  className="h-9 w-9 rounded-full flex items-center justify-center text-stone-400 hover:text-stone-600 hover:bg-stone-100 transition-colors disabled:opacity-30"
                >
                  <ImagePlus className="h-5 w-5" />
                </button>
                <Button
                  type="submit"
                  disabled={(!input.trim() && images.length === 0) || isLoading || !isRunning}
                  className="h-9 w-9 rounded-full bg-stone-800 hover:bg-stone-700 disabled:opacity-30"
                >
                  {isLoading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Send className="h-4 w-4" />
                  )}
                </Button>
              </div>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
