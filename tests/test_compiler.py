"""Tests for the AGENTS.md compiler."""

from pathlib import Path

from hatc.compiler import compile_directory

EXAMPLE_DIR = Path(__file__).parent.parent / "example"


def test_compile_produces_output():
    md = compile_directory(EXAMPLE_DIR)
    assert len(md) > 0
    assert "AGENTS.md" in md


def test_compile_contains_intent():
    md = compile_directory(EXAMPLE_DIR)
    assert "#! hardened remote deployment target" in md
    assert "#! minimal attack surface SSH" in md


def test_compile_contains_file_reference():
    md = compile_directory(EXAMPLE_DIR)
    assert "@ssh.nix" in md


def test_compile_contains_cross_file_deps():
    md = compile_directory(EXAMPLE_DIR)
    assert "Cross-file dependencies" in md
    assert "firewall" in md
