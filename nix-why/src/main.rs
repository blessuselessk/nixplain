//! nix-why — Nix configuration semantic analyzer using local LLM.
//!
//! Takes NixOS configuration context (signals from hatc extract) and produces
//! human-readable intent, posture, and rationale annotations.

mod model;
mod output;

use anyhow::Result;
use clap::Parser;
use std::io::{self, Read};
use std::path::PathBuf;

use model::{build_prompt, detect_model_family, get_model_path, run_inference, ModelFamily};
use output::parse_response;

#[derive(Parser)]
#[command(name = "nix-why", about = "Analyze NixOS configurations using local LLM")]
struct Cli {
    /// Nix code or signal description to analyze
    input: Option<String>,

    /// Path to GGUF model file
    #[arg(long)]
    model: Option<PathBuf>,

    /// Model family (auto-detected from filename if not set)
    #[arg(long, value_enum)]
    family: Option<ModelFamily>,

    /// Output as JSON
    #[arg(long)]
    json: bool,
}

fn main() -> Result<()> {
    let cli = Cli::parse();

    // Get input from argument or stdin
    let input = if let Some(ref text) = cli.input {
        text.clone()
    } else {
        let mut buf = String::new();
        io::stdin().read_to_string(&mut buf)?;
        buf
    };

    if input.trim().is_empty() {
        eprintln!("No input provided. Pass Nix code as argument or via stdin.");
        std::process::exit(1);
    }

    // Resolve model
    let model_info = get_model_path(cli.model.as_ref())?;
    let family = cli.family
        .or(model_info.embedded_family)
        .unwrap_or_else(|| detect_model_family(&model_info.path));

    eprintln!("Model: {} ({})", model_info.path.display(), family);

    // Build prompt and run inference
    let prompt = build_prompt(&input, family);
    let response = run_inference(&model_info.path, &prompt)?;
    let analysis = parse_response(&response);

    if cli.json {
        println!("{}", serde_json::to_string_pretty(&analysis)?);
    } else {
        println!("#! {}", analysis.intent);
        if analysis.posture == "locked" {
            println!("#=");
        } else if analysis.posture == "soft" {
            println!("#?");
        }
        if !analysis.rationale.is_empty() {
            println!("#~ {}", analysis.rationale);
        }
    }

    Ok(())
}
