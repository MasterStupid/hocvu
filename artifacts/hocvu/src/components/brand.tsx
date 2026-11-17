import { cn } from '@/lib/utils';
import universityLogo from './university-logo.png';

export function UniversityLogo({ className, size = 44 }: { className?: string; size?: number }) {
  return <img src={universityLogo} alt="Logo Trường Đại học Hải Phòng" width={size} height={size}
    className={cn('shrink-0 rounded-full bg-white object-contain p-0.5', className)} />;
}

/** Square cinnabar seal, the mark stamped on official Vietnamese documents. */
export function Seal({ className, size = 36 }: { className?: string; size?: number }) {
  return (
    <svg viewBox="0 0 40 40" width={size} height={size} className={cn('shrink-0', className)} aria-hidden="true">
      <rect x="1.5" y="1.5" width="37" height="37" rx="5" fill="hsl(var(--seal))" />
      <rect x="5" y="5" width="30" height="30" rx="2.5" fill="none" stroke="hsl(var(--paper))" strokeWidth="1.4" opacity=".9" />
      <text x="20" y="25.5" textAnchor="middle" fontFamily="Newsreader, serif" fontSize="15" fontWeight="600" fill="hsl(var(--paper))" letterSpacing="-.5">HV</text>
    </svg>
  );
}

export function Wordmark({ invert = false }: { invert?: boolean }) {
  return (
    <span className="flex items-center gap-2.5">
      <UniversityLogo size={40} />
      <span className="leading-none min-w-0">
        <span className={cn('block font-serif text-[1.35rem] font-semibold tracking-tight', invert && 'text-sidebar-accent-foreground')}>HocVu</span>
        <span className={cn('block mt-1 text-[9px] font-semibold leading-[1.4] tracking-[.06em]', invert && 'text-sidebar-foreground/75')}>
          TRƯỜNG ĐẠI HỌC<br />HẢI PHÒNG
        </span>
      </span>
    </span>
  );
}
