//! Parse structured responses from the LLM.

use serde::Serialize;

/// Parsed Nix analysis result
#[derive(Debug, Serialize)]
pub struct NixAnalysis {
    pub intent: String,
    pub posture: String,
    pub rationale: String,
}

/// Parse INTENT/POSTURE/RATIONALE from model output.
pub fn parse_response(response: &str) -> NixAnalysis {
    let mut intent = String::new();
    let mut posture = String::new();
    let mut rationale = String::new();
    let mut current = "intent";

    for line in response.lines() {
        let line = line.trim();
        let lower = line.to_lowercase();

        if lower.starts_with("intent:") {
            current = "intent";
            let rest = line[7..].trim();
            if !rest.is_empty() {
                intent = rest.to_string();
            }
        } else if lower.starts_with("posture:") {
            current = "posture";
            let rest = line[8..].trim();
            if !rest.is_empty() {
                posture = rest.to_string();
            }
        } else if lower.starts_with("rationale:") {
            current = "rationale";
            let rest = line[10..].trim();
            if !rest.is_empty() {
                rationale = rest.to_string();
            }
        } else if !line.is_empty() {
            let target = match current {
                "intent" => &mut intent,
                "posture" => &mut posture,
                "rationale" => &mut rationale,
                _ => &mut intent,
            };
            if !target.is_empty() {
                target.push(' ');
            }
            target.push_str(line);
        }
    }

    // Normalize posture
    let posture_lower = posture.to_lowercase();
    posture = if posture_lower.contains("locked") || posture_lower.contains("hard") {
        "locked".to_string()
    } else if posture_lower.contains("soft") {
        "soft".to_string()
    } else if posture_lower.contains("neutral") {
        "neutral".to_string()
    } else {
        posture
    };

    NixAnalysis { intent, posture, rationale }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_basic() {
        let resp = "INTENT: Disable password auth for SSH security\n\
                    POSTURE: locked\n\
                    RATIONALE: Prevents brute-force attacks on SSH.";
        let a = parse_response(resp);
        assert_eq!(a.intent, "Disable password auth for SSH security");
        assert_eq!(a.posture, "locked");
        assert!(a.rationale.contains("brute-force"));
    }

    #[test]
    fn test_parse_multiline_rationale() {
        let resp = "INTENT: Lock SSH password auth\n\
                    POSTURE: locked\n\
                    RATIONALE: Security requirement.\n\
                    Prevents unauthorized access via passwords.";
        let a = parse_response(resp);
        assert!(a.rationale.contains("Security requirement"));
        assert!(a.rationale.contains("Prevents unauthorized"));
    }

    #[test]
    fn test_posture_normalization() {
        let resp = "INTENT: test\nPOSTURE: Locked (hard constraint)\nRATIONALE: none";
        let a = parse_response(resp);
        assert_eq!(a.posture, "locked");
    }
}
