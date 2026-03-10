"""Enrich extracted NixSignals with LLM-generated intents via nix-why."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .extractor import NixSignal
from .models import Block, Intent


def find_nix_why() -> str | None:
    """Find nix-why binary: PATH → NIX_WHY env → known nix store path."""
    path = shutil.which("nix-why")
    if path:
        return path
    import os
    env_path = os.environ.get("NIX_WHY")
    if env_path and Path(env_path).exists():
        return env_path
    # Try the flake build output
    store_path = "/nix/store/3wj1s5224m7afy3ra49ywxr134rlj3qd-nix-why-0.1.0/bin/nix-why"
    if Path(store_path).exists():
        return store_path
    return None


def format_signal_input(sig: NixSignal) -> str:
    """Format a NixSignal as input for nix-why.

    Uses the format that achieved 7/7 accuracy:
      INPUT: Attribute: {attrpath} | Kind: {kind} | Value: {value}
    """
    parts = [f"Attribute: {sig.attrpath}", f"Kind: {sig.kind}"]
    if sig.value:
        parts.append(f"Value: {sig.value}")
    if sig.guard:
        parts.append(f"Guard: {sig.guard}")
    if sig.priority is not None:
        parts.append(f"Priority: {sig.priority}")
    if sig.message:
        parts.append(f"Message: {sig.message}")
    return "INPUT: " + " | ".join(parts)


def enrich_signal(sig: NixSignal, nix_why: str) -> dict[str, str] | None:
    """Call nix-why --json to generate intent/posture/rationale for a single signal."""
    input_text = format_signal_input(sig)
    try:
        result = subprocess.run(
            [nix_why, "--json", input_text],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    if result.returncode != 0:
        return None

    try:
        parsed = json.loads(result.stdout)
        if "intent" in parsed:
            return parsed
    except json.JSONDecodeError:
        pass
    return None


def enrich_blocks(
    signals: list[NixSignal],
    blocks: list[Block],
    nix_why: str | None = None,
) -> list[Block]:
    """Enrich blocks with LLM-generated intents from nix-why.

    Each signal maps 1:1 to a block (same index). The nix-why output
    fills the block's Intent field.
    """
    if nix_why is None:
        nix_why = find_nix_why()
    if not nix_why:
        return blocks

    for sig, block in zip(signals, blocks):
        if block.intent:
            continue  # already has an intent
        result = enrich_signal(sig, nix_why)
        if result:
            block.intent = Intent(
                text=result["intent"],
                line=block.start_line,
            )
    return blocks
