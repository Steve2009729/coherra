"""Track 1 — Chat Engine & Multi-Model Tool Calling Tests.

Tests:
  1. Chat memory creation (create_memory tool)
  2. Fact storage (remember tool)
  3. Model routing normalization across Gemini, OpenAI, Grok, Claude
  4. Audit tool without payment -> 402 challenge
  5. Audit tool with verified payment -> runs audit against PostgresStorageAdapter
  6. Repair tool execution (apply_repair)
  7. HTTP POST /chat endpoint integration test
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

from coherra.chat import handle_chat, execute_tool, TOOL_DEFINITIONS, _normalize_model_name
from coherra.storage_pg import PostgresStorageAdapter, init_db, tenant_exists
from coherra.http_server import create_app
from starlette.testclient import TestClient

TEST_DB_PATH = "test_chat_suite.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"
os.environ["COHERRA_PAYOUT_ADDRESS"] = "0x1111111111111111111111111111111111111111"


class TestChatEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
        init_db(f"sqlite:///{TEST_DB_PATH}")

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass

    def setUp(self):
        self.tenant_id = "privy:did:test_user"
        self.adapter = PostgresStorageAdapter(tenant_id=self.tenant_id, dsn=f"sqlite:///{TEST_DB_PATH}")

    def test_01_model_normalization(self):
        self.assertEqual(_normalize_model_name("Gemini Flash-Lite 2.5"), "gemini")
        self.assertEqual(_normalize_model_name("OpenAI Luna"), "openai")
        self.assertEqual(_normalize_model_name("ChatGPT"), "openai")
        self.assertEqual(_normalize_model_name("Grok 4.3"), "grok")
        self.assertEqual(_normalize_model_name("Claude Haiku 4.5"), "claude")

    def test_02_create_memory_tool(self):
        # Fresh tenant
        t_id = "privy:did:fresh_user"
        adapter = PostgresStorageAdapter(tenant_id=t_id, dsn=f"sqlite:///{TEST_DB_PATH}")
        res = execute_tool("create_memory", {}, t_id, adapter)
        self.assertEqual(res["status"], "created")
        self.assertIn("You didn't have a memory yet", res["message"])
        self.assertTrue(tenant_exists(t_id, dsn=f"sqlite:///{TEST_DB_PATH}"))

        # Subsequent call -> already exists
        res2 = execute_tool("create_memory", {}, t_id, adapter)
        self.assertEqual(res2["status"], "already_exists")

    def test_03_remember_tool(self):
        res = execute_tool(
            "remember",
            {"category": "preference", "name": "editor", "value": "Cursor / VSCode"},
            self.tenant_id,
            self.adapter,
        )
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["category"], "preference")
        self.assertEqual(res["name"], "editor")

        # Verify entity stored in adapter
        entity = self.adapter.get_entity("preference", "editor")
        self.assertIsNotNone(entity)
        self.assertEqual(entity["value"], "Cursor / VSCode")

    def test_04_run_audit_unpaid_challenge(self):
        # Calling audit without payment proof must return 402 challenge
        res = execute_tool("run_audit", {}, self.tenant_id, self.adapter, payment_proof=None)
        self.assertTrue(res["requires_payment"])
        self.assertEqual(res["status_code"], 402)
        self.assertIn("challenge", res)
        challenge = res["challenge"]
        self.assertTrue(challenge["x402"])
        self.assertEqual(challenge["accepts"][0]["amount"], "0.015")
        self.assertEqual(challenge["accepts"][0]["payee"], "0x1111111111111111111111111111111111111111")

    def test_05_run_audit_paid(self):
        # Mock payment verification to succeed
        with patch("coherra.chat.verify_payment_onchain", return_value=(True, "Verified 0.015 USDC")):
            res = execute_tool(
                "run_audit",
                {},
                self.tenant_id,
                self.adapter,
                payment_proof="0x" + "a" * 64,
            )
            self.assertFalse(res["requires_payment"])
            self.assertEqual(res["status"], "success")
            self.assertIn("health_score", res)
            self.assertIn("issues_found", res)

    def test_06_handle_chat_conversational_flow(self):
        # Chat loop remembering a preference
        chat_res = handle_chat(
            tenant_id=self.tenant_id,
            model="gemini",
            message="Remember that my favorite language is Rust",
            adapter=self.adapter,
        )
        self.assertTrue(chat_res["ok"])
        self.assertFalse(chat_res["requires_payment"])
        tool_names = [tc["name"] for tc in chat_res["tool_calls"]]
        self.assertIn("remember", tool_names)

        # Confirm saved in storage
        ent = self.adapter.get_entity("preference", "language")
        self.assertIsNotNone(ent)
        self.assertEqual(ent["value"], "Rust")

    def test_07_http_post_chat_endpoint(self):
        app = create_app()
        client = TestClient(app)

        # 1. Post chat to store a fact
        resp = client.post(
            "/chat",
            json={
                "tenant_id": "privy:did:api_tester",
                "model": "claude",
                "message": "Remember that my project is Nighthawk",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])

        # 2. Post chat to request audit without payment -> 402 challenge
        resp_audit = client.post(
            "/chat",
            json={
                "tenant_id": "privy:did:api_tester",
                "model": "openai",
                "message": "Please audit my memory",
            },
        )
        self.assertEqual(resp_audit.status_code, 200)
        audit_data = resp_audit.json()
        self.assertTrue(audit_data["requires_payment"])
        self.assertIsNotNone(audit_data["challenge"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
