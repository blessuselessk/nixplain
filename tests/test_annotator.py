"""Tests for the frame-based intent annotator."""

import tempfile
from pathlib import Path

from hatc.annotator import IntentFrame, annotate_file, _fill_frame
from hatc.parser import parse_lines


def _annotate(content: str) -> list[str]:
    """Helper: write content to a temp file and annotate it."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".nix", delete=False) as f:
        f.write(content)
        f.flush()
        return annotate_file(f.name)


def _frame_from(content: str) -> IntentFrame:
    """Helper: parse content and return the IntentFrame for the first unannotated block."""
    lines = content.splitlines()
    blocks = parse_lines(lines)
    for block in blocks:
        if not block.intent:
            return _fill_frame(block, lines)
    raise AssertionError("No unannotated block found")


# === IntentFrame.render() tests — the grammar ===

class TestIntentFrameRender:
    """Test the render method in isolation — this IS the grammar spec."""

    def test_empty_frame_returns_none(self):
        assert IntentFrame().render() is None

    def test_posture_only_returns_none(self):
        """Posture without subject isn't useful."""
        assert IntentFrame(posture="locked").render() == "locked"

    def test_subject_only(self):
        f = IntentFrame(subject="PasswordAuthentication")
        assert f.render() == "PasswordAuthentication"

    def test_posture_and_subject(self):
        f = IntentFrame(posture="locked", subject="PasswordAuthentication")
        assert f.render() == "locked PasswordAuthentication"

    def test_soft_posture(self):
        f = IntentFrame(posture="soft", subject="UseDns")
        assert f.render() == "soft UseDns"

    def test_reason_in_parens(self):
        f = IntentFrame(posture="locked", subject="Ciphers", reason="FIPS-140-2")
        assert f.render() == "locked Ciphers (FIPS-140-2)"

    def test_authority_in_parens(self):
        f = IntentFrame(posture="locked", subject="X", authority="security-team")
        assert f.render() == "locked X (by security-team)"

    def test_reason_and_authority(self):
        f = IntentFrame(
            posture="locked", subject="X",
            reason="SOC2-CC6.1", authority="security-team",
        )
        assert f.render() == "locked X (SOC2-CC6.1, by security-team)"

    def test_expiry(self):
        f = IntentFrame(
            posture="locked", subject="ports",
            authority="team-lead", expiry="Q2-migration",
        )
        assert f.render() == "locked ports (by team-lead, until Q2-migration)"

    def test_all_grant_fields(self):
        f = IntentFrame(
            posture="locked", subject="X",
            reason="SOC2", authority="sec-team", expiry="2026-06-01",
        )
        assert f.render() == "locked X (SOC2, by sec-team, until 2026-06-01)"

    def test_deviation_qualifier(self):
        f = IntentFrame(
            posture="locked", subject="PermitRootLogin",
            deviation="prohibit-password",
        )
        assert f.render() == "locked PermitRootLogin — non-default prohibit-password"

    def test_conflict_qualifier(self):
        f = IntentFrame(
            posture="soft", subject="X11Forwarding",
            conflict="ForwardAgent",
        )
        assert f.render() == "soft X11Forwarding — conflicts with ForwardAgent"

    def test_role_qualifier(self):
        f = IntentFrame(posture="soft", subject="UseDns", role="cross-file")
        assert f.render() == "soft UseDns — cross-file"

    def test_note_qualifier(self):
        f = IntentFrame(posture="soft", subject="X11Forwarding", note="toggle for debugging")
        assert f.render() == "soft X11Forwarding — toggle for debugging"

    def test_multiple_qualifiers(self):
        f = IntentFrame(
            posture="locked", subject="PermitRootLogin",
            reason="SOC2-CC6.1",
            deviation="prohibit-password",
            conflict="PasswordAuthentication",
        )
        rendered = f.render()
        assert "non-default prohibit-password" in rendered
        assert "conflicts with PasswordAuthentication" in rendered
        assert "(SOC2-CC6.1)" in rendered

    def test_all_slots_filled(self):
        f = IntentFrame(
            posture="locked", subject="PermitRootLogin",
            authority="security-team", reason="SOC2-CC6.1", expiry="Q2",
            deviation="prohibit-password", conflict="PasswordAuth",
            role="gated by enable", note="important",
        )
        rendered = f.render()
        assert "locked PermitRootLogin" in rendered
        assert "SOC2-CC6.1" in rendered
        assert "by security-team" in rendered
        assert "until Q2" in rendered
        assert "non-default prohibit-password" in rendered
        assert "conflicts with PasswordAuth" in rendered
        assert "gated by enable" in rendered
        assert "important" in rendered

    def test_qualifiers_joined_with_commas(self):
        f = IntentFrame(
            posture="locked", subject="X",
            deviation="val", conflict="Y", role="cross-file",
        )
        rendered = f.render()
        # After the em dash, qualifiers separated by commas
        after_dash = rendered.split("—")[1].strip()
        assert after_dash.count(",") == 2  # 3 items, 2 commas


