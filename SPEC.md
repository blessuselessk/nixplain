# HATC — Human-Agent Teaming Comments

**Version:** 0.1.0-draft
**Scope:** Inline code commenting standard for human-agent collaboration
**Initial target:** Nix configuration language
**Companion standards:** AGENTS.md (discovery layer), TOON (compact serialization)

---

## Problem

Code comments today serve one audience (humans) in one mode (prose). In human-agent teaming:

- Agents waste context tokens parsing prose that doesn't help them
- Humans can't see what constraints an agent is operating under
- There's no structured way to say "don't touch this" vs "feel free to change this"
- AGENTS.md files duplicate information that already lives next to the code
- No standard bridges inline annotations with file-level agent context

## Design Principles

1. **Single source of truth** — inline comments are authoritative; everything else is derived
2. **Tags, not layers** — metadata dimensions are orthogonal, not hierarchical
3. **Progressive disclosure by depth** — scanning costs less than reading
4. **Human-toggleable** — comment/uncomment to switch behavior
5. **Token-dense** — maximize meaning per token; structured beats prose
6. **Composable with AGENTS.md** — reference, don't duplicate

---

## Syntax

### Comment Prefix

All HATC comments use `#` followed by a tag character. Regular comments (`##`) are unaffected.

```
#<tag> <content>
```

### Tags

| Tag | Alias | Meaning | Example |
|-----|-------|---------|---------|
| `#!` | `#intent:` | Why this block/option exists (freeform) | `#! hardened remote deployment target` |
| `#=` | `#hard:` | Hard constraint — grant-style structured fields | `#= by:security-team \| for:SOC2-CC6.1` |
| `#?` | `#soft:` | Soft constraint — grant-style structured fields | `#? by:anyone` |
| `#>` | | Dependency — this affects target | `#> openFirewall` |
| `#<` | | Dependency — this depends on source | `#< enable` |
| `#<>` | | Dependency — mutual constraint | `#<> PermitRootLogin` |
| `#>>` | | Dependency — this gates target (target only matters if this is set) | `#>> settings` |
| `#<<` | | Dependency — gated by source (this only matters if source is set) | `#<< enable` |
| `#><` | | Dependency — conflicts with target | `#>< ForwardAgent` |
| `#\|` | `#opt:` | Option space — valid alternatives with selection markers | `#\| *prohibit-password\|no\|**yes` |
| `#~` | `#why:` | Rationale — history, reasoning, links | `#~ disabled after 2024 audit CVE-XXXX` |

### Constraint Grants

