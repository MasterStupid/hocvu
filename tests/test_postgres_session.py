from concurrent.futures import ThreadPoolExecutor
import threading

from core.postgres_session import PostgresSessionStore
from core.session import SessionAccessError, SessionClosedError, LEGACY_API_OWNER
from persistence_helpers import PostgresCase, add_turn, RESPONSE


class PostgresHistoryTests(PostgresCase):
    def test_history_context_and_evidence_survive_another_store(self):
        store = PostgresSessionStore()
        store.authorize("hội thoại / 1?", "owner-a", create=True)
        first_id = add_turn(store, "hội thoại / 1?")
        other = PostgresSessionStore()
        history = other.get_history("hội thoại / 1?", 10, owner="owner-a")
        self.assertEqual(history[0]["id"], first_id)
        for field in ("references", "card", "confidence", "refused", "refusal_reason"):
            self.assertEqual(history[0][field], RESPONSE[field])
        self.assertIn("bảo lưu", other.contextualize("hội thoại / 1?", "Còn điều kiện nào khác?")[0])
        self.assertEqual(other.list_conversations("owner-a")[0]["turn_count"], 1)

    def test_shared_login_does_not_change_ownership_or_claim_legacy(self):
        store = PostgresSessionStore()
        store.authorize("private", "owner-a", create=True)
        add_turn(store, "private")
        for owner in ("owner-b", LEGACY_API_OWNER):
            with self.assertRaises(SessionAccessError):
                store.get_history("private", 10, owner=owner)
        self.assertEqual(store.list_conversations("owner-b"), [])
        add_turn(store, "legacy", response=None)
        self.assertIsNone(store.get_history("legacy", 10, owner=LEGACY_API_OWNER)[0]["references"])
        with self.assertRaises(SessionAccessError):
            store.authorize("legacy", "owner-b", create=True)

    def test_delete_tombstone_blocks_late_saves_across_stores(self):
        store = PostgresSessionStore()
        store.authorize("deleted", "owner-a", create=True)
        add_turn(store, "deleted")
        other = PostgresSessionStore()
        self.assertEqual(other.delete_history("deleted"), 1)
        with self.assertRaises(SessionClosedError):
            add_turn(store, "deleted")
        self.assertTrue(store.is_closed("deleted", owner="owner-a"))
        self.assertEqual(store.list_conversations("owner-a"), [])
        self.assertEqual(other.delete_history("deleted"), 0)

    def test_concurrent_claims_are_serialized(self):
        store = PostgresSessionStore()
        barrier = threading.Barrier(2)
        def claim(owner):
            barrier.wait(timeout=10)
            try:
                store.authorize("new", owner, create=True)
                return True
            except SessionAccessError:
                return False
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(claim, ["owner-a", "owner-b"]))
        self.assertEqual(sorted(results), [False, True])

    def test_bound_session_names_and_turn_order(self):
        store = PostgresSessionStore()
        name = "phiên ' ? % ; DROP TABLE turns;"
        store.authorize(name, "owner-a", create=True)
        ids = [add_turn(store, name) for _ in range(3)]
        self.assertEqual([row["id"] for row in store.get_history(name, 2, owner="owner-a")], ids[-2:])
        store.authorize("second", "owner-a", create=True)
        add_turn(store, "second")
        self.assertEqual([row["session_id"] for row in store.list_conversations("owner-a")], ["second", name])
        self.assertEqual(store.list_conversations("owner-a")[1]["turn_count"], 3)
