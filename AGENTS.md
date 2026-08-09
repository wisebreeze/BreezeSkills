# AGENTS.md — AI working guide for this workspace

This workspace is an MCPE (Minecraft: Pocket Edition) Android native-mod /
hook research environment. The methodology comes from three open-source
projects, one per language/runtime combination:

- **C++ / preloader** — [BedrockTools](https://github.com/RadiantByte/BedrockTools)
- **C++ / BreezeAPI** — [wisebreeze/BreezeAPI](https://github.com/wisebreeze/BreezeAPI)
- **Rust** — [mcbegamerxx954/mtbinloader2](https://github.com/mcbegamerxx954/mtbinloader2)

Your job is to apply that methodology to a local `libminecraftpe.so`:
locate functions, extract/verify signatures or offsets, write hooks or
patches, compile an arm64 `.so`, and verify it.

## 0. Rules

- **Method source**: for the C++/preloader path, the reference is
  BedrockTools' code. For the C++/BreezeAPI path, the reference is the
  BreezeAPI source. For the Rust path, the reference is mtbinloader2.
  Do not invent new abstractions; follow the existing code shapes.
- For any hooking/modding/IDA/signature/build task, **read the skill
  first**: `skills/mcpe-native-modding/SKILL.md` plus its `references/`
  and `scripts/`.
- Everything you produce must be **machine-agnostic and English-readable**:
  use placeholders like `<libminecraftpe.so>`, `<NDK>`, `<your-mod-dir>`,
  `<BreezeAPI-dir>` instead of local absolute paths; do not bake in
  game-version numbers, file sizes, or build-specific addresses.
- The target binary is usually `libminecraftpe.so` in the workspace root.
  Confirm its path with `rg --files` / `Glob` before operating on it.
- **Default language is C++.** Use Rust only when the user asks for it
  or the host toolchain is Rust-native.
- When the user does not specify a runtime, ask which launcher/SDK the
  mod targets before writing code.

## 1. Standard workflow

```
read SKILL.md
  -> Step 0: pick language (C++ default | Rust) + runtime (preloader | BreezeAPI)
  -> Step 1: name the game function behind the feature
  -> Step 2: locate (signature dictionary | symbol | offset | pattern)
  -> Step 3: analyze (optional disassembler)
  -> Step 4: feasibility -> hook choice
     (inline hook | head-replace | byte patch | vtable | GOT/PLT | JS)
  -> Step 5: verify (verify_signatures.py | ResolveSymbol | pattern match)
  -> Step 6: implement with the canonical shapes
  -> Step 7: build -> package -> deploy -> logcat verify
```

## 2. File map

| Path | Purpose |
|---|---|
| `skills/mcpe-native-modding/SKILL.md` | skill entry: architecture, API tables, 7-step workflow |
| `skills/mcpe-native-modding/references/feature-workflow.md` | feature -> function -> feasibility -> hook decision; Step 0 language+runtime |
| `skills/mcpe-native-modding/references/hook-techniques.md` | Part A (preloader) / Part B (BreezeAPI) / Part C (Rust) hook reference |
| `skills/mcpe-native-modding/references/so-analysis.md` | direct `.so` analysis (ELF/sections/symbols/strings/signatures) |
| `skills/mcpe-native-modding/references/build-deploy.md` | Part A/B/C build, manifest, `.levipack` / `jniLibs`, deploy |
| `skills/mcpe-native-modding/references/ida-workflow.md` | optional IDA / IDA Pro MCP guide |
| `skills/mcpe-native-modding/references/version-porting.md` | Part A/B/C porting checklist |
| `skills/mcpe-native-modding/scripts/` | verify_signatures, elf_facts, aarch64_enc, package_levipack |
| `skills/mcpe-native-modding/NOTICE` | attribution to BedrockTools, BreezeAPI, mtbinloader2, and deps |
| `AGENTS.md` / `CLAUDE.md` | per-agent entry guides (Codex / Claude Code & others) |

## 3. Ethics and safety

- Only hook/patch binaries and versions the user explicitly authorized;
  keep work to learning/personal use and respect the game's terms of
  service.
- Do not ship or perform unapproved network scraping or cracking actions.
- Always keep a backup of the original `.so`; fail safely on version
  mismatch (never write garbage bytes).
