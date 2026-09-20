"""Guarded execution, approvals, and SQLite audit records."""

from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from creditdelta_mcp.guardian import Decision, PolicyEngine


class GuardedExecutor:
    """Enforce Guardian decisions before executing registered local tools."""

    def __init__(self, data_directory: str | Path = ".creditdelta_data") -> None:
        self.data_directory = Path(data_directory).resolve()
        self.reports_directory = self.data_directory / "reports"
        self.trash_directory = self.data_directory / "trash"
        self.outbox_path = self.data_directory / "mock_outbox.jsonl"
        self.database_path = self.data_directory / "guardian.db"
        self.reports_directory.mkdir(parents=True, exist_ok=True)
        self.trash_directory.mkdir(parents=True, exist_ok=True)
        self.policy = PolicyEngine(str(self.reports_directory))
        self._initialize_database()

    def propose(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Evaluate a call, executing only calls that are immediately allowed."""
        result = self.policy.evaluate(tool_name, arguments)
        approval_id = None
        execution = None
        status = result.decision.value

        if result.decision == Decision.ALLOW:
            execution = self._execute(tool_name, arguments)
            status = "EXECUTED"
        elif result.decision == Decision.REQUIRE_APPROVAL:
            approval_id = uuid.uuid4().hex
            self._store_pending(approval_id, tool_name, arguments)

        self._write_audit(tool_name, arguments, result.decision.value, result.risk, status)
        return {
            **result.to_dict(),
            "status": status,
            "approval_id": approval_id,
            "result": execution,
        }

    def resolve_approval(self, approval_id: str, approve: bool) -> dict[str, Any]:
        """Approve or reject one pending action exactly once."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT tool_name, arguments_json, status FROM approvals WHERE id = ?",
                (approval_id,),
            ).fetchone()
            if row is None:
                raise ValueError("Approval ID was not found.")
            tool_name, arguments_json, status = row
        if status != "PENDING":
            raise ValueError(f"Approval has already been resolved as {status}.")

        arguments = json.loads(arguments_json)
        if not approve:
            with self._connect() as connection:
                connection.execute(
                    "UPDATE approvals SET status = ?, resolved_at = ? WHERE id = ?",
                    ("REJECTED", self._now(), approval_id),
                )
            self._write_audit(tool_name, arguments, "REQUIRE_APPROVAL", "high", "REJECTED")
            return {"approval_id": approval_id, "status": "REJECTED", "result": None}

        # Re-evaluate at execution time so changed policies fail closed.
        policy_result = self.policy.evaluate(tool_name, arguments)
        if policy_result.decision == Decision.DENY:
            with self._connect() as connection:
                connection.execute(
                    "UPDATE approvals SET status = ?, resolved_at = ? WHERE id = ?",
                    ("DENIED_BY_POLICY", self._now(), approval_id),
                )
            self._write_audit(tool_name, arguments, "DENY", policy_result.risk, "DENIED_BY_POLICY")
            return {"approval_id": approval_id, "status": "DENIED_BY_POLICY", "result": None}

        execution = self._execute(tool_name, arguments)
        with self._connect() as connection:
            connection.execute(
                "UPDATE approvals SET status = ?, resolved_at = ? WHERE id = ?",
                ("APPROVED_AND_EXECUTED", self._now(), approval_id),
            )
        self._write_audit(
            tool_name, arguments, policy_result.decision.value, policy_result.risk, "APPROVED_AND_EXECUTED"
        )
        return {
            "approval_id": approval_id,
            "status": "APPROVED_AND_EXECUTED",
            "result": execution,
        }

    def list_pending(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, tool_name, arguments_redacted_json, created_at "
                "FROM approvals WHERE status = 'PENDING' ORDER BY created_at DESC"
            ).fetchall()
        return [
            {
                "approval_id": row[0],
                "tool_name": row[1],
                "arguments": json.loads(row[2]),
                "created_at": row[3],
            }
            for row in rows
        ]

    def list_audit(self, limit: int = 20) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise ValueError("Limit must be between 1 and 100.")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT created_at, tool_name, arguments_redacted_json, decision, risk, status "
                "FROM audit_events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "created_at": row[0],
                "tool_name": row[1],
                "arguments": json.loads(row[2]),
                "decision": row[3],
                "risk": row[4],
                "status": row[5],
            }
            for row in rows
        ]

    def _execute(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "read_file":
            path = Path(arguments["path"]).expanduser().resolve()
            return {"path": str(path), "content": path.read_text(encoding="utf-8")}
        if tool_name == "write_file":
            path = Path(arguments["path"]).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            content = str(arguments.get("content", ""))
            path.write_text(content, encoding="utf-8")
            return {"path": str(path), "bytes_written": len(content.encode("utf-8"))}
        if tool_name == "delete_file":
            path = Path(arguments["path"]).expanduser().resolve()
            if not path.is_file():
                raise FileNotFoundError(f"Report does not exist: {path.name}")
            destination = self.trash_directory / f"{uuid.uuid4().hex}_{path.name}"
            shutil.move(str(path), destination)
            return {"original_path": str(path), "recoverable_copy": str(destination)}
        if tool_name == "send_email":
            record = {
                "created_at": self._now(),
                "recipient": str(arguments.get("recipient", "")),
                "subject": str(arguments.get("subject", "CreditDelta report")),
                "message": str(arguments.get("message", "")),
                "simulated": True,
            }
            with self.outbox_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
            return {"status": "SIMULATED_EMAIL_SAVED", "recipient": record["recipient"]}
        raise ValueError(f"No executor is registered for tool '{tool_name}'.")

    def _store_pending(self, approval_id: str, tool_name: str, arguments: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO approvals "
                "(id, tool_name, arguments_json, arguments_redacted_json, status, created_at) "
                "VALUES (?, ?, ?, ?, 'PENDING', ?)",
                (
                    approval_id,
                    tool_name,
                    json.dumps(arguments),
                    json.dumps(self._redact(arguments)),
                    self._now(),
                ),
            )

    def _write_audit(
        self, tool_name: str, arguments: dict[str, Any], decision: str, risk: str, status: str
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO audit_events "
                "(created_at, tool_name, arguments_redacted_json, decision, risk, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (self._now(), tool_name, json.dumps(self._redact(arguments)), decision, risk, status),
            )

    def _redact(self, value: Any, key: str = "") -> Any:
        sensitive_keys = {"password", "secret", "token", "api_key", "authorization"}
        if key.lower() in sensitive_keys:
            return "[REDACTED]"
        if isinstance(value, dict):
            return {item_key: self._redact(item, item_key) for item_key, item in value.items()}
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        if isinstance(value, str) and self.policy._find_sensitive_data(value):
            return "[REDACTED SENSITIVE CONTENT]"
        return value

    def _initialize_database(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY,
                    tool_name TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    arguments_redacted_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    arguments_redacted_json TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    risk TEXT NOT NULL,
                    status TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
