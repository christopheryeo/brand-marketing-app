#!/usr/bin/env python3
"""Synchronise the generated Wiki SQLite index to a MySQL query replica."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
SGT = dt.timezone(dt.timedelta(hours=8))
SCHEMA_VERSION = 1
TABLES: dict[str, tuple[str, ...]] = {
    "entities": ("id", "type", "name", "path", "data_json"),
    "aliases": ("entity_id", "alias"),
    "email_addresses": ("entity_id", "email"),
    "relationships": ("from_id", "relationship_type", "to_id", "role", "status", "source_id", "locator"),
    "source_refs": ("entity_id", "source_id", "locator", "evidence_hash"),
    "business_outcomes": ("entity_id", "outcome_type", "description", "owner_id", "due_at", "status", "source_id", "locator"),
    "fulltext": ("entity_id", "entity_type", "name", "content"),
}
MYSQL_TABLES = {**{name: name for name in TABLES if name != "fulltext"}, "fulltext": "fulltext_index"}


def now_sgt() -> str:
    return dt.datetime.now(SGT).isoformat(timespec="seconds")


def default_run_id() -> str:
    return dt.datetime.now(SGT).strftime("%Y%m%dT%H%M%S-mysql-sync")


def load_env(path: Path) -> dict[str, str]:
    """Read the repository's simple key=value file without sourcing it."""
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    required = ("host", "port", "username", "password", "db name")
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise ValueError(f"Missing database settings in {path.name}: {', '.join(missing)}")
    try:
        port = int(values["port"])
    except ValueError as error:
        raise ValueError("Database port must be an integer") from error
    if not 1 <= port <= 65535:
        raise ValueError("Database port is outside the valid range")
    return values


def sql_literal(value: Any) -> str:
    """Encode text as hex so source content cannot alter generated SQL."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    encoded = str(value).encode("utf-8")
    if not encoded:
        return "''"
    return f"CONVERT(X'{encoded.hex()}' USING utf8mb4)"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_local_index(connection: sqlite3.Connection) -> dict[str, int]:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise RuntimeError(f"SQLite integrity check failed: {integrity}")
    existing = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    missing = sorted(set(TABLES) - existing)
    if missing:
        raise RuntimeError(f"SQLite index is missing tables: {', '.join(missing)}")
    broken = connection.execute(
        "SELECT COUNT(*) FROM relationships r LEFT JOIN entities e ON r.to_id=e.id WHERE e.id IS NULL"
    ).fetchone()[0]
    if broken:
        raise RuntimeError(f"SQLite index has {broken} broken relationships")
    return {table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in TABLES}


def schema_sql() -> str:
    return """
