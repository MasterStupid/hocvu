import { useMemo, useState } from 'react';
import { Link } from 'wouter';
import { motion } from 'framer-motion';
import { ArrowUpRight, BookOpen, Info, Library, Search } from 'lucide-react';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { PageHeader } from '@/components/app-shell';
import { EmptyPanel, ErrorPanel, SkeletonLines } from '@/components/states';
import { useCatalog, useCatalogDetail, useHealth } from '@/hooks/use-public';
import { describeError } from '@/lib/api';
import { formatDate, retrievalLabel } from '@/lib/format';

const fold = (s: string) => s.toLocaleLowerCase('vi-VN').normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/đ/g, 'd');

export default function LibraryPage() {
  const catalog = useCatalog();
  const health = useHealth();
  const [q, setQ] = useState('');
  const [selectedRid, setSelectedRid] = useState<string | null>(null);
  const [articleFilter, setArticleFilter] = useState('');
  const detail = useCatalogDetail(selectedRid);

  const items = useMemo(() => {
    const all = catalog.data || [];
    const f = fold(q.trim());
    return f ? all.filter((d) => fold(`${d.title} ${d.rid} ${d.version}`).includes(f)) : all;
  }, [catalog.data, q]);

  const filteredArticles = useMemo(() => {
    const articles = detail.data?.articles || [];
    const f = fold(articleFilter.trim());
    if (!f) return articles;
    return articles.filter((a) => fold(`${a.aid} ${a.heading} ${a.text}`).includes(f));
  }, [detail.data, articleFilter]);

  return (
    <div className="px-4 sm:px-8 lg:px-12 py-8 sm:py-12 max-w-5xl">
      <PageHeader kicker="Danh mục công khai" title="Thư viện văn bản">
        Các văn bản quy chế đào tạo đang được lập chỉ mục để HocVu tra cứu và trích dẫn. Sinh viên có thể mở đọc toàn văn từng điều khoản công khai hoặc đặt câu hỏi trực tiếp.
      </PageHeader>

      {health.data?.demo_only && (
        <div className="mt-6 flex items-start gap-2.5 rounded-lg border border-ochre/35 bg-ochre/8 px-4 py-3 text-xs text-foreground" role="note">
          <Info className="w-4 h-4 text-ochre shrink-0 mt-0.5" aria-hidden="true" />
          <p className="leading-relaxed">
            <strong>Kho đang hiển thị dữ liệu minh họa:</strong> Chưa có văn bản quy chế chính thức nào được tải lên khu quản trị.
          </p>
        </div>
      )}

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
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => { setSelectedRid(d.rid); setArticleFilter(''); }}
                  className="btn btn-outline btn-sm"
                  data-testid={`button-read-${d.rid}`}
                >
                  <BookOpen /> <span className="hidden sm:inline">Đọc văn bản</span>
                </button>
                <Link href={`/?q=${encodeURIComponent(`Văn bản "${d.title}" (mã ${d.rid}) quy định những gì?`)}`}
                  className="btn btn-ghost btn-sm opacity-75 group-hover:opacity-100" data-testid={`link-ask-${d.rid}`}>
                  <span className="hidden sm:inline">Hỏi đáp</span> <ArrowUpRight />
                </Link>
              </div>
            </motion.li>
          ))}
        </ol>
      </div>

      <Sheet open={Boolean(selectedRid)} onOpenChange={(open) => { if (!open) setSelectedRid(null); }}>
        <SheetContent side="right" className="w-full sm:max-w-2xl p-0 bg-background flex flex-col">
          <SheetHeader className="px-6 pt-6 pb-4 border-b border-border text-left">
            <span className="kicker text-seal">Toàn văn quy chế công khai</span>
            <SheetTitle className="font-serif text-2xl leading-snug mt-1">
              {detail.data?.title || 'Đang tải văn bản…'}
            </SheetTitle>
            <SheetDescription className="font-mono text-xs">
              {detail.data ? (
                <>
                  {detail.data.rid}
                  {detail.data.version ? ` · Bản ${detail.data.version}` : ''}
                  {detail.data.valid_from ? ` · Hiệu lực từ ${formatDate(detail.data.valid_from)}` : ''}
                  {detail.data.valid_until ? ` đến ${formatDate(detail.data.valid_until)}` : ''}
                </>
              ) : 'Đang nạp các điều khoản đã lập chỉ mục…'}
            </SheetDescription>
          </SheetHeader>

          <div className="px-6 py-3 border-b border-border bg-muted/30">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" aria-hidden="true" />
              <input
                type="search"
                className="field pl-9 !min-h-9 text-sm"
                placeholder="Lọc nhanh điều khoản trong văn bản này…"
                value={articleFilter}
                onChange={(e) => setArticleFilter(e.target.value)}
                data-testid="input-filter-articles"
              />
            </div>
          </div>

          <div className="flex-1 overflow-y-auto scroll-thin px-6 py-5 space-y-4">
            {detail.isLoading && <SkeletonLines rows={6} />}
            {detail.isError && <ErrorPanel message={describeError(detail.error)} onRetry={() => detail.refetch()} retrying={detail.isFetching} />}
            {detail.isSuccess && filteredArticles.length === 0 && (
              <EmptyPanel title="Không có điều khoản khớp">Thử từ khóa khác hoặc xóa bộ lọc phía trên.</EmptyPanel>
            )}
            {filteredArticles.map((art) => (
              <article key={`${art.aid}-${art.heading}`} className="paper px-4 py-3.5 space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <span className="kicker text-seal">{art.aid}</span>
                    {art.heading && <h3 className="font-serif text-lg font-medium leading-snug">{art.heading}</h3>}
                  </div>
                  <Link
                    href={`/?q=${encodeURIComponent(`${art.heading || art.aid} trong "${detail.data?.title || ''}" quy định như thế nào?`)}`}
                    onClick={() => setSelectedRid(null)}
                    className="btn btn-ghost btn-sm shrink-0"
                  >
                    Hỏi <ArrowUpRight />
                  </Link>
                </div>
                <p className="text-sm leading-relaxed text-foreground/90 whitespace-pre-line">{art.text}</p>
              </article>
            ))}
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
}
