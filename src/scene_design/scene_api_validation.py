"""Resolve generated source names against the selected Manim runtime, without executing it."""
import json
from pathlib import Path
import subprocess

from src.scene_design import manim_runtime
from src.shared._workflow_store import WorkflowError

# Only trusted installed modules are loaded. Generated source is parsed, never exec'd.
_PROBE = r'''
import ast, builtins, importlib, json, symtable, sys
sys.dont_write_bytecode = True
source = json.load(sys.stdin)
tree = ast.parse(source)
table = symtable.symtable(source, "<scene>", "exec")
modules = {
    "manim": "manim", "numpy": "numpy", "math": "math",
    "manim_kit": "src.scene_design.manim_kit",
    "src.scene_design.manim_kit": "src.scene_design.manim_kit",
}
namespace = dict(vars(builtins))
imported = {}
issues = []
def error(node, message):
    issues.append((node.lineno, node.col_offset + 1, message))
def load(name):
    return importlib.import_module(modules[name])
def resolve_import(node):
    bindings = {}
    names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module]
    if isinstance(node, ast.ImportFrom) and node.level:
        error(node, "Relative imports are unsupported")
        return bindings
    if any(name not in modules for name in names):
        error(node, "Unsupported import")
        return bindings
    if isinstance(node, ast.Import):
        for alias in node.names:
            value = load(alias.name)
            if alias.asname or "." not in alias.name:
                bindings[alias.asname or alias.name] = value
            else:
                bindings["src"] = importlib.import_module("src")
    else:
        module = load(node.module)
        for alias in node.names:
            if alias.name == "*":
                for name in getattr(module, "__all__", [k for k in vars(module) if not k.startswith("_")]):
                    bindings[name] = getattr(module, name)
            elif not hasattr(module, alias.name):
                error(node, "Unavailable imported API " + node.module + "." + alias.name)
            else:
                bindings[alias.asname or alias.name] = getattr(module, alias.name)
    return bindings
# Validate every import; only module-scope imports supply global names.
resolved_imports = {id(node): resolve_import(node) for node in ast.walk(tree)
                    if isinstance(node, (ast.Import, ast.ImportFrom))}
def collect_global_imports(node):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
        return
    imported.update(resolved_imports.get(id(node), {}))
    for child in ast.iter_child_nodes(node):
        collect_global_imports(child)
collect_global_imports(tree)
namespace.update(imported)
# symtable understands parameters, nested functions, closures, lambda and comprehension scopes.
module_bindings = {s.get_name() for s in table.get_symbols()
                   if s.is_assigned() or s.is_imported() or s.is_namespace()}
nodes = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)]
local_imports = set()
def check_scope(scope):
    for symbol in scope.get_symbols():
        name = symbol.get_name()
        if scope is not table and symbol.is_imported():
            local_imports.add(name)
        if (symbol.is_referenced() and (symbol.is_global() or scope.get_type() == "module")
                and name not in namespace and name not in module_bindings):
            locations = [n for n in nodes if n.id == name and n.lineno >= scope.get_lineno()]
            if locations:
                error(min(locations, key=lambda n: (n.lineno, n.col_offset)),
                      "Undefined name/API " + name)
    for child in scope.get_children():
        check_scope(child)
check_scope(table)
# Resolve explicit imported namespace/class paths, e.g. m.Polygon and Axes.plot.
# Instance attributes and values returned by calls require runtime/type analysis.
# Skip roots shadowed by local bindings rather than rejecting valid local objects.
shadowed = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
shadowed.update(local_imports)
shadowed.update(n.arg for n in ast.walk(tree) if isinstance(n, ast.arg))
shadowed.update(n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)))
for node in ast.walk(tree):
    if not isinstance(node, ast.Attribute) or not isinstance(node.ctx, ast.Load):
        continue
    parts = []
    root = node
    while isinstance(root, ast.Attribute):
        parts.insert(0, root.attr)
        root = root.value
    if not isinstance(root, ast.Name) or root.id not in imported or root.id in shadowed:
        continue
    value = imported[root.id]
    for part in parts:
        try:
            value = getattr(value, part)
        except AttributeError:
            error(node, "Unavailable installed API " + ".".join([root.id] + parts))
            break
print(json.dumps(sorted(set(issues))))
'''


def validate_scene_apis(source):
    """Reject unresolved globals/imported APIs before any renderer is started."""
    try:
        result = subprocess.run(
            [manim_runtime.python_executable(), "-c", _PROBE],
            input=json.dumps(source), text=True, capture_output=True,
            cwd=Path(__file__).resolve().parents[2], timeout=30,
        )
        if result.returncode:
            raise ValueError(result.stderr[-1000:])
        issues = json.loads(result.stdout.strip().splitlines()[-1])
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise WorkflowError("DEPENDENCY_ERROR", "Cannot validate installed scene APIs: " + str(exc)) from None
    if issues:
        line, column, message = issues[0]
        raise WorkflowError("INVALID_SCENE_CODE", f"Line {line}, column {column}: {message}")
    return source
