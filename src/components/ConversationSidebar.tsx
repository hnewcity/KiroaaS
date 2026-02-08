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
    <div className="w-[240px] h-full bg-[#E8E8E6] flex flex-col overflow-hidden flex-shrink-0 rounded-l-[32px]">
      {/* Header */}
      <div className="px-4 pt-5 pb-2 flex-shrink-0">
        <h2 className="text-sm font-bold text-stone-500 tracking-tight mb-3 px-1">{t('tabChat')}</h2>
        <button
          onClick={onNewChat}
          className="w-full flex items-center gap-2 px-3 py-2 text-stone-500 hover:text-stone-700 hover:bg-black/5 rounded-lg transition-colors text-sm font-medium"
        >
          <Plus className="h-4 w-4" />
          {t('newChat')}
        </button>
      </div>

      {/* Conversations List */}
      <div className="flex-1 overflow-y-auto px-3 pb-3">
        {conversations.length === 0 ? (
          <div className="text-center py-8 px-4">
            <MessageSquare className="h-8 w-8 text-stone-400 mx-auto mb-2" />
            <p className="text-stone-400 text-xs">{t('noConversations')}</p>
          </div>
        ) : (
          <div className="space-y-0.5">
            {conversations.map((conv) => (
              <div
                key={conv.id}
                className={`group relative rounded-lg transition-colors ${currentConversationId === conv.id
                    ? 'bg-black/[0.06]'
                    : 'hover:bg-black/[0.04]'
                  }`}
              >
                {editingId === conv.id ? (
                  <div className="flex items-center gap-1 p-1.5">
                    <input
                      type="text"
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleConfirmRename(conv.id);
                        if (e.key === 'Escape') handleCancelRename();
                      }}
                      className="flex-1 bg-white text-stone-800 text-sm px-2 py-1 rounded-md border border-stone-300 focus:outline-none focus:border-stone-400"
                      autoFocus
                    />
                    <button
                      onClick={() => handleConfirmRename(conv.id)}
                      className="p-1 text-green-600 hover:text-green-500"
                    >
                      <Check className="h-3.5 w-3.5" />
                    </button>
                    <button
                      onClick={handleCancelRename}
                      className="p-1 text-stone-400 hover:text-stone-500"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ) : deleteConfirmId === conv.id ? (
                  <div className="p-2">
                    <p className="text-xs text-stone-500 mb-2">{t('deleteConfirm')}</p>
                    <div className="flex gap-1">
                      <button
                        onClick={() => handleConfirmDelete(conv.id)}
                        className="flex-1 px-2 py-1 bg-red-500 hover:bg-red-400 text-white text-xs rounded-md"
                      >
                        {t('confirm')}
                      </button>
                      <button
                        onClick={handleCancelDelete}
                        className="flex-1 px-2 py-1 bg-stone-300 hover:bg-stone-200 text-stone-700 text-xs rounded-md"
                      >
                        {t('dismiss')}
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    onClick={() => onSelectConversation(conv.id)}
                    className="w-full text-left px-2.5 py-2 pr-8"
                  >
                    <p className="text-sm text-stone-600 truncate font-medium leading-snug">
                      {conv.title}
                    </p>
                    <p className="text-[11px] text-stone-400 mt-0.5">
                      {formatDate(conv.updatedAt)}
                    </p>
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
                      className="p-1 text-stone-400 hover:text-stone-600 rounded-md hover:bg-black/5"
                    >
                      <Pencil className="h-3 w-3" />
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDeleteClick(conv.id);
                      }}
                      className="p-1 text-stone-400 hover:text-red-500 rounded-md hover:bg-black/5"
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