# === Frame filling from parsed blocks ===

class TestFillFrame:
    """Test that parsed HATC annotations fill the correct frame slots."""

    def test_hard_constraint_fills_posture(self):
        frame = _frame_from("#= by:sec-team\nX = 1;")
        assert frame.posture == "locked"

    def test_soft_constraint_fills_posture(self):
        frame = _frame_from("#?\nX = 1;")
        assert frame.posture == "soft"

    def test_by_field_fills_authority(self):
        frame = _frame_from("#= by:crypto-team\nX = 1;")
        assert frame.authority == "crypto-team"

    def test_for_field_fills_reason(self):
        frame = _frame_from("#= by:sec | for:SOC2-CC6.1\nX = 1;")
        assert frame.reason == "SOC2-CC6.1"

    def test_until_field_fills_expiry(self):
        frame = _frame_from("#= by:lead | until:Q2-migration\nX = 1;")
        assert frame.expiry == "Q2-migration"

    def test_attr_name_fills_subject(self):
        frame = _frame_from("#=\nPasswordAuthentication = false;")
        assert frame.subject == "PasswordAuthentication"

    def test_non_default_option_fills_deviation(self):
        frame = _frame_from("#| *prohibit-password|no|**yes\nPermitRootLogin = \"prohibit-password\";")
        assert frame.deviation == "prohibit-password"

    def test_default_option_no_deviation(self):
        frame = _frame_from("#| ***22|2222|443\nports = [ 22 ];")
        assert frame.deviation is None

    def test_conflict_arrow_fills_conflict(self):
        frame = _frame_from("#?\n#>< ForwardAgent\nX11 = false;")
        assert frame.conflict == "ForwardAgent"

    def test_cross_file_dep_fills_role(self):
        frame = _frame_from("#?\n#> ../fw.nix:networking.firewall\nX = 1;")
        assert frame.role == "cross-file"

    def test_gate_dep_fills_role(self):
        frame = _frame_from("#?\n#>> settings\nX = 1;")
        assert frame.role == "gates settings"

    def test_gated_by_fills_role(self):
        frame = _frame_from("#?\n#<< enable\nX = 1;")
        assert frame.role == "gated by enable"

    def test_soft_free_text_fills_note(self):
        frame = _frame_from("#? preference — toggle for debugging\nX = 1;")
        assert frame.note == "preference — toggle for debugging"

    def test_hard_constraint_takes_priority_over_soft(self):
        frame = _frame_from("#= by:sec-team | for:SOC2\n#? by:anyone\nX = 1;")
        assert frame.posture == "locked"
        assert frame.authority == "sec-team"
        assert frame.reason == "SOC2"

    def test_multiple_hard_constraints_first_grant_wins(self):
        frame = _frame_from("#= by:sec-team | for:SOC2\n#= by:crypto | for:FIPS\nX = 1;")
        assert frame.reason == "SOC2"
        assert frame.authority == "sec-team"


# === End-to-end annotation tests ===

