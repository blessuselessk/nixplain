"""AGENTS.md compiler — generates index from HATC-annotated files."""

from __future__ import annotations

from pathlib import Path

from .models import Block
from .parser import parse_file


def compile_directory(directory: str | Path) -> str:
    """Walk a directory for .nix files, parse HATC annotations, and generate AGENTS.md."""
    directory = Path(directory)
    nix_files = sorted(directory.rglob("*.nix"))

    all_blocks: dict[Path, list[Block]] = {}
    for nix_file in nix_files:
        blocks = parse_file(nix_file)
        if blocks:
            all_blocks[nix_file] = blocks

    return _emit_agents_md(directory, all_blocks)


def _emit_agents_md(base: Path, file_blocks: dict[Path, list[Block]]) -> str:
    """Emit AGENTS.md content from parsed blocks."""
    sections: list[str] = ["# AGENTS.md", "", "Auto-generated from HATC annotations.", ""]

    # Group files by directory
    dirs: dict[Path, list[Path]] = {}
    for fpath in sorted(file_blocks.keys()):
        rel = fpath.relative_to(base)
        parent = rel.parent
        dirs.setdefault(parent, []).append(fpath)

    for dir_path in sorted(dirs.keys()):
        dir_label = str(dir_path) + "/" if str(dir_path) != "." else "./"
        sections.append(f"## {dir_label}")
        sections.append("")

        for fpath in dirs[dir_path]:
            rel = fpath.relative_to(base)
            sections.append(f"### {rel.name}")
            sections.append(f"@{rel}")

            blocks = file_blocks[fpath]
            for block in blocks:
                if block.intent:
                    sections.append(f"#! {block.intent.text}")
            sections.append("")

    # Cross-file dependency map
    cross_deps = _extract_cross_file_deps(base, file_blocks)
    if cross_deps:
        sections.append("## Cross-file dependencies")
        sections.append("")
        for dep_line in cross_deps:
            sections.append(dep_line)
        sections.append("")

    return "\n".join(sections)


def _extract_cross_file_deps(
    base: Path, file_blocks: dict[Path, list[Block]]
) -> list[str]:
    """Extract dependency arrows that reference other files."""
    seen: set[str] = set()
    deps: list[str] = []
    arrow_symbols = {
        ">": "→",
        "<": "←",
        "<>": "↔",
        ">>": "⇒",
        "<<": "⇐",
        "><": "⊗",
    }
    for fpath, blocks in sorted(file_blocks.items()):
        rel = fpath.relative_to(base)
        for block in blocks:
            for dep in block.dependencies:
                # Cross-file deps contain ':' or '/' in the target
                if ":" in dep.target or "/" in dep.target:
                    symbol = arrow_symbols.get(dep.arrow, dep.arrow)
                    source = f"{rel.name}"
                    line = f"{source} {symbol} {dep.target}"
                    if line not in seen:
                        seen.add(line)
                        deps.append(line)
    return deps
