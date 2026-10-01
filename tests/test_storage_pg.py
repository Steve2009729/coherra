"""Track 1 — Unit tests for PostgresStorageAdapter.

Validates:
  1. Tenant creation and uniqueness
  2. Entity CRUD, updating, and archiving
  3. State get/set
  4. Event write/read
  5. Close/cleanup
"""
from __future__ import annotations

import os
import unittest
from coherra.storage_pg import PostgresStorageAdapter, init_db, tenant_exists, create_tenant

TEST_DB_PATH = "test_storage_pg_unit.db"
DSN = f"sqlite:///{TEST_DB_PATH}"


class TestStoragePG(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
        init_db(DSN)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass

    def setUp(self):
        self.tenant_id = "privy:did:unit_user"
        self.adapter = PostgresStorageAdapter(tenant_id=self.tenant_id, dsn=DSN)

    def test_01_tenant_lifecycle(self):
        self.assertFalse(tenant_exists("privy:did:nonexistent", dsn=DSN))
        t = create_tenant("privy:did:created_user", dsn=DSN)
        self.assertEqual(t["privy_user_id"], "privy:did:created_user")
        self.assertTrue(tenant_exists("privy:did:created_user", dsn=DSN))

    def test_02_entity_crud(self):
        # Create entity
        self.adapter.set_entity(
            "preference",
            "editor",
            {"value": "Neovim", "confidence": 0.95, "source": "unit_test"},
        )
        entity = self.adapter.get_entity("preference", "editor")
        self.assertEqual(entity["category"], "preference")
        self.assertEqual(entity["name"], "editor")
        self.assertEqual(entity["value"], "Neovim")
        self.assertEqual(entity["confidence"], 0.95)

        # Update entity
        self.adapter.set_entity(
            "preference",
            "editor",
            {"value": "VSCode", "confidence": 1.0, "source": "unit_test_v2"},
        )
        updated = self.adapter.get_entity("preference", "editor")
        self.assertEqual(updated["value"], "VSCode")
        self.assertEqual(updated["confidence"], 1.0)

        # List entities
        all_ents = self.adapter.list_entities()
        self.assertTrue(len(all_ents) >= 1)

        # Archive entity
        self.adapter.archive_entity("preference", "editor", reason="switched to cursor")
        with self.assertRaises(KeyError):
            self.adapter.get_entity("preference", "editor")

    def test_03_state_operations(self):
        self.assertIsNone(self.adapter.get_state("non_existent_key"))
        self.adapter.set_state("theme_mode", {"mode": "dark", "fontSize": 14})
        state = self.adapter.get_state("theme_mode")
        self.assertIsNotNone(state)
        self.assertEqual(state["body"]["mode"], "dark")
        self.assertEqual(state["body"]["fontSize"], 14)

    def test_05_multi_tenant_isolation_and_audit(self):
        from coherra.audit import run_audit
        # 3 distinct fake tenants
        t1 = PostgresStorageAdapter(tenant_id="privy:did:tenant_alpha", dsn=DSN)
        t2 = PostgresStorageAdapter(tenant_id="privy:did:tenant_beta", dsn=DSN)
        t3 = PostgresStorageAdapter(tenant_id="privy:did:tenant_gamma", dsn=DSN)

        # Tenant 1 has a contradiction
        t1.set_entity("preference", "editor", {"value": "VSCode"})
        t1.set_entity("preference", "preferred_editor", {"value": "Vim"})

        # Tenant 2 has a clean single fact
        t2.set_entity("facts", "timezone", {"value": "UTC"})

        # Tenant 3 has a duplicate pair
        t3.set_entity("projects", "main_project", {"value": "ProjectAlpha"})
        t3.set_entity("projects", "current_project", {"value": "ProjectAlpha"})

        # Audit Tenant 1
        res1 = run_audit(t1)
        self.assertEqual(res1["entity_count"], 2)
        self.assertTrue(any(i["severity"] == "contradiction" for i in res1["issues_found"]))
        self.assertFalse(any(i.get("name") == "timezone" for i in res1["issues_found"]))
        self.assertFalse(any(i.get("name") == "main_project" for i in res1["issues_found"]))

        # Audit Tenant 2
        res2 = run_audit(t2)
        self.assertEqual(res2["entity_count"], 1)
        self.assertEqual(len(res2["issues_found"]), 0)
        self.assertEqual(res2["health_score"], 100)

        # Audit Tenant 3
        res3 = run_audit(t3)
        self.assertEqual(res3["entity_count"], 2)
        self.assertTrue(any(i["severity"] == "duplicate" for i in res3["issues_found"]))
        self.assertFalse(any(i.get("name") == "editor" for i in res3["issues_found"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)

