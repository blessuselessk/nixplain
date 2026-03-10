"""Static intent annotator — synthesizes #! lines from HATC metadata.

Uses frame semantics: each HATC signal fills exactly one typed slot in an
IntentFrame. The render() method is the grammar — the only place where
composition rules live.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import Block
from .parser import parse_lines


@dataclass
class IntentFrame:
    """Semantic frame for intent synthesis. Each field has exactly one source."""

    # From #= or #? tag
    posture: str | None = None          # "locked" | "soft"

    # From attribute name on the code line
    subject: str | None = None          # "PasswordAuthentication"

    # From grant by: field
    authority: str | None = None        # "security-team"

    # From grant for: field
    reason: str | None = None           # "SOC2-CC6.1"

    # From grant until: field
    expiry: str | None = None           # "Q2-migration"

    # From #| active != default
    deviation: str | None = None        # "prohibit-password"

    # From dependency arrow shape
    role: str | None = None             # "cross-file" | "gates X" | "gated by X"

    # From #>< arrows
    conflict: str | None = None         # "ForwardAgent"

    # From #? free text (e.g. "preference — toggle for debugging")
    note: str | None = None

    def render(self) -> str | None:
        """Compose intent from filled slots. This method IS the grammar.

        Pattern:
            [posture] subject [(reason)] [by authority] [until expiry] [— qualifier, ...]
        """
        if not self.subject and not self.posture:
            return None

        # Core: posture + subject
        parts: list[str] = []
        if self.posture:
            parts.append(self.posture)
        if self.subject:
            parts.append(self.subject)

        # Parenthetical: reason, authority, expiry
        parens: list[str] = []
        if self.reason:
            parens.append(self.reason)
        if self.authority:
            parens.append(f"by {self.authority}")
        if self.expiry:
            parens.append(f"until {self.expiry}")
        if parens:
            parts.append(f"({', '.join(parens)})")

        # Qualifiers after em dash
        quals: list[str] = []
        if self.deviation:
            quals.append(f"non-default {self.deviation}")
        if self.conflict:
            quals.append(f"conflicts with {self.conflict}")
        if self.role:
            quals.append(self.role)
        if self.note:
            quals.append(self.note)

        intent = " ".join(parts)
        if quals:
            intent = f"{intent} — {', '.join(quals)}"

        return intent


def annotate_file(filepath: str | Path, *, refine: bool = False) -> list[str]:
    """Analyze a file and return suggested #! annotations.

    Default: deterministic frame-based synthesis from HATC metadata.
    refine=True: optional LLM polish via Anthropic API.
    """
    filepath = Path(filepath)
    lines = filepath.read_text().splitlines()
    blocks = parse_lines(lines, str(filepath))

    suggestions: list[tuple[int, str]] = []
    for block in blocks:
        if block.intent:
            continue
        if not (block.constraints or block.dependencies or block.options or block.rationales):
            continue

        frame = _fill_frame(block, lines)
        intent = frame.render()
        if intent:
            suggestions.append((block.start_line, intent))

    if not suggestions:
        return []

    if refine:
        suggestions = _llm_refine(suggestions)

    return [f"Line {line}: #! {intent}" for line, intent in suggestions]


def _fill_frame(block: Block, lines: list[str]) -> IntentFrame:
    """Fill an IntentFrame from a block's annotations. One source per slot."""
    frame = IntentFrame()

    # Subject: from attribute name
    frame.subject = _find_attribute_name(block, lines)

    # Posture + grant fields: from first constraint
    hard = [c for c in block.constraints if c.hard]
    soft = [c for c in block.constraints if not c.hard]

    if hard:
        frame.posture = "locked"
        # Use first hard constraint's grant for authority/reason/expiry
        for c in hard:
            if c.grant.for_ and not frame.reason:
                frame.reason = c.grant.for_
            if c.grant.by and not frame.authority:
                frame.authority = c.grant.by
            if c.grant.until and not frame.expiry:
                frame.expiry = c.grant.until
    elif soft:
        frame.posture = "soft"
        for c in soft:
            if c.grant.by and not frame.authority:
                frame.authority = c.grant.by
            if c.grant.for_ and not frame.reason:
                frame.reason = c.grant.for_
            if c.grant.until and not frame.expiry:
                frame.expiry = c.grant.until
            # Soft constraint free text as note
            if c.text and not frame.note:
                frame.note = c.text

    # Deviation: from option spaces
    for opt in block.options:
        for o in opt.options:
            if o.active and not o.default:
                frame.deviation = o.value
                break
        if frame.deviation:
            break

    # Role: from dependency shape
    frame.role = _dependency_role(block)

    # Conflict: from #>< arrows
    conflicts = [d.target for d in block.dependencies if d.arrow == "><"]
    if conflicts:
        frame.conflict = ", ".join(conflicts)

    return frame


def _dependency_role(block: Block) -> str | None:
    """Derive role from dependency arrow shape."""
    if not block.dependencies:
        return None

    cross = [d for d in block.dependencies if ":" in d.target or "/" in d.target]
    gates = [d for d in block.dependencies if d.arrow == ">>"]
    gated = [d for d in block.dependencies if d.arrow == "<<"]

    if cross:
        return "cross-file"
    if gates:
        targets = ", ".join(d.target for d in gates)
        return f"gates {targets}"
    if gated:
        sources = ", ".join(sorted(set(d.target for d in gated)))
        return f"gated by {sources}"
    return None


def _find_attribute_name(block: Block, lines: list[str]) -> str | None:
    """Extract the attribute name from the code line after annotations."""
    for i in range(block.start_line - 1, min(block.end_line + 1, len(lines))):
        line = lines[i].strip()
        if line.startswith("#") or not line:
            continue
        if "=" in line:
            name = line.split("=")[0].strip().rstrip("{").strip()
            if name and not name.startswith("#"):
                return name
    return None


# --- Optional LLM refinement ---

def _llm_refine(suggestions: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Optional LLM polish of synthesized intents."""
    try:
        import anthropic
        client = anthropic.Anthropic()
    except Exception:
        import sys
        print("Warning: LLM refinement unavailable, using static intents", file=sys.stderr)
        return suggestions

    refined = []
    for line, intent in suggestions:
        prompt = (
            f"Tighten this #! intent to 10 words or fewer. "
            f"Keep WHY, not WHAT. Preserve compliance refs.\n\n"
            f"Current: #! {intent}\n\n"
            f"Respond with ONLY the text, no #! prefix, no quotes."
        )
        try:
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=50,
                messages=[{"role": "user", "content": prompt}],
            )
            text = msg.content[0].text.strip().lstrip("#!").strip()
            refined.append((line, text))
        except Exception:
            refined.append((line, intent))

    return refined
