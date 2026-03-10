"""Tests for the Nix semantic extractor."""

from pathlib import Path
from textwrap import dedent
import tempfile

import pytest

from hatc.extractor import extract_file, extract_blocks, signals_to_blocks, NixSignal


FIXTURE = Path(__file__).parent.parent / "example" / "ssh-bare.nix"


def _parse(code: str) -> list[NixSignal]:
    """Helper: write code to a temp file and extract signals."""
    with tempfile.NamedTemporaryFile(suffix=".nix", mode="w", delete=False) as f:
        f.write(dedent(code))
        f.flush()
        return extract_file(Path(f.name))


# ---- Signal extraction tests ----

class TestMkForce:
    def test_detects_mkforce(self):
        signals = _parse("""
            { lib, ... }: {
              services.foo = lib.mkForce true;
            }
        """)
        assert len(signals) == 1
        assert signals[0].kind == "mkForce"
        assert signals[0].attrpath == "services.foo"
        assert signals[0].value == "true"

    def test_nested_mkforce(self):
        signals = _parse("""
            { lib, ... }: {
              services.ssh.settings = {
                PasswordAuth = lib.mkForce false;
              };
            }
        """)
        mk = [s for s in signals if s.kind == "mkForce"]
        assert len(mk) == 1
        assert mk[0].attrpath == "services.ssh.settings.PasswordAuth"


class TestMkDefault:
    def test_detects_mkdefault(self):
        signals = _parse("""
            { lib, ... }: {
              services.foo = lib.mkDefault "bar";
            }
        """)
        assert len(signals) == 1
        assert signals[0].kind == "mkDefault"
        assert signals[0].value == '"bar"'

    def test_mkdefault_bool(self):
        signals = _parse("""
            { lib, ... }: {
              x = lib.mkDefault false;
            }
        """)
        assert signals[0].kind == "mkDefault"
        assert signals[0].value == "false"


class TestMkOverride:
    def test_low_priority(self):
        signals = _parse("""
            { lib, ... }: {
              services.foo = lib.mkOverride 50 true;
            }
        """)
        assert len(signals) == 1
        assert signals[0].kind == "mkOverride"
        assert signals[0].priority == 50

    def test_high_priority(self):
        signals = _parse("""
            { lib, ... }: {
              services.foo = lib.mkOverride 1000 false;
            }
        """)
        assert signals[0].priority == 1000


class TestMkIf:
    def test_detects_mkif_guard(self):
        signals = _parse("""
            { config, lib, ... }: {
              services.foo = lib.mkIf config.services.bar.enable {
                baz = true;
              };
            }
        """)
        mkif = [s for s in signals if s.kind == "mkIf"]
        assert len(mkif) == 1
        assert mkif[0].guard == "config.services.bar.enable"

    def test_mkif_recurses_into_body(self):
        signals = _parse("""
            { config, lib, ... }: {
              services.foo = lib.mkIf config.bar.enable {
                x = lib.mkForce true;
              };
            }
        """)
        kinds = [s.kind for s in signals]
        assert "mkIf" in kinds
        assert "mkForce" in kinds

    def test_mkif_body_attrpath(self):
        signals = _parse("""
            { config, lib, ... }: {
              services.foo = lib.mkIf config.bar.enable {
                x = lib.mkForce true;
              };
            }
        """)
        mk = [s for s in signals if s.kind == "mkForce"]
        assert mk[0].attrpath == "services.foo.x"


class TestImports:
    def test_detects_imports(self):
        signals = _parse("""
            { ... }: {
              imports = [ ./hardware.nix ./networking.nix ];
            }
        """)
        imports = [s for s in signals if s.kind == "import"]
        assert len(imports) == 2
        assert imports[0].value == "./hardware.nix"
        assert imports[1].value == "./networking.nix"


