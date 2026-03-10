"""Inject HATC comments into bare .nix files from extracted+enriched blocks."""

from __future__ import annotations

from pathlib import Path

from .models import Block


def blocks_to_comments(block: Block) -> list[str]:
    """Convert an enriched Block into HATC comment lines."""
    comments: list[str] = []

    if block.intent:
        comments.append(f"#! {block.intent.text}")

    for c in block.constraints:
        tag = "#=" if c.hard else "#?"
        if c.text:
            comments.append(f"{tag} {c.text}")
        else:
            comments.append(tag)

    for d in block.dependencies:
        comments.append(f"#{d.arrow} {d.target}")

    for r in block.rationales:
        comments.append(f"#~ {r.text}")

    return comments


def inject_comments(source_lines: list[str], blocks: list[Block]) -> list[str]:
    """Insert HATC comment lines above the code lines they annotate.

    Returns a new list of lines with comments injected.
    """
    # Build insertion map: line_number → list of comment strings
    insertions: dict[int, list[str]] = {}
    for block in blocks:
        comments = blocks_to_comments(block)
        if not comments:
            continue
        line = block.start_line  # 1-indexed
        insertions.setdefault(line, []).extend(comments)

    # Build output, inserting comments before their target lines
    output: list[str] = []
    for i, line in enumerate(source_lines):
        line_num = i + 1  # 1-indexed
        if line_num in insertions:
            # Match indentation of the code line
            stripped = line.lstrip()
            indent = line[:len(line) - len(stripped)] if stripped else "    "
            for comment in insertions[line_num]:
                output.append(f"{indent}{comment}")
        output.append(line)

    return output


def inject_file(
    path: Path,
    blocks: list[Block],
    *,
    in_place: bool = False,
) -> str:
    """Inject HATC comments into a .nix file.

    Returns the annotated source. If in_place=True, overwrites the file.
    """
    source_lines = path.read_text().splitlines()
    result_lines = inject_comments(source_lines, blocks)
    result = "\n".join(result_lines) + "\n"

    if in_place:
        path.write_text(result)

    return result
