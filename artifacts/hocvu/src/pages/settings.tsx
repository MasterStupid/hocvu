import type { ReactNode } from 'react';
import { Loader2, Monitor, Moon, RotateCw, Square, Sun, Volume2 } from 'lucide-react';
import { Switch } from '@/components/ui/switch';
import { PageHeader } from '@/components/app-shell';
import { ErrorPanel, SkeletonLines } from '@/components/states';
import { useHealth } from '@/hooks/use-public';
import { useSpeaker } from '@/hooks/use-voice';
import { describeError } from '@/lib/api';
import { retrievalLabel } from '@/lib/format';
import { RATES, VOICES, usePrefs, type ThemePref } from '@/lib/prefs';
import { cn } from '@/lib/utils';

function Row({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <div className="grid sm:grid-cols-[1fr_auto] gap-3 sm:gap-8 items-center py-5 border-b border-border last:border-0">
      <div><p className="font-medium">{title}</p>{hint && <p className="text-sm text-muted-foreground mt-0.5">{hint}</p>}</div>
      <div>{children}</div>
    </div>
  );
}

function Segmented<T extends string>({ value, options, onChange, label }: { value: T; options: { id: T; label: string; icon?: ReactNode }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex p-1 rounded-md bg-muted border border-border">
      {options.map((o) => (
        <button key={o.id} type="button" role="radio" aria-checked={value === o.id} onClick={() => onChange(o.id)}
          className={cn('flex items-center gap-1.5 px-3 h-8 rounded text-sm transition-colors', value === o.id ? 'bg-paper shadow-sm text-foreground' : 'text-muted-foreground hover:text-foreground')}
          data-testid={`radio-${label}-${o.id}`}>{o.icon}{o.label}</button>
      ))}
    </div>
  );
}

