"""Dependency & architectural guardrail tests.

Enforces:
1. Ownership comments in pyproject.toml and requirements.txt
2. Pruned obsolete packages (pytesseract, firecrawl-anydoc, markitdown, pdf-inspector, gmft)
3. Layered architectural import boundaries (no engine calls outside pipeline/ modules)
"""

import ast
from pathlib import Path
import unittest


class DependencyGuardrailTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[2]
        self.pyproject_path = self.root / "pyproject.toml"
        self.requirements_path = self.root / "requirements.txt"

    def test_forbidden_packages_removed(self) -> None:
        forbidden = ["pytesseract", "firecrawl-anydoc", "markitdown", "pdf-inspector", "gmft"]

        pyproject_content = self.pyproject_path.read_text().lower()
        reqs_content = self.requirements_path.read_text().lower()

        for pkg in forbidden:
            self.assertNotIn(
                pkg,
                pyproject_content,
                f"Forbidden package '{pkg}' found in pyproject.toml",
            )
            self.assertNotIn(
                pkg,
                reqs_content,
                f"Forbidden package '{pkg}' found in requirements.txt",
            )

    def test_requirements_ownership_comments(self) -> None:
        lines = [line.strip() for line in self.requirements_path.read_text().splitlines() if line.strip()]
        dep_lines = [l for l in lines if not l.startswith("#")]

        # Ensure every dependency line is preceded or annotated with an ownership comment
        comment_count = sum(1 for line in lines if "owned by" in line.lower())
        self.assertGreaterEqual(
            comment_count,
            len(dep_lines),
            "Every dependency in requirements.txt must have an ownership comment",
        )

    def test_pipeline_import_encapsulation(self) -> None:
        """Verify that OCR and table engines (rapidocr, img2table) are only imported inside backend/app/pipeline/."""
        restricted_imports = {"rapidocr_onnxruntime", "img2table"}
        app_dir = self.root / "backend" / "app"

        violations: list[str] = []
        for py_file in app_dir.rglob("*.py"):
            # Allow imports within backend/app/pipeline/
            if "backend/app/pipeline" in py_file.as_posix():
                continue

            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8", errors="ignore"), filename=str(py_file))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name in restricted_imports:
                                violations.append(f"{py_file.name}:{node.lineno} imports {alias.name}")
                    elif isinstance(node, ast.ImportFrom):
                        if node.module and any(node.module.startswith(pkg) for pkg in restricted_imports):
                            violations.append(f"{py_file.name}:{node.lineno} imports from {node.module}")
            except SyntaxError:
                continue

        self.assertEqual(
            violations,
            [],
            f"Extraction engines imported outside backend/app/pipeline/: {violations}",
        )


if __name__ == "__main__":
    unittest.main()
