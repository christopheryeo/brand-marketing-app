import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "sync_mysql.py"
SPEC = importlib.util.spec_from_file_location("sync_mysql", MODULE_PATH)
SYNC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SYNC)


class MysqlSyncTests(unittest.TestCase):
    def test_load_env_supports_repository_keys_without_exposing_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env.local"
            path.write_text("host=db.example\nport=3306\nusername=user\npassword='secret'\ndb name=wiki\n", encoding="utf-8")
            values = SYNC.load_env(path)
        self.assertEqual(values["password"], "secret")
        self.assertEqual(values["db name"], "wiki")

    def test_sql_literal_hex_encodes_untrusted_text(self):
        encoded = SYNC.sql_literal("O'Reilly; DROP TABLE entities")
        self.assertNotIn("DROP TABLE", encoded)
        self.assertTrue(encoded.startswith("CONVERT(X'"))

    def test_validate_local_index_rejects_broken_relationship(self):
        connection = sqlite3.connect(":memory:")
        for table, columns in SYNC.TABLES.items():
            definitions = ",".join(f'"{column}" TEXT' for column in columns)
            connection.execute(f'CREATE TABLE "{table}" ({definitions})')
        connection.execute("INSERT INTO relationships (from_id,relationship_type,to_id) VALUES ('a','links','missing')")
        with self.assertRaisesRegex(RuntimeError, "broken relationships"):
            SYNC.validate_local_index(connection)
        connection.close()


if __name__ == "__main__":
    unittest.main()
