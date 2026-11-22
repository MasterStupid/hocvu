"""Run the existing HocVu application as a single Replit artifact service."""
from __future__ import annotations

import os
from pathlib import Path
import runpy
import sys

APP = Path(__file__).resolve().parent / "app"
WORKSPACE = APP.parents[2]


def main() -> None:
    try:
        port = int(os.environ.get("PORT", ""))
    except ValueError:
        port = 0
    if not 0 < port < 65536:
        raise RuntimeError("PORT must be set to a number between 1 and 65535.")
    if os.environ.get("BASE_PATH", "/") != "/":
        raise RuntimeError("This imported application must be mounted at '/'.")

    ui = APP.parent / "dist" / "public"
    if not (ui / "index.html").is_file():
        raise RuntimeError("React build is missing. Run pnpm --filter @workspace/hocvu run build.")
    os.environ["HV_UI_DIR"] = str(ui)

    published = os.environ.get("REPLIT_DEPLOYMENT") == "1"
    os.environ.setdefault("HV_SEMANTIC", "0")
    os.environ.setdefault("HV_BROWSER_AUTH", "1")
    os.environ.setdefault("HV_STORAGE_BACKEND", "replit" if published else "local")
    if not published:
        os.environ.setdefault("HV_DATA_DIR", str(WORKSPACE / ".local" / "hocvu-data"))

    # Reuse the existing server-side secret for preview startup only. Never
    # expose it to the browser, logs, command arguments, or source control.
    # A dedicated HV_API_TOKEN always takes precedence; publishing requires it.
    if not published and not os.environ.get("HV_API_TOKEN"):
        secret = os.environ.get("SESSION_SECRET")
        if not secret:
            raise RuntimeError("Set HV_API_TOKEN in Replit Secrets before starting.")
        os.environ["HV_API_TOKEN"] = secret
    if not os.environ.get("HV_API_TOKEN"):
        raise RuntimeError("Publishing requires a dedicated HV_API_TOKEN secret.")

    os.chdir(APP)
    sys.path.insert(0, str(APP))
    sys.argv = ["manage.py", "serve", "--host", "0.0.0.0", "--port", str(port)]
    runpy.run_path(str(APP / "manage.py"), run_name="__main__")


if __name__ == "__main__":
    main()
