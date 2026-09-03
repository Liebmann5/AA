"""Shared AST binding helpers for the architecture pins (Batch 1, Stage B).

Three questions the pins keep needing answered, in one dependency-free,
AST-only module:

    top_level_bindings(path)            — which names does this module bind
                                          at module scope?
    name_used_outside_import(tree, name) — is this name referenced in an
                                          executable position anywhere in
                                          this tree?
    explicit_base_names(class_node)      — dotted names of a class's explicit
                                          base classes.

Deliberately nothing else lives here. The port pin (Stage A) does not import
this module yet — it is a separate stage and may adopt these helpers in a
later batch.
"""

from __future__ import annotations

import ast
from pathlib import Path

__all__ = [
    "top_level_bindings",
    "name_used_outside_import",
    "explicit_base_names",
]


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────


def _is_type_checking(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _collect_target_names(target: ast.expr, out: set) -> None:
    if isinstance(target, ast.Name):
        out.add(target.id)
    elif isinstance(target, ast.Starred):
        _collect_target_names(target.value, out)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            _collect_target_names(elt, out)
    # Attribute targets (self.x) and Subscript targets bind nothing at module
    # scope in the sense this helper answers, so they are ignored here.


def _visit_module_block(stmts: list, out: set) -> None:
    """Collect names bound by a sequence of module-level statements, recursing
    into module-level if / try / with / for / while bodies (R-C: bindings
    inside those blocks count) but never into function or class bodies."""
    for node in stmts:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                _collect_target_names(target, out)
        elif isinstance(node, ast.AnnAssign):
            _collect_target_names(node.target, out)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                out.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.If):
            _visit_module_block(node.body, out)
            _visit_module_block(node.orelse, out)
        elif isinstance(node, ast.Try):
            _visit_module_block(node.body, out)
            for handler in node.handlers:
                if handler.name:
                    out.add(handler.name)
                _visit_module_block(handler.body, out)
            _visit_module_block(node.orelse, out)
            _visit_module_block(node.finalbody, out)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    _collect_target_names(item.optional_vars, out)
            _visit_module_block(node.body, out)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            _collect_target_names(node.target, out)
            _visit_module_block(node.body, out)
            _visit_module_block(node.orelse, out)
        elif isinstance(node, ast.While):
            _visit_module_block(node.body, out)
            _visit_module_block(node.orelse, out)


def _dotted(expr: ast.expr) -> str:
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        base = _dotted(expr.value)
        return f"{base}.{expr.attr}" if base else expr.attr
    if isinstance(expr, ast.Subscript):
        return _dotted(expr.value)
    if isinstance(expr, ast.Call):
        return _dotted(expr.func)
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Public helpers
# ─────────────────────────────────────────────────────────────────────────────


def top_level_bindings(path: Path) -> set:
    """Return the set of names bound at module scope in *path*.

    Bound means: a ``def``, ``class``, assignment, annotated assignment, or
    import alias — including inside module-level ``if`` / ``try`` / ``with`` /
    ``for`` / ``while`` bodies (R-C). Function and class bodies are not
    entered. Returns an empty set if the file does not parse; callers decide
    how to report that case.
    """
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    names: set = set()
    _visit_module_block(tree.body, names)
    return names


def name_used_outside_import(tree: ast.Module, name: str) -> bool:
    """Return True if *name* appears in an executable position in *tree*.

    Counts any ``ast.Name`` / ``ast.Attribute`` load — an annotation, a call,
    a base class, an isinstance, an assignment — anywhere except inside an
    ``if TYPE_CHECKING:`` block. ImportFrom aliases are not Name nodes, so a
    bare import of *name* never counts.
    """
    found = False

    class _Visitor(ast.NodeVisitor):
        def visit_If(self, node: ast.If) -> None:
            if _is_type_checking(node.test):
                return
            self.generic_visit(node)

        def visit_Name(self, node: ast.Name) -> None:
            nonlocal found
            if isinstance(node.ctx, ast.Load) and node.id == name:
                found = True

        def visit_Attribute(self, node: ast.Attribute) -> None:
            nonlocal found
            if isinstance(node.ctx, ast.Load) and node.attr == name:
                found = True
            self.generic_visit(node)

    _Visitor().visit(tree)
    return found


def explicit_base_names(class_node: ast.ClassDef) -> list:
    """Return the dotted names of *class_node*'s explicit base classes.

    Examples: ``DiscoveryProviderPort``, ``typing.Protocol``, ``ABC``.
    Subscripts (``Generic[T]``) resolve to their value; calls resolve to
    their function. Unresolvable expressions are dropped.
    """
    names: list = []
    for base in class_node.bases:
        dotted = _dotted(base)
        if dotted:
            names.append(dotted)
    return names
