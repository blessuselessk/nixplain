//! Model loading, inference, and prompt construction.
//! Adapted from github:jamesbrink/why (MIT license).

use anyhow::{bail, Context, Result};
use clap::ValueEnum;
use llama_cpp_2::context::params::LlamaContextParams;
use llama_cpp_2::llama_backend::LlamaBackend;
use llama_cpp_2::llama_batch::LlamaBatch;
use llama_cpp_2::model::params::LlamaModelParams;
use llama_cpp_2::model::LlamaModel;
use llama_cpp_2::model::{AddBos, Special};
use llama_cpp_2::sampling::LlamaSampler;
use std::env;
use std::fmt;
use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::num::NonZeroU32;
use std::path::{Path, PathBuf};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

/// Model family for prompt template selection
#[derive(Debug, Clone, Copy, PartialEq, Eq, ValueEnum)]
pub enum ModelFamily {
    Qwen,
    Gemma,
    Smollm,
}

impl fmt::Display for ModelFamily {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ModelFamily::Qwen => write!(f, "qwen"),
            ModelFamily::Gemma => write!(f, "gemma"),
            ModelFamily::Smollm => write!(f, "smollm"),
        }
    }
}

/// Magic marker for embedded model trailer (compatible with `why`)
pub const MAGIC: &[u8; 8] = b"WHYMODEL";

pub struct EmbeddedModelInfo {
    pub offset: u64,
    pub size: u64,
    pub family: Option<ModelFamily>,
}

pub struct ModelPathInfo {
    pub path: PathBuf,
    pub embedded_family: Option<ModelFamily>,
}

const TEMPLATE_CHATML: &str = include_str!("prompts/chatml.txt");
const TEMPLATE_GEMMA: &str = include_str!("prompts/gemma.txt");

pub fn find_embedded_model() -> Result<EmbeddedModelInfo> {
    let exe_path = env::current_exe().context("failed to get executable path")?;
    let mut file = File::open(&exe_path).context("failed to open self")?;
    let file_len = file.metadata()?.len();

    if file_len >= 25 {
        file.seek(SeekFrom::End(-25))?;
        let mut trailer = [0u8; 25];
        file.read_exact(&mut trailer)?;
        if &trailer[0..8] == MAGIC {
            let offset = u64::from_le_bytes(trailer[8..16].try_into().unwrap());
            let size = u64::from_le_bytes(trailer[16..24].try_into().unwrap());
            let family = match trailer[24] {
                0 => Some(ModelFamily::Qwen),
                1 => Some(ModelFamily::Gemma),
                2 => Some(ModelFamily::Smollm),
                _ => None,
            };
            return Ok(EmbeddedModelInfo { offset, size, family });
        }
    }
    bail!("No embedded model found")
}

pub fn get_model_path(cli_model: Option<&PathBuf>) -> Result<ModelPathInfo> {
    if let Some(model_path) = cli_model {
        if model_path.exists() {
            return Ok(ModelPathInfo { path: model_path.clone(), embedded_family: None });
        }
        bail!("Model not found: {}", model_path.display());
    }

    if let Ok(info) = find_embedded_model() {
        let exe_path = env::current_exe()?;
        let mut file = File::open(&exe_path)?;
        let temp_path = env::temp_dir().join("nix-why-model.gguf");
        if !temp_path.exists() || temp_path.metadata().map(|m| m.len()).unwrap_or(0) != info.size {
            eprintln!("Extracting embedded model...");
            file.seek(SeekFrom::Start(info.offset))?;
            let model_size = usize::try_from(info.size)
                .context("Model size exceeds addressable memory")?;
            let mut model_data = vec![0u8; model_size];
            file.read_exact(&mut model_data)?;
            std::fs::write(&temp_path, model_data)?;
        }
        return Ok(ModelPathInfo { path: temp_path, embedded_family: info.family });
    }

    // Fallback: look for model file
    let candidates = [
        PathBuf::from("model.gguf"),
        env::current_exe()
            .ok()
            .and_then(|p| p.parent().map(|p| p.join("model.gguf")))
            .unwrap_or_default(),
    ];
    for path in candidates {
        if path.exists() {
            return Ok(ModelPathInfo { path, embedded_family: None });
        }
    }
    bail!("No model found. Use --model <path> to specify a GGUF model.")
}

