"""Tests for the HATC comment injector."""

from nixplain.injector import inject_comments, blocks_to_comments
from nixplain.models import Block, Constraint, Dependency, Grant, Intent, Rationale


class TestBlocksToComments:
    def test_intent_only(self):
        block = Block(intent=Intent(text="Force-enable SSH", line=8),
                      start_line=8, end_line=8)
        assert blocks_to_comments(block) == ["#! Force-enable SSH"]

    def test_hard_constraint(self):
        block = Block(constraints=[Constraint(hard=True, text="", grant=Grant(), line=8)],
                      start_line=8, end_line=8)
        assert "#=" in blocks_to_comments(block)

    def test_soft_constraint(self):
        block = Block(constraints=[Constraint(hard=False, text="", grant=Grant(), line=8)],
                      start_line=8, end_line=8)
        assert "#?" in blocks_to_comments(block)

    def test_constraint_with_text(self):
        block = Block(constraints=[Constraint(hard=True, text="reason", grant=Grant(), line=8)],
                      start_line=8, end_line=8)
        assert "#= reason" in blocks_to_comments(block)

    def test_dependency(self):
        block = Block(dependencies=[Dependency(arrow="<<", target="config.x", line=8)],
                      start_line=8, end_line=8)
        assert "#<< config.x" in blocks_to_comments(block)

    def test_rationale(self):
        block = Block(rationales=[Rationale(text="because reasons", line=8)],
                      start_line=8, end_line=8)
        assert "#~ because reasons" in blocks_to_comments(block)

    def test_full_block(self):
        block = Block(
            intent=Intent(text="Lock SSH", line=8),
            constraints=[Constraint(hard=True, text="", grant=Grant(), line=8)],
            dependencies=[Dependency(arrow="<<", target="enable", line=8)],
            rationales=[Rationale(text="security", line=8)],
            start_line=8, end_line=8,
        )
        comments = blocks_to_comments(block)
        assert comments[0] == "#! Lock SSH"
        assert "#=" in comments
        assert "#<< enable" in comments
        assert "#~ security" in comments

    def test_empty_block(self):
        block = Block(start_line=8, end_line=8)
        assert blocks_to_comments(block) == []


class TestInjectComments:
    def test_injects_before_target_line(self):
        source = ["{ ... }:", "{", "  x = 1;", "}"]
        block = Block(intent=Intent(text="set x", line=3), start_line=3, end_line=3)
        result = inject_comments(source, [block])
        assert result[2] == "  #! set x"
        assert result[3] == "  x = 1;"

    def test_preserves_indentation(self):
        source = ["    deeply = nested;"]
        block = Block(intent=Intent(text="deep", line=1), start_line=1, end_line=1)
        result = inject_comments(source, [block])
        assert result[0] == "    #! deep"

    def test_no_blocks_returns_unchanged(self):
        source = ["line1", "line2"]
        result = inject_comments(source, [])
        assert result == source

    def test_multiple_blocks_different_lines(self):
        source = ["a = 1;", "b = 2;"]
        blocks = [
            Block(intent=Intent(text="first", line=1), start_line=1, end_line=1),
            Block(intent=Intent(text="second", line=2), start_line=2, end_line=2),
        ]
        result = inject_comments(source, blocks)
        assert len(result) == 4
        assert result[0] == "#! first"
        assert result[2] == "#! second"

    def test_multiple_comments_same_line(self):
        source = ["  x = lib.mkForce true;"]
        block = Block(
            intent=Intent(text="force x", line=1),
            constraints=[Constraint(hard=True, text="", grant=Grant(), line=1)],
            start_line=1, end_line=1,
        )
        result = inject_comments(source, [block])
        assert len(result) == 3  # #!, #=, original
        assert result[0] == "  #! force x"
        assert result[1] == "  #="
