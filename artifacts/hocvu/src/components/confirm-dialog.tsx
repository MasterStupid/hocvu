import type { ReactNode } from 'react';
import {
  AlertDialog, AlertDialogContent, AlertDialogDescription, AlertDialogTitle,
} from '@/components/ui/alert-dialog';

export function ConfirmDialog({ open, onOpenChange, title, children, confirmLabel, onConfirm, busy, tone = 'danger' }: {
  open: boolean; onOpenChange: (v: boolean) => void; title: string; children: ReactNode;
  confirmLabel: string; onConfirm: () => void; busy?: boolean; tone?: 'danger' | 'primary';
}) {
  return (
    <AlertDialog open={open} onOpenChange={(v) => { if (!busy) onOpenChange(v); }}>
      <AlertDialogContent className="bg-paper border-card-border max-w-md">
        <span className="kicker text-seal">Xác nhận</span>
        <AlertDialogTitle className="font-serif text-2xl font-medium leading-tight">{title}</AlertDialogTitle>
        <AlertDialogDescription asChild>
          <div className="text-sm text-muted-foreground space-y-2">{children}</div>
        </AlertDialogDescription>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn btn-ghost" onClick={() => onOpenChange(false)} disabled={busy} data-testid="button-confirm-cancel">Hủy</button>
          <button type="button" className={tone === 'danger' ? 'btn btn-danger' : 'btn btn-primary'} onClick={onConfirm} disabled={busy} data-testid="button-confirm-ok">
            {busy ? 'Đang xử lý…' : confirmLabel}
          </button>
        </div>
      </AlertDialogContent>
    </AlertDialog>
  );
}
