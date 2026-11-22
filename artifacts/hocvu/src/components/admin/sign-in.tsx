import { useState, type FormEvent } from 'react';
import { motion } from 'framer-motion';
import { Eye, EyeOff, KeyRound, Loader2, LockKeyhole } from 'lucide-react';
import { Seal } from '@/components/brand';
import { ApiError, describeError } from '@/lib/api';
import { useAdminAuth } from '@/lib/admin-auth';

export function SignIn() {
  const { signIn } = useAdminAuth();
  const [password, setPassword] = useState('');
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!password || busy) return;
    setBusy(true); setError(null);
    try {
      await signIn(password);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401
        ? 'Mật khẩu không đúng, hoặc máy chủ chưa được cấu hình mật khẩu quản trị.'
        : describeError(err));
    } finally { setBusy(false); }
  };

  return (
    <div className="min-h-[calc(100dvh-3.5rem)] md:min-h-[100dvh] grid lg:grid-cols-[1.05fr_1fr]">
      <div className="hidden lg:flex flex-col justify-between bg-primary text-primary-foreground p-12 relative overflow-hidden">
        <div className="absolute inset-0 opacity-[.07] ruled" aria-hidden="true" />
        <span className="kicker !text-primary-foreground/60 relative">Khu vực quản trị · Hồ sơ được bảo vệ</span>
        <div className="relative">
          <p className="font-serif text-5xl leading-[1.05]">Mỗi văn bản tải lên<br />sẽ trở thành căn cứ<br /><em className="text-[hsl(var(--seal))] italic">cho hàng nghìn câu trả lời.</em></p>
          <p className="mt-6 max-w-md text-primary-foreground/70 text-sm">Hãy kiểm tra số quyết định, điều khoản và ngày áp dụng trước khi lập chỉ mục. Sinh viên sẽ đọc chính những trích dẫn này.</p>
        </div>
        <Seal size={56} className="relative" />
      </div>

      <div className="flex items-center justify-center px-5 py-12">
        <motion.form onSubmit={submit} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="w-full max-w-sm">
          <div className="w-12 h-12 rounded-md bg-seal/10 text-seal grid place-items-center"><LockKeyhole className="w-5 h-5" /></div>
          <h1 className="font-serif text-4xl mt-5 font-medium">Đăng nhập quản trị</h1>
          <p className="text-sm text-muted-foreground mt-2">Nhập mật khẩu truy cập tài liệu. Mật khẩu chỉ giữ trong bộ nhớ của thẻ này và sẽ bị quên khi bạn đăng xuất hoặc tải lại trang.</p>

          <label htmlFor="admin-password" className="label mt-8">Mật khẩu</label>
          <div className="relative">
            <KeyRound className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" aria-hidden="true" />
            <input id="admin-password" type={show ? 'text' : 'password'} autoComplete="current-password" className="field pl-9 pr-10"
              value={password} onChange={(e) => setPassword(e.target.value)} disabled={busy} autoFocus
              aria-invalid={!!error} aria-describedby={error ? 'signin-error' : undefined} data-testid="input-admin-password" />
            <button type="button" onClick={() => setShow((v) => !v)} className="absolute right-1 top-1/2 -translate-y-1/2 btn btn-ghost btn-icon btn-sm"
              aria-label={show ? 'Ẩn mật khẩu' : 'Hiện mật khẩu'} data-testid="button-toggle-password">{show ? <EyeOff /> : <Eye />}</button>
          </div>
          {error && <p id="signin-error" role="alert" className="text-sm text-destructive mt-2">{error}</p>}

          <button type="submit" className="btn btn-primary w-full mt-5 h-11" disabled={!password || busy} data-testid="button-sign-in">
            {busy ? <><Loader2 className="animate-spin" /> Đang xác minh…</> : 'Mở khu quản trị'}
          </button>

          <div className="mt-8 rounded-md border border-border bg-muted/40 px-4 py-3 text-xs text-muted-foreground leading-relaxed">
            <p className="font-medium text-foreground text-[.8rem] mb-1">Dành cho cán bộ quản trị</p>
            Khu vực này dùng để tải lên và cập nhật văn bản quy chế chính thức. Sinh viên không cần đăng nhập để tra cứu hỏi đáp. Nếu bạn là quản trị viên và chưa có mật khẩu, hãy liên hệ bộ phận vận hành hệ thống.
          </div>
        </motion.form>
      </div>
    </div>
  );
}
