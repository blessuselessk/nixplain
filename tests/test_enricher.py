"""Tests for the enricher module."""

from unittest.mock import patch, MagicMock
from nixplain.enricher import (
    format_signal_input, enrich_blocks, find_nix_why,
)
from nixplain.extractor import NixSignal
from nixplain.models import Block, Constraint, Grant


class TestFormatSignalInput:
    def test_mkforce(self):
        sig = NixSignal(kind="mkForce", attrpath="services.openssh.enable",
                        line=8, value="true")
        result = format_signal_input(sig)
        assert result == "INPUT: Attribute: services.openssh.enable | Kind: mkForce | Value: true"

    def test_mkif_with_guard(self):
        sig = NixSignal(kind="mkIf", attrpath="services.openssh.settings",
                        line=12, guard="config.services.openssh.enable")
        result = format_signal_input(sig)
        assert "Guard: config.services.openssh.enable" in result

    def test_mkoverride_with_priority(self):
        sig = NixSignal(kind="mkOverride", attrpath="foo", line=1,
                        value="bar", priority=50)
        result = format_signal_input(sig)
        assert "Priority: 50" in result

    def test_assertion_with_message(self):
        sig = NixSignal(kind="assertion", attrpath="assertions", line=27,
                        value="config.x == false", message="compliance")
        result = format_signal_input(sig)
        assert "Message: compliance" in result

    def test_import(self):
        sig = NixSignal(kind="import", attrpath="imports", line=5,
                        value="../firewall.nix")
        result = format_signal_input(sig)
        assert result == "INPUT: Attribute: imports | Kind: import | Value: ../firewall.nix"


class TestEnrichBlocks:
    def test_enriches_blocks_with_mock_nix_why(self):
        sig = NixSignal(kind="mkForce", attrpath="services.openssh.enable",
                        line=8, value="true")
        block = Block(file="test.nix", start_line=8, end_line=8,
                      constraints=[Constraint(hard=True, text="", grant=Grant(), line=8)])

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '{"intent": "Force-enable SSH", "posture": "locked", "rationale": "reason"}'

        with patch("nixplain.enricher.subprocess.run", return_value=mock_result):
            result = enrich_blocks([sig], [block], nix_why="/fake/nix-why")

        assert result[0].intent is not None
        assert result[0].intent.text == "Force-enable SSH"

    def test_skips_blocks_with_existing_intent(self):
        from nixplain.models import Intent
        sig = NixSignal(kind="mkForce", attrpath="x", line=1, value="true")
        block = Block(file="t.nix", start_line=1, end_line=1,
                      intent=Intent(text="existing", line=1))

        with patch("nixplain.enricher.subprocess.run") as mock_run:
            enrich_blocks([sig], [block], nix_why="/fake/nix-why")
            mock_run.assert_not_called()

    def test_handles_nix_why_failure(self):
        sig = NixSignal(kind="mkForce", attrpath="x", line=1, value="true")
        block = Block(file="t.nix", start_line=1, end_line=1,
                      constraints=[Constraint(hard=True, text="", grant=Grant(), line=1)])

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with patch("nixplain.enricher.subprocess.run", return_value=mock_result):
            result = enrich_blocks([sig], [block], nix_why="/fake/nix-why")

        assert result[0].intent is None

    def test_no_nix_why_returns_blocks_unchanged(self):
        sig = NixSignal(kind="mkForce", attrpath="x", line=1, value="true")
        block = Block(file="t.nix", start_line=1, end_line=1)

        with patch("nixplain.enricher.find_nix_why", return_value=None):
            result = enrich_blocks([sig], [block])

        assert result[0].intent is None


class TestCompilerIntegration:
    def test_compile_bare_with_mock_enrichment(self):
        """Test that compile --bare --enrich produces AGENTS.md with intents."""
        from nixplain.compiler import compile_directory
        from nixplain.extractor import extract_file, signals_to_blocks
        from nixplain.models import Intent
        from pathlib import Path

        def mock_source(path: Path) -> list:
            sigs = extract_file(path)
            blocks = signals_to_blocks(sigs, file=str(path))
            # Simulate enrichment by manually setting intents
            for block in blocks:
                block.intent = Intent(text=f"Test intent for L{block.start_line}",
                                      line=block.start_line)
            return blocks

        content = compile_directory("example/", block_source=mock_source)
        assert "# AGENTS.md" in content
        assert "ssh-bare.nix" in content
        assert "#! Test intent for L" in content