class TestAssertions:
    def test_detects_assertion(self):
        signals = _parse("""
            { config, ... }: {
              assertions = [{
                assertion = config.foo == true;
                message = "foo must be enabled";
              }];
            }
        """)
        asserts = [s for s in signals if s.kind == "assertion"]
        assert len(asserts) == 1
        assert asserts[0].message == "foo must be enabled"

    def test_assertion_without_message(self):
        signals = _parse("""
            { config, ... }: {
              assertions = [{
                assertion = config.foo == true;
              }];
            }
        """)
        asserts = [s for s in signals if s.kind == "assertion"]
        assert len(asserts) == 1
        assert asserts[0].message is None


# ---- Signal → Block mapping tests ----

class TestSignalToBlock:
    def test_mkforce_to_hard_constraint(self):
        sig = NixSignal(kind="mkForce", attrpath="a.b", line=1, value="true")
        blocks = signals_to_blocks([sig])
        assert len(blocks) == 1
        assert len(blocks[0].constraints) == 1
        assert blocks[0].constraints[0].hard is True

    def test_mkdefault_to_soft_constraint(self):
        sig = NixSignal(kind="mkDefault", attrpath="a.b", line=1, value="false")
        blocks = signals_to_blocks([sig])
        assert blocks[0].constraints[0].hard is False

    def test_mkoverride_low_is_hard(self):
        sig = NixSignal(kind="mkOverride", attrpath="a.b", line=1, priority=50)
        blocks = signals_to_blocks([sig])
        assert blocks[0].constraints[0].hard is True

    def test_mkoverride_high_is_soft(self):
        sig = NixSignal(kind="mkOverride", attrpath="a.b", line=1, priority=1000)
        blocks = signals_to_blocks([sig])
        assert blocks[0].constraints[0].hard is False

    def test_mkif_to_gated_dependency(self):
        sig = NixSignal(kind="mkIf", attrpath="a.b", line=1, guard="config.x.enable")
        blocks = signals_to_blocks([sig])
        assert len(blocks[0].dependencies) == 1
        assert blocks[0].dependencies[0].arrow == "<<"
        assert blocks[0].dependencies[0].target == "config.x.enable"

    def test_import_to_dependency(self):
        sig = NixSignal(kind="import", attrpath="imports", line=1, value="./foo.nix")
        blocks = signals_to_blocks([sig])
        assert blocks[0].dependencies[0].arrow == ">"
        assert blocks[0].dependencies[0].target == "./foo.nix"

    def test_assertion_to_constraint_and_rationale(self):
        sig = NixSignal(kind="assertion", attrpath="assertions", line=1,
                        value="config.x == false", message="compliance requirement")
        blocks = signals_to_blocks([sig])
        assert blocks[0].constraints[0].hard is True
        assert len(blocks[0].rationales) == 1
        assert blocks[0].rationales[0].text == "compliance requirement"


# ---- End-to-end fixture test ----

class TestFixture:
    def test_ssh_bare_signal_count(self):
        signals = extract_file(FIXTURE)
        assert len(signals) >= 7  # import, 2x mkForce, 2x mkDefault, mkIf, assertion

    def test_ssh_bare_signal_kinds(self):
        signals = extract_file(FIXTURE)
        kinds = {s.kind for s in signals}
        assert "import" in kinds
        assert "mkForce" in kinds
        assert "mkDefault" in kinds
        assert "mkIf" in kinds
        assert "assertion" in kinds

    def test_ssh_bare_blocks(self):
        blocks = extract_blocks(FIXTURE)
        assert len(blocks) >= 7
        hard = [b for b in blocks for c in b.constraints if c.hard]
        soft = [b for b in blocks for c in b.constraints if not c.hard]
        deps = [b for b in blocks for d in b.dependencies]
        assert len(hard) >= 3   # 2x mkForce + 1 assertion
        assert len(soft) >= 2   # 2x mkDefault
        assert len(deps) >= 2   # 1 import + 1 mkIf

    def test_mkif_guard_path(self):
        signals = extract_file(FIXTURE)
        mkif = [s for s in signals if s.kind == "mkIf"]
        assert len(mkif) == 1
        assert mkif[0].guard == "config.services.openssh.enable"

    def test_assertion_message(self):
        signals = extract_file(FIXTURE)
        asserts = [s for s in signals if s.kind == "assertion"]
        assert len(asserts) == 1
        assert "compliance" in asserts[0].message
