---
name: mcpe-native-modding
description: "Develop native mods and hooks for MCPE (Minecraft: Pocket Edition) Android arm64 by following the open-source BedrockTools methodology. Use when the user wants to: hook, patch, or mod libminecraftpe.so; write a LeviLauncher / preloader native mod (.so); turn a desired feature into concrete game-function hooks; decide between inline hooks, vtable hooks, and direct byte patches; extract or verify ARM64 byte signatures; build an arm64-v8a Android .so with NDK + CMake; package a mod (manifest.json / .levipack); port a mod to a new MCPE version; or understand MCPE internals such as tick, render, FOV, packet, attack, screen, weather, time, skin, and UI hooks. Not for Java/Spigot/Forge mods or for non-MCPE ELF targets without adaptation."
---

# MCPE Native Modding

This skill teaches how to build native (`.so`) mods for **MCPE** on Android
**arm64-v8a**. The target binary is `libminecraftpe.so`, the stripped native
library that contains nearly all game logic (tick, render, network, UI,
weather, time, skin, packets). The runtime is **LeviLauncher + preloader**;
the preloader SDK is open source at
[LiteLDev/preloader-android](https://github.com/LiteLDev/preloader-android).

The methodology follows the open-source
[BedrockTools](https://github.com/RadiantByte/BedrockTools) project (GPL-3.0).
See `NOTICE` for attribution.

Everything here is **machine-agnostic**: replace `<libminecraftpe.so>`,
`<NDK>`, `<your-mod-dir>` with real paths on your machine. Do not bake in
game-version numbers, file sizes, or build-specific addresses.

## 1. How the runtime loads your mod

```
LeviLauncher (Java)
      |
      v
libpreloader.so   -- scans mods/, validates manifest.json, dlopen()s your .so
      |
      v
libMyMod.so       -- must export PLGetModRegistration(); preloader calls
                      load / enable / disable / unload
      |
      v
libminecraftpe.so -- loaded by the game LATER; your mod hooks dlopen to wait
```

Key consequences:

- Your `.so` is loaded **before** the game library. You cannot resolve
  signatures at `load()` time directly; you must either hook `dlopen` and
  finish setup when `libminecraftpe.so` appears, or poll with
  `dlopen("libminecraftpe.so", RTLD_NOW | RTLD_NOLOAD)`.
- `GlossInit(true)` must be the first call in `load()`; without it, hooks
  silently fail.
- The game `.so` is **stripped** (no symbol table). Function addressing is
  done by **byte signatures** (function-head machine code with `?` wildcards),
  resolved at runtime by scanning `.text`.
- Signatures, member offsets, and vtable slots are **version-sensitive**.
  Porting to a new MCPE version means re-extracting / re-verifying (see
  `references/version-porting.md`).

## 2. Core APIs

| Purpose | API | Header |
|---|---|---|
| Register a mod | `PL_REGISTER_MOD(Type, inst)` | `pl/Mod.hpp` |
| Inline hook (with chain) | `pl::memory::hook(target, detour, &orig, priority)` / `unhook` | `pl/memory/Hook.hpp` |
| Low-level hook engine | `GlossInit(true)`, `GlossHook`, `GlossGotHook`, `GlossPltHook`, `GlossHookByName` | `pl/Gloss.h` |
| Resolve a signature | `pl::memory::resolveSignature(pattern, "libminecraftpe.so")` | `pl/memory/Signature.hpp` |
| Patch memory | `pl::memory::writeBytes / readBytes / revertPatch` | `pl/memory/Patch.hpp` |
| Resolve vtable slot by RTTI | `pl::memory::resolveVtableFunction(typeInfoName, slot, module)` | `pl/memory/Vtable.hpp` |
| Logging | `pl::log::Logger::getOrCreate(name)` | `pl/Logger.hpp` |
| Mouse input | `pl::input::registerMouseCallback(...)` | `pl/Input.hpp` |
| In-game menu | `pl::modmenu::ModuleBuilder / ButtonBuilder` | `pl/ModMenu.hpp` |

Thin wrappers (reuse as-is, do not reinvent):

- `hooks::install(target, detour, &original)` / `hooks::remove(handle)` —
  wraps `pl::memory::hook` and records a handle for clean teardown.
- `sdk::field<T>(obj, off)` — typed member access at a byte offset.
- `sdk::virtualCall<Ret>(inst, slot, ...)` — call a vtable slot by index.
- `sdk::patchMemory(addr, data, size)` — mprotect RWX + memcpy +
  `__builtin___clear_cache` + restore RX.
- `sdk::function<Fn>(SignatureId)` — turn a resolved signature address into
  a typed function pointer.

## 3. The 7-step workflow

Follow this order. Skipping steps is the most common cause of crashes.

### Step 1 — Name the game function behind the feature

Before touching the binary, decide which game function implements the
behavior the user wants to change. Common mappings:

| Feature | Game function | Strategy |
|---|---|---|
| Zoom / FOV | `GetFov` | inline hook, modify return |
| Low sensitivity while zoomed | `LocalPlayerApplyTurnDelta` | inline hook, scale input |
| Hide held item while zoomed | `BaseOptionRegistryGetHideItemInHand` | inline hook, force true |
| Fullbright | `Fullbright` | head-replace patch (return max light) |
| Time of day | `Time` / `SetTime` | inline hook, override return/arg |
| Cancel attack | `GameModeAttack` / `SurvivalModeAttack` | inline hook + cancellable event |
| Player tick logic | `NormalTick` | inline hook + event |
| Per-frame logic | `eglSwapBuffers` (libEGL.so) | hook exported symbol |
| Screen open/close | `ContainerScreenControllerOpen/Dtor`, `ChatScreenOpen/Dtor` | inline hook + event |
| Reach / hit result | `LevelGetHitResult`, `HitResultGetEntity` | resolve + call |
| Player name / skin | `ActorGetNameTag`, `ActorSetNameTag` + field offsets | hook / field access |
| Weather / biome | `WeatherTick`, `WeatherIsRaining`, `BiomeGetTemperature` | hook / field access |
| Outgoing packets | `LoopbackPacketSenderSendToServer` | inline hook |

### Step 2 — Locate the function

1. Check the signature dictionary first (`Signatures.cpp` in the
   BedrockTools source tree). If it has an entry, resolve and proceed.
2. Otherwise, search community knowledge for the function name.
3. Only as a last resort, use a disassembler (IDA / Ghidra) to find a new
   function via string xrefs (see `references/ida-workflow.md`).

### Step 3 — Analyze (optional)

If the function is undocumented, decompile it at the resolved address and
confirm: what it returns, what it writes, what it calls, and its calling
convention (arm64: args in X0..., return in X0/W0/S0). This step is optional
for functions already in the dictionary.

### Step 4 — Pick the hook technique

| Situation | Technique |
|---|---|
| Need logic before/after, or to modify args/return | inline hook |
| Function should just return a constant / do nothing | head-replace patch (back up first, then `RET`) |
| Change a constant / branch / force a path | byte patch with original-byte verification |
| Override a virtual method | vtable slot hook |
| Hook a library import (e.g. EGL) | symbol + `hooks::install` on `dlsym` result |
| Wait for the game library | hook `dlopen` |

**Safety rules (non-negotiable):**

1. Always `readBytes` the current bytes before patching.
2. If current == target → already patched, skip.
3. If current == expected original → apply patch.
4. Otherwise → version mismatch: log and skip. **Never write garbage.**

### Step 5 — Verify signatures on the actual `.so`

```bash
python scripts/verify_signatures.py <libminecraftpe.so> \
    --sigs <path/to/Signatures.cpp> \
    --json sig_report.json
```

Verdicts:

- `UNIQUE` — exactly one match; safe to hook.
- `AMBIGUOUS` — multiple matches; lengthen the pattern or add fixed anchor bytes.
- `MISSING` — no match; wrong version, re-extract with a disassembler.

### Step 6 — Implement

Two canonical shapes (full templates in `references/hook-techniques.md`):

Inline hook:

```cpp
static std::string (*versionOriginal)(void*) = nullptr;
static std::string versionDetour(void* self) {
    std::string v = versionOriginal ? versionOriginal(self) : std::string{};
    return v + " | MyMod v1.0";
}
uintptr_t addr = pl::memory::resolveSignature(pattern, "libminecraftpe.so");
pl::memory::hook((void*)addr, (void*)versionDetour, (void**)&versionOriginal);
```

Safe byte patch:

```cpp
std::array<uint8_t,4> expected{...}, replacement{...};
auto cur = pl::memory::readBytes(addr, 4);
if (cur == replacement) return;               // already patched
if (cur == expected) pl::memory::writeBytes(addr, replacement, "mypatch");
// else: version mismatch -> log and skip
```

### Step 7 — Build, package, deploy, verify

See `references/build-deploy.md` for the full NDK + CMake commands. The
output `.so` must export `PLGetModRegistration`; ship it next to a valid
`manifest.json` into the launcher's `mods/` directory. Verify with
`adb logcat`.

## 4. Typed events

Game callbacks can be converted into typed events that modules subscribe to
via `bus().subscribe<Event>(cb, priority)`. Third-party mods subscribe
through the runtime ABI.

| Event | Source hook | Use case |
|---|---|---|
| `FrameEvent` | `eglSwapBuffers` | every frame |
| `LocalPlayerTickEvent` | `NormalTick` | player tick |
| `ClientInstanceUpdateEvent` | `ClientInstanceUpdate` | get ClientInstance |
| `AttackEvent` (cancellable) | `GameModeAttack` / `SurvivalModeAttack` | attack logic |
| `ScreenStateEvent` | screen Open/Dtor hooks | UI state |
| `MouseInputEvent` | `pl::input` | mouse |

## 5. References (load on demand)

- `references/feature-workflow.md` — feature → function → feasibility →
  hook-decision guide with worked examples.
- `references/hook-techniques.md` — full hook technique reference: inline
  hooks, chains, head replacement, NOP/branch patches, vtable, GOT/PLT,
  dlopen/EGL hooks, signature format rules.
- `references/so-analysis.md` — analyze the `.so` on disk without a device.
- `references/build-deploy.md` — NDK+CMake build, manifest, `.levipack`
  packaging, deployment, logcat verification.
- `references/ida-workflow.md` — optional IDA / IDA Pro MCP guidance.
- `references/version-porting.md` — porting checklist for new MCPE versions.

## 6. Scripts

- `scripts/verify_signatures.py` — scan a `.so` for all signatures parsed
  from `Signatures.cpp`; report UNIQUE/AMBIGUOUS/MISSING.
- `scripts/elf_facts.py` — read-only ELF facts (header, segments, sections,
  dynamic symbols, version strings) for a fresh `.so`.
- `scripts/aarch64_enc.py` — encode AArch64 patch instructions
  (MOV/NOP/RET/BR/FMOV).
- `scripts/package_levipack.py` — package a mod into `.levipack` (manifest +
  `.so` + resources) and verify the result.

## 7. Notes

- This skill uses the shared `SKILL.md` frontmatter convention
  (`name` + `description`), so it is discoverable by Codex, Claude Code,
  Cursor, and other agents that support agent skills.
- Hook/patch only what the user explicitly authorized; keep to learning
  and personal use and respect the game's terms of service.
- Always keep a backup of the original `.so`; fail safely on version
  mismatch.