export default function SettingsPage() {
  const p = usePrefs();
  const health = useHealth();
  const speaker = useSpeaker(p.voice, p.rate);
  const testing = speaker.activeKey === 'test';

  return (
    <div className="px-4 sm:px-8 lg:px-12 py-8 sm:py-12 max-w-4xl">
      <PageHeader kicker="Tùy chọn trên trình duyệt này" title="Cài đặt">
        Tùy chọn được lưu cục bộ trên thiết bị và không chứa dữ liệu nhạy cảm.
      </PageHeader>

      <section className="mt-10">
        <h2 className="kicker text-seal mb-1">Giao diện</h2>
        <Row title="Chủ đề màu" hint="Giấy sáng cho ban ngày, mực tối cho ban đêm.">
          <Segmented label="theme" value={p.theme} onChange={(v: ThemePref) => p.set('theme', v)} options={[
            { id: 'light', label: 'Sáng', icon: <Sun className="w-3.5 h-3.5" /> },
            { id: 'dark', label: 'Tối', icon: <Moon className="w-3.5 h-3.5" /> },
            { id: 'system', label: 'Theo máy', icon: <Monitor className="w-3.5 h-3.5" /> },
          ]} />
        </Row>
        <Row
          title="AI diễn đạt theo nguồn"
          hint={health.data?.llm_available === false
            ? 'Máy chủ chưa cấu hình API key AI — hệ thống đang dùng chế độ trích xuất trực tiếp từ văn bản.'
            : 'Mặc định cho ô hỏi đáp. AI chỉ viết lại nội dung đã truy xuất, không thêm quy định mới.'}
        >
          <Switch
            checked={health.data?.llm_available === false ? false : p.aiEnabled}
            disabled={health.data?.llm_available === false}
            onCheckedChange={(v) => p.set('aiEnabled', v)}
            aria-label="AI diễn đạt theo nguồn"
            data-testid="switch-ai"
          />
        </Row>
      </section>

      <section className="mt-10">
        <h2 className="kicker text-seal mb-1">Giọng nói &amp; Hội thoại</h2>
        <Row title="Giọng" hint="Dùng khi bấm Nghe hoặc bật tự đọc / Live.">
          <Segmented label="voice" value={p.voice} onChange={(v) => p.set('voice', v)} options={VOICES.map((v) => ({ id: v.id, label: v.label }))} />
        </Row>
        <Row title="Tốc độ">
          <Segmented label="rate" value={p.rate} onChange={(v) => p.set('rate', v)} options={RATES.map((r) => ({ id: r.id, label: r.label }))} />
        </Row>
        <Row title="Tự đọc câu trả lời mới" hint="Tự động phát giọng đọc ngay khi nhận câu trả lời (có giọng trình duyệt dự phòng nếu Edge-TTS gián đoạn).">
          <Switch checked={p.autoSpeak} onCheckedChange={(v) => p.set('autoSpeak', v)} aria-label="Tự đọc câu trả lời" data-testid="switch-autospeak" />
        </Row>
        <Row title="Tự gửi sau khi nói xong" hint="Khi dùng nút Nói thường, đếm ngược ngắn 1,2 giây rồi tự gửi (vẫn có nút Sửa lại). Chế độ Live luôn tự gửi.">
          <Switch checked={p.autoSendVoice} onCheckedChange={(v) => p.set('autoSendVoice', v)} aria-label="Tự gửi sau khi nói xong" data-testid="switch-autosend" />
        </Row>
        <Row title="Nghe thử" hint={speaker.error || undefined}>
          <button type="button" className="btn btn-outline" data-testid="button-test-voice"
            onClick={() => { speaker.unlock(); if (testing) speaker.stop(); else void speaker.speak('test', 'Xin chào, tôi là HocVu. Tôi hỗ trợ tra cứu quy chế đào tạo, chứng chỉ IELTS, TOEIC và luôn dẫn nguồn điều khoản.'); }}>
            {testing && speaker.phase === 'loading' ? <Loader2 className="animate-spin" /> : testing ? <Square /> : <Volume2 />}
            {testing ? (speaker.phase === 'loading' ? 'Đang tạo…' : 'Dừng') : 'Nghe thử'}
          </button>
        </Row>
      </section>

      <section className="mt-10">
        <div className="flex items-center justify-between mb-3">
          <h2 className="kicker text-seal">Trạng thái hệ thống</h2>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => health.refetch()} disabled={health.isFetching} data-testid="button-refresh-health">
            <RotateCw className={cn(health.isFetching && 'animate-spin')} /> Kiểm tra lại
          </button>
        </div>
        {health.isLoading && <SkeletonLines rows={2} />}
        {health.isError && <ErrorPanel title="Không kết nối được máy chủ" message={describeError(health.error)} onRetry={() => health.refetch()} retrying={health.isFetching} />}
        {health.data && (
          <dl className="grid grid-cols-2 md:grid-cols-3 gap-px bg-border border border-border rounded-lg overflow-hidden">
            {[
              ['Trạng thái', health.data.status === 'ok' ? 'Hoạt động' : health.data.status],
              ['Văn bản lập chỉ mục', `${health.data.documents}${health.data.demo_only ? ' (mẫu)' : ''}`],
              ['Truy xuất', retrievalLabel(health.data.retrieval)],
              ['AI diễn đạt', health.data.llm_available ? `Sẵn sàng (${health.data.llm_backend || 'cloud'})` : 'Chưa cấu hình (chỉ trích xuất)'],
              ['STT dự phòng', health.data.stt_fallback ? 'Sẵn sàng trên máy chủ' : 'Chỉ dùng trình duyệt'],
              ['Giọng đọc', health.data.voice || 'Chưa rõ'],
            ].map(([k, v]) => (
              <div key={k} className="bg-paper px-4 py-3.5"><dt className="kicker">{k}</dt><dd className="mt-1 font-medium break-words" data-testid={`text-health-${k}`}>{v}</dd></div>
            ))}
          </dl>
        )}
        {health.data?.semantic_error && <p className="text-sm text-ochre mt-3">Tìm kiếm ngữ nghĩa đang tắt: {health.data.semantic_error}. Hệ thống dùng tìm kiếm từ khóa kết hợp từ điển đồng nghĩa thay thế.</p>}
      </section>

      <section className="mt-10 paper px-5 py-4 text-sm text-muted-foreground">
        <p className="font-medium text-foreground">Về dữ liệu hội thoại</p>
        <p className="mt-1">Hội thoại được gắn với một khóa ngẫu nhiên lưu trong trình duyệt này. Xóa dữ liệu trang web sẽ khiến trình duyệt mất quyền mở lại các hội thoại cũ; máy chủ chỉ lưu dấu băm của khóa.</p>
      </section>
    </div>
  );
}
