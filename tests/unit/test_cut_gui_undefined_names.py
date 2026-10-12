import ast
import builtins
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[2] / "plugin" / "fortsmart_precision"
CHECKED_MODULES = (
    "gui/planting_line_cut_dialog.py",
    "gui/fortsmart_workspace_dialog.py",
    "gui/machine_work_geometry_widget.py",
    "algorithms/simulate_obstacle_border_cut.py",
    "core/longitudinal_cut_engine.py",
    "core/obstacle_border_pass_engine.py",
)


def _bound_names(node):
    names = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
            names.add(child.id)
        elif isinstance(child, ast.arg):
            names.add(child.arg)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(child.name)
        elif isinstance(child, (ast.Import, ast.ImportFrom)):
            for alias in child.names:
                names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(child, ast.ExceptHandler) and child.name:
            names.add(child.name)
        elif isinstance(child, (ast.Global, ast.Nonlocal)):
            names.update(child.names)
    return names


def _module_names(tree):
    names = set(dir(builtins)) | {"__file__", "__name__"}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
        else:
            names |= _bound_names(node)
    return names


def undefined_names_in_functions(source):
    """Nomes lidos em funcoes que nao existem no modulo nem na funcao externa."""
    tree = ast.parse(source)
    module_names = _module_names(tree)
    problems = []
    outer_functions = [
        item
        for node in tree.body
        for item in (node.body if isinstance(node, ast.ClassDef) else [node])
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    for function in outer_functions:
        known = module_names | _bound_names(function)
        for child in ast.walk(function):
            if (
                isinstance(child, ast.Name)
                and isinstance(child.ctx, ast.Load)
                and child.id not in known
            ):
                problems.append((function.name, child.id, child.lineno))
    return problems


class CutGuiUndefinedNamesTest(unittest.TestCase):
    def test_detector_finds_name_from_other_method(self):
        source = (
            "class D:\n"
            "    def a(self):\n"
            "        lines = 1\n"
            "    def b(self):\n"
            "        return lines.name()\n"
        )
        self.assertEqual(undefined_names_in_functions(source), [("b", "lines", 5)])

    def test_cut_dialogs_have_no_undefined_names(self):
        for module in CHECKED_MODULES:
            source = (PLUGIN_DIR / module).read_text(encoding="utf-8")
            with self.subTest(module=module):
                self.assertEqual(undefined_names_in_functions(source), [])


if __name__ == "__main__":
    unittest.main()
