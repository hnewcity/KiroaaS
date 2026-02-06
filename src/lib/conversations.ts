/**
 * Conversation types and utilities
 */

import type { MessageContent } from '@/components/ChatView';

export interface ConversationMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string | MessageContent[];
  timestamp: number;
}

export interface Conversation {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messages: ConversationMessage[];
  model?: string;
}

export interface ConversationsData {
  conversations: Conversation[];
}

/**
 * Generate a unique ID
 */
export function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
}

/**
 * Generate a title from the first user message
 */
export function generateTitle(content: string | MessageContent[]): string {
  let text: string;
  if (typeof content === 'string') {
    text = content;
  } else {
    const textPart = content.find(c => c.type === 'text');
    text = textPart?.text || 'New conversation';
  }

  // Truncate to ~30 chars at word boundary
  if (text.length <= 30) return text;
  const truncated = text.substring(0, 30);
  const lastSpace = truncated.lastIndexOf(' ');
  return (lastSpace > 15 ? truncated.substring(0, lastSpace) : truncated) + '...';
}
