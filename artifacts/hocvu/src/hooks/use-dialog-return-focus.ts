import { useRef } from 'react';

/** Controlled admin dialogs have multiple openers, not a single Radix Trigger. */
export function useDialogReturnFocus() {
  const opener = useRef<HTMLElement | null>(null);
  return {
    onOpenAutoFocus: () => {
      opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    },
    onCloseAutoFocus: (event: Event) => {
      const target = opener.current;
      if (target?.isConnected && !target.matches(':disabled')) {
        event.preventDefault();
        target.focus({ preventScroll: true });
      }
      opener.current = null;
    },
  };
}
