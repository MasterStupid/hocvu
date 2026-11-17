import { useState, type ReactNode } from 'react';
import { Link, useLocation } from 'wouter';
import { BookOpenText, FolderLock, Menu, MessagesSquare, Settings2 } from 'lucide-react';
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet';
import { Wordmark } from '@/components/brand';
import { useHealth } from '@/hooks/use-public';
import { cn } from '@/lib/utils';

const NAV = [
  { href: '/', label: 'Hỏi đáp', hint: 'Tra cứu có căn cứ', icon: MessagesSquare, match: (p: string) => p === '/' },
  { href: '/library', label: 'Thư viện', hint: 'Danh mục văn bản', icon: BookOpenText, match: (p: string) => p.startsWith('/library') },
  { href: '/documents', label: 'Quản trị', hint: 'Tài liệu được bảo vệ', icon: FolderLock, match: (p: string) => p.startsWith('/documents') },
  { href: '/settings', label: 'Cài đặt', hint: 'Giao diện, giọng đọc', icon: Settings2, match: (p: string) => p.startsWith('/settings') },
];

export function HealthBadge({ compact = false }: { compact?: boolean }) {
  const health = useHealth();
  const online = health.isSuccess && health.data.status === 'ok' && !health.isError;
  const label = health.isLoading ? 'Đang kiểm tra' : online ? 'Trực tuyến' : 'Mất kết nối';
  return (
    <div className="flex items-center gap-2 text-xs" role="status" data-testid="status-health">
      <span className={cn('relative w-2 h-2 rounded-full', health.isLoading ? 'bg-ochre' : online ? 'bg-jade' : 'bg-seal')}>
        {online && <span className="absolute inset-0 rounded-full bg-jade animate-ping opacity-40" />}
      </span>
      <span>{label}</span>
      {!compact && online && <span className="opacity-60">· {health.data.documents} văn bản</span>}
    </div>
  );
}

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  const [location] = useLocation();
  const path = location === '/documents.html' ? '/documents' : location;
  return (
    <nav aria-label="Điều hướng chính" className="flex flex-col gap-1">
      {NAV.map((item, i) => {
        const active = item.match(path);
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            aria-current={active ? 'page' : undefined}
            data-testid={`link-nav-${item.href.replace('/', '') || 'home'}`}
            className={cn(
              'group relative flex items-center gap-3 rounded-md px-3 py-2.5 transition-colors',
              active ? 'bg-sidebar-accent text-sidebar-accent-foreground' : 'text-sidebar-foreground/75 hover:text-sidebar-accent-foreground hover:bg-sidebar-accent/50',
            )}
          >
            {active && <span className="absolute left-0 top-2 bottom-2 w-[3px] rounded-r bg-sidebar-primary" aria-hidden="true" />}
            <span className="font-mono text-[.65rem] opacity-50 w-4">{String(i + 1).padStart(2, '0')}</span>
            <Icon className="w-4 h-4 shrink-0" aria-hidden="true" />
            <span className="flex-1 min-w-0">
              <span className="block text-sm font-medium">{item.label}</span>
              <span className="block text-[.7rem] opacity-55 truncate">{item.hint}</span>
            </span>
          </Link>
        );
      })}
    </nav>
  );
}

function SidebarBody({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <div className="flex h-full flex-col gap-8 p-5 text-sidebar-foreground">
      <Link href="/" onClick={onNavigate} className="rounded-md" data-testid="link-brand"><Wordmark invert /></Link>
      <NavList onNavigate={onNavigate} />
      <div className="mt-auto space-y-4">
        <p className="text-[.72rem] leading-relaxed text-sidebar-foreground/55">
          Mỗi câu trả lời phải dẫn về điều, khoản cụ thể. Khi nguồn chưa đủ, HocVu từ chối thay vì đoán.
        </p>
        <div className="border-t border-sidebar-border pt-4"><HealthBadge /></div>
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="min-h-[100dvh] md:grid md:grid-cols-[248px_1fr]">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 btn btn-primary">Bỏ qua điều hướng</a>
      <aside className="hidden md:block sticky top-0 h-[100dvh] bg-sidebar border-r border-sidebar-border">
        <SidebarBody />
      </aside>

      <header className="md:hidden sticky top-0 z-30 flex items-center justify-between px-4 h-14 bg-sidebar text-sidebar-foreground border-b border-sidebar-border">
        <Link href="/" className="rounded-md" data-testid="link-brand-mobile"><Wordmark invert /></Link>
        <div className="flex items-center gap-3">
          <div className="hidden sm:block"><HealthBadge compact /></div>
          <button type="button" className="btn btn-icon text-sidebar-foreground hover:bg-sidebar-accent" onClick={() => setOpen(true)} aria-label="Mở menu điều hướng" aria-expanded={open} data-testid="button-open-nav">
            <Menu />
          </button>
        </div>
      </header>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="left" className="w-[280px] p-0 bg-sidebar border-sidebar-border">
          <SheetTitle className="sr-only">Điều hướng</SheetTitle>
          <SheetDescription className="sr-only">Chọn trang trong HocVu</SheetDescription>
          <SidebarBody onNavigate={() => setOpen(false)} />
        </SheetContent>
      </Sheet>

      <main id="main" className="min-w-0">{children}</main>
    </div>
  );
}

export function PageHeader({ kicker, title, children, actions }: { kicker: string; title: string; children?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between border-b border-border pb-6">
      <div className="max-w-2xl">
        <span className="kicker text-seal">{kicker}</span>
        <h1 className="font-serif text-4xl sm:text-5xl font-medium leading-[1.05] mt-2">{title}</h1>
        {children && <div className="text-muted-foreground mt-3 text-[.95rem]">{children}</div>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  );
}
