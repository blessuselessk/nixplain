"""Tests for nixf integration."""

import tempfile
from pathlib import Path
from textwrap import dedent

import pytest

from nixplain.nixf import analyze_file, enrich_signals, find_nixf_tidy, NixfDiagnostic


@pytest.fixture
def has_nixf():
    """Skip tests if nixf-tidy is not available."""
    if not find_nixf_tidy():
        pytest.skip("nixf-tidy not found")


def _write_nix(code: str) -> Path:
    f = tempfile.NamedTemporaryFile(suffix=".nix", mode="w", delete=False)
    f.write(dedent(code))
    f.flush()
    return Path(f.name)


class TestAnalyzeFile:
    def test_clean_file_no_diagnostics(self, has_nixf):
        path = _write_nix("""
            { config, lib, ... }:
            {
              services.openssh.enable = lib.mkForce true;
            }
        """)
        diags = analyze_file(path)
        # config is unused but that's a warning, not necessarily zero
        errors = [d for d in diags if d.severity == 1]
        assert len(errors) == 0

    def test_undefined_variable(self, has_nixf):
        path = _write_nix("""
            { lib, ... }:
            {
              x = mkForce true;
            }
        """)
        diags = analyze_file(path)
        undef = [d for d in diags if d.sname == "sema-undefined-variable"]
        assert len(undef) >= 1
        assert any(d.args == ["mkForce"] for d in undef)

    def test_duplicate_attr(self, has_nixf):
        path = _write_nix("""
            { ... }:
            {
              x = 1;
              x = 2;
            }
        """)
        diags = analyze_file(path)
        dups = [d for d in diags if d.sname == "sema-duplicated-attrname"]
        assert len(dups) >= 1
        assert dups[0].args == ["x"]

    def test_unused_let(self, has_nixf):
        path = _write_nix("""
            { ... }:
            let unused = 42; in
            { x = 1; }
        """)
        diags = analyze_file(path)
        unused = [d for d in diags if d.sname == "sema-unused-def-let"]
        assert len(unused) >= 1

    def test_unused_formal(self, has_nixf):
        path = _write_nix("""
            { config, lib, ... }:
            {
              x = lib.mkForce true;
            }
        """)
        diags = analyze_file(path)
        unused = [d for d in diags if "unused" in d.sname and "config" in d.args]
        assert len(unused) >= 1


class TestEnrichSignals:
    def test_enrich_undefined_variable(self):
        diags = [NixfDiagnostic(
            sname="sema-undefined-variable", severity=1,
            message="undefined variable", line=5, column=10,
            args=["mkForce"],
        )]
        enrichments = enrich_signals([], diags)
        assert len(enrichments) == 1
        assert enrichments[0]["line"] == 5
        assert enrichments[0]["issues"][0]["kind"] == "undefined-variable"
        assert enrichments[0]["issues"][0]["name"] == "mkForce"

    def test_enrich_duplicate_attr(self):
        diags = [NixfDiagnostic(
            sname="sema-duplicated-attrname", severity=1,
            message="duplicated attrname", line=8, column=4,
            args=["enable"],
        )]
        enrichments = enrich_signals([], diags)
        assert enrichments[0]["issues"][0]["kind"] == "duplicate-attr"

    def test_enrich_unused_let(self):
        diags = [NixfDiagnostic(
            sname="sema-unused-def-let", severity=2,
            message="not used", line=3, column=2,
            args=["foo"],
        )]
        enrichments = enrich_signals([], diags)
        assert enrichments[0]["issues"][0]["kind"] == "unused-binding"

    def test_enrich_empty(self):
        assert enrich_signals([], []) == []

    def test_multiple_issues_same_line(self):
        diags = [
            NixfDiagnostic(sname="sema-undefined-variable", severity=1,
                           message="", line=5, column=0, args=["a"]),
            NixfDiagnostic(sname="sema-undefined-variable", severity=1,
                           message="", line=5, column=10, args=["b"]),
        ]
        enrichments = enrich_signals([], diags)
        assert len(enrichments) == 1
        assert len(enrichments[0]["issues"]) == 2
