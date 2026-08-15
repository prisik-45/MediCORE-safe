import unittest
from types import SimpleNamespace
from uuid import uuid4

from backend.app.services.sql_executor import validate_readonly_sql, execute_readonly_sql
from backend.app.mcp.tools import (
    execute_readonly_sql_tool,
    get_structured_query_results_tool,
    perform_catalog_update_tool
)


class SQLExecutorMCPTest(unittest.TestCase):
    def test_validate_readonly_sql_accepts_valid_select(self) -> None:
        query = "SELECT ingredient_name, price_per_unit FROM catalog_items WHERE ingredient_name ILIKE '%citric acid%'"
        validated = validate_readonly_sql(query)
        self.assertTrue(validated.startswith("SELECT"))
        self.assertIn("LIMIT 100", validated)

    def test_validate_readonly_sql_rejects_with_clause(self) -> None:
        query = "WITH recent_items AS (SELECT ingredient_name FROM catalog_items) SELECT ingredient_name FROM recent_items"
        with self.assertRaises(ValueError):
            validate_readonly_sql(query)

    def test_validate_readonly_sql_rejects_wildcard_select(self) -> None:
        query = "SELECT * FROM catalog_items WHERE tenant_id = :tenant_id"
        with self.assertRaises(ValueError):
            validate_readonly_sql(query, require_tenant=True)

    def test_validate_readonly_sql_allows_count_star(self) -> None:
        query = "SELECT count(*) AS item_count FROM catalog_items WHERE tenant_id = :tenant_id"
        validated = validate_readonly_sql(query, require_tenant=True)
        self.assertIn("count(*)", validated)

    def test_validate_readonly_sql_rejects_insert(self) -> None:
        query = "INSERT INTO catalog_items (ingredient_name) VALUES ('Test')"
        with self.assertRaises(ValueError):
            validate_readonly_sql(query)

    def test_validate_readonly_sql_rejects_update(self) -> None:
        query = "UPDATE catalog_items SET price_per_unit = 10"
        with self.assertRaises(ValueError):
            validate_readonly_sql(query)

    def test_validate_readonly_sql_rejects_delete(self) -> None:
        query = "DELETE FROM suppliers WHERE id = '123'"
        with self.assertRaises(ValueError):
            validate_readonly_sql(query)

    def test_validate_readonly_sql_rejects_drop_table(self) -> None:
        query = "DROP TABLE suppliers"
        with self.assertRaises(ValueError):
            validate_readonly_sql(query)

    def test_validate_readonly_sql_rejects_stacked_query_comment_hacks(self) -> None:
        query = "SELECT * FROM catalog_items; DROP TABLE suppliers"
        with self.assertRaises(ValueError):
            validate_readonly_sql(query)

    def test_validate_readonly_sql_rejects_auth_users_exfiltration_subquery(self) -> None:
        query = (
            "SELECT ingredient_name, (SELECT email FROM auth.users LIMIT 1) AS exfil "
            "FROM catalog_items WHERE tenant_id = :tenant_id"
        )
        with self.assertRaises(ValueError):
            validate_readonly_sql(query, require_tenant=True)

    def test_validate_readonly_sql_rejects_non_catalogue_tables(self) -> None:
        query = "SELECT token FROM employee_invitations WHERE tenant_id = :tenant_id"
        with self.assertRaises(ValueError):
            validate_readonly_sql(query, require_tenant=True)

    def test_validate_readonly_sql_rejects_dangerous_functions(self) -> None:
        query = "SELECT pg_read_file('/etc/passwd') FROM catalog_items WHERE tenant_id = :tenant_id"
        with self.assertRaises(ValueError):
            validate_readonly_sql(query, require_tenant=True)

    def test_validate_readonly_sql_requires_each_join_alias_to_be_tenant_scoped(self) -> None:
        query = (
            "SELECT ci.ingredient_name, s.name AS supplier_name "
            "FROM catalog_items ci JOIN suppliers s ON ci.supplier_id = s.id "
            "WHERE ci.tenant_id = :tenant_id"
        )
        with self.assertRaises(ValueError):
            validate_readonly_sql(query, require_tenant=True)

    def test_validate_readonly_sql_rejects_implicit_comma_joins(self) -> None:
        query = (
            "SELECT ci.ingredient_name, s.name AS supplier_name "
            "FROM catalog_items ci, suppliers s "
            "WHERE ci.tenant_id = :tenant_id AND s.tenant_id = :tenant_id"
        )
        with self.assertRaises(ValueError):
            validate_readonly_sql(query, require_tenant=True)

    def test_validate_readonly_sql_accepts_tenant_scoped_join(self) -> None:
        query = (
            "SELECT ci.ingredient_name, s.name AS supplier_name "
            "FROM catalog_items ci JOIN suppliers s ON ci.supplier_id = s.id "
            "WHERE ci.tenant_id = :tenant_id AND s.tenant_id = :tenant_id LIMIT 50"
        )
        validated = validate_readonly_sql(query, require_tenant=True)
        self.assertIn("LIMIT 50", validated)

    def test_validate_readonly_sql_caps_large_limit(self) -> None:
        query = "SELECT ingredient_name FROM catalog_items WHERE tenant_id = :tenant_id LIMIT 10000"
        validated = validate_readonly_sql(query, require_tenant=True)
        self.assertIn("LIMIT 100", validated)

    def test_mcp_get_structured_query_results_tool(self) -> None:
        tenant_id = uuid4()
        fake_rows = [{"ingredient_name": "Citric Acid", "price_per_unit": 12.5}]
        
        class FakeResult:
            returns_rows = True
            def keys(self):
                return ["ingredient_name", "price_per_unit"]
            def fetchall(self):
                return [("Citric Acid", 12.5)]

        class FakeDB:
            def execute(self, statement, params=None):
                return FakeResult()

        db = FakeDB()
        res = get_structured_query_results_tool(
            db,
            "SELECT ingredient_name, price_per_unit FROM catalog_items WHERE tenant_id = :tenant_id",
            tenant_id=tenant_id,
        )
        self.assertEqual(res["count"], 1)
        self.assertEqual(res["rows"][0]["ingredient_name"], "Citric Acid")
        self.assertEqual(res["rows"][0]["price_per_unit"], 12.5)

    def test_tenant_query_rejects_parameter_without_tenant_predicate(self) -> None:
        class FakeDB:
            def execute(self, statement, params=None):
                raise AssertionError("Unscoped SQL must not run")

        self.assertEqual(
            execute_readonly_sql(FakeDB(), "SELECT :tenant_id AS tenant", tenant_id=uuid4()),
            [],
        )

    def test_tenant_query_rejects_unscoped_join_before_execution(self) -> None:
        class FakeDB:
            def execute(self, statement, params=None):
                raise AssertionError("Unscoped SQL must not run")

        query = (
            "SELECT ci.ingredient_name, s.name AS supplier_name "
            "FROM catalog_items ci JOIN suppliers s ON ci.supplier_id = s.id "
            "WHERE ci.tenant_id = :tenant_id"
        )
        self.assertEqual(execute_readonly_sql(FakeDB(), query, tenant_id=uuid4()), [])


if __name__ == "__main__":
    unittest.main()