pub fn detect_model_family(model_path: &Path) -> ModelFamily {
    let filename = model_path.file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_lowercase();
    if filename.contains("gemma") {
        ModelFamily::Gemma
    } else if filename.contains("smol") {
        ModelFamily::Smollm
    } else {
        ModelFamily::Qwen
    }
}

pub fn build_prompt(input: &str, family: ModelFamily) -> String {
    let template = match family {
        ModelFamily::Gemma => TEMPLATE_GEMMA,
        ModelFamily::Qwen | ModelFamily::Smollm => TEMPLATE_CHATML,
    };
    template.replace("{input}", input.trim())
}

/// Run inference and return the generated text.
pub fn run_inference(
    model_path: &PathBuf,
    prompt: &str,
) -> Result<String> {
    let backend = LlamaBackend::init()?;
    let model_params = LlamaModelParams::default().with_n_gpu_layers(1000);
    let model = LlamaModel::load_from_file(&backend, model_path, &model_params)
        .with_context(|| "Failed to load model")?;

    let ctx_params = LlamaContextParams::default()
        .with_n_ctx(Some(NonZeroU32::new(2048).unwrap()));
    let mut ctx = model.new_context(&backend, ctx_params)
        .with_context(|| "Failed to create context")?;

    let mut tokens = model.str_to_token(prompt, AddBos::Always)
        .with_context(|| "Failed to tokenize")?;
    if tokens.len() > 1500 {
        tokens.truncate(1500);
    }

    let batch_size = tokens.len().max(512);
    let mut batch = LlamaBatch::new(batch_size, 1);
    let last_idx = (tokens.len() - 1) as i32;
    for (i, token) in tokens.iter().enumerate() {
        batch.add(*token, i as i32, &[0], i as i32 == last_idx)?;
    }
    ctx.decode(&mut batch)?;

    let seed = {
        let t = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_nanos();
        (t ^ (t >> 32)) as u32
    };
    let mut sampler = LlamaSampler::chain_simple([
        LlamaSampler::top_k(40),
        LlamaSampler::top_p(0.9, 1),
        LlamaSampler::temp(0.7),
        LlamaSampler::dist(seed),
    ]);

    let max_gen_tokens = 256;
    let mut n_cur = batch.n_tokens();
    let start_n = n_cur;
    let mut output = String::new();
    let mut utf8_buffer: Vec<u8> = Vec::new();

    while (n_cur - start_n) < max_gen_tokens as i32 {
        let token = sampler.sample(&ctx, batch.n_tokens() - 1);
        sampler.accept(token);
        if model.is_eog_token(token) {
            break;
        }

        let bytes = model.token_to_bytes(token, Special::Tokenize)?;
        utf8_buffer.extend_from_slice(&bytes);

        match std::str::from_utf8(&utf8_buffer) {
            Ok(s) => {
                output.push_str(s);
                utf8_buffer.clear();
            }
            Err(e) => {
                let valid_up_to = e.valid_up_to();
                if valid_up_to > 0 {
                    output.push_str(&String::from_utf8(utf8_buffer[..valid_up_to].to_vec()).unwrap_or_default());
                    utf8_buffer = utf8_buffer[valid_up_to..].to_vec();
                }
            }
        }

        batch.clear();
        batch.add(token, n_cur, &[0], true)?;
        ctx.decode(&mut batch)?;
        n_cur += 1;
    }

    if !utf8_buffer.is_empty() {
        output.push_str(&String::from_utf8_lossy(&utf8_buffer));
    }

    Ok(output)
}