SET NAMES utf8mb4;
SET time_zone = '+08:00';
SET SESSION sql_mode = 'STRICT_ALL_TABLES,NO_ENGINE_SUBSTITUTION';
CREATE TABLE IF NOT EXISTS `entities` (
  `id` VARCHAR(255) NOT NULL, `type` VARCHAR(128) NOT NULL, `name` TEXT NULL,
  `path` VARCHAR(1024) NOT NULL, `data_json` JSON NOT NULL,
  PRIMARY KEY (`id`), KEY `idx_entities_type` (`type`), KEY `idx_entities_path` (`path`(255))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS `aliases` (
  `entity_id` VARCHAR(255) NOT NULL, `alias` TEXT NULL,
  KEY `idx_aliases_entity` (`entity_id`), KEY `idx_aliases_alias` (`alias`(255))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS `email_addresses` (
  `entity_id` VARCHAR(255) NOT NULL, `email` VARCHAR(320) NULL,
  KEY `idx_email_entity` (`entity_id`), KEY `idx_email_value` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS `relationships` (
  `from_id` VARCHAR(255) NOT NULL, `relationship_type` VARCHAR(128) NOT NULL,
  `to_id` VARCHAR(255) NOT NULL, `role` TEXT NULL, `status` VARCHAR(128) NULL,
  `source_id` VARCHAR(255) NULL, `locator` TEXT NULL,
  KEY `idx_relationship_from` (`from_id`), KEY `idx_relationship_to` (`to_id`),
  KEY `idx_relationship_type` (`relationship_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS `source_refs` (
  `entity_id` VARCHAR(255) NOT NULL, `source_id` VARCHAR(255) NULL,
  `locator` TEXT NULL, `evidence_hash` VARCHAR(255) NULL,
  KEY `idx_source_refs_entity` (`entity_id`), KEY `idx_source_refs_source` (`source_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS `business_outcomes` (
  `entity_id` VARCHAR(255) NOT NULL, `outcome_type` VARCHAR(128) NULL,
  `description` LONGTEXT NULL, `owner_id` VARCHAR(255) NULL, `due_at` VARCHAR(128) NULL,
  `status` VARCHAR(128) NULL, `source_id` VARCHAR(255) NULL, `locator` TEXT NULL,
  KEY `idx_outcomes_entity` (`entity_id`), KEY `idx_outcomes_owner` (`owner_id`),
  KEY `idx_outcomes_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS `fulltext_index` (
  `entity_id` VARCHAR(255) NOT NULL, `entity_type` VARCHAR(128) NOT NULL,
  `name` TEXT NULL, `content` LONGTEXT NOT NULL,
  PRIMARY KEY (`entity_id`), KEY `idx_fulltext_type` (`entity_type`),
  FULLTEXT KEY `ft_name_content` (`name`,`content`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS `sync_metadata` (
  `replica_id` TINYINT NOT NULL, `schema_version` INT NOT NULL,
  `synced_at_sgt` DATETIME(6) NOT NULL, `source_sha256` CHAR(64) NOT NULL,
  `row_counts` JSON NOT NULL, PRIMARY KEY (`replica_id`),
  CONSTRAINT `chk_single_replica` CHECK (`replica_id` = 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
""".strip()


def insert_statements(
    connection: sqlite3.Connection,
    source_table: str,
    target_table: str,
    columns: Sequence[str],
    max_chars: int = 4_000_000,
) -> Iterable[str]:
    quoted_columns = ",".join(f"`{column}`" for column in columns)
    prefix = f"INSERT INTO `{target_table}` ({quoted_columns}) VALUES\n"
    cursor = connection.execute(f'SELECT {",".join(columns)} FROM "{source_table}"')
    batch: list[str] = []
    batch_chars = len(prefix)
    for row in cursor:
        encoded = "(" + ",".join(sql_literal(value) for value in row) + ")"
        if batch and batch_chars + len(encoded) + 2 > max_chars:
            yield prefix + ",\n".join(batch) + ";\n"
            batch = []
            batch_chars = len(prefix)
        batch.append(encoded)
        batch_chars += len(encoded) + 2
    if batch:
        yield prefix + ",\n".join(batch) + ";\n"


def mysql_command(settings: dict[str, str], mysql_binary: str) -> list[str]:
    return [
        mysql_binary,
        "--connect-timeout=10",
        "--protocol=TCP",
        "--default-character-set=utf8mb4",
        "--batch",
        "--skip-column-names",
        "--raw",
        "--host", settings["host"],
        "--port", settings["port"],
        "--user", settings["username"],
        "--database", settings["db name"],
    ]


def sync(sqlite_path: Path, env_path: Path, mysql_binary: str) -> dict[str, Any]:
    settings = load_env(env_path)
    resolved_mysql = shutil.which(mysql_binary)
    if not resolved_mysql:
        raise RuntimeError(f"MySQL client not found: {mysql_binary}")

    source_hash = sha256_file(sqlite_path)
    sqlite_connection = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    counts = validate_local_index(sqlite_connection)
    started_at = now_sgt()
    mysql_env = os.environ.copy()
    mysql_env["MYSQL_PWD"] = settings["password"]
    process = subprocess.Popen(
        mysql_command(settings, resolved_mysql),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=mysql_env,
    )
    assert process.stdin is not None
    try:
        process.stdin.write(schema_sql() + "\nSTART TRANSACTION;\n")
        for target in ("aliases", "email_addresses", "relationships", "source_refs", "business_outcomes", "fulltext_index", "entities"):
            process.stdin.write(f"DELETE FROM `{target}`;\n")
        process.stdin.write("DELETE FROM `sync_metadata`;\n")
        for source_table, columns in TABLES.items():
            target_table = MYSQL_TABLES[source_table]
            for statement in insert_statements(sqlite_connection, source_table, target_table, columns):
                process.stdin.write(statement)
        synced_sql = dt.datetime.now(SGT).strftime("%Y-%m-%d %H:%M:%S.%f")
        counts_json = json.dumps(counts, sort_keys=True, separators=(",", ":"))
        process.stdin.write(
            "INSERT INTO `sync_metadata` (`replica_id`,`schema_version`,`synced_at_sgt`,`source_sha256`,`row_counts`) VALUES "
            f"(1,{SCHEMA_VERSION},{sql_literal(synced_sql)},{sql_literal(source_hash)},{sql_literal(counts_json)});\n"
        )
        assertions = [f"(SELECT COUNT(*) FROM `{MYSQL_TABLES[name]}`)={count}" for name, count in counts.items()]
        assertions.append("(SELECT COUNT(*) FROM `relationships` r LEFT JOIN `entities` e ON r.`to_id`=e.`id` WHERE e.`id` IS NULL)=0")
        process.stdin.write(
            "CREATE TEMPORARY TABLE `_wiki_sync_assert` (`ok` TINYINT NOT NULL CHECK (`ok`=1));\n"
            f"INSERT INTO `_wiki_sync_assert` VALUES ({' AND '.join(assertions)});\n"
            "DROP TEMPORARY TABLE `_wiki_sync_assert`;\nCOMMIT;\n"
        )
        verification_pairs = ",".join(
            f"'{name}',(SELECT COUNT(*) FROM `{MYSQL_TABLES[name]}`)" for name in TABLES
        )
        process.stdin.write(f"SELECT CONCAT('__VERIFY__', JSON_OBJECT({verification_pairs}));\n")
        process.stdin.close()
        stdout = process.stdout.read() if process.stdout else ""
        stderr = process.stderr.read() if process.stderr else ""
        return_code = process.wait()
    except Exception:
        process.kill()
        process.wait()
        raise
    finally:
        sqlite_connection.close()
        mysql_env["MYSQL_PWD"] = ""

    if return_code != 0:
        safe_error = stderr.strip() or "MySQL client exited without an error message"
        raise RuntimeError(f"MySQL sync failed and was not committed: {safe_error}")
    verification_line = next((line for line in stdout.splitlines() if line.startswith("__VERIFY__")), None)
    if not verification_line:
        raise RuntimeError("MySQL sync completed without a verification result")
    remote_counts = json.loads(verification_line.removeprefix("__VERIFY__"))
    if remote_counts != counts:
        raise RuntimeError(f"Post-sync count mismatch: expected {counts}, received {remote_counts}")
    return {
        "direction": "wiki-to-mysql",
        "status": "committed",
        "schemaVersion": SCHEMA_VERSION,
        "startedAt": started_at,
        "completedAt": now_sgt(),
        "source": str(sqlite_path.relative_to(ROOT) if sqlite_path.is_relative_to(ROOT) else sqlite_path),
        "sourceSha256": source_hash,
        "rowCounts": counts,
        "totalRows": sum(counts.values()),
        "integrity": {"sqlite": "ok", "mysqlCounts": "matched", "brokenRelationships": 0},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", type=Path, default=ROOT / "index" / "wiki.sqlite")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.local")
    parser.add_argument("--mysql-bin", default="mysql")
    parser.add_argument("--run-id", default=default_run_id())
    parser.add_argument("--check-only", action="store_true", help="Validate local inputs without connecting or writing to MySQL")
    args = parser.parse_args()
    run_dir = ROOT / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    try:
        settings = load_env(args.env_file)
        with sqlite3.connect(f"file:{args.sqlite}?mode=ro", uri=True) as connection:
            counts = validate_local_index(connection)
        if args.check_only:
            result: dict[str, Any] = {
                "runId": args.run_id,
                "status": "check-only",
                "checkedAt": now_sgt(),
                "source": str(args.sqlite),
                "rowCounts": counts,
                "databaseConfig": {"present": True, "portValid": bool(settings["port"])},
            }
        else:
            result = {"runId": args.run_id, **sync(args.sqlite, args.env_file, args.mysql_bin)}
        receipt = run_dir / "mysql-sync-receipt.json"
        receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        failure = {
            "runId": args.run_id,
            "status": "failed",
            "failedAt": now_sgt(),
            "error": f"{type(error).__name__}: {error}",
        }
        (run_dir / "mysql-sync-failure.json").write_text(
            json.dumps(failure, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(failure, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
