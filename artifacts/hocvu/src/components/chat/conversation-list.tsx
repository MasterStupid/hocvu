import { Plus, RotateCw, Trash2 } from 'lucide-react';
import { useConversations } from '@/hooks/use-chat';
import { describeError } from '@/lib/api';
import { historyGroup, historyTime } from '@/lib/format';
import { cn } from '@/lib/utils';

export function ConversationList({ currentId, onOpen, onNew, onDelete, disabled }: {
  currentId: string;
  onOpen: (id: string) => void;
  onNew: () => void;
  onDelete?: (id: string, title: string) => void;
  disabled: boolean;
}) {
  const q = useConversations();
  const list = q.data || [];
  const hasCurrent = list.some((c) => c.session_id === currentId);
  let group = '';

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center gap-2 px-4 pt-4 pb-3">
        <button type="button" className="btn btn-primary flex-1" onClick={onNew} disabled={disabled} data-testid="button-new-chat">
          <Plus /> Hội thoại mới
        </button>
        <button type="button" className="btn btn-outline btn-icon" onClick={() => q.refetch()} disabled={q.isFetching}
          aria-label="Làm mới danh sách hội thoại" data-testid="button-refresh-conversations">
          <RotateCw className={cn(q.isFetching && 'animate-spin')} />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto scroll-thin px-2 pb-4" aria-busy={q.isLoading || disabled}>
        {!hasCurrent && (
          <div className="mx-2 mb-2 rounded-md px-3 py-2.5 bg-seal/8 border border-seal/25" aria-current="page">
            <p className="text-sm font-medium">Phiên tra cứu hiện tại</p>
            <p className="text-xs text-muted-foreground">Chưa có lượt được lưu</p>
          </div>
        )}
        {q.isLoading && <div className="space-y-2 px-2">{[0, 1, 2, 3].map((i) => <div key={i} className="h-12 rounded-md bg-muted animate-pulse" />)}</div>}
        {q.isError && (
          <div className="mx-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-xs" role="alert">
            Không tải được danh sách: {describeError(q.error)}
            <button type="button" className="block mt-1.5 underline underline-offset-2" onClick={() => q.refetch()} data-testid="button-retry-conversations">Thử lại</button>
          </div>
        )}
        {q.isSuccess && list.length === 0 && (
          <p className="px-3 py-6 text-xs text-muted-foreground text-center">Chưa có hội thoại nào được lưu trong trình duyệt này.</p>
        )}
        {list.map((c) => {
          const label = historyGroup(c.updated_at);
          const heading = label !== group ? (group = label) : null;
          const active = c.session_id === currentId;
          return (
            <div key={c.session_id}>
              {heading && <p className="kicker px-3 pt-4 pb-1.5">{heading}</p>}
              <div
                className={cn(
                  'group relative flex items-center rounded-md transition-colors',
                  active ? 'bg-paper shadow-sm border border-border' : 'hover:bg-foreground/5 border border-transparent',
                )}
              >
                {active && <span className="absolute left-0 top-2.5 bottom-2.5 w-[3px] rounded-r bg-seal" aria-hidden="true" />}
                <button
                  type="button"
                  onClick={() => onOpen(c.session_id)}
                  disabled={disabled && !active}
                  aria-current={active ? 'page' : undefined}
                  title={c.title}
                  data-testid={`button-conversation-${c.session_id}`}
                  className="flex-1 min-w-0 text-left px-3 py-2"
                >
                  <span className="block text-sm truncate">{c.title}</span>
                  <span className="block text-[.7rem] text-muted-foreground font-mono mt-0.5">{c.turn_count} lượt · {historyTime(c.updated_at)}</span>
                </button>
                {onDelete && (
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={(e) => { e.stopPropagation(); onDelete(c.session_id, c.title); }}
                    aria-label={`Xóa hội thoại ${c.title}`}
                    title="Xóa hội thoại này"
                    data-testid={`button-delete-conversation-${c.session_id}`}
                    className="mr-1.5 p-1.5 rounded text-muted-foreground opacity-0 group-hover:opacity-100 focus:opacity-100 hover:text-destructive hover:bg-destructive/10 transition-opacity"
                  >
                    <Trash2 className="w-3.5 h-3.5" aria-hidden="true" />
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
      {q.isSuccess && <p className="px-4 py-3 border-t border-border text-[.7rem] text-muted-foreground">{list.length} hội thoại lưu theo trình duyệt này.</p>}
    </div>
  );
}
