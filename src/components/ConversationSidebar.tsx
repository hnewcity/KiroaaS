import { useState } from 'react';
import { Plus, MessageSquare, Trash2, Pencil, Check, X } from 'lucide-react';
import { useI18n } from '@/hooks/useI18n';
import type { Conversation } from '@/lib/conversations';

interface ConversationSidebarProps {
  conversations: Conversation[];
  currentConversationId: string | null;
  onSelectConversation: (id: string | null) => void;
  onNewChat: () => void;
  onDeleteConversation: (id: string) => void;
  onRenameConversation: (id: string, title: string) => void;
}

export function ConversationSidebar({
  conversations,
  currentConversationId,
  onSelectConversation,
  onNewChat,
  onDeleteConversation,
  onRenameConversation,
}: ConversationSidebarProps) {
  const { t } = useI18n();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);

  const handleStartRename = (conv: Conversation) => {
    setEditingId(conv.id);
    setEditTitle(conv.title);
  };

  const handleConfirmRename = (id: string) => {
    if (editTitle.trim()) {
      onRenameConversation(id, editTitle.trim());
    }
    setEditingId(null);
    setEditTitle('');
  };

  const handleCancelRename = () => {
    setEditingId(null);
    setEditTitle('');
  };

  const handleDeleteClick = (id: string) => {
    setDeleteConfirmId(id);
  };

  const handleConfirmDelete = (id: string) => {
    onDeleteConversation(id);
    setDeleteConfirmId(null);
  };

  const handleCancelDelete = () => {
    setDeleteConfirmId(null);
  };

  const formatDate = (timestamp: number) => {
    const date = new Date(timestamp);
    const now = new Date();
    const diffDays = Math.floor((now.getTime() - date.getTime()) / (1000 * 60 * 60 * 24));

    if (diffDays === 0) {
      return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } else if (diffDays === 1) {
      return 'Yesterday';
    } else if (diffDays < 7) {
      return date.toLocaleDateString([], { weekday: 'short' });
    } else {
      return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
    }
  };

  return (
    <div className="w-[240px] h-full bg-[#1a1a1a] flex flex-col rounded-l-[24px] overflow-hidden">
      {/* Header with New Chat button */}
      <div className="p-3 flex-shrink-0">
        <button
          onClick={onNewChat}
          className="w-full flex items-center gap-2 px-4 py-2.5 bg-[#2a2a2a] hover:bg-[#333] text-white rounded-xl transition-colors text-sm font-medium"
        >
          <Plus className="h-4 w-4" />
          {t('newChat')}
        </button>
      </div>

      {/* Conversations List */}
      <div className="flex-1 overflow-y-auto px-2 pb-3">
        {conversations.length === 0 ? (
          <div className="text-center py-8 px-4">
            <MessageSquare className="h-8 w-8 text-stone-600 mx-auto mb-2" />
            <p className="text-stone-500 text-xs">{t('noConversations')}</p>
          </div>
        ) : (
          <div className="space-y-1">
            {conversations.map((conv) => (
              <div
                key={conv.id}
                className={`group relative rounded-xl transition-colors ${
                  currentConversationId === conv.id
                    ? 'bg-[#2a2a2a]'
                    : 'hover:bg-[#222]'
                }`}
              >
                {editingId === conv.id ? (
                  <div className="flex items-center gap-1 p-2">
                    <input
                      type="text"
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleConfirmRename(conv.id);
                        if (e.key === 'Escape') handleCancelRename();
                      }}
                      className="flex-1 bg-[#333] text-white text-sm px-2 py-1 rounded-lg border border-stone-600 focus:outline-none focus:border-stone-500"
                      autoFocus
                    />
                    <button
                      onClick={() => handleConfirmRename(conv.id)}
                      className="p-1 text-green-400 hover:text-green-300"
                    >
                      <Check className="h-4 w-4" />
                    </button>
                    <button
                      onClick={handleCancelRename}
                      className="p-1 text-stone-400 hover:text-stone-300"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                ) : deleteConfirmId === conv.id ? (
                  <div className="p-2">
                    <p className="text-xs text-stone-400 mb-2">{t('deleteConfirm')}</p>
                    <div className="flex gap-1">
                      <button
                        onClick={() => handleConfirmDelete(conv.id)}
                        className="flex-1 px-2 py-1 bg-red-600 hover:bg-red-500 text-white text-xs rounded-lg"
                      >
                        {t('confirm')}
                      </button>
                      <button
                        onClick={handleCancelDelete}
                        className="flex-1 px-2 py-1 bg-stone-600 hover:bg-stone-500 text-white text-xs rounded-lg"
                      >
                        {t('dismiss')}
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    onClick={() => onSelectConversation(conv.id)}
                    className="w-full text-left p-2.5 pr-8"
                  >
                    <div className="flex items-start gap-2">
                      <MessageSquare className="h-4 w-4 text-stone-500 flex-shrink-0 mt-0.5" />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm text-white truncate font-medium">
                          {conv.title}
                        </p>
                        <p className="text-xs text-stone-500 mt-0.5">
                          {formatDate(conv.updatedAt)}
                        </p>
                      </div>
                    </div>
                  </button>
                )}

                {/* Action buttons - show on hover when not editing */}
                {editingId !== conv.id && deleteConfirmId !== conv.id && (
                  <div className="absolute right-1 top-1/2 -translate-y-1/2 flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleStartRename(conv);
                      }}
                      className="p-1.5 text-stone-400 hover:text-white rounded-lg hover:bg-[#333]"
                    >
                      <Pencil className="h-3 w-3" />
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDeleteClick(conv.id);
                      }}
                      className="p-1.5 text-stone-400 hover:text-red-400 rounded-lg hover:bg-[#333]"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
