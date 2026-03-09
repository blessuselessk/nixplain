"""Tests for the HATC parser against example/ssh.nix."""

from pathlib import Path

from hatc.parser import parse_file, parse_lines
from hatc.models import Block

EXAMPLE = Path(__file__).parent.parent / "example" / "ssh.nix"


def test_parse_example_returns_blocks():
    blocks = parse_file(EXAMPLE)
    assert len(blocks) > 0


def test_intent_blocks_found():
    blocks = parse_file(EXAMPLE)
    intents = [b for b in blocks if b.intent]
    # At least the top-level and services.openssh intents
    assert len(intents) >= 2
    texts = [b.intent.text for b in intents]
    assert "hardened remote deployment target" in texts
    assert "minimal attack surface SSH" in texts


def test_hard_constraints_parsed():
    blocks = parse_file(EXAMPLE)
    all_constraints = []
    for b in blocks:
        all_constraints.extend(b.constraints)
    hard = [c for c in all_constraints if c.hard]
    assert len(hard) >= 3  # security-team x2 + crypto-team


def test_grant_fields_parsed():
    blocks = parse_file(EXAMPLE)
    all_constraints = []
    for b in blocks:
        all_constraints.extend(b.constraints)
    # Find the SOC2 constraint
    soc2 = [c for c in all_constraints if c.grant.for_ == "SOC2-CC6.1"]
    assert len(soc2) >= 1
    assert soc2[0].grant.by == "security-team"


def test_soft_constraints_parsed():
    blocks = parse_file(EXAMPLE)
    all_constraints = []
    for b in blocks:
        all_constraints.extend(b.constraints)
    soft = [c for c in all_constraints if not c.hard]
    assert len(soft) >= 2  # "preference" and "by:anyone"


def test_dependency_arrows_parsed():
    blocks = parse_file(EXAMPLE)
    all_deps = []
    for b in blocks:
        all_deps.extend(b.dependencies)
    arrows = {d.arrow for d in all_deps}
    assert ">>" in arrows
    assert ">" in arrows
    assert "<>" in arrows
    assert "<<" in arrows
    assert "><" in arrows


def test_cross_file_deps():
    blocks = parse_file(EXAMPLE)
    all_deps = []
    for b in blocks:
        all_deps.extend(b.dependencies)
    cross = [d for d in all_deps if ":" in d.target]
    assert len(cross) >= 1
    assert any("firewall" in d.target for d in cross)


def test_option_spaces_parsed():
    blocks = parse_file(EXAMPLE)
    all_opts = []
    for b in blocks:
        all_opts.extend(b.options)
    assert len(all_opts) >= 3  # ports, PasswordAuth, PermitRootLogin, X11, UseDns

    # Check the PermitRootLogin option space
    permit_opts = None
    for opt in all_opts:
        values = [o.value for o in opt.options]
        if "prohibit-password" in values:
            permit_opts = opt
            break
    assert permit_opts is not None
    assert len(permit_opts.options) == 4
    active = [o for o in permit_opts.options if o.active]
    assert len(active) == 1
    assert active[0].value == "prohibit-password"
    defaults = [o for o in permit_opts.options if o.default]
    assert len(defaults) == 1
    assert defaults[0].value == "yes"


def test_triple_star_active_and_default():
    blocks = parse_file(EXAMPLE)
    all_opts = []
    for b in blocks:
        all_opts.extend(b.options)
    # The ports option: ***22|2222|443
    port_opts = None
    for opt in all_opts:
        values = [o.value for o in opt.options]
        if "22" in values and "2222" in values:
            port_opts = opt
            break
    assert port_opts is not None
    twenty_two = [o for o in port_opts.options if o.value == "22"][0]
    assert twenty_two.active is True
    assert twenty_two.default is True


def test_rationale_parsed():
    blocks = parse_file(EXAMPLE)
    all_rationales = []
    for b in blocks:
        all_rationales.extend(b.rationales)
    assert len(all_rationales) >= 1
    assert any("team preference" in r.text for r in all_rationales)


def test_parse_gate_dependency():
    """#>> should parse as gate arrow."""
    lines = [
        "#>> settings|openFirewall",
        "enable = true;",
    ]
    blocks = parse_lines(lines)
    all_deps = []
    for b in blocks:
        all_deps.extend(b.dependencies)
    gates = [d for d in all_deps if d.arrow == ">>"]
    assert len(gates) >= 1


def test_aliases_accepted():
    """Keyword aliases should parse identically to tag characters."""
    lines_tag = ["#! hardened SSH", "#= by:security-team"]
    lines_alias = ["#intent: hardened SSH", "#hard: by:security-team"]
    blocks_tag = parse_lines(lines_tag)
    blocks_alias = parse_lines(lines_alias)
    assert blocks_tag[0].intent.text == blocks_alias[0].intent.text
