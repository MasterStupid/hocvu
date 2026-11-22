"""Setup checks for a freshly imported project.

Everything here is isolated: a throwaway PostgreSQL cluster in a temporary
directory, an in-memory object store, synthetic credentials and a temporary
data directory. The project's real database, App Storage and secrets are
removed from every child environment, and authentication stays enabled.
"""
import contextlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from packaging.requirements import Requirement

from core.corpus import build_corpus

APP = Path(__file__).resolve().parents[1]
ARTIFACT = APP.parent
WORKSPACE = ARTIFACT.parents[1]
TOKEN = "synthetic-setup-check-only"
BUILT_IN_DOCUMENTS = len(build_corpus())
TABLES = ("hv_turns", "hv_closed_sessions", "hv_session_owners", "hv_document_state", "hv_storage_imports")
# Never let a child process inherit the project's real storage or secrets.
INHERITED = re.compile(
    r"^(DATABASE_URL|PG.*|HV_.*|.*OBJECT.*|SESSION_SECRET|REPLIT_DEPLOYMENT|PORT|BASE_PATH"
    r"|GEMINI_.*|GROQ_.*|OPENAI_.*|ANTHROPIC_.*)$"
)


def isolated_environment(data_dir, **extra):
    environment = {key: value for key, value in os.environ.items() if not INHERITED.match(key)}
    environment.update({
        "HV_DATA_DIR": str(data_dir), "HV_SEMANTIC": "0", "HV_BROWSER_AUTH": "1",
        "HV_API_TOKEN": TOKEN, "PYTHONDONTWRITEBYTECODE": "1",
    })
    environment.update(extra)
    return environment


def manage(environment, *arguments):
    return subprocess.run(
        [sys.executable, "manage.py", *arguments], cwd=APP, env=environment,
        capture_output=True, text=True, timeout=120,
    )


