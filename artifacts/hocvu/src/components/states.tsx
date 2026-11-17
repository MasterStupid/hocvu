import type { ReactNode } from 'react';
import { AlertTriangle, RotateCw } from 'lucide-react';
import { cn } from '@/lib/utils';

export function SkeletonLines({ rows = 3, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn('space-y-3', className)} aria-hidden="true">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="h-10 rounded-md bg-muted animate-pulse" style={{ opacity: 1 - i * 0.18, animationDelay: `${i * 90}ms` }} />
      ))}
    </div>
  );
}

export function ErrorPanel({ title = 'Không tải được dữ liệu', message, onRetry, retrying, className }: {
  title?: string; message: string; onRetry?: () => void; retrying?: boolean; className?: string;
}) {
  return (
    <div role="alert" className={cn('paper margin-line pl-5 pr-4 py-4 flex gap-3 items-start', className)}>
      <AlertTriangle className="w-5 h-5 text-seal mt-0.5 shrink-0" aria-hidden="true" />
      <div className="flex-1 min-w-0">
        <p className="font-medium">{title}</p>
        <p className="text-sm text-muted-foreground mt-0.5 break-words">{message}</p>
      </div>
      {onRetry && (
        <button type="button" className="btn btn-outline btn-sm" onClick={onRetry} disabled={retrying} data-testid="button-retry">
          <RotateCw className={cn(retrying && 'animate-spin')} /> Thử lại
        </button>
      )}
    </div>
  );
}

export function EmptyPanel({ title, children, icon, className }: { title: string; children?: ReactNode; icon?: ReactNode; className?: string }) {
  return (
    <div className={cn('text-center py-12 px-6 border border-dashed border-border rounded-lg', className)}>
      {icon && <div className="mx-auto mb-3 w-11 h-11 rounded-full bg-muted grid place-items-center text-muted-foreground">{icon}</div>}
      <p className="font-serif text-xl">{title}</p>
      {children && <div className="text-sm text-muted-foreground mt-1.5 max-w-md mx-auto">{children}</div>}
    </div>
  );
}

export function NoticeBar({ tone, children, onClose, action }: {
  tone: 'info' | 'ok' | 'warn' | 'error'; children: ReactNode; onClose?: () => void; action?: ReactNode;
}) {
  const color = { info: 'border-primary/30 bg-primary/5', ok: 'border-jade/40 bg-jade/8', warn: 'border-ochre/50 bg-ochre/10', error: 'border-destructive/40 bg-destructive/8' }[tone];
  const dot = { info: 'bg-primary', ok: 'bg-jade', warn: 'bg-ochre', error: 'bg-destructive' }[tone];
  return (
    <div role={tone === 'error' ? 'alert' : 'status'} className={cn('flex items-start gap-3 rounded-md border px-3.5 py-2.5 text-sm', color)}>
      <span className={cn('mt-[.45rem] w-1.5 h-1.5 rounded-full shrink-0', dot)} aria-hidden="true" />
      <div className="flex-1 min-w-0">{children}</div>
      {action}
      {onClose && <button type="button" onClick={onClose} className="text-xs underline underline-offset-2 text-muted-foreground hover:text-foreground" data-testid="button-dismiss-notice">Đóng</button>}
    </div>
  );
}
