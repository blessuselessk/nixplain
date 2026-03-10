"""nixf integration — semantic analysis via nixf-tidy subprocess."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class NixfDiagnostic:
    """A diagnostic from nixf-tidy."""
    sname: str          # e.g. "sema-undefined-variable", "sema-duplicated-attrname"
    severity: int       # 1=error, 2=warning, 3=note
    message: str
    line: int           # 0-indexed from nixf, we store as 1-indexed
    column: int
    args: list[str]     # e.g. the variable name


def find_nixf_tidy() -> str | None:
    """Find nixf-tidy binary, preferring PATH then nix store."""
    path = shutil.which("nixf-tidy")
    if path:
        return path
    # Try a known nix store path (set by flake devShell)
    import os
    nixf_bin = os.environ.get("NIXF_TIDY")
    if nixf_bin and Path(nixf_bin).exists():
        return nixf_bin
    return None


def analyze_file(path: Path, variable_lookup: bool = True) -> list[NixfDiagnostic]:
    """Run nixf-tidy on a .nix file and return diagnostics."""
    nixf = find_nixf_tidy()
    if not nixf:
        return []

    cmd = [nixf]
    if variable_lookup:
        cmd.append("--variable-lookup")

    source = path.read_bytes()
    try:
        result = subprocess.run(
            cmd, input=source, capture_output=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    if not result.stdout.strip():
        return []

    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    diagnostics = []
    for d in raw:
        rng = d.get("range", {})
        lcur = rng.get("lCur", {})
        diagnostics.append(NixfDiagnostic(
            sname=d.get("sname", ""),
            severity=d.get("severity", 0),
            message=d.get("message", ""),
            line=lcur.get("line", 0) + 1,  # nixf is 0-indexed
            column=lcur.get("column", 0),
            args=d.get("args", []),
        ))
    return diagnostics


def enrich_signals(signals: list, diagnostics: list[NixfDiagnostic]) -> list[dict]:
    """Enrich NixSignal list with nixf diagnostics.

    Returns a list of enrichment dicts keyed by line number:
    - undefined_vars: variables used but not in scope
    - unused_formals: function args not referenced
    - duplicate_attrs: attribute names bound twice
    - unused_lets: let bindings never used
    """
    enrichments: dict[int, dict] = {}

    for d in diagnostics:
        line = d.line
        if line not in enrichments:
            enrichments[line] = {
                "line": line,
                "issues": [],
            }

        if d.sname == "sema-undefined-variable":
            enrichments[line]["issues"].append({
                "kind": "undefined-variable",
                "name": d.args[0] if d.args else "",
                "severity": "error",
            })
        elif d.sname == "sema-duplicated-attrname":
            enrichments[line]["issues"].append({
                "kind": "duplicate-attr",
                "name": d.args[0] if d.args else "",
                "severity": "error",
            })
        elif d.sname.startswith("sema-unused-def"):
            enrichments[line]["issues"].append({
                "kind": "unused-binding",
                "name": d.args[0] if d.args else "",
                "severity": "warning",
                "detail": d.sname,
            })

    return list(enrichments.values())