def probe(environment, **options):
    result = subprocess.run(
        [sys.executable, "-m", "tests.helpers.fresh_import_probe", json.dumps(options)],
        cwd=APP, env=environment, capture_output=True, text=True, timeout=180,
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    line = next(line for line in result.stdout.splitlines() if line.startswith("PROBE "))
    return json.loads(line[len("PROBE "):])


class TemporaryDataCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.data = self.root / "data"
        self.ui = self.root / "ui"
        self.ui.mkdir()
        (self.ui / "index.html").write_text("<!doctype html><title>HocVu AI</title>", encoding="utf-8")

    def environment(self, **extra):
        return isolated_environment(self.data, HV_UI_DIR=str(self.ui), **extra)

    def assert_auth_is_enforced(self, result):
        self.assertEqual(result["auth"], {"browser": True, "api_token": True})
        self.assertEqual(result["documents_anonymous"]["status"], 401)
        self.assertEqual(result["documents_wrong_token"]["status"], 401)


class RunButtonTests(unittest.TestCase):
    """Run must open the web app; test commands belong to validation only."""

    def setUp(self):
        self.replit = tomllib.loads((WORKSPACE / ".replit").read_text(encoding="utf-8"))
        self.artifact = tomllib.loads((ARTIFACT / ".replit-artifact" / "artifact.toml").read_text(encoding="utf-8"))
        self.scripts = json.loads((ARTIFACT / "package.json").read_text(encoding="utf-8"))["scripts"]

    def test_run_button_starts_the_web_service_of_the_artifact(self):
        service = self.artifact["services"][0]
        self.assertEqual(self.replit["workflows"]["runButton"], f"{self.artifact['id']}: {service['name']}")
        self.assertEqual(self.artifact["kind"], "web")
        self.assertEqual(service["development"]["run"], "pnpm --filter @workspace/hocvu run dev")
        self.assertEqual(self.artifact["previewPath"], "/")
        self.assertEqual({"/", "/api"}, set(service["paths"]))

    def test_run_button_is_never_a_test_or_validation_workflow(self):
        run_button = self.replit["workflows"]["runButton"]
        checks = set()
        for workflow in self.replit["workflows"].get("workflow", []):
            tasks = workflow.get("tasks", [])
            commands = " ".join(str(task.get("args", "")) for task in tasks)
            if (workflow.get("metadata", {}).get("isValidation")
                    or re.search(r"\b(test|typecheck|vitest|playwright|unittest)\b", commands)):
                checks.add(workflow["name"])
        self.assertTrue(checks, "The validation workflows are expected to stay configured")
        self.assertNotIn(run_button, checks)
        for workflow in self.replit["workflows"].get("workflow", []):
            # A group that launches checks must not be the Run button either.
            launched = {task.get("args") for task in workflow.get("tasks", []) if task.get("task") == "workflow.run"}
            if launched & checks:
                self.assertNotEqual(workflow["name"], run_button)

    def test_dev_command_builds_then_serves_without_running_tests(self):
        dev = self.scripts["dev"]
        self.assertEqual([part.strip() for part in dev.split("&&")], ["pnpm run build", "python run.py"])
        for script in (dev, self.scripts["build"], self.scripts["serve"]):
            self.assertIsNone(re.search(r"vitest|playwright|unittest|typecheck|\btest\b", script), script)
        self.assertIn("vite build", self.scripts["build"])


class DependencySetupTests(unittest.TestCase):
    """A fresh import installs from the lockfiles; report what is missing by name."""

    def test_lockfile_covers_every_frontend_dependency(self):
        package = json.loads((ARTIFACT / "package.json").read_text(encoding="utf-8"))
        declared = {**package.get("dependencies", {}), **package.get("devDependencies", {})}
        lock = (WORKSPACE / "pnpm-lock.yaml").read_text(encoding="utf-8")
        match = re.search(r"^  artifacts/hocvu:\n(.*?)(?=^  \S|\Z)", lock, re.M | re.S)
        self.assertIsNotNone(match, "pnpm-lock.yaml has no entry for artifacts/hocvu; run pnpm install")
        locked = set(re.findall(r"^      '?([^\s':]+(?:/[^\s':]+)?)'?:$", match.group(1), re.M))
        self.assertEqual(sorted(set(declared) - locked), [], "Run pnpm install to update pnpm-lock.yaml")

    def test_frontend_dependencies_are_installed(self):
        package = json.loads((ARTIFACT / "package.json").read_text(encoding="utf-8"))
        declared = {**package.get("dependencies", {}), **package.get("devDependencies", {})}
        missing = [name for name in sorted(declared) if not (ARTIFACT / "node_modules" / name / "package.json").is_file()]
        self.assertEqual(missing, [], "Run pnpm install --frozen-lockfile")

    def test_python_dependencies_are_installed_at_supported_versions(self):
        problems = []
        for line in (APP / "requirements.production.txt").read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            requirement = Requirement(line)
            try:
                installed = importlib.metadata.version(requirement.name)
            except importlib.metadata.PackageNotFoundError:
                problems.append(f"{requirement.name}: not installed")
                continue
            if not requirement.specifier.contains(installed, prereleases=True):
                problems.append(f"{requirement.name}: {installed} does not satisfy {requirement.specifier}")
        self.assertEqual(problems, [], "Install the Python dependencies listed in pyproject.toml")

    def test_python_lockfile_covers_production_dependencies(self):
        lock = tomllib.loads((WORKSPACE / "uv.lock").read_text(encoding="utf-8"))
        locked = {re.sub(r"[-_.]+", "-", package["name"]).lower() for package in lock["package"]}
        wanted = set()
        for line in (APP / "requirements.production.txt").read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                wanted.add(re.sub(r"[-_.]+", "-", Requirement(line).name).lower())
        self.assertEqual(sorted(wanted - locked), [])


class FrontendBuildTests(TemporaryDataCase):
    def test_clean_build_is_served_and_health_is_ready_on_empty_local_storage(self):
        output = self.root / "build"
        environment = {key: value for key, value in os.environ.items() if not INHERITED.match(key)}
        built = subprocess.run(
            ["pnpm", "exec", "vite", "build", "--config", "vite.config.ts", "--outDir", str(output), "--emptyOutDir"],
            cwd=ARTIFACT, env={**environment, "NODE_ENV": "production"},
            capture_output=True, text=True, timeout=240,
        )
        self.assertEqual(built.returncode, 0, built.stdout[-3000:] + built.stderr[-3000:])
        page = (output / "index.html").read_text(encoding="utf-8")
        assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', page)
        self.assertTrue(any(asset.endswith(".js") for asset in assets), page)
        self.assertTrue(any(asset.endswith(".css") for asset in assets), page)
        for asset in assets:
            self.assertTrue((output / asset.lstrip("/")).is_file(), asset)
        script = next(asset for asset in assets if asset.endswith(".js"))

        # The same build, an empty data folder and no index: the first health
        # request must build the index itself and report ready.
        result = probe(
            isolated_environment(self.data, HV_UI_DIR=str(output), HV_STORAGE_BACKEND="local"),
            asset=script,
        )
        self.assertEqual(result["shell"]["status"], 200)
        self.assertIn(script, result["shell"]["body"])
        self.assertEqual(result["asset"]["status"], 200)
        self.assertEqual(result["health"]["status"], 200, result["health"])
        self.assertEqual(result["health"]["body"]["status"], "ok")
        # Only the built-in sample regulations; nothing was imported.
        self.assertEqual(result["health"]["body"]["documents"], BUILT_IN_DOCUMENTS)
        self.assertEqual(result["health"]["body"]["retrieval"], "bm25")
        self.assert_auth_is_enforced(result)
        self.assertEqual(result["documents_admin"]["status"], 200)
        self.assertEqual({item["kind"] for item in result["documents_admin"]["body"]}, {"demo"})
        self.assertTrue((self.data / "index" / "index.json").is_file())


class LauncherTests(unittest.TestCase):
    """run.py must name the missing setup step instead of failing obscurely."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        spec = importlib.util.spec_from_file_location("hocvu_run_under_test", ARTIFACT / "run.py")
        self.run = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.run)
        self.app = self.root / "artifacts" / "hocvu" / "app"
        self.app.mkdir(parents=True)
        (self.app / "manage.py").write_text("", encoding="utf-8")
        self.enterContext(patch.object(self.run, "APP", self.app))
        self.enterContext(patch.object(self.run, "WORKSPACE", self.root))
        self.chdir = self.enterContext(patch.object(self.run.os, "chdir"))
        self.started = self.enterContext(patch.object(self.run.runpy, "run_path"))
        self.enterContext(patch.object(sys, "argv", list(sys.argv)))
        self.enterContext(patch.object(sys, "path", list(sys.path)))

    def build(self):
        ui = self.app.parent / "dist" / "public"
        ui.mkdir(parents=True)
        (ui / "index.html").write_text("<!doctype html>", encoding="utf-8")
        return ui

    @contextlib.contextmanager
    def environment(self, **values):
        with patch.dict(os.environ, values, clear=True):
            yield

    def test_missing_or_invalid_port_is_named(self):
        self.build()
        for values in ({}, {"PORT": ""}, {"PORT": "web"}, {"PORT": "0"}, {"PORT": "70000"}):
            with self.subTest(values=values), self.environment(HV_API_TOKEN=TOKEN, **values):
                with self.assertRaisesRegex(RuntimeError, "PORT"):
                    self.run.main()
        self.started.assert_not_called()

    def test_missing_frontend_build_names_the_build_command(self):
        with self.environment(PORT="5000", HV_API_TOKEN=TOKEN):
            with self.assertRaisesRegex(RuntimeError, r"pnpm --filter @workspace/hocvu run build"):
                self.run.main()
        self.started.assert_not_called()

    def test_wrong_mount_path_is_rejected(self):
        self.build()
        with self.environment(PORT="5000", HV_API_TOKEN=TOKEN, BASE_PATH="/hocvu/"):
            with self.assertRaisesRegex(RuntimeError, "mounted at '/'"):
                self.run.main()

    def test_missing_access_secret_is_named_and_never_defaulted(self):
        self.build()
        with self.environment(PORT="5000"):
            with self.assertRaisesRegex(RuntimeError, "HV_API_TOKEN"):
                self.run.main()
        # A preview-only fallback must not satisfy a published deployment.
        with self.environment(PORT="5000", REPLIT_DEPLOYMENT="1", SESSION_SECRET="preview-only"):
            with self.assertRaisesRegex(RuntimeError, "dedicated HV_API_TOKEN"):
                self.run.main()
        self.started.assert_not_called()

    def test_preview_start_uses_local_storage_and_keeps_authentication(self):
        ui = self.build()
        with self.environment(PORT="5000", SESSION_SECRET="synthetic-preview-secret"):
            self.run.main()
            self.assertEqual(os.environ["HV_UI_DIR"], str(ui))
            self.assertEqual(os.environ["HV_STORAGE_BACKEND"], "local")
            self.assertEqual(os.environ["HV_DATA_DIR"], str(self.root / ".local" / "hocvu-data"))
            self.assertEqual(os.environ["HV_BROWSER_AUTH"], "1")
            self.assertEqual(os.environ["HV_SEMANTIC"], "0")
            self.assertEqual(os.environ["HV_API_TOKEN"], "synthetic-preview-secret")
            # The secret travels in the environment only, never on a command line.
            self.assertEqual(sys.argv, ["manage.py", "serve", "--host", "0.0.0.0", "--port", "5000"])
        self.started.assert_called_once_with(str(self.app / "manage.py"), run_name="__main__")
        self.chdir.assert_called_once_with(self.app)

    def test_published_start_requires_persistent_storage_by_default(self):
        self.build()
        with self.environment(PORT="5000", REPLIT_DEPLOYMENT="1", HV_API_TOKEN=TOKEN):
            self.run.main()
            self.assertEqual(os.environ["HV_STORAGE_BACKEND"], "replit")
            self.assertNotIn("HV_DATA_DIR", os.environ)
        self.started.assert_called_once()

    def test_configured_storage_choice_is_not_overridden(self):
        self.build()
        with self.environment(PORT="5000", HV_API_TOKEN=TOKEN, HV_STORAGE_BACKEND="replit", HV_BROWSER_AUTH="1"):
            self.run.main()
            self.assertEqual(os.environ["HV_STORAGE_BACKEND"], "replit")
            self.assertEqual(os.environ["HV_API_TOKEN"], TOKEN)


class MissingStorageTests(TemporaryDataCase):
    """Persistent mode without its storage must say what is missing, and stop."""

    def test_schema_setup_without_a_database_fails_with_one_clear_line(self):
        result = manage(self.environment(HV_STORAGE_BACKEND="replit"), "init-storage-schema")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr.strip(), "Chưa cấu hình PostgreSQL. Không chuyển sang lưu cục bộ.")
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        self.assertFalse((self.data / "sessions.db").exists())

    def test_schema_setup_never_runs_from_a_published_process(self):
        result = manage(
            self.environment(HV_STORAGE_BACKEND="replit", REPLIT_DEPLOYMENT="1",
                             DATABASE_URL="postgresql://unused@127.0.0.1:1/unused"),
            "init-storage-schema",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Publish", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_unreachable_database_does_not_leak_its_address(self):
        url = "postgresql://setup_user:setup-password@127.0.0.1:1/setup_db?connect_timeout=2"
        result = manage(self.environment(HV_STORAGE_BACKEND="replit", DATABASE_URL=url), "init-storage-schema")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Không kết nối được PostgreSQL", result.stderr)
        for secret in ("setup-password", "setup_user", "setup_db"):
            self.assertNotIn(secret, result.stdout + result.stderr)

    def test_health_names_the_missing_database_while_the_page_still_loads(self):
        result = probe(self.environment(HV_STORAGE_BACKEND="replit", HV_STORAGE_BUCKET_ID="synthetic-bucket"))
        self.assertEqual(result["shell"]["status"], 200)
        self.assertEqual(result["health"]["status"], 503)
        self.assertEqual(result["health"]["body"], {"detail": "Chưa cấu hình PostgreSQL. Không chuyển sang lưu cục bộ."})
        self.assert_auth_is_enforced(result)
        # An administrator sees the same explicit reason, not an empty library.
        self.assertEqual(result["documents_admin"]["status"], 503)
        # Nothing was created locally as a silent substitute.
        self.assertFalse(result["local_history_file"])
        self.assertEqual(result["local_documents"], [])


class LocalPostgres:
    """A private cluster on a Unix socket inside a temporary directory."""

    def __init__(self):
        self.directory = tempfile.TemporaryDirectory(prefix="hvpg")
        root = Path(self.directory.name)
        self.cluster, self.sockets, self.log = root / "cluster", root / "s", root / "postgres.log"
        self.sockets.mkdir()
        self.url = f"postgresql://hocvu_setup@/postgres?host={self.sockets}"

    def start(self):
        environment = {key: value for key, value in os.environ.items() if not INHERITED.match(key)}
        subprocess.run(
            ["initdb", "-D", str(self.cluster), "-U", "hocvu_setup", "-A", "trust", "-E", "UTF8",
             "--locale=C", "--no-sync"],
            env=environment, check=True, capture_output=True, text=True, timeout=120,
        )
        options = f"-c listen_addresses='' -c unix_socket_directories='{self.sockets}' -c fsync=off -c max_connections=20"
        subprocess.run(
            ["pg_ctl", "-D", str(self.cluster), "-l", str(self.log), "-o", options, "-w", "-t", "60", "start"],
            env=environment, check=True, capture_output=True, text=True, timeout=120,
        )

    def stop(self):
        subprocess.run(
            ["pg_ctl", "-D", str(self.cluster), "-m", "immediate", "-w", "stop"],
            capture_output=True, text=True, timeout=60,
        )
        self.directory.cleanup()

    def reset(self):
        import psycopg
        with psycopg.connect(self.url, autocommit=True) as connection:
            connection.execute("DROP SCHEMA public CASCADE")
            connection.execute("CREATE SCHEMA public")

    def query(self, sql):
        import psycopg
        with psycopg.connect(self.url) as connection:
            return connection.execute(sql).fetchall()


class DevelopmentSchemaTests(TemporaryDataCase):
    """Health after `init-storage-schema`, on a database that holds no real data."""

    @classmethod
    def setUpClass(cls):
        if os.environ.get("REPLIT_DEPLOYMENT") == "1":
            raise unittest.SkipTest("Setup checks never run from a published process")
        if not all(shutil.which(tool) for tool in ("initdb", "pg_ctl")):
            raise unittest.SkipTest("PostgreSQL server tools are not installed; cannot start an isolated database")
        cls.postgres = LocalPostgres()
        try:
            cls.postgres.start()
        except Exception:
            cls.postgres.stop()
            raise
        cls.addClassCleanup(cls.postgres.stop)

    def setUp(self):
        super().setUp()
        self.postgres.reset()
        # The isolated database is the only one a child process can reach.
        self.assertNotEqual(self.postgres.url, os.environ.get("DATABASE_URL"))

    def persistent(self, **extra):
        return self.environment(**{
            "HV_STORAGE_BACKEND": "replit", "DATABASE_URL": self.postgres.url,
            "HV_STORAGE_BUCKET_ID": "synthetic-bucket", **extra,
        })

    def tables(self):
        return {row[0] for row in self.postgres.query(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )}

    def test_health_names_missing_tables_before_schema_setup(self):
        result = probe(self.persistent())
        self.assertEqual(result["shell"]["status"], 200)
        self.assertEqual(result["health"]["status"], 503)
        detail = result["health"]["body"]["detail"]
        self.assertIn("Thiếu bảng PostgreSQL", detail)
        self.assertIn("init-storage-schema", detail)
        self.assertEqual(result["documents_admin"]["status"], 503)
        self.assertEqual(self.tables(), set(), "A health request must never create tables")
        self.assert_auth_is_enforced(result)

    def test_schema_setup_is_repeatable_and_imports_no_data(self):
        for _ in range(2):
            result = manage(self.persistent(), "init-storage-schema")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {"schema": "ready", "environment": "development"})
        self.assertEqual(self.tables(), set(TABLES))
        for table in TABLES:
            self.assertEqual(self.postgres.query(f"SELECT count(*) FROM {table}")[0][0], 0, table)
        self.assertFalse((self.data / "sessions.db").exists())

    def test_health_after_schema_setup_asks_for_the_explicit_store_choice(self):
        self.assertEqual(manage(self.persistent(), "init-storage-schema").returncode, 0)
        result = probe(self.persistent())
        self.assertEqual(result["shell"]["status"], 200)
        self.assertEqual(result["health"]["status"], 503)
        detail = result["health"]["body"]["detail"]
        self.assertIn("Chưa khởi tạo kho", detail)
        self.assertIn("init-empty-storage --confirm", detail)
        self.assertIn("migrate-storage", detail)
        self.assertNotIn("hocvu_setup", json.dumps(result, ensure_ascii=False))
        self.assert_auth_is_enforced(result)
        self.assertEqual(result["documents_admin"]["status"], 503)
        # Health did not pick an empty store, or import anything, on its own.
        self.assertEqual(self.postgres.query("SELECT count(*) FROM hv_document_state")[0][0], 0)
        self.assertFalse(result["local_history_file"])
        self.assertEqual(result["local_documents"], [])

    def test_health_is_ready_after_schema_and_confirmed_empty_store(self):
        self.assertEqual(manage(self.persistent(), "init-storage-schema").returncode, 0)
        result = probe(self.persistent(), initialize_empty=True)
        self.assertEqual(result["health"]["status"], 200, result["health"])
        self.assertEqual(result["health"]["body"]["status"], "ok")
        # Only the built-in sample regulations; nothing was imported.
        self.assertEqual(result["health"]["body"]["documents"], BUILT_IN_DOCUMENTS)
        self.assert_auth_is_enforced(result)
        self.assertEqual(result["documents_admin"]["status"], 200)
        self.assertEqual({item["kind"] for item in result["documents_admin"]["body"]}, {"demo"})
        self.assertEqual(self.postgres.query("SELECT revision, manifest FROM hv_document_state"), [(1, [])])
        self.assertEqual(self.postgres.query("SELECT count(*) FROM hv_turns")[0][0], 0)
        # History and documents live in the configured store only.
        self.assertFalse(result["local_history_file"])

    def test_health_names_the_missing_bucket(self):
        self.assertEqual(manage(self.persistent(), "init-storage-schema").returncode, 0)
        result = probe(self.persistent(HV_STORAGE_BUCKET_ID=""))
        self.assertEqual(result["shell"]["status"], 200)
        self.assertEqual(result["health"]["status"], 503)
        self.assertRegex(result["health"]["body"]["detail"], "bucket App Storage|Chưa khởi tạo kho")
        self.assertFalse(result["local_history_file"])
        self.assertEqual(result["local_documents"], [])
        setup = manage(self.persistent(HV_STORAGE_BUCKET_ID=""), "init-empty-storage", "--confirm")
        self.assertEqual(setup.returncode, 1)
        self.assertEqual(
            setup.stderr.strip(),
            "Chưa cấu hình bucket App Storage của dự án. Không lưu thay thế trên ổ đĩa.",
        )
        self.assertEqual(self.postgres.query("SELECT count(*) FROM hv_document_state")[0][0], 0)


if __name__ == "__main__":
    unittest.main()
