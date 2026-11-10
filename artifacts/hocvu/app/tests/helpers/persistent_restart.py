"""Child process used by the opt-in real PostgreSQL/App Storage restart check."""
import json
from pathlib import Path
import sys
import zipfile

from core.engine import HocVuEngine
from core.persistent_documents import DocumentState
from core.session import SessionAccessError, SessionClosedError
from core.settings import DATA, INDEX_JSON, AppConfig
from core.storage_transfer import backup_persistent
from tests.test_documents import make_subject_docx
from tests.persistence_helpers import RESPONSE, add_turn


def main():
    phase, result_file = sys.argv[1:]
    if phase == "write":
        DocumentState().initialize_empty(confirmed=True)
    engine = HocVuEngine.load_or_build(AppConfig(semantic_enabled=False), INDEX_JSON)
    assert engine.storage_status()["persistent"]
    if phase == "write":
        content = make_subject_docx([
            ("Quy chế kiểm chứng lưu trữ", 1),
            ("Điều 1. Hỗ trợ nghiên cứu", 2),
            ("Sinh viên nghiên cứu được hỗ trợ 700000 đồng mỗi tháng.", 0),
        ])
        entry = engine.add_document("kiem-chung.docx", content, metadata={"document_date": "2020-01-01"})
        engine.session.authorize("persistent-check", "owner-a", create=True)
        add_turn(engine.session, "persistent-check")
        engine.session.authorize("deleted-check", "owner-a", create=True)
        add_turn(engine.session, "deleted-check")
        engine.session.delete_history("deleted-check")
        result = {"entry": entry, "content_hex": content.hex()}
        Path(result_file).write_text(json.dumps(result), encoding="utf-8")
    else:
        saved = json.loads(Path(result_file).read_text(encoding="utf-8"))
        # A new process and a new empty cache must recover real cloud bytes.
        entry = saved["entry"]
        assert engine.documents.list()[0]["id"] == entry["id"]
        assert (engine.documents.root / entry["stored_name"]).read_bytes() == bytes.fromhex(saved["content_hex"])
        assert "700000" in engine.document_text(entry["id"])["text"]
        assert any(hit.chunk.rid == entry["rid"] for hit in engine.searcher.search("hỗ trợ nghiên cứu", 10, "2026-01-01"))
        history = engine.history("persistent-check", owner="owner-a")
        assert len(history) == 1
        for field in ("references", "card", "confidence", "refused", "refusal_reason"):
            assert history[0][field] == RESPONSE[field]
        try:
            engine.history("persistent-check", owner="owner-b")
        except SessionAccessError:
            pass
        else:
            raise AssertionError("Another owner read private history")
        try:
            add_turn(engine.session, "deleted-check")
        except SessionClosedError:
            pass
        else:
            raise AssertionError("A deleted conversation accepted a new turn")
        backup = backup_persistent(engine.documents, output_dir=DATA / "backups")
        remote = engine.documents.blobs.client.download_as_bytes(backup["backup_key"])
        assert remote == Path(backup["path"]).read_bytes()
        with zipfile.ZipFile(backup["path"]) as archive:
            assert len(json.loads(archive.read("history.json"))["turns"]) == 1
            assert archive.read("documents/" + entry["stored_name"]) == bytes.fromhex(saved["content_hex"])
        assert Path(backup["path"]).stat().st_mode & 0o777 == 0o600
    assert not (DATA / "sessions.db").exists()
    print("Persistent storage phase verified:", phase)


if __name__ == "__main__":
    main()
