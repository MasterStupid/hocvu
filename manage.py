import argparse
import json
import os
import sys
import uuid
from core.settings import load_config, ensure_dirs, INDEX_JSON, EVAL_JSON, DOCS, SERVER_META, RAW, DATA
from core.corpus import build_corpus, build_qa, build_markdown
from core.index_storage import atomic_write, index_write_lock
from core.documents import DocumentError, DocumentRepository
from core.document_recovery import recover_document_dates
from pathlib import Path
from core.engine import build_index, HocVuEngine
from core.evaluation import evaluate
from server.app import main as serve_main


def generate_demo_data(config, output_dir: Path) -> dict:
    """Export the bundled demo corpus without opening the engine or user stores."""
    corpus = build_corpus(seed=config.seed)
    questions = build_qa(corpus, seed=config.seed)
    payloads = {
        "corpus.json": json.dumps(
            [regulation.to_dict() for regulation in corpus], ensure_ascii=False, indent=2,
        ) + "\n",
        "corpus.md": build_markdown(corpus) + "\n",
        "qa_testset.json": json.dumps(
            [question.to_dict() for question in questions], ensure_ascii=False, indent=2,
        ) + "\n",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    with index_write_lock(output_dir / "corpus.json"):
        for filename, text in payloads.items():
            atomic_write(output_dir / filename, text.encode("utf-8"))
    return {
        "seed": config.seed,
        "documents": len(corpus),
        "articles": sum(len(regulation.articles) for regulation in corpus),
        "questions": len(questions),
        "files": [str(output_dir / filename) for filename in payloads],
    }


def main():
    parser = argparse.ArgumentParser(description="HocVu AI CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    subparsers.add_parser("doctor", help="Check environment")
    subparsers.add_parser("generate", help="Export bundled demo regulations and QA data")
    subparsers.add_parser("ingest", help="Build index")
    subparsers.add_parser("backup-storage", help="Create a private verified data backup")
    migrate_parser = subparsers.add_parser("migrate-storage", help="Import a backup into empty Replit storage (development only)")
    migrate_parser.add_argument("--backup", type=Path, help="Use a verified existing HocVu backup")
    migrate_parser.add_argument("--apply", action="store_true")
    migrate_parser.add_argument("--confirm", action="store_true")
    subparsers.add_parser("init-storage-schema", help="Apply PostgreSQL schema in development only; never use in production")

    subparsers.add_parser("audit-document-dates", help="Read-only audit of invalid stored document dates")
    repair_parser = subparsers.add_parser("repair-document-dates", help="Offline recovery of selected invalid document dates")
    repair_parser.add_argument("--plan", type=Path, required=True, help="Administrator's JSON selection and confirmed dates")
    repair_parser.add_argument("--apply", action="store_true", help="Apply the plan (default: read-only dry run)")
    repair_parser.add_argument("--confirm", action="store_true", help="Confirm the dates were checked by an administrator")
    
    ask_parser = subparsers.add_parser("ask", help="Ask a question")
    ask_parser.add_argument("question", help="The question to ask")
    
    subparsers.add_parser("chat", help="Interactive terminal chat")
    
    serve_parser = subparsers.add_parser("serve", help="Start web server")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument("--verbose", action="store_true")
    serve_parser.add_argument("--open", action="store_true", dest="open_browser")
    
    subparsers.add_parser("stats", help="Show index statistics")
    subparsers.add_parser("evaluate", help="Evaluate engine")
    
    args = parser.parse_args()
    config = load_config()
    if args.command in {"backup-storage", "migrate-storage", "init-storage-schema"}:
        from core.persistent_db import StorageUnavailable, connect_database
        from core.storage_backend import document_repository, storage_backend
        from core.storage_transfer import backup_local, backup_persistent, import_backup
        try:
            if args.command == "init-storage-schema":
                if os.environ.get("REPLIT_DEPLOYMENT") == "1":
                    raise StorageUnavailable("Schema production chỉ được áp dụng qua Publish.")
                with connect_database() as connection:
                    connection.execute((Path(__file__).parent / "migrations" / "001_persistent_storage.sql").read_text())
                result = {"schema": "ready", "environment": "development"}
            elif args.command == "backup-storage":
                repository = document_repository(DOCS)
                result = backup_persistent(repository) if storage_backend() == "replit" else backup_local(DATA)
            else:
                if args.apply and SERVER_META.exists():
                    try:
                        pid = int(json.loads(SERVER_META.read_text())["pid"])
                        os.kill(pid, 0)
                    except (ProcessLookupError, ValueError, KeyError, json.JSONDecodeError):
                        pass
                    else:
                        raise StorageUnavailable("Hãy dừng máy chủ trước khi chuyển dữ liệu để không bỏ sót lượt hỏi/tài liệu mới.")
                backup = args.backup
                if backup is None:
                    saved = backup_local(DATA)
                    backup = Path(saved["path"])
                    print(json.dumps({"backup": saved["path"], "documents": saved["documents"], "turns": saved["turns"]}), flush=True)
                result = import_backup(backup, apply=args.apply, confirmed=args.confirm)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except (StorageUnavailable, DocumentError) as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from None
        except Exception:
            print("Thao tác lưu trữ thất bại; không chuyển sang lưu cục bộ và không ghi đè dữ liệu đích.", file=sys.stderr)
            raise SystemExit(1) from None
        return
    if args.command == "generate":
        try:
            result = generate_demo_data(config, RAW)
        except OSError:
            print("Không thể xuất dữ liệu mẫu. Kiểm tra dung lượng và quyền ghi thư mục dữ liệu.", file=sys.stderr)
            raise SystemExit(1) from None
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.command in {"audit-document-dates", "repair-document-dates"}:
        from core.storage_backend import storage_backend
        if storage_backend() == "replit":
            print("Công cụ phục hồi ngày offline chỉ dùng với bản sao cục bộ. Với kho bền vững, sửa ngày qua trang quản lý.", file=sys.stderr)
            raise SystemExit(1)
        repository = DocumentRepository(DOCS, create_dirs=False)
        try:
            # Always report the count first, even if the repair plan is invalid.
            print(json.dumps(repository.audit_document_dates(), ensure_ascii=False), flush=True)
            if args.command == "repair-document-dates":
                try:
                    plan = json.loads(args.plan.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    raise DocumentError("Không đọc được kế hoạch JSON hợp lệ.") from None
                print(json.dumps(recover_document_dates(
                    config, repository, INDEX_JSON, plan,
                    apply=args.apply, confirmed=args.confirm, server_meta=SERVER_META,
                ), ensure_ascii=False))
        except (DocumentError, OSError) as exc:
            # Never echo arbitrary parser/extractor errors or document content.
            message = str(exc) if isinstance(exc, DocumentError) else "Không thể đọc/ghi dữ liệu phục hồi."
            print(message, file=sys.stderr)
            raise SystemExit(1) from None
        except Exception:
            print("Phục hồi thất bại. Giữ máy chủ dừng và kiểm tra tệp gốc/chỉ mục; không ghi nội dung tài liệu vào log.", file=sys.stderr)
            raise SystemExit(1) from None
        return
    ensure_dirs()
    
    if args.command == "doctor":
        print("Checking environment...")
        print(f"Config loaded: {config.summary()}")
        print(f"Index exists: {INDEX_JSON.exists()}")
        
    elif args.command == "ingest":
        print("Building index...")
        from core.storage_backend import storage_backend
        if storage_backend() == "replit":
            HocVuEngine.load_or_build(config, INDEX_JSON).rebuild_index()
        else:
            build_index(config)
        print("Done.")
        
    elif args.command == "ask":
        engine = HocVuEngine.load_or_build(config, INDEX_JSON)
        resp = engine.ask(args.question, str(uuid.uuid4()))
        print(f"\nQ: {resp.query}\nA: {resp.answer}\nConfidence: {resp.confidence:.2f}")
        
    elif args.command == "chat":
        engine = HocVuEngine.load_or_build(config, INDEX_JSON)
        session_id = str(uuid.uuid4())
        print("HocVu AI Chat (type 'exit' to quit)")
        try:
            while True:
                q = input("\nBạn: ")
                if q.lower() in ('exit', 'quit'):
                    break
                resp = engine.ask(q, session_id)
                print(f"AI: {resp.answer}")
        except (EOFError, KeyboardInterrupt):
            print("\nĐã kết thúc hội thoại.")
            
    elif args.command == "serve":
        serve_main(host=args.host, port=args.port, verbose=args.verbose, open_browser=args.open_browser)
        
    elif args.command == "stats":
        if not INDEX_JSON.exists():
            print("Index not found.")
            return
        with open(INDEX_JSON, 'r', encoding='utf-8') as f:
            data = json.load(f)
        chunks = data.get('chunks', [])
        print(f"Total chunks: {len(chunks)}")
        
    elif args.command == "evaluate":
        report = evaluate(HocVuEngine.load_or_build(config, INDEX_JSON), EVAL_JSON)
        print(f"Grounded retrieval accuracy: {report['grounded_retrieval_accuracy']:.1%}")
        print(f"Out-of-scope refusal accuracy: {report['out_of_scope_refusal_accuracy']:.1%}")
        print(f"Detailed report: {EVAL_JSON}")
        
    else:
        parser.print_help()

if __name__ == '__main__':
    main()
