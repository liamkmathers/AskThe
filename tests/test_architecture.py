"""Guards for the engineering rules in CLAUDE.md."""

import ast
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
PACKAGE = REPO / "askthe"
CORE = PACKAGE / "core"

# The core may use the standard library, pydantic, and itself. Nothing else.
CORE_ALLOWED = {"pydantic", "askthe"}


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_core_has_no_io_or_adapter_dependencies():
    for path in CORE.rglob("*.py"):
        for module in imported_modules(path):
            top = module.split(".")[0]
            if top == "askthe":
                assert module.startswith("askthe.core"), f"{path.name} imports {module}"
            else:
                assert top in CORE_ALLOWED or top in sys.stdlib_module_names, (
                    f"{path.name} imports {module}"
                )


def test_only_wiring_constructs_adapters():
    for path in PACKAGE.rglob("*.py"):
        if path.parent.name == "adapters" or path.name == "wiring.py":
            continue
        for module in imported_modules(path):
            assert not module.startswith("askthe.adapters"), f"{path.name} imports {module}"


def test_engine_names_no_creator():
    """Creator names and glossary terms belong in creators/*.yaml, never in askthe/."""
    names = set()
    for config in (REPO / "creators").glob("*.yaml"):
        data = yaml.safe_load(config.read_text())
        names |= {data["display_name"], data["slug"]}
        names |= {entry["name"] for entry in data.get("glossary", [])}
    for path in PACKAGE.rglob("*.py"):
        text = path.read_text().lower()
        for name in names:
            assert name.lower() not in text, f"{path.relative_to(REPO)} mentions {name!r}"
