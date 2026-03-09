"""Data models for parsed HATC annotations."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Intent:
    """#! — why this block/option exists."""
    text: str
    line: int


@dataclass
class Grant:
    """Structured fields on #= and #? constraints."""
    by: str | None = None
    for_: str | None = None
    until: str | None = None


@dataclass
class Constraint:
    """#= (hard) or #? (soft) constraint with optional grant."""
    hard: bool
    text: str
    grant: Grant
    line: int


@dataclass
class Dependency:
    """#> #< #<> #>> #<< #>< — dependency arrow."""
    arrow: str
    target: str
    line: int


@dataclass
class OptionValue:
    """A single value in an option space."""
    value: str
    active: bool = False
    default: bool = False


@dataclass
class OptionSpace:
    """#| — valid alternatives with selection markers."""
    options: list[OptionValue]
    line: int


@dataclass
class Rationale:
    """#~ — history, reasoning, links."""
    text: str
    line: int


@dataclass
class Block:
    """A group of HATC annotations attached to a code block."""
    intent: Intent | None = None
    constraints: list[Constraint] = field(default_factory=list)
    dependencies: list[Dependency] = field(default_factory=list)
    options: list[OptionSpace] = field(default_factory=list)
    rationales: list[Rationale] = field(default_factory=list)
    file: str = ""
    start_line: int = 0
    end_line: int = 0
