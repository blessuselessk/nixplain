"""Tests for the static intent annotator."""

import tempfile
from pathlib import Path

from hatc.annotator import annotate_file


def test_annotate_unannotated_block():
    """A block with constraints but no #! should get a suggestion."""
    content = """\
services.openssh = {
  #= by:security-team | for:SOC2-CC6.1
  PasswordAuthentication = false;

  #? by:anyone
  UseDns = true;
};
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".nix", delete=False) as f:
        f.write(content)
        f.flush()
        suggestions = annotate_file(f.name)

    assert len(suggestions) >= 1
    assert "hard constraint" in suggestions[0].lower()


def test_annotate_fully_annotated():
    """A file where all blocks have #! should produce no suggestions."""
    content = """\
#! hardened SSH
services.openssh = {
  #= by:security-team
  PasswordAuthentication = false;
};
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".nix", delete=False) as f:
        f.write(content)
        f.flush()
        suggestions = annotate_file(f.name)

    assert len(suggestions) == 0


def test_annotate_no_hatc():
    """A file with no HATC annotations should produce no suggestions."""
    content = """\
{ config, ... }:
{
  services.openssh.enable = true;
}
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".nix", delete=False) as f:
        f.write(content)
        f.flush()
        suggestions = annotate_file(f.name)

    assert len(suggestions) == 0
