import { useState, useRef, useEffect, useCallback } from 'react';
import { Send, Loader2, Trash2, ImagePlus, X, Sparkles, Copy, Check } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useI18n } from '@/hooks/useI18n';
import { ConversationSidebar } from './ConversationSidebar';
import type { Conversation } from '@/lib/conversations';

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      onClick={handleCopy}
      className="p-1.5 rounded-lg bg-white/80 hover:bg-white text-stone-500 hover:text-stone-700 transition-colors shadow-sm"
    >
      {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
    </button>
  );
}

export interface MessageContent {
  type: 'text' | 'image_url';
  text?: string;
  image_url?: { url: string };
}

export interface Message {
  role: 'user' | 'assistant';
  content: string | MessageContent[];
}

interface ChatViewProps {
  host: string;
  port: number;
  apiKey: string;
  isRunning: boolean;
  messages: Message[];
  onMessagesChange: (messages: Message[]) => void;
  conversations: Conversation[];
  currentConversationId: string | null;
  onSelectConversation: (id: string | null) => void;
  onNewChat: () => void;
  onDeleteConversation: (id: string) => void;
  onRenameConversation: (id: string, title: string) => void;
}

export function ChatView({
  host,
  port,
  apiKey,
  isRunning,
  messages,
  onMessagesChange,
  conversations,
  currentConversationId,
  onSelectConversation,
  onNewChat,
  onDeleteConversation,
  onRenameConversation,
}: ChatViewProps) {
  // 0.0.0.0 is for server binding (listen on all interfaces), not a valid client address
  const fetchHost = host === '0.0.0.0' ? '127.0.0.1' : host;
  const { t } = useI18n();
  const [input, setInput] = useState('');
  const [images, setImages] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [model, setModel] = useState('claude-sonnet-4-5');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const composingRef = useRef(false);
  const compositionEndTimeRef = useRef(0);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const isNearBottomRef = useRef(true);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  const handleScroll = () => {
    const el = scrollContainerRef.current;
    if (!el) return;
    // Consider "near bottom" if within 150px of the bottom
    isNearBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 150;
  };

  useEffect(() => {
    if (isNearBottomRef.current) {
      scrollToBottom();
    }
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
    const newMessages = [...messages, userMessage];
    onMessagesChange(newMessages);
    setInput('');
    setImages([]);
    setIsLoading(true);

    try {
      const response = await fetch(`http://${fetchHost}:${port}/v1/chat/completions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${apiKey}`,
        },
        body: JSON.stringify({
          model,
          messages: newMessages.map(m => ({
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
      let currentMessages = newMessages;

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
                  currentMessages = [...currentMessages, { role: 'assistant', content: assistantContent }];
                  onMessagesChange(currentMessages);
                  messageAdded = true;
                } else {
                  currentMessages = [
                    ...currentMessages.slice(0, -1),
                    { role: 'assistant', content: assistantContent },
                  ];
                  onMessagesChange(currentMessages);
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
      onMessagesChange([
        ...newMessages,
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
    if (e.key === 'Enter' && !e.shiftKey && !composingRef.current && Date.now() - compositionEndTimeRef.current > 100) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const clearChat = () => {
    onMessagesChange([]);
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
    'claude-opus-4-6',
    'claude-sonnet-4-5',
    'claude-opus-4-5',
    'claude-haiku-4-5',
  ];

  const [availableModels, setAvailableModels] = useState<string[]>(models);

  // Fetch models from API
  const fetchModels = useCallback(async () => {
    if (!isRunning) return;
    try {
      const response = await fetch(`http://${fetchHost}:${port}/v1/models`, {
        headers: {
          'Authorization': `Bearer ${apiKey}`,
        },
      });
      if (response.ok) {
        const data = await response.json();
        const modelIds = data.data?.map((m: { id: string }) => m.id).filter((id: string) => id && !id.includes('auto-kiro'));
        if (modelIds && modelIds.length > 0) {
          setAvailableModels(modelIds);
          // If current model is not in the list, select the first one
          if (!modelIds.includes(model)) {
            setModel(modelIds[0]);
          }
        }
      }
    } catch {
      // Fall back to default models
    }
  }, [host, port, apiKey, isRunning, model]);

  useEffect(() => {
    fetchModels();
  }, [fetchModels]);

  return (
    <div className="flex h-full overflow-hidden">
      {/* Conversation Sidebar */}
      <ConversationSidebar
        conversations={conversations}
        currentConversationId={currentConversationId}
        onSelectConversation={onSelectConversation}
        onNewChat={onNewChat}
        onDeleteConversation={onDeleteConversation}
        onRenameConversation={onRenameConversation}
      />

      {/* Chat Area */}
      <div className="flex-1 flex flex-col overflow-hidden bg-[#F3F3F2]">
        {/* Header: clear button only */}
        {messages.length > 0 && (
          <div className="flex items-center justify-end px-4 py-2">
            <button
              type="button"
              onClick={clearChat}
              className="text-xs text-stone-400 hover:text-stone-600 transition-colors flex items-center gap-1 px-3 py-1.5 rounded-full hover:bg-stone-100"
            >
              <Trash2 className="h-3 w-3" />
              {t('clear')}
            </button>
          </div>
        )}

        {/* Messages Area */}
        <div ref={scrollContainerRef} onScroll={handleScroll} className={`flex-1 px-4 ${messages.length > 0 ? 'overflow-y-auto' : 'flex items-center justify-center'}`}>
          {!isRunning ? (
            <div className="flex flex-col items-center justify-center h-full">
              <div className="text-center max-w-lg mx-auto">
                <p className="text-4xl font-bold text-stone-300 tracking-tight mb-2">{t('chatServerOffline')}</p>
                <p className="text-sm text-stone-400">{t('chatServerOfflineDesc')}</p>
              </div>
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
                      <div className="text-stone-700 text-sm leading-relaxed">
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                          components={{
                            code({ className, children, ...props }) {
                              const match = /language-(\w+)/.exec(className || '');
                              const codeString = String(children).replace(/\n$/, '');
                              const isInline = !match && !codeString.includes('\n');

                              if (isInline) {
                                return (
                                  <code className="bg-stone-100 text-stone-700 px-1.5 py-0.5 rounded text-[13px] font-mono" {...props}>
                                    {children}
                                  </code>
                                );
                              }

                              return (
                                <div className="relative group my-3">
                                  <div className="absolute right-2 top-2 opacity-0 group-hover:opacity-100 transition-opacity">
                                    <CopyButton text={codeString} />
                                  </div>
                                  <SyntaxHighlighter
                                    style={oneLight}
                                    language={match?.[1] || 'text'}
                                    PreTag="div"
                                    customStyle={{
                                      margin: 0,
                                      borderRadius: '12px',
                                      fontSize: '13px',
                                      padding: '16px',
                                    }}
                                  >
                                    {codeString}
                                  </SyntaxHighlighter>
                                </div>
                              );
                            },
                            table({ children }) {
                              return (
                                <div className="my-3 overflow-x-auto rounded-xl border border-stone-200">
                                  <table className="min-w-full divide-y divide-stone-200">
                                    {children}
                                  </table>
                                </div>
                              );
                            },
                            thead({ children }) {
                              return <thead className="bg-stone-100">{children}</thead>;
                            },
                            th({ children }) {
                              return <th className="px-4 py-2 text-left text-xs font-semibold text-stone-600">{children}</th>;
                            },
                            td({ children }) {
                              return <td className="px-4 py-2 text-sm border-t border-stone-100">{children}</td>;
                            },
                            p({ children }) {
                              return <p className="my-2">{children}</p>;
                            },
                            ul({ children }) {
                              return <ul className="my-2 ml-6 list-disc space-y-1">{children}</ul>;
                            },
                            ol({ children }) {
                              return <ol className="my-2 ml-6 list-decimal space-y-1">{children}</ol>;
                            },
                            li({ children }) {
                              return <li className="pl-1 [&>ul]:mt-1 [&>ol]:mt-1">{children}</li>;
                            },
                            h1({ children }) {
                              return <h1 className="text-xl font-bold mt-4 mb-2">{children}</h1>;
                            },
                            h2({ children }) {
                              return <h2 className="text-lg font-bold mt-4 mb-2">{children}</h2>;
                            },
                            h3({ children }) {
                              return <h3 className="text-base font-bold mt-3 mb-2">{children}</h3>;
                            },
                            blockquote({ children }) {
                              return <blockquote className="border-l-4 border-stone-300 pl-4 my-2 text-stone-600 italic">{children}</blockquote>;
                            },
                            a({ href, children }) {
                              return <a href={href} className="text-blue-600 hover:underline" target="_blank" rel="noopener noreferrer">{children}</a>;
                            },
                          }}
                        >
                          {messageText}
                        </ReactMarkdown>
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

            <form onSubmit={handleSubmit} className="flex flex-col bg-white/80 rounded-2xl p-2.5 gap-1.5">
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
                    {availableModels.map((m) => (
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
                  onCompositionStart={() => { composingRef.current = true; }}
                  onCompositionEnd={() => { composingRef.current = false; compositionEndTimeRef.current = Date.now(); }}
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
    </div>
  );
}
