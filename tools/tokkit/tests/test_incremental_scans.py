from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tokkit.db import init_db
from tokkit.ingest_augment_history import scan_augment_history
from tokkit.ingest_claude_code import scan_claude_code
from tokkit.ingest_codex import scan_codex


class IncrementalScanTests(unittest.TestCase):
    def test_codex_incremental_scan_only_reads_appended_lines(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        tz = ZoneInfo("Asia/Shanghai")

        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp)
            session_file = codex_home / "sessions" / "2026" / "05" / "03" / "rollout.jsonl"
            session_file.parent.mkdir(parents=True, exist_ok=True)
            session_file.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "session_meta",
                                "payload": {
                                    "id": "session-1",
                                    "source": "vscode",
                                    "cwd": "/tmp/project",
                                    "originator": "Codex Desktop",
                                    "model_provider": "openai",
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "type": "turn_context",
                                "payload": {
                                    "turn_id": "turn-1",
                                    "model": "gpt-5.5",
                                    "cwd": "/tmp/project",
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "type": "event_msg",
                                "timestamp": "2026-05-03T10:00:00+08:00",
                                "payload": {
                                    "type": "token_count",
                                    "info": {
                                        "last_token_usage": {
                                            "input_tokens": 100,
                                            "output_tokens": 10,
                                            "cached_input_tokens": 40,
                                            "reasoning_output_tokens": 2,
                                            "total_tokens": 110,
                                        }
                                    },
                                },
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            first = scan_codex(conn, codex_home=codex_home, tz=tz)
            second = scan_codex(conn, codex_home=codex_home, tz=tz)

            with session_file.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "type": "event_msg",
                            "timestamp": "2026-05-03T10:05:00+08:00",
                            "payload": {
                                "type": "token_count",
                                "info": {
                                    "last_token_usage": {
                                        "input_tokens": 120,
                                        "output_tokens": 12,
                                        "cached_input_tokens": 60,
                                        "reasoning_output_tokens": 3,
                                        "total_tokens": 132,
                                    }
                                },
                            },
                        }
                    )
                    + "\n"
                )

            third = scan_codex(conn, codex_home=codex_home, tz=tz)

        rows = conn.execute(
            """
            SELECT source, model, total_tokens
            FROM usage_records
            WHERE app = 'codex'
            ORDER BY started_at
            """
        ).fetchall()

        self.assertEqual((first.files_scanned, first.records_seen), (1, 1))
        self.assertEqual((second.files_scanned, second.records_seen), (0, 0))
        self.assertEqual((third.files_scanned, third.records_seen), (1, 1))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["source"], "codex:vscode")
        self.assertEqual(rows[1]["source"], "codex:vscode")
        self.assertEqual(rows[1]["model"], "gpt-5.5")
        self.assertEqual(rows[1]["total_tokens"], 132)

    def test_codex_rewrite_rescans_single_file_and_drops_stale_rows(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        tz = ZoneInfo("Asia/Shanghai")

        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp)
            session_file = codex_home / "sessions" / "2026" / "05" / "03" / "rollout.jsonl"
            session_file.parent.mkdir(parents=True, exist_ok=True)
            session_file.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "session_meta",
                                "payload": {
                                    "id": "session-2",
                                    "source": "cli",
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "type": "turn_context",
                                "payload": {
                                    "turn_id": "turn-1",
                                    "model": "gpt-5.4",
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "type": "event_msg",
                                "timestamp": "2026-05-03T11:00:00+08:00",
                                "payload": {
                                    "type": "token_count",
                                    "info": {
                                        "last_token_usage": {
                                            "input_tokens": 50,
                                            "output_tokens": 5,
                                            "cached_input_tokens": 10,
                                            "reasoning_output_tokens": 1,
                                            "total_tokens": 55,
                                        }
                                    },
                                },
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            scan_codex(conn, codex_home=codex_home, tz=tz)

            session_file.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "session_meta",
                                "payload": {
                                    "id": "session-2",
                                    "source": "cli",
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "type": "turn_context",
                                "payload": {
                                    "turn_id": "turn-2",
                                    "model": "gpt-5.5",
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "type": "event_msg",
                                "timestamp": "2026-05-03T11:10:00+08:00",
                                "payload": {
                                    "type": "token_count",
                                    "info": {
                                        "last_token_usage": {
                                            "input_tokens": 70,
                                            "output_tokens": 7,
                                            "cached_input_tokens": 20,
                                            "reasoning_output_tokens": 2,
                                            "total_tokens": 77,
                                        }
                                    },
                                },
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            rewrite = scan_codex(conn, codex_home=codex_home, tz=tz)

        rows = conn.execute(
            """
            SELECT external_id, model, total_tokens
            FROM usage_records
            WHERE app = 'codex'
            ORDER BY started_at
            """
        ).fetchall()

        self.assertEqual((rewrite.files_scanned, rewrite.records_seen), (1, 1))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["external_id"], "session-2:2026-05-03T11:10:00+08:00")
        self.assertEqual(rows[0]["model"], "gpt-5.5")
        self.assertEqual(rows[0]["total_tokens"], 77)

    def test_claude_incremental_scan_updates_only_new_or_better_records(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        tz = ZoneInfo("Asia/Shanghai")

        with tempfile.TemporaryDirectory() as tmp:
            claude_home = Path(tmp)
            session_file = claude_home / "projects" / "demo" / "session-1.jsonl"
            session_file.parent.mkdir(parents=True, exist_ok=True)
            session_file.write_text(
                json.dumps(
                    {
                        "type": "assistant",
                        "timestamp": "2026-05-03T12:00:00+08:00",
                        "cwd": "/tmp/project",
                        "entrypoint": "cli",
                        "uuid": "evt-1",
                        "message": {
                            "id": "msg-1",
                            "model": "claude-sonnet-4-6",
                            "type": "assistant",
                            "usage": {
                                "input_tokens": 100,
                                "cache_creation_input_tokens": 20,
                                "cache_read_input_tokens": 40,
                                "output_tokens": 10,
                            },
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            first = scan_claude_code(conn, claude_home=claude_home, tz=tz)
            second = scan_claude_code(conn, claude_home=claude_home, tz=tz)

            with session_file.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "type": "assistant",
                            "timestamp": "2026-05-03T12:02:00+08:00",
                            "cwd": "/tmp/project",
                            "entrypoint": "cli",
                            "uuid": "evt-2",
                            "message": {
                                "id": "msg-1",
                                "model": "claude-sonnet-4-6",
                                "type": "assistant",
                                "usage": {
                                    "input_tokens": 120,
                                    "cache_creation_input_tokens": 30,
                                    "cache_read_input_tokens": 60,
                                    "output_tokens": 20,
                                },
                            },
                        }
                    )
                    + "\n"
                )

            third = scan_claude_code(conn, claude_home=claude_home, tz=tz)

        rows = conn.execute(
            """
            SELECT source, external_id, input_tokens, cached_input_tokens, output_tokens, total_tokens
            FROM usage_records
            WHERE app = 'claude-code'
            ORDER BY started_at
            """
        ).fetchall()

        self.assertEqual((first.files_scanned, first.records_seen), (1, 1))
        self.assertEqual((second.files_scanned, second.records_seen), (0, 0))
        self.assertEqual((third.files_scanned, third.records_seen), (1, 1))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "claude-code:cli")
        self.assertEqual(rows[0]["external_id"], "session-1:msg-1")
        self.assertEqual(rows[0]["input_tokens"], 150)
        self.assertEqual(rows[0]["cached_input_tokens"], 60)
        self.assertEqual(rows[0]["output_tokens"], 20)
        self.assertEqual(rows[0]["total_tokens"], 230)

    def test_augment_history_reuses_checkpoint_cache_after_first_scan(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        tz = ZoneInfo("Asia/Shanghai")
        request_id = "11111111-1111-1111-1111-111111111111"

        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            augment_root = workspace_root / "demo" / "Augment.vscode-augment"
            selection_file = augment_root / "augment-global-state" / "requestIdSelectionMetadata.json"
            shard_file = augment_root / "augment-user-assets" / "agent-edits" / "shards" / "one.json"
            checkpoint_dir = augment_root / "augment-user-assets" / "checkpoint-documents" / "alpha"
            checkpoint_one = checkpoint_dir / f"doc-1746273600000-{request_id}.json"
            checkpoint_two = checkpoint_dir / f"doc-1746273660000-{request_id}.json"

            selection_file.parent.mkdir(parents=True, exist_ok=True)
            shard_file.parent.mkdir(parents=True, exist_ok=True)
            checkpoint_dir.mkdir(parents=True, exist_ok=True)

            selection_file.write_text(
                json.dumps(
                    [
                        [
                            request_id,
                            {
                                "value": {
                                    "selectedCode": "print('hello')",
                                    "prefix": "def run():\n",
                                    "suffix": "\nrun()\n",
                                    "path": "/tmp/project/app.py",
                                    "language": "python",
                                }
                            },
                        ]
                    ]
                ),
                encoding="utf-8",
            )
            shard_file.write_text(
                json.dumps(
                    {
                        "checkpoints": {
                            "a": [
                                {
                                    "sourceToolCallRequestId": request_id,
                                    "timestamp": 1746273600000,
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            checkpoint_one.write_text(
                json.dumps(
                    {
                        "originalCode": "print('hello')\n",
                        "modifiedCode": "print('hello')\nprint('world')\n",
                        "path": {
                            "rootPath": "/tmp/project",
                            "relPath": "app.py",
                        },
                    }
                ),
                encoding="utf-8",
            )

            first = scan_augment_history(conn, workspace_storage_root=workspace_root, tz=tz)
            total_after_first = conn.execute(
                """
                SELECT total_tokens
                FROM usage_records
                WHERE app = 'augment' AND external_id = ?
                """,
                (f"history:{request_id}",),
            ).fetchone()["total_tokens"]

            second = scan_augment_history(conn, workspace_storage_root=workspace_root, tz=tz)

            checkpoint_two.write_text(
                json.dumps(
                    {
                        "originalCode": "print('hello')\nprint('world')\n",
                        "modifiedCode": "print('hello')\nprint('world')\nprint('again')\n",
                        "path": {
                            "rootPath": "/tmp/project",
                            "relPath": "app.py",
                        },
                    }
                ),
                encoding="utf-8",
            )
            third = scan_augment_history(conn, workspace_storage_root=workspace_root, tz=tz)
            total_after_third = conn.execute(
                """
                SELECT total_tokens
                FROM usage_records
                WHERE app = 'augment' AND external_id = ?
                """,
                (f"history:{request_id}",),
            ).fetchone()["total_tokens"]

        self.assertEqual((first.checkpoint_files_seen, first.request_records_emitted), (1, 1))
        self.assertEqual(second.checkpoint_files_seen, 0)
        self.assertEqual(third.checkpoint_files_seen, 1)
        self.assertGreater(total_after_first, 0)
        self.assertGreater(total_after_third, total_after_first)


if __name__ == "__main__":
    unittest.main()
