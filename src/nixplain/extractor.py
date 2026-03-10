"""Extract Nix module-system semantics from bare .nix files via tree-sitter."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import tree_sitter as ts
import tree_sitter_nix as tsnix

from .models import Block, Constraint, Dependency, Grant, Rationale

_NIX_LANG = ts.Language(tsnix.language())
_PARSER = ts.Parser(_NIX_LANG)


@dataclass
class NixSignal:
    """A semantic signal detected in bare Nix code."""
    kind: str               # mkForce, mkDefault, mkOverride, mkIf, import, assertion
    attrpath: str            # dotted path of the enclosing binding
    line: int
    value: str | None = None       # argument text
    guard: str | None = None       # mkIf: condition attrpath
    priority: int | None = None    # mkOverride: priority number
    message: str | None = None     # assertion: message string


def extract_file(path: Path) -> list[NixSignal]:
    """Parse a .nix file and extract all Nix semantic signals."""
    source = path.read_bytes()
    tree = _PARSER.parse(source)
    signals: list[NixSignal] = []
    _walk(tree.root_node, signals, [])
    return signals


def _walk(node: ts.Node, signals: list[NixSignal], attr_context: list[str]):
    """Walk the AST, tracking the current attribute path context."""
    if node.type == "binding":
        _process_binding(node, signals, attr_context)
        return  # _process_binding recurses into the value
    for child in node.children:
        _walk(child, signals, attr_context)


def _process_binding(node: ts.Node, signals: list[NixSignal], attr_context: list[str]):
    """Process a single binding node: attrpath = expression;"""
    ap_node = node.child_by_field_name("attrpath")
    expr_node = node.child_by_field_name("expression")
    if not ap_node or not expr_node:
        return

    local_path = _attrpath_text(ap_node)
    full_path = ".".join(attr_context + [local_path])

    # Check for special binding keys
    if local_path == "imports":
        _extract_imports(expr_node, signals, node.start_point.row + 1)
        return
    if local_path == "assertions":
        _extract_assertions(expr_node, signals)
        return

    # Check if the expression is a lib.mk* call
    _extract_mk_signals(expr_node, signals, full_path, attr_context + [local_path])


def _extract_mk_signals(node: ts.Node, signals: list[NixSignal],
                         attrpath: str, attr_context: list[str]):
    """Detect mkForce, mkDefault, mkOverride, mkIf in an expression."""
    if node.type != "apply_expression":
        # Recurse into attrset bodies to find nested bindings
        if node.type == "attrset_expression":
            for child in node.children:
                _walk(child, signals, attr_context)
        return

    func_name, func_node = _resolve_function(node)
    if not func_name:
        # Not a recognized pattern — recurse into children
        for child in node.named_children:
            _extract_mk_signals(child, signals, attrpath, attr_context)
        return

    line = node.start_point.row + 1
    arg = node.child_by_field_name("argument")
    arg_text = arg.text.decode() if arg else None

    if func_name == "mkForce":
        signals.append(NixSignal(
            kind="mkForce", attrpath=attrpath, line=line,
            value=arg_text,
        ))
    elif func_name == "mkDefault":
        signals.append(NixSignal(
            kind="mkDefault", attrpath=attrpath, line=line,
            value=arg_text,
        ))
    elif func_name == "mkOverride":
        # Curried: (mkOverride N) value — this node is the outer apply
        # func_node is the inner apply whose argument is the priority
        inner_arg = func_node.child_by_field_name("argument")
        priority = None
        if inner_arg and inner_arg.type == "integer_expression":
            try:
                priority = int(inner_arg.text.decode())
            except ValueError:
                pass
        signals.append(NixSignal(
            kind="mkOverride", attrpath=attrpath, line=line,
            value=arg_text, priority=priority,
        ))
    elif func_name == "mkIf":
        # Curried: (mkIf cond) body — this node is the outer apply
        inner_arg = func_node.child_by_field_name("argument")
        guard = None
        if inner_arg:
            guard = _node_to_attrpath(inner_arg)
        signals.append(NixSignal(
            kind="mkIf", attrpath=attrpath, line=line,
            guard=guard,
        ))
        # Recurse into the body (the outer argument)
        if arg and arg.type == "attrset_expression":
            for child in arg.children:
                _walk(child, signals, attr_context)

    # For unrecognized functions, recurse into the argument
    elif arg:
        _extract_mk_signals(arg, signals, attrpath, attr_context)


def _resolve_function(node: ts.Node) -> tuple[str | None, ts.Node | None]:
    """Resolve the function name from an apply_expression.

    Returns (func_name, func_apply_node) where func_apply_node is the
    inner apply_expression for curried calls (mkOverride, mkIf).

    Handles:
      lib.mkForce x       → ("mkForce", None)
      (lib.mkIf cond) x   → ("mkIf", inner_apply)
      (lib.mkOverride n) x → ("mkOverride", inner_apply)
    """
    func = node.child_by_field_name("function")
    if not func:
        return None, None

    # Direct: lib.mkForce x
    if func.type == "select_expression":
        name = _select_tail(func)
        if name in ("mkForce", "mkDefault"):
            return name, None
        return None, None

    # Curried: (lib.mkIf cond) body  or  (lib.mkOverride n) value
    if func.type == "apply_expression":
        inner_func = func.child_by_field_name("function")
        if inner_func and inner_func.type == "select_expression":
            name = _select_tail(inner_func)
            if name in ("mkIf", "mkOverride"):
                return name, func
    return None, None


def _select_tail(node: ts.Node) -> str | None:
    """Get the last identifier in a select_expression (e.g. 'mkForce' from 'lib.mkForce')."""
    ap = node.child_by_field_name("attrpath")
    if ap:
        children = [c for c in ap.named_children if c.type == "identifier"]
        if children:
            return children[-1].text.decode()
    return None


def _attrpath_text(node: ts.Node) -> str:
    """Convert an attrpath node to dotted string."""
    parts = []
    for child in node.named_children:
        if child.type == "identifier":
            parts.append(child.text.decode())
        elif child.type == "string_expression":
            parts.append(child.text.decode().strip('"'))
    return ".".join(parts)


def _node_to_attrpath(node: ts.Node) -> str:
    """Try to convert a node to a dotted attribute path string."""
    if node.type == "select_expression":
        expr = node.child_by_field_name("expression")
        ap = node.child_by_field_name("attrpath")
        if expr and ap:
            base = _node_to_attrpath(expr)
            tail = _attrpath_text(ap)
            return f"{base}.{tail}" if base else tail
    if node.type == "variable_expression":
        name_node = node.child_by_field_name("name")
        if name_node:
            return name_node.text.decode()
    return node.text.decode()


def _extract_imports(node: ts.Node, signals: list[NixSignal], line: int):
    """Extract import paths from a list_expression."""
    if node.type != "list_expression":
        return
    for child in node.named_children:
        if child.type == "path_expression":
            signals.append(NixSignal(
                kind="import", attrpath="imports", line=line,
                value=child.text.decode(),
            ))


def _extract_assertions(node: ts.Node, signals: list[NixSignal]):
    """Extract assertion entries from a list of attrsets."""
    if node.type != "list_expression":
        return
    for elem in node.named_children:
        if elem.type != "attrset_expression":
            continue
        assertion_text = None
        message_text = None
        line = elem.start_point.row + 1
        for child in elem.named_children:
            if child.type == "binding_set":
                for binding in child.named_children:
                    if binding.type != "binding":
                        continue
                    ap = binding.child_by_field_name("attrpath")
                    ex = binding.child_by_field_name("expression")
                    if not ap or not ex:
                        continue
                    key = _attrpath_text(ap)
                    if key == "assertion":
                        assertion_text = ex.text.decode()
                    elif key == "message":
                        message_text = ex.text.decode().strip('"')
        signals.append(NixSignal(
            kind="assertion", attrpath="assertions", line=line,
            value=assertion_text, message=message_text,
        ))


# ---- Signal → Block mapping ----

def signals_to_blocks(signals: list[NixSignal], file: str = "") -> list[Block]:
    """Convert extracted NixSignals into HATC Block objects."""
    blocks: list[Block] = []
    for sig in signals:
        block = Block(file=file, start_line=sig.line, end_line=sig.line)

        if sig.kind == "mkForce":
            block.constraints.append(Constraint(
                hard=True, text="", grant=Grant(), line=sig.line,
            ))
        elif sig.kind == "mkDefault":
            block.constraints.append(Constraint(
                hard=False, text="", grant=Grant(), line=sig.line,
            ))
        elif sig.kind == "mkOverride":
            hard = sig.priority is not None and sig.priority < 100
            block.constraints.append(Constraint(
                hard=hard, text=f"priority {sig.priority}" if sig.priority else "",
                grant=Grant(), line=sig.line,
            ))
        elif sig.kind == "mkIf":
            if sig.guard:
                block.dependencies.append(Dependency(
                    arrow="<<", target=sig.guard, line=sig.line,
                ))
        elif sig.kind == "import":
            if sig.value:
                block.dependencies.append(Dependency(
                    arrow=">", target=sig.value, line=sig.line,
                ))
        elif sig.kind == "assertion":
            block.constraints.append(Constraint(
                hard=True, text=sig.value or "", grant=Grant(), line=sig.line,
            ))
            if sig.message:
                block.rationales.append(Rationale(
                    text=sig.message, line=sig.line,
                ))

        blocks.append(block)
    return blocks


def extract_blocks(path: Path) -> list[Block]:
    """High-level: extract signals and convert to blocks in one step."""
    signals = extract_file(path)
    return signals_to_blocks(signals, file=str(path))
