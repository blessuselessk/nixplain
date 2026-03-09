"""Static intent annotator — suggests #! lines for unannotated blocks."""

from __future__ import annotations

from pathlib import Path

from .models import Block
from .parser import parse_lines


def annotate_file(filepath: str | Path) -> list[str]:
    """Analyze a file and return suggested #! annotations for unannotated blocks.

    Uses static analysis signals:
    - Count and type of constraints
    - Dependency graph shape
    - Attribute names in the surrounding code
    """
    filepath = Path(filepath)
    lines = filepath.read_text().splitlines()
    blocks = parse_lines(lines, str(filepath))

    # Find blocks that have annotations but no intent
    suggestions: list[str] = []
    for block in blocks:
        if block.intent:
            continue
        if not (block.constraints or block.dependencies or block.options or block.rationales):
            continue

        suggestion = _generate_suggestion(block, lines)
        if suggestion:
            suggestions.append(
                f"Line {block.start_line}: #! {suggestion}"
            )

    return suggestions


def _generate_suggestion(block: Block, lines: list[str]) -> str | None:
    """Generate a candidate #! line from static signals."""
    signals: list[str] = []

    # Constraint analysis
    hard = [c for c in block.constraints if c.hard]
    soft = [c for c in block.constraints if not c.hard]
    if hard:
        reasons = []
        for c in hard:
            if c.grant.for_:
                reasons.append(c.grant.for_)
        if reasons:
            signals.append(f"{len(hard)} hard constraints ({', '.join(reasons)})")
        else:
            signals.append(f"{len(hard)} hard constraints")
    if soft:
        signals.append(f"{len(soft)} soft constraints")

    # Dependency analysis
    if block.dependencies:
        cross_file = [d for d in block.dependencies if ":" in d.target or "/" in d.target]
        if cross_file:
            signals.append(f"cross-file deps")
        else:
            signals.append(f"{len(block.dependencies)} local deps")

    # Option space analysis
    for opt in block.options:
        non_default = [o for o in opt.options if o.active and not o.default]
        if non_default:
            signals.append(f"non-default: {non_default[0].value}")

    # Try to find the attribute name from the code line following the block
    attr_name = _find_attribute_name(block, lines)
    if attr_name:
        prefix = attr_name
    else:
        prefix = "block"

    if not signals:
        return None

    return f"{prefix} ({', '.join(signals)})"


def _find_attribute_name(block: Block, lines: list[str]) -> str | None:
    """Try to extract the attribute name from the line following annotations."""
    # Look at lines around end_line for an assignment
    for i in range(block.start_line - 1, min(block.end_line + 1, len(lines))):
        line = lines[i].strip()
        # Skip HATC comments and blanks
        if line.startswith("#") or not line:
            continue
        # Look for Nix assignment: name = value;
        if "=" in line:
            name = line.split("=")[0].strip().rstrip("{").strip()
            if name and not name.startswith("#"):
                return name
    return None