`#=` (hard) and `#?` (soft) support structured grant fields, inspired by [Tailscale's grant syntax](https://tailscale.com/kb/1467/grants-vs-acls). Grants answer not just "is this locked?" but "who can change it, why, and for how long?"

#### Grant Fields

| Field | Meaning | Examples |
|-------|---------|---------|
| `by:` | Who can change this | `security-team`, `team-lead`, `anyone`, `nobody` |
| `for:` | Why it's constrained | `SOC2-CC6.1`, `FIPS-140-2`, `runtime-stability` |
| `until:` | Expiry condition | `Q2-migration`, `2026-06-01`, `audit-complete` |

Fields are pipe-delimited after the tag:

```nix
#= by:security-team | for:SOC2-CC6.1
#= by:team-lead | until:Q2-migration
#= by:nobody | for:runtime-will-crash
#? by:anyone
#? by:frontend-team | for:UX-preference
```

All fields are optional. Bare `#=` means "hard constraint, no further metadata":

```nix
#=
PasswordAuthentication = false;
```

#### Interaction with `#!` (Intent)

`#!` is freeform block-level intent. `#=` and `#?` are per-option grants. They don't merge — they compose:

```nix
#! hardened remote deployment target
services.openssh = {
  #= by:security-team | for:SOC2-CC6.1
  PasswordAuthentication = false;

  #= by:crypto-team | for:FIPS-140-2
  Ciphers = "aes256-gcm@openssh.com";

  #= by:team-lead | until:Q2-migration
  ports = [ 22 ];

  #? by:anyone
  UseDns = true;
};
```

An agent reading this block knows:
- **Block intent:** hardened remote deployment target
- **PasswordAuthentication:** locked by security team (SOC2)
- **Ciphers:** locked by crypto team (FIPS) — different authority
- **ports:** temporarily frozen by team lead
- **UseDns:** soft, anyone can change

### Dependency References

Bare names resolve in the enclosing block (lexical scoping). Qualify to reference other scopes:

| Reference | Resolves to |
|-----------|-------------|
| `name` | Nearest match in enclosing block |
| `block.name` | Different block, same file |
| `file:block.name` | Different file, same directory |
| `path/to/file:block.name` | Different directory |

```nix
#> openFirewall                                      ## same block
#> services.openssh.openFirewall                     ## same file, different block
#> firewall.nix:networking.firewall                  ## same directory, different file
#> ../network/firewall.nix:networking.firewall       ## different directory
```

### Option Space Markers

The `#|` tag supports prefix markers to indicate selection state:

| Marker | Meaning | Example |
|--------|---------|---------|
| (none) | Available option | `no` |
| `*` | Active selection | `*prohibit-password` |
| `**` | Upstream/module default | `**yes` |
| `***` | Active selection AND is the default | `***false` |

```nix
#| *prohibit-password|no|forced-commands-only|**yes
PermitRootLogin = "prohibit-password";
```

Reading this, an agent instantly knows:
- **4 valid options** exist
- `prohibit-password` is **active** (`*`, first position)
- `yes` is the **upstream default** (`**`, last position)
- The active selection **deviates from default** (no `***`)

When active matches default:

```nix
#| ***false|true
PasswordAuthentication = false;
```

`***` signals "I chose this deliberately and it happens to be the default."

Versus:

```nix
#| **false|true
PasswordAuthentication = false;
```

No `*` — the value matches default but hasn't been explicitly marked as an active choice.

### Ordering Convention

Active selection sorts first, default sorts last. Markers are the source of truth; ordering is a readability convention:

```
#| *active|other|other|**default
```

### Emoji Aliases (optional)

Agents and tooling MUST accept both forms. Humans choose whichever they prefer.

| Tag | Emoji |
|-----|-------|
| `#!` | `#🎯` |
| `#=` | `#🔒` |
| `#?` | `#🔧` |
| `#>` `#<` `#<>` `#>>` `#<<` `#><` | `#🔗` + arrow |
| `#\|` | `#⊕` |
| `#~` | `#📎` |

*(Emoji rendering depends on environment. Tag characters are the canonical form.)*

---

## Scoping Rules

### Block Scope (Closures)

A `#!` (intent) comment applies to the entire block that follows it — the attribute set or expression it precedes. All other tags within that block inherit this context.

```nix
#! hardened remote deployment target
services.openssh = {
  #= by:security-team | for:SOC2-CC6.1
  #<> PermitRootLogin
  PasswordAuthentication = false;
};
```

Reading `PasswordAuthentication = false` in isolation, an agent knows:
- **Block intent:** hardened remote deployment target (from enclosing `#!`)
- **Constraint:** hard, compliance SOC2-CC6.1 (from `#=`)
- **Dependency:** mutual constraint with PermitRootLogin (from `#<>`)

This is the closure model — `#!` is the enclosing environment, and per-option tags close over it.

### Option Scope

Tags without `#!` apply only to the immediately following line:

```nix
#? preference
#| *true|**false
UseDns = true;
```

### Lexical Resolution

Bare names in dependency tags resolve to the nearest match in the enclosing block. This mirrors how closures capture variables — look in the current scope first:

```nix
services.openssh = {
  enable = true;              ## ← "enable" resolves here
  settings = {
    #<< enable                ## means services.openssh.enable
    PermitRootLogin = "prohibit-password";
  };
};
```

If you mean a different scope, qualify it:

```nix
#<< services.nginx.enable     ## explicit: not our block's enable
```

### Multi-line Tags

If a tag needs multiple lines, indent continuation lines:

```nix
#~ disabled after 2024 audit finding CVE-XXXX
#~   see https://internal.wiki/ssh-hardening
#~   reviewed by security team 2024-03-15
X11Forwarding = false;
```

---

## Progressive Disclosure

Agents read at three depths depending on their task:

### Depth 0 — Scan (planning)

Read only `#!` lines. Answers: "what blocks exist and what are they for?"

```
Cost: ~1 line per block
Use: deciding which files to open, planning changes across files
```

### Depth 1 — Assess (pre-edit)

Read `#!`, `#=`, `#?`, and all dependency arrows. Answers: "what are the constraints and couplings?"

```
Cost: ~3-5 lines per block
Use: understanding what can and cannot change before editing
```

### Depth 2 — Edit (active modification)

Read all tags including `#|` and `#~`. Answers: "what are my options and why were these choices made?"

```
Cost: full annotation set
Use: actively changing a value, needs option space and rationale
```

An agent operating at Depth 0 skips everything except `#!`. The tag prefixes make filtering trivial.

---

## Human Toggle Pattern

Nix's comment syntax enables a natural toggle:

```nix
#| *prohibit-password|no|forced-commands-only|**yes
# PermitRootLogin = "yes";
# PermitRootLogin = "no";
  PermitRootLogin = "prohibit-password";
# PermitRootLogin = "forced-commands-only";
```

One line is uncommented (active). The others are commented alternatives. A human toggles by moving the `#` between lines. The `#|` tag above documents that this is an intentional choice set, not dead code.

### Full Example

```nix
#! minimal attack surface SSH
services.openssh = {
  #>> settings|openFirewall
  enable = true;

  #| ***22|2222|443
  #> openFirewall
  #> ../network/firewall.nix:networking.firewall.allowedTCPPorts
  ports = [ 22 ];

  settings = {
    #= by:security-team | for:SOC2-CC6.1
    #<> PermitRootLogin
    #<< enable
    PasswordAuthentication = false;

    #= by:security-team | for:SOC2-CC6.1
    #| *prohibit-password|no|forced-commands-only|**yes
    #<> PasswordAuthentication
    #<< enable
    PermitRootLogin = "prohibit-password";

    #? preference — toggle for debugging
    #>< ForwardAgent
    # X11Forwarding = true;
    X11Forwarding = false;
  };

  #<< enable
  #< ports
  #> ../network/firewall.nix:networking.firewall.allowedTCPPorts
  openFirewall = true;
};
```

---

## AGENTS.md Integration

### AGENTS.md as Index

AGENTS.md becomes a reference map, not a content store. APM (or similar tooling) compiles it by extracting `#!` lines and building references:

```markdown
## src/server/

### ssh.nix
@src/server/ssh.nix
#! hardened remote deployment target

### dns.nix
@src/server/dns.nix
#! local DNS caching with fallback

### firewall.nix
@src/server/firewall.nix
#! zone-based filtering, default deny
```

### Cross-File Dependency Map

The compiler can also extract dependency arrows that cross file boundaries and include them in AGENTS.md:

```markdown
## Cross-file dependencies

ssh.nix:ports → firewall.nix:networking.firewall.allowedTCPPorts
ssh.nix:openFirewall → firewall.nix:networking.firewall.allowedTCPPorts
ssh.nix:enable >> ssh.nix:settings
```

This gives an agent a dependency graph for planning without opening any files.

### Loading Behavior

| Agent context | What loads | Source |
|---|---|---|
| File not open | `#!` summary + cross-file deps | Compiled AGENTS.md index |
| File opened | All inline tags | Source file directly |
| File open + AGENTS.md loaded | Skip AGENTS.md entry for that file | Dedup via `@` reference |

The `@path/to/file` reference is the mechanism — if the agent already has the file, it doesn't follow the reference.

### Compilation

An APM-style compiler performs:

1. **Scan** — walk source files for `#!` intent lines
2. **Extract** — collect cross-file dependency arrows (`#>`, `#<`, etc. with path references)
3. **Infer** — generate candidate `#!` for unannotated blocks (see Intent Compilation below)
4. **Index** — build `{file: intent}` map + dependency graph
5. **Emit** — write AGENTS.md with `@references`, `#!` summaries, and cross-file dep map
6. **Verify** — ensure every annotated file appears in the index

No content is duplicated. AGENTS.md is a table of contents + dependency graph.

### Intent Compilation

Blocks without a `#!` line can have intent inferred through a two-pass process.

#### Pass 1 — Static Analysis (deterministic, cheap)

The compiler examines the block and derives a candidate intent from:

| Signal | What it reveals | Example |
|---|---|---|
| Module `description` field | Generic function | "Enable the OpenSSH daemon" |
| Count/type of `#=` constraints | Security posture | 3 hard constraints → security-related |
| Deviation from defaults | Customization intent | non-default port → stealth/hardening |
| Dependency graph shape | Integration role | many cross-file `#>` → infrastructure-critical |
| Attribute names/values | Domain | `PermitRootLogin`, `PasswordAuthentication` → auth surface |

The static pass produces a structured candidate:

```
## Auto-generated candidate:
#! SSH (3 hard constraints, non-default port, cross-file deps to firewall)
```

#### Pass 2 — Agent Refinement (optional, requires LLM)

Feed the block + static analysis to an agent with a tight prompt:

```
Given this Nix block and its static analysis, write a #! intent
line of 10 words or fewer that captures WHY this block exists
(not what it does).

Static analysis: SSH service, 3 hard compliance constraints,
non-default port, cross-file deps to firewall and certificates.

Block:
  services.openssh = { ... }
```

Produces:

```
#! hardened remote deployment target
```

#### Compilation Rules

1. **Block has `#!`** → skip, it's already annotated
2. **Block has no `#!`** → generate one
3. **No useful signals** → generate nothing
4. **Human doesn't like it** → edit or delete it like any other line

#### Nix-Specific Static Signals

The Nix module system provides rich signals for static analysis:

| Source | How to access | What it provides |
|---|---|---|
| `options.*.description` | `nix-instantiate --eval` | Module descriptions |
| `options.*.type` | `nix-instantiate --eval` | Type constraints |
| `options.*.default` | `nix-instantiate --eval` | Default values (to detect deviation) |
| `config` vs `options` | Static analysis | Which options are actually set |
| `imports` | File scanning | Cross-file dependency graph |

A Nix-aware compiler can query the module system directly to power Pass 1 without parsing Nix expressions itself.

---

## Nix-Specific Conventions

### Module Options

Nix module options already carry type, default, and description via the module system. HATC comments add what the module system doesn't provide: **intent, constraints, dependencies, and rationale**.

Do NOT duplicate module system metadata in comments:

```nix
## BAD — duplicates what the module system already knows
#~ type: boolean, default: false
PasswordAuthentication = false;

## GOOD — adds what the module system doesn't know
#= by:security-team | for:SOC2-CC6.1
PasswordAuthentication = false;
```

### Flake Inputs

```nix
{
  inputs = {
    #! primary package source
    #= by:team-lead | for:stability — do not auto-update without testing
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.05";

    #? convenience — can switch to stable
    nixpkgs-unstable.url = "github:NixOS/nixpkgs/nixos-unstable";

    #< nixpkgs
    home-manager.url = "github:nix-community/home-manager";
    home-manager.inputs.nixpkgs.follows = "nixpkgs";
  };
}
```

### Overlays and Overrides

```nix
#! patch openssl for FIPS compliance
#= by:crypto-team | for:FIPS-140-2
#> ssh.nix:services.openssh
#> nginx.nix:services.nginx
final: prev: {
  openssl = prev.openssl.overrideAttrs (old: {
    patches = old.patches ++ [ ./fips-mode.patch ];
  });
}
```

---

## Grammar (EBNF)

```ebnf
hatc_comment  = "#" tag " " content ;
tag           = intent | hard | soft | dep | opt | rationale ;
intent        = "!" | "intent:" ;
hard          = "=" | "hard:" ;
soft          = "?" | "soft:" ;
dep           = dep_arrow ;
dep_arrow     = ">"        (* this affects target *)
              | "<"        (* this depends on source *)
              | "<>"       (* mutual constraint *)
              | ">>"       (* this gates target *)
              | "<<"       (* gated by source *)
              | "><" ;     (* conflicts with target *)
opt           = "|" | "opt:" ;
rationale     = "~" | "why:" ;
content       = { any_char } ;
continuation  = "#" tag "  " content ;  (* 2+ space indent = continuation *)

(* Constraint grants: #= and #? take optional structured fields *)
grant_content = grant_field { " | " grant_field } ;
grant_field   = grant_key ":" grant_value ;
grant_key     = "by" | "for" | "until" ;
grant_value   = { any_char - "|" } ;

(* Dependency references *)
dep_content   = dep_ref { "|" dep_ref } ;   (* pipe-delimited for multiple targets *)
dep_ref       = [ path ":" ] attr_path ;
path          = { any_char - ":" } ;        (* relative file path *)
attr_path     = identifier { "." identifier } ;
identifier    = letter { letter | digit | "_" | "-" } ;

(* Option space: pipe-delimited, no brackets *)
(* Convention: active first, default last *)
opt_content   = opt_value { "|" opt_value } ;
opt_value     = [ marker ] value ;
marker        = "***"     (* active + default *)
              | "**"      (* default *)
              | "*" ;     (* active *)
value         = { any_char - "|" } ;
```

Parsers MUST:
- Accept both tag characters and keyword aliases
- Accept both tag characters and emoji aliases
- Ignore lines starting with `##` (regular comments)
- Treat unknown tag characters as regular comments
- Parse dependency arrows as the longest matching prefix (`<<` before `<`, `>>` before `>`, `<>` and `><` as two-char tokens)

---

## Token Budget Analysis

For a typical NixOS service block (10 options):

| Annotation style | Tokens (approx) |
|---|---|
| No comments | 0 |
| Prose comments (1 line each) | ~150 |
| HATC Depth 0 only (`#!`) | ~10 |
| HATC Depth 0+1 (`#! #= #? #< #>`) | ~40 |
| HATC Full (all tags) | ~80 |

HATC at full depth uses ~half the tokens of prose, with more structured information. At Depth 0 (planning), it's ~15x cheaper.

---

## Non-Goals

- **Replacing AGENTS.md** — HATC complements it, doesn't compete
- **Language server integration** — possible future work, not in v0.1
- **Enforcement/linting** — annotations are advisory, not validated
- **Execution** — unlike Metacode, HATC comments are metadata, not directives

---

## Related Work

| Project | Relationship |
|---|---|
| [AGENTS.md](https://agents.md) | Discovery layer — HATC provides what AGENTS.md points to |
| [Metacode](https://github.com/mutating/metacode) | Tool directives — HATC is semantic metadata, not action commands |
| [ACE/HumanLayer](https://github.com/humanlayer/advanced-context-engineering-for-coding-agents) | Workflow — HATC is the inline data that workflows consume |
| [APM](https://github.com/danielmeppiel/apm) | Compiler — APM-style compilation builds AGENTS.md from HATC annotations |
| [TOON](https://github.com/toon-format/toon) | Serialization — potential format for compiled HATC output |
