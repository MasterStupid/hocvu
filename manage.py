import argparse
import os
import sys
import uuid
from core.settings import load_config, ensure_dirs, INDEX_JSON, EVAL_JSON
from core.engine import build_index, HocVuEngine
from core.evaluation import evaluate
from server.app import main as serve_main

def main():
    parser = argparse.ArgumentParser(description="HocVu AI CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    subparsers.add_parser("doctor", help="Check environment")
    subparsers.add_parser("generate", help="Generate mock data")
    subparsers.add_parser("ingest", help="Build index")
    
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
    ensure_dirs()
    
    if args.command == "doctor":
        print("Checking environment...")
        print(f"Config loaded: {config.summary()}")
        print(f"Index exists: {INDEX_JSON.exists()}")
        
    elif args.command == "generate":
        print("Generating mock data... (Not implemented)")
        
    elif args.command == "ingest":
        print("Building index...")
        build_index(config)
        print("Done.")
        
    elif args.command == "ask":
        if not INDEX_JSON.exists():
            print("Index not found. Run 'ingest' first.")
            return
        engine = HocVuEngine.load(config, INDEX_JSON)
        resp = engine.ask(args.question, str(uuid.uuid4()))
        print(f"\nQ: {resp.query}\nA: {resp.answer}\nConfidence: {resp.confidence:.2f}")
        
    elif args.command == "chat":
        if not INDEX_JSON.exists():
            print("Index not found. Run 'ingest' first.")
            return
        engine = HocVuEngine.load(config, INDEX_JSON)
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
        import json
        with open(INDEX_JSON, 'r', encoding='utf-8') as f:
            data = json.load(f)
        chunks = data.get('chunks', [])
        print(f"Total chunks: {len(chunks)}")
        
    elif args.command == "evaluate":
        if not INDEX_JSON.exists():
            build_index(config)
        report = evaluate(HocVuEngine.load(config, INDEX_JSON), EVAL_JSON)
        print(f"Grounded retrieval accuracy: {report['grounded_retrieval_accuracy']:.1%}")
        print(f"Out-of-scope refusal accuracy: {report['out_of_scope_refusal_accuracy']:.1%}")
        print(f"Detailed report: {EVAL_JSON}")
        
    else:
        parser.print_help()

if __name__ == '__main__':
    main()
