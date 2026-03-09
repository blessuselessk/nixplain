"""HATC comment parser — extracts annotations from source files."""

from __future__ import annotations

import re
from pathlib import Path

from .models import (
    Block,
    Constraint,
    Dependency,
    Grant,
    Intent,
    OptionSpace,
    OptionValue,
    Rationale,
)

# Tag aliases (keyword and emoji forms map to canonical tags)
_ALIASES = {
    "intent:": "!",
    "hard:": "=",
    "soft:": "?",
    "opt:": "|",
    "why:": "~",
    "\U0001f3af": "!",  # 🎯
    "\U0001f512": "=",  # 🔒
    "\U0001f527": "?",  # 🔧
    "\u2295": "|",      # ⊕
    "\U0001f4ce": "~",  # 📎
}

# Dependency arrows, ordered longest-first for greedy matching
_DEP_ARROWS = ["<<", ">>", "<>", "><", "<", ">"]

# Regex to detect HATC comment lines
_HATC_LINE = re.compile(r"^(\s*)#(.+)$")


def _parse_tag(tag_rest: str) -> tuple[str, str] | None:
    """Parse tag character(s) and content from the part after '#'.

    Returns (canonical_tag, content) or None if not an HATC comment.
    """
    # Check aliases first (keyword and emoji)
    for alias, canonical in _ALIASES.items():
        if tag_rest.startswith(alias):
            return canonical, tag_rest[len(alias):].strip()

    # Check dependency arrows (longest match first)
    for arrow in _DEP_ARROWS:
        if tag_rest.startswith(arrow):
            rest = tag_rest[len(arrow):]
            # Must be followed by space or end-of-string to be HATC
            if not rest or rest[0] == " ":
                return arrow, rest.strip()

    # Single-char tags: ! = ? | ~
    if tag_rest and tag_rest[0] in "!=?|~":
        tag = tag_rest[0]
        rest = tag_rest[1:]
        if not rest or rest[0] == " ":
            return tag, rest.strip()

    return None


def _parse_grant(text: str) -> tuple[str, Grant]:
    """Parse grant fields from constraint content.

    Returns (remaining_text, Grant).
    Text before the first field (or the whole string if no fields) is free text.
    """
    grant = Grant()
    # Split on pipe to find field segments
    parts = [p.strip() for p in text.split("|")]
    free_parts = []

    for part in parts:
        if part.startswith("by:"):
            grant.by = part[3:].strip()
        elif part.startswith("for:"):
            grant.for_ = part[4:].strip()
        elif part.startswith("until:"):
            grant.until = part[6:].strip()
        else:
            free_parts.append(part)

    free_text = " ".join(free_parts).strip()
    return free_text, grant


def _parse_option_space(text: str) -> list[OptionValue]:
    """Parse pipe-delimited option values with markers."""
    values = []
    for raw in text.split("|"):
        raw = raw.strip()
        if not raw:
            continue
        active = False
        default = False
        if raw.startswith("***"):
            active = True
            default = True
            raw = raw[3:]
        elif raw.startswith("**"):
            default = True
            raw = raw[2:]
        elif raw.startswith("*"):
            active = True
            raw = raw[1:]
        values.append(OptionValue(value=raw, active=active, default=default))
    return values


def parse_file(filepath: str | Path) -> list[Block]:
    """Parse a file and return a list of HATC Blocks."""
    filepath = Path(filepath)
    lines = filepath.read_text().splitlines()
    return parse_lines(lines, str(filepath))


def parse_lines(lines: list[str], filename: str = "<string>") -> list[Block]:
    """Parse lines of source code and return HATC Blocks.

    Grouping strategy:
    - A #! intent starts a new block that spans until the next #! or end of its
      brace-delimited scope.
    - Consecutive HATC annotations without a #! are grouped into a block that
      ends at the next non-HATC, non-blank line (the line they annotate).
    """
    blocks: list[Block] = []
    # Track brace depth for scope
    brace_depth = 0
    # Current intent block (scope-level)
    intent_block: Block | None = None
    intent_depth: int = 0
    # Current annotation accumulator (option-level annotations before a code line)
    pending: list[tuple[str, str, int]] = []  # (tag, content, line_number)

    def _flush_pending(end_line: int) -> None:
        nonlocal pending
        if not pending:
            return
        block = Block(file=filename, start_line=pending[0][2], end_line=end_line)
        for tag, content, ln in pending:
            _add_annotation(block, tag, content, ln)
        # If there's an enclosing intent block, nest under it;
        # otherwise emit as standalone
        blocks.append(block)
        pending = []

    for i, line in enumerate(lines):
        lineno = i + 1
        stripped = line.strip()

        # Count braces for scope tracking
        for ch in stripped:
            if ch == "{":
                brace_depth += 1
            elif ch == "}":
                brace_depth -= 1
                # If we've closed the intent block's scope, end it
                if intent_block and brace_depth < intent_depth:
                    intent_block.end_line = lineno
                    intent_block = None

        # Skip regular comments (##) and blank lines
        if stripped.startswith("##") or not stripped:
            continue

        m = _HATC_LINE.match(line)
        if m:
            tag_rest = m.group(2)
            parsed = _parse_tag(tag_rest)
            if parsed:
                tag, content = parsed
                if tag == "!":
                    # Flush any pending option-level annotations
                    _flush_pending(lineno - 1)
                    # Start a new intent block
                    intent_block = Block(
                        intent=Intent(text=content, line=lineno),
                        file=filename,
                        start_line=lineno,
                        end_line=lineno,
                    )
                    intent_depth = brace_depth
                    blocks.append(intent_block)
                else:
                    # If inside an intent block, add to it
                    if intent_block:
                        _add_annotation(intent_block, tag, content, lineno)
                    else:
                        pending.append((tag, content, lineno))
                continue

        # Non-HATC, non-blank line — flush pending annotations
        _flush_pending(lineno)

    # Flush anything remaining
    _flush_pending(len(lines))

    return blocks


def _add_annotation(block: Block, tag: str, content: str, lineno: int) -> None:
    """Add a parsed annotation to a block."""
    if tag == "=":
        text, grant = _parse_grant(content)
        block.constraints.append(Constraint(hard=True, text=text, grant=grant, line=lineno))
    elif tag == "?":
        text, grant = _parse_grant(content)
        block.constraints.append(Constraint(hard=False, text=text, grant=grant, line=lineno))
    elif tag in _DEP_ARROWS:
        # Handle pipe-delimited multiple targets
        targets = [t.strip() for t in content.split("|") if t.strip()]
        for target in targets:
            block.dependencies.append(Dependency(arrow=tag, target=target, line=lineno))
    elif tag == "|":
        options = _parse_option_space(content)
        block.options.append(OptionSpace(options=options, line=lineno))
    elif tag == "~":
        block.rationales.append(Rationale(text=content, line=lineno))
