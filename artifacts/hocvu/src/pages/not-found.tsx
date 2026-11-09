import { Link } from 'wouter';
import { Seal } from '@/components/brand';

export default function NotFound() {
  return (
    <div className="min-h-[70dvh] grid place-items-center px-6">
      <div className="text-center max-w-md">
        <Seal size={52} className="mx-auto opacity-80" />
        <p className="kicker mt-6">Mã lỗi 404</p>
        <h1 className="font-serif text-4xl mt-2">Không có điều khoản này</h1>
        <p className="text-muted-foreground mt-3">Trang bạn tìm không tồn tại hoặc đã được chuyển đi.</p>
        <Link href="/" className="btn btn-primary mt-6" data-testid="link-home">Về trang hỏi đáp</Link>
      </div>
    </div>
  );
}