class TestAnnotateFile:
    """Test full pipeline: file → suggestions."""

    def test_unannotated_hard_constraint(self):
        suggestions = _annotate("""\
services.openssh = {
  #= by:security-team | for:SOC2-CC6.1
  PasswordAuthentication = false;
};
""")
        assert len(suggestions) >= 1
        assert "locked" in suggestions[0].lower()
        assert "SOC2-CC6.1" in suggestions[0]
        assert "security-team" in suggestions[0]

    def test_unannotated_soft_constraint(self):
        suggestions = _annotate("""\
#? by:anyone
UseDns = true;
""")
        assert len(suggestions) >= 1
        assert "soft" in suggestions[0].lower()
        assert "anyone" in suggestions[0]

    def test_fully_annotated_no_suggestions(self):
        suggestions = _annotate("""\
#! hardened SSH
services.openssh = {
  #= by:security-team
  PasswordAuthentication = false;
};
""")
        assert len(suggestions) == 0

    def test_no_hatc_no_suggestions(self):
        suggestions = _annotate("""\
{ config, ... }:
{
  services.openssh.enable = true;
}
""")
        assert len(suggestions) == 0

    def test_option_deviation_in_suggestion(self):
        suggestions = _annotate("""\
#= by:sec
#| *prohibit-password|no|**yes
PermitRootLogin = "prohibit-password";
""")
        assert len(suggestions) == 1
        assert "non-default prohibit-password" in suggestions[0]

    def test_conflict_in_suggestion(self):
        suggestions = _annotate("""\
#? preference
#>< ForwardAgent
X11Forwarding = false;
""")
        assert len(suggestions) == 1
        assert "conflicts with ForwardAgent" in suggestions[0]

    def test_cross_file_dep_in_suggestion(self):
        suggestions = _annotate("""\
#? by:anyone
#> ../network/firewall.nix:networking.firewall.allowedTCPPorts
openFirewall = true;
""")
        assert len(suggestions) == 1
        assert "cross-file" in suggestions[0]

    def test_expiry_in_suggestion(self):
        suggestions = _annotate("""\
#= by:team-lead | until:Q2-migration
ports = [ 22 ];
""")
        assert len(suggestions) == 1
        assert "until Q2-migration" in suggestions[0]

    def test_gate_dep_in_suggestion(self):
        suggestions = _annotate("""\
#? preference
#>> settings
enable = true;
""")
        assert len(suggestions) == 1
        assert "gates settings" in suggestions[0]

    def test_multiple_blocks_multiple_suggestions(self):
        suggestions = _annotate("""\
services.openssh = {
  #= by:security-team | for:SOC2-CC6.1
  PasswordAuthentication = false;

  #= by:crypto-team | for:FIPS-140-2
  Ciphers = [ "aes256-gcm@openssh.com" ];

  #? by:anyone
  UseDns = true;
};
""")
        assert len(suggestions) >= 3

    def test_annotated_block_children_not_suggested(self):
        """Blocks under a #! intent should not get their own suggestions."""
        suggestions = _annotate("""\
#! hardened SSH
services.openssh = {
  #= by:security-team | for:SOC2-CC6.1
  PasswordAuthentication = false;

  #= by:crypto-team | for:FIPS-140-2
  Ciphers = [ "aes256-gcm@openssh.com" ];
};
""")
        assert len(suggestions) == 0

    def test_bare_hard_constraint_no_grant(self):
        suggestions = _annotate("""\
#=
PasswordAuthentication = false;
""")
        assert len(suggestions) == 1
        assert "locked" in suggestions[0].lower()
        assert "PasswordAuthentication" in suggestions[0]

    def test_suggestion_line_numbers(self):
        suggestions = _annotate("""\
## regular comment
#= by:sec | for:SOC2
PasswordAuthentication = false;
""")
        assert len(suggestions) >= 1
        assert suggestions[0].startswith("Line 2:")

    def test_triple_star_no_deviation(self):
        """***value means active AND default — no deviation signal."""
        suggestions = _annotate("""\
#? preference
#| ***false|true
PasswordAuthentication = false;
""")
        assert len(suggestions) == 1
        assert "non-default" not in suggestions[0]
