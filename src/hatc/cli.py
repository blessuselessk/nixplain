"""HATC CLI — parse, compile, annotate."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

import click

from .annotator import annotate_file
from .compiler import compile_directory
from .extractor import extract_file, extract_blocks
from .parser import parse_file


def _blocks_to_dicts(blocks) -> list[dict]:
    return [asdict(b) for b in blocks]


def _compact(data: list[dict]) -> list[dict]:
    """Strip nulls, empty lists, empty strings, and flatten grants for TOON."""
    out = []
    for block in data:
        b: dict = {}

        # Intent — just the text and line, or omit entirely
        if block.get("intent"):
            b["intent"] = block["intent"]["text"]
            b["intent_line"] = block["intent"]["line"]

        # Constraints — flatten grant fields into the constraint
        if block.get("constraints"):
            rows = []
            for c in block["constraints"]:
                row: dict = {"hard": c["hard"], "line": c["line"]}
                if c.get("text"):
                    row["text"] = c["text"]
                grant = c.get("grant", {})
                if grant.get("by"):
                    row["by"] = grant["by"]
                if grant.get("for_"):
                    row["for"] = grant["for_"]
                if grant.get("until"):
                    row["until"] = grant["until"]
                rows.append(row)
            b["constraints"] = rows

        # Dependencies — already flat, just pass through
        if block.get("dependencies"):
            b["deps"] = block["dependencies"]

        # Options — flatten into compact form
        if block.get("options"):
            rows = []
            for opt in block["options"]:
                rows.append({
                    "line": opt["line"],
                    "values": [
                        _compact_option(o) for o in opt["options"]
                    ],
                })
            b["options"] = rows

        # Rationales — just text and line
        if block.get("rationales"):
            b["rationales"] = block["rationales"]

        b["file"] = block["file"]
        b["lines"] = [block["start_line"], block["end_line"]]

        out.append(b)
    return out


def _compact_option(o: dict) -> str:
    """Encode an option value with markers as a single string."""
    v = o["value"]
    if o["active"] and o["default"]:
        return f"***{v}"
    if o["default"]:
        return f"**{v}"
    if o["active"]:
        return f"*{v}"
    return v


def _serialize(data, fmt: str) -> str:
    if fmt == "toon":
        from toon_format import encode
        return encode(_compact(data))
    return json.dumps(data, indent=2)


@click.group()
@click.version_option(package_name="hatc")
def cli():
    """HATC — Human-Agent Teaming Comments toolchain."""


@cli.command()
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option("-f", "--format", "fmt", type=click.Choice(["json", "toon"]), default="json",
              help="Output format (default: json)")
def parse(file: Path, fmt: str):
    """Parse HATC annotations from a file."""
    blocks = parse_file(file)
    click.echo(_serialize(_blocks_to_dicts(blocks), fmt))


@cli.command()
@click.argument("directory", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("-o", "--output", type=click.Path(path_type=Path), default=None,
              help="Output file (default: stdout)")
@click.option("--bare", is_flag=True, default=False,
              help="Extract from bare .nix files (no HATC comments needed)")
@click.option("--enrich", is_flag=True, default=False,
              help="Use nix-why LLM to generate intents (implies --bare)")
def compile(directory: Path, output: Path | None, bare: bool, enrich: bool):
    """Compile HATC annotations into AGENTS.md."""
    if enrich:
        bare = True

    if bare:
        from .enricher import enrich_blocks, find_nix_why
        from .extractor import extract_file as ext_file, signals_to_blocks

        nix_why = find_nix_why() if enrich else None

        def bare_source(path: Path) -> list:
            sigs = ext_file(path)
            blocks = signals_to_blocks(sigs, file=str(path))
            if enrich and nix_why:
                enrich_blocks(sigs, blocks, nix_why)
            return blocks

        content = compile_directory(directory, block_source=bare_source)
    else:
        content = compile_directory(directory)

    if output:
        output.write_text(content)
        click.echo(f"Wrote {output}")
    else:
        click.echo(content)


@cli.command()
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option("--refine", is_flag=True, default=False,
              help="Use LLM (Claude) to refine static signals into human-quality intents")
def annotate(file: Path, refine: bool):
    """Suggest #! intent annotations for unannotated blocks."""
    suggestions = annotate_file(file, refine=refine)
    if suggestions:
        for s in suggestions:
            click.echo(s)
    else:
        click.echo("No suggestions — all blocks are annotated or have no HATC tags.")


@cli.command()
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option("-f", "--format", "fmt", type=click.Choice(["json", "toon"]), default="json",
              help="Output format (default: json)")
@click.option("--signals", is_flag=True, default=False,
              help="Output raw NixSignals instead of HATC blocks")
@click.option("--nixf", "use_nixf", is_flag=True, default=False,
              help="Include nixf semantic diagnostics (requires nixf-tidy)")
@click.option("--enrich", is_flag=True, default=False,
              help="Use nix-why LLM to generate intent/posture/rationale for each signal")
def extract(file: Path, fmt: str, signals: bool, use_nixf: bool, enrich: bool):
    """Extract Nix module-system semantics from bare .nix files."""
    sigs = extract_file(file)

    if signals and not enrich:
        from dataclasses import asdict
        data = [asdict(s) for s in sigs]
    else:
        blocks = extract_blocks(file)

        if enrich:
            from .enricher import enrich_blocks
            blocks = enrich_blocks(sigs, blocks)

        data = _blocks_to_dicts(blocks)

    if use_nixf:
        from .nixf import analyze_file as nixf_analyze, enrich_signals
        diagnostics = nixf_analyze(file)
        enrichments = enrich_signals([], diagnostics)
        output = {"blocks" if not signals else "signals": data, "nixf": enrichments}
        click.echo(json.dumps(output, indent=2))
        return

    click.echo(_serialize(data, fmt))


def main():
    cli()
