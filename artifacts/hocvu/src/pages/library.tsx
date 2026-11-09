import { useMemo, useState } from 'react';
import { Link } from 'wouter';
import { motion } from 'framer-motion';
import { ArrowUpRight, Library, Search } from 'lucide-react';
import { PageHeader } from '@/components/app-shell';
import { EmptyPanel, ErrorPanel, SkeletonLines } from '@/components/states';
import { useCatalog, useHealth } from '@/hooks/use-public';
import { describeError } from '@/lib/api';
import { retrievalLabel } from '@/lib/format';

const fold = (s: string) => s.toLocaleLowerCase('vi-VN').normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/đ/g, 'd');

export default function LibraryPage() {
  const catalog = useCatalog();
  const health = useHealth();
  const [q, setQ] = useState('');
  const items = useMemo(() => {
    const all = catalog.data || [];
    const f = fold(q.trim());
    return f ? all.filter((d) => fold(`${d.title} ${d.rid} ${d.version}`).includes(f)) : all;
  }, [catalog.data, q]);

  return (
    <div className="px-4 sm:px-8 lg:px-12 py-8 sm:py-12 max-w-5xl">
      <PageHeader kicker="Danh mục công khai" title="Thư viện văn bản">
        Các văn bản đang được lập chỉ mục để HocVu trích dẫn. Trang này chỉ hiển thị tên, mã và phiên bản; nội dung gốc được bảo vệ trong khu quản trị.
      </PageHeader>

      <div className="grid sm:grid-cols-3 gap-px bg-border border border-border rounded-lg overflow-hidden mt-8">
        {[
          { k: 'Văn bản lập chỉ mục', v: health.isSuccess ? String(health.data.documents) : health.isError ? 'Không rõ' : '…' },
          { k: 'Phương thức truy xuất', v: health.isSuccess ? retrievalLabel(health.data.retrieval) : '…' },
          { k: 'Kết quả đang hiển thị', v: catalog.isSuccess ? String(items.length) : '…' },
        ].map((s) => (
          <div key={s.k} className="bg-paper px-5 py-4">
            <p className="kicker">{s.k}</p>
            <p className="font-serif text-3xl mt-1" data-testid={`text-stat-${fold(s.k).replace(/\s+/g, '-')}`}>{s.v}</p>
          </div>
        ))}
      </div>

      <div className="relative mt-8">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" aria-hidden="true" />
        <input type="search" className="field pl-9" placeholder="Tìm theo tên, mã văn bản hoặc phiên bản…" value={q} onChange={(e) => setQ(e.target.value)}
          aria-label="Tìm văn bản" data-testid="input-search-library" />
      </div>

      <div className="mt-6">
        {catalog.isLoading && <SkeletonLines rows={5} />}
        {catalog.isError && <ErrorPanel message={describeError(catalog.error)} onRetry={() => catalog.refetch()} retrying={catalog.isFetching} />}
        {catalog.isSuccess && catalog.data.length === 0 && (
          <EmptyPanel title="Chưa có văn bản nào" icon={<Library className="w-5 h-5" />}>Quản trị viên cần tải lên hoặc lập chỉ mục văn bản trước khi tra cứu.</EmptyPanel>
        )}
        {catalog.isSuccess && catalog.data.length > 0 && items.length === 0 && (
          <EmptyPanel title="Không có văn bản khớp">Thử từ khóa khác, ví dụ “học bổng” hoặc “đào tạo”.</EmptyPanel>
        )}
        <ol className="divide-y divide-border border-y border-border">
          {items.map((d, i) => (
            <motion.li key={d.rid} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: Math.min(i, 12) * 0.03 }}
              className="group grid grid-cols-[2.5rem_1fr_auto] gap-3 items-center py-4">
              <span className="font-mono text-xs text-muted-foreground">{String(i + 1).padStart(3, '0')}</span>
              <div className="min-w-0">
                <p className="font-serif text-lg leading-snug">{d.title}</p>
                <p className="text-xs text-muted-foreground font-mono mt-0.5 truncate">{d.rid}{d.version ? ` · Bản ${d.version}` : ''}</p>
              </div>
              <Link href={`/?q=${encodeURIComponent(`Văn bản "${d.title}" quy định những gì?`)}`}
                className="btn btn-ghost btn-sm opacity-70 group-hover:opacity-100" data-testid={`link-ask-${d.rid}`}>
                <span className="hidden sm:inline">Hỏi về văn bản</span> <ArrowUpRight />
              </Link>
            </motion.li>
          ))}
        </ol>
      </div>
    </div>
  );
}
