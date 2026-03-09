"""HATC CLI — parse, compile, annotate."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

import click

from .annotator import annotate_file
from .compiler import compile_directory
from .parser import parse_file


def _blocks_to_dicts(blocks) -> list[dict]:
    return [asdict(b) for b in blocks]


def _serialize(data, fmt: str) -> str:
    if fmt == "toon":
        from toon_format import encode
        return encode(data)
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
def compile(directory: Path, output: Path | None):
    """Compile HATC annotations into AGENTS.md."""
    content = compile_directory(directory)
    if output:
        output.write_text(content)
        click.echo(f"Wrote {output}")
    else:
        click.echo(content)


@cli.command()
@click.argument("file", type=click.Path(exists=True, path_type=Path))
def annotate(file: Path):
    """Suggest #! intent annotations for unannotated blocks."""
    suggestions = annotate_file(file)
    if suggestions:
        for s in suggestions:
            click.echo(s)
    else:
        click.echo("No suggestions — all blocks are annotated or have no HATC tags.")


def main():
    cli()
