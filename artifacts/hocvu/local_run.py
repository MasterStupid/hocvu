"""Local one-command launcher for HocVu AI (React UI + FastAPI backend)."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import runpy
import secrets
import shutil
import subprocess
import sys


HOCVU_DIR = Path(__file__).resolve().parent
APP_DIR = HOCVU_DIR / "app"
WORKSPACE_DIR = HOCVU_DIR.parents[1]
UI_DIST = HOCVU_DIR / "dist" / "public"


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if name and len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if name:
            os.environ.setdefault(name, value)


def _ensure_react_build() -> None:
    if (UI_DIST / "index.html").is_file():
        return
    pnpm = shutil.which("pnpm")
    if not pnpm:
        raise RuntimeError(
            "Chưa có bản build giao diện React (artifacts/hocvu/dist/public/index.html) "
            "và không tìm thấy pnpm. Hãy cài Node.js + pnpm rồi chạy:\n"
            "  pnpm install && pnpm --filter @workspace/hocvu run build"
        )
    print("Đang build giao diện React lần đầu (pnpm --filter @workspace/hocvu run build)...")
    result = subprocess.run([pnpm, "--filter", "@workspace/hocvu", "run", "build"], cwd=str(WORKSPACE_DIR))
    if result.returncode != 0 or not (UI_DIST / "index.html").is_file():
        raise RuntimeError("Build giao diện React thất bại. Kiểm tra Node.js/pnpm và thử chạy lại.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Start HocVu AI locally with the React Voice UI.")
    parser.add_argument("--host", default=os.environ.get("HV_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--open", action="store_true", dest="open_browser")
    parser.add_argument("--semantic", action="store_true", help="Bật tìm kiếm ngữ nghĩa (HV_SEMANTIC=1)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    _load_dotenv(WORKSPACE_DIR / ".env")
    _load_dotenv(APP_DIR / ".env")

    if args.semantic:
        os.environ["HV_SEMANTIC"] = "1"
    else:
        os.environ.setdefault("HV_SEMANTIC", "0")

    os.environ.setdefault("HV_STORAGE_BACKEND", "local")
    os.environ.setdefault("HV_BROWSER_AUTH", "1")

    if not os.environ.get("HV_API_TOKEN"):
        if os.environ.get("REPLIT_DEPLOYMENT") == "1":
            raise RuntimeError("Publishing requires a dedicated HV_API_TOKEN secret.")
        token = secrets.token_urlsafe(18)
        os.environ["HV_API_TOKEN"] = token
        print("=" * 68)
        print("HV_API_TOKEN chưa được đặt trong .env — đã tạo mật khẩu tạm cho phiên local:")
        print(f"  Mật khẩu trang Quản trị (/documents): {token}")
        print("Đặt HV_API_TOKEN trong tệp .env để dùng mật khẩu cố định.")
        print("=" * 68)

    _ensure_react_build()
    os.environ["HV_UI_DIR"] = str(UI_DIST)

    os.chdir(APP_DIR)
    sys.path.insert(0, str(APP_DIR))
    argv = ["manage.py", "serve", "--host", args.host, "--port", str(args.port)]
    if args.open_browser:
        argv.append("--open")
    if args.verbose:
        argv.append("--verbose")
    sys.argv = argv
    runpy.run_path(str(APP_DIR / "manage.py"), run_name="__main__")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nĐã dừng máy chủ HocVu AI.")
    except Exception as exc:
        print(f"\nKhông thể khởi chạy HocVu AI: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
