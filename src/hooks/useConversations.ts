import { useState, useEffect, useCallback } from 'react';
import {
  loadConversations,
  createConversation as createConversationApi,
  updateConversation as updateConversationApi,
  deleteConversation as deleteConversationApi,
  renameConversation as renameConversationApi,
} from '@/lib/tauri';
import type { Conversation, ConversationMessage } from '@/lib/conversations';
import { generateId, generateTitle } from '@/lib/conversations';
import type { Message } from '@/components/ChatView';

/**
 * Hook for managing conversations
 */
export function useConversations() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Load conversations on mount
  useEffect(() => {
    const load = async () => {
      try {
        const data = await loadConversations();
        setConversations(data.conversations);
        // Select the most recent conversation if available
        if (data.conversations.length > 0) {
          setCurrentConversationId(data.conversations[0].id);
        }
        setIsLoading(false);
      } catch (err) {
        console.error('Failed to load conversations:', err);
        setError(err instanceof Error ? err.message : 'Failed to load conversations');
        setIsLoading(false);
      }
    };

    load();
  }, []);

  // Get current conversation
  const currentConversation = conversations.find(c => c.id === currentConversationId) || null;

  // Get messages for current conversation
  const messages: Message[] = currentConversation?.messages.map(m => ({
    role: m.role,
    content: m.content,
  })) || [];

  // Create a new conversation
  const createConversation = useCallback(async (model?: string) => {
    const now = Date.now();
    const newConversation: Conversation = {
      id: generateId(),
      title: 'New Chat',
      createdAt: now,
      updatedAt: now,
      messages: [],
      model,
    };

    try {
      await createConversationApi(newConversation);
      setConversations(prev => [newConversation, ...prev]);
      setCurrentConversationId(newConversation.id);
      setError(null);
      return newConversation;
    } catch (err) {
      console.error('Failed to create conversation:', err);
      setError(err instanceof Error ? err.message : 'Failed to create conversation');
      throw err;
    }
  }, []);

  // Update messages in current conversation
  const updateMessages = useCallback(async (newMessages: Message[], model?: string) => {
    if (!currentConversationId) {
      // Create a new conversation if none exists
      const conv = await createConversation(model);
      if (newMessages.length === 0) return;

      const now = Date.now();
      const conversationMessages: ConversationMessage[] = newMessages.map(m => ({
        id: generateId(),
        role: m.role,
        content: m.content,
        timestamp: now,
      }));

      // Generate title from first user message
      const firstUserMessage = newMessages.find(m => m.role === 'user');
      const title = firstUserMessage ? generateTitle(firstUserMessage.content) : 'New Chat';

      const updatedConversation: Conversation = {
        ...conv,
        title,
        updatedAt: now,
        messages: conversationMessages,
        model,
      };

      try {
        await updateConversationApi(updatedConversation);
        setConversations(prev => prev.map(c =>
          c.id === conv.id ? updatedConversation : c
        ));
      } catch (err) {
        console.error('Failed to update conversation:', err);
      }
      return;
    }

    const conversation = conversations.find(c => c.id === currentConversationId);
    if (!conversation) return;

    const now = Date.now();
    const conversationMessages: ConversationMessage[] = newMessages.map((m, index) => {
      // Reuse existing message IDs where possible
      const existingMessage = conversation.messages[index];
      return {
        id: existingMessage?.id || generateId(),
        role: m.role,
        content: m.content,
        timestamp: existingMessage?.timestamp || now,
      };
    });

    // Generate title from first user message if title is still default
    let title = conversation.title;
    if (title === 'New Chat' && newMessages.length > 0) {
      const firstUserMessage = newMessages.find(m => m.role === 'user');
      if (firstUserMessage) {
        title = generateTitle(firstUserMessage.content);
      }
    }

    const updatedConversation: Conversation = {
      ...conversation,
      title,
      updatedAt: now,
      messages: conversationMessages,
      model: model || conversation.model,
    };

    try {
      await updateConversationApi(updatedConversation);
      setConversations(prev => prev.map(c =>
        c.id === currentConversationId ? updatedConversation : c
      ));
      setError(null);
    } catch (err) {
      console.error('Failed to update conversation:', err);
      setError(err instanceof Error ? err.message : 'Failed to update conversation');
    }
  }, [currentConversationId, conversations, createConversation]);

  // Delete a conversation
  const deleteConversation = useCallback(async (id: string) => {
    try {
      await deleteConversationApi(id);
      setConversations(prev => {
        const filtered = prev.filter(c => c.id !== id);
        // If we deleted the current conversation, select another
        if (currentConversationId === id) {
          setCurrentConversationId(filtered.length > 0 ? filtered[0].id : null);
        }
        return filtered;
      });
      setError(null);
    } catch (err) {
      console.error('Failed to delete conversation:', err);
      setError(err instanceof Error ? err.message : 'Failed to delete conversation');
      throw err;
    }
  }, [currentConversationId]);

  // Rename a conversation
  const renameConversation = useCallback(async (id: string, title: string) => {
    try {
      await renameConversationApi(id, title);
      setConversations(prev => prev.map(c =>
        c.id === id ? { ...c, title } : c
      ));
      setError(null);
    } catch (err) {
      console.error('Failed to rename conversation:', err);
      setError(err instanceof Error ? err.message : 'Failed to rename conversation');
      throw err;
    }
  }, []);

  // Select a conversation
  const selectConversation = useCallback((id: string | null) => {
    setCurrentConversationId(id);
  }, []);

  // Start a new chat (create new conversation and select it)
  const startNewChat = useCallback(async (model?: string) => {
    await createConversation(model);
  }, [createConversation]);

  return {
    conversations,
    currentConversation,
    currentConversationId,
    messages,
    isLoading,
    error,
    createConversation,
    updateMessages,
    deleteConversation,
    renameConversation,
    selectConversation,
    startNewChat,
  };
}
