---
name: mcpe-native-modding
description: "Develop native mods and hooks for MCPE (Minecraft: Pocket Edition) Android arm64, supporting two interchangeable runtimes: the open-source BedrockTools methodology on LeviLauncher/preloader, and BreezeAPI (Dobby-based, with embedded QuickJS). Use when the user wants to: hook, patch, or mod libminecraftpe.so; write a native mod (.so) for either preloader or BreezeAPI; turn a desired feature into concrete game-function hooks; decide between inline hooks, vtable hooks, byte patches, and symbol/offset/address hooks; extract or verify ARM64 byte signatures; build an arm64-v8a Android .so with NDK + CMake; package a mod (manifest.json / .levipack or jniLibs); port a mod to a new MCPE version; or understand MCPE internals such as tick, render, FOV, packet, attack, screen, weather, time, skin, and UI hooks. Not for Java/Spigot/Forge mods or for non-MCPE ELF targets without adaptation."
---

# MCPE Native Modding

This skill teaches how to build native (`.so`) mods for **MCPE** on Android
**arm64-v8a**. The target binary is `libminecraftpe.so`, the stripped native
library that contains nearly all game logic (tick, render, network, UI,
weather, time, skin, packets).

This skill supports **two interchangeable runtimes**. Pick one based on the
host launcher / SDK the user targets; the hooking methodology is shared, but
the registration, addressing, and packaging differ.

| Runtime | Hook engine | Function addressing | Scripting | Packaging |
|---|---|---|---|---|
| **preloader** (LeviLauncher) | Gloss (inline / GOT / PLT / vtable) | byte signatures (function-head scan) | typed C++ events | `.levipack` into `mods/` |
| **BreezeAPI** | Dobby (inline) | symbol name / library offset / absolute address | embedded QuickJS (ES2024) | `libbreeze_api.so` into `jniLibs/` |

The preloader methodology follows the open-source
[BedrockTools](https://github.com/RadiantByte/BedrockTools) project; see
`NOTICE` for attribution. BreezeAPI is at
[wisebreeze/BreezeAPI](https://github.com/wisebreeze/BreezeAPI) (Apache-2.0).

Everything here is **machine-agnostic**: replace `<libminecraftpe.so>`,
`<NDK>`, `<your-mod-dir>`, `<BreezeAPI-dir>` with real paths on your
machine. Do not bake in game-version numbers, file sizes, or build-specific
addresses.

## 1. How each runtime loads your mod

### preloader (LeviLauncher)

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
  signatures at `load()` time directly; hook `dlopen` and finish setup when
  `libminecraftpe.so` appears, or poll with
  `dlopen("libminecraftpe.so", RTLD_NOW | RTLD_NOLOAD)`.
- `GlossInit(true)` must be the first call in `load()`; without it, hooks
  silently fail.
- The game `.so` is **stripped**. Function addressing is done by **byte
  signatures** (function-head machine code with `?` wildcards), resolved at
  runtime by scanning `.text`.

### BreezeAPI

```
Host app (Java/Kotlin)
      |
      v
System.loadLibrary("breeze_api")   -- loads libbreeze_api.so into the process
      |
      v
Your code calls breeze::BreezeAPI::Instance().Init()
      |
      v
HookBySymbol / HookByOffset / HookByAddress on libminecraftpe.so
(which must already be loaded; resolve its base via ResolveLibraryBase)
```

Key consequences:

- `libbreeze_api.so` is a normal Android shared library shipped in
  `jniLibs/arm64-v8a/`. The host app loads it via `System.loadLibrary`.
- `Init()` must be called once before any hook/JS operation; it is
  idempotent.
- Function addressing uses **symbol names** (when exported), **library
  offsets** (relative to the library base), or **absolute addresses**.
  Dobby's internal symbol resolver handles unexported symbols as a
  fallback after `dlsym`.
- BreezeAPI embeds **QuickJS**; you can register native C++ callbacks as
  JS globals and `EvalJS` / `EvalJSModule` for runtime scripting.
- 16KB page alignment is set for Android 15+ compatibility.

## 2. Core APIs

### preloader

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

### BreezeAPI

| Purpose | API | Header |
|---|---|---|
| Singleton access | `breeze::BreezeAPI::Instance()` | `breeze_api.h` |
| Lifecycle | `Init(config)` / `Shutdown()` / `IsInitialized()` | `breeze_api.h` |
| Hook by symbol | `HookBySymbol(library, symbol, replace, &orig, tag)` | `breeze_api.h` |
| Hook by offset | `HookByOffset(library, offset, replace, &orig, tag)` | `breeze_api.h` |
| Hook by address | `HookByAddress(target, replace, &orig, tag)` | `breeze_api.h` |
| Unhook | `Unhook(target)` / `UnhookAll()` | `breeze_api.h` |
| Resolve library base | `ResolveLibraryBase(library)` | `breeze_api.h` |
| Resolve symbol | `ResolveSymbol(library, symbol)` | `breeze_api.h` |
| Query hooks | `GetHookInfo(target)` / `GetHookInfoByTag(tag)` / `GetAllHooks()` | `breeze_api.h` |
| Logging | `SetLogLevel(level)` / `GetLogLevel()` | `breeze_api.h` |
| Eval JS | `EvalJS(source, filename)` / `EvalJSModule(source, filename)` | `breeze_api.h` |
| Register JS function | `RegisterJSFunction(name, callback)` / `UnregisterJSFunction(name)` | `breeze_api.h` |
| Register JS module | `RegisterJSModule(specifier, source)` | `breeze_api.h` |
| JS globals | `SetJSGlobalString/Number/Bool` / `GetJSGlobalString/Number` | `breeze_api.h` |
| JS memory | `JSGC()` / `GetJSMemoryUsage()` / `SetJSMemoryLimit(n)` / `SetJSStackSize(n)` | `breeze_api.h` |

A flat C ABI is also available (`breeze_init`, `breeze_hook_symbol`,
`breeze_hook_offset`, `breeze_hook_address`, `breeze_unhook`,
`breeze_resolve_symbol`, `breeze_js_eval`, ...) for JNI consumers.

## 3. The 7-step workflow

Follow this order. Skipping steps is the most common cause of crashes.

### Step 0 — Choose the runtime

- If the host is **LeviLauncher** → use **preloader** (signatures, Gloss,
  `.levipack`).
- If the host app loads **`libbreeze_api.so`** via `System.loadLibrary`
  → use **BreezeAPI** (symbol/offset/address hooks, Dobby, QuickJS).
- If unsure, ask the user which launcher/SDK the mod targets.

The remaining steps note where the two runtimes diverge.

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

**preloader:**

1. Check the signature dictionary first (`Signatures.cpp` in the
   BedrockTools source tree). If it has an entry, resolve and proceed.
2. Otherwise, search community knowledge for the function name.
3. Only as a last resort, use a disassembler (IDA / Ghidra) to find a new
   function via string xrefs (see `references/ida-workflow.md`).

**BreezeAPI:**

1. If the function is an **exported symbol**, use `HookBySymbol` directly
   (Dobby's resolver falls back past `dlsym`).
2. If you know the **offset from the library base** (from a disassembler
   or a prior signature resolve), use `HookByOffset`.
3. If you have an **absolute address** at runtime (e.g. from
   `ResolveSymbol` or `ResolveLibraryBase + offset`), use `HookByAddress`.
4. For stripped, unexported functions, you still need a disassembler to
   find the offset once; then `HookByOffset` is stable across loads
   (the offset is fixed per game version).

### Step 3 — Analyze (optional)

If the function is undocumented, decompile it at the resolved address and
confirm: what it returns, what it writes, what it calls, and its calling
convention (arm64: args in X0..., return in X0/W0/S0). This step is
optional for functions already in the dictionary or with a known symbol.

### Step 4 — Pick the hook technique

| Situation | preloader | BreezeAPI |
|---|---|---|
| Need logic before/after, or to modify args/return | `pl::memory::hook` (inline) | `HookBySymbol/Offset/Address` |
| Function should just return a constant / do nothing | head-replace patch (back up first, then `RET`) | hook that returns early without calling orig |
| Change a constant / branch / force a path | byte patch with original-byte verification | byte patch via `ResolveLibraryBase + offset` + mprotect (BreezeAPI has no built-in patch API; use the preloader pattern or raw mprotect) |
| Override a virtual method | vtable slot hook (`resolveVtableFunction`) | `HookByOffset` on the vtable slot (compute slot address manually) |
| Hook a library import (e.g. EGL) | symbol + `hooks::install` on `dlsym` result | `HookBySymbol("libEGL.so", "eglSwapBuffers", ...)` |
| Wait for the game library | hook `dlopen` | poll `ResolveLibraryBase("libminecraftpe.so")` until non-null |
| Runtime scripting / config | typed C++ events | `EvalJS` + `RegisterJSFunction` |

**Safety rules (non-negotiable, both runtimes):**

1. Always read the current bytes before patching.
2. If current == target → already patched, skip.
3. If current == expected original → apply patch.
4. Otherwise → version mismatch: log and skip. **Never write garbage.**

### Step 5 — Verify signatures on the actual `.so` (preloader only)

```bash
python scripts/verify_signatures.py <libminecraftpe.so> \
    --sigs <path/to/Signatures.cpp> \
    --json sig_report.json
```

Verdicts:

- `UNIQUE` — exactly one match; safe to hook.
- `AMBIGUOUS` — multiple matches; lengthen the pattern or add fixed anchor bytes.
- `MISSING` — no match; wrong version, re-extract with a disassembler.

For BreezeAPI, this step is replaced by confirming the symbol resolves
(`ResolveSymbol` returns non-null) or the offset is correct (decompile at
`base + offset` matches the expected function head).

### Step 6 — Implement

**preloader — inline hook:**

```cpp
static std::string (*versionOriginal)(void*) = nullptr;
static std::string versionDetour(void* self) {
    std::string v = versionOriginal ? versionOriginal(self) : std::string{};
    return v + " | MyMod v1.0";
}
uintptr_t addr = pl::memory::resolveSignature(pattern, "libminecraftpe.so");
pl::memory::hook((void*)addr, (void*)versionDetour, (void**)&versionOriginal);
```

**preloader — safe byte patch:**

```cpp
std::array<uint8_t,4> expected{...}, replacement{...};
auto cur = pl::memory::readBytes(addr, 4);
if (cur == replacement) return;               // already patched
if (cur == expected) pl::memory::writeBytes(addr, replacement, "mypatch");
// else: version mismatch -> log and skip
```

**BreezeAPI — hook by symbol:**

```cpp
#include <breeze_api.h>

static void* (*orig_GameTick)(void*, int) = nullptr;
void* hook_GameTick(void* self, int dt) {
    // custom logic
    return orig_GameTick(self, dt);
}

void install() {
    auto& api = breeze::BreezeAPI::Instance();
    api.Init();
    api.HookBySymbol(
        "libminecraftpe.so",
        "_ZN6Server4tickEi",
        (void*)hook_GameTick,
        (void**)&orig_GameTick,
        "ServerTick");
}
```

**BreezeAPI — hook by offset (for stripped functions):**

```cpp
auto& api = breeze::BreezeAPI::Instance();
api.Init();
// offset from a prior disassembly; stable per game version
api.HookByOffset(
    "libminecraftpe.so",
    0x1234560,
    (void*)hook_GameTick,
    (void**)&orig_GameTick,
    "ServerTickByOffset");
```

**BreezeAPI — JS scripting:**

```cpp
api.RegisterJSFunction("getTickRate", [](const std::vector<std::string>&) {
    return std::to_string(20);
});
auto r = api.EvalJS(R"(var rate = getTickRate(); "Tick rate: " + rate;)");
// r.value == "Tick rate: 20"
```

### Step 7 — Build, package, deploy, verify

See `references/build-deploy.md` for the full NDK + CMake commands for
**both** runtimes:

- **preloader**: output `.so` must export `PLGetModRegistration`; ship it
  next to a valid `manifest.json` into the launcher's `mods/` directory
  (or package as `.levipack`).
- **BreezeAPI**: ship `libbreeze_api.so` in `jniLibs/arm64-v8a/` and link
  your mod against it (IMPORTED target or submodule).

Verify with `adb logcat` in both cases.

## 4. Typed events (preloader) vs JS scripting (BreezeAPI)

**preloader** converts game callbacks into typed C++ events that modules
subscribe to via `bus().subscribe<Event>(cb, priority)`. Third-party mods
subscribe through the runtime ABI.

| Event | Source hook | Use case |
|---|---|---|
| `FrameEvent` | `eglSwapBuffers` | every frame |
| `LocalPlayerTickEvent` | `NormalTick` | player tick |
| `ClientInstanceUpdateEvent` | `ClientInstanceUpdate` | get ClientInstance |
| `AttackEvent` (cancellable) | `GameModeAttack` / `SurvivalModeAttack` | attack logic |
| `ScreenStateEvent` | screen Open/Dtor hooks | UI state |
| `MouseInputEvent` | `pl::input` | mouse |

**BreezeAPI** uses the embedded QuickJS engine for runtime scripting:
register native callbacks as JS globals, evaluate JS strings/modules, and
share state via JS globals. This is the scripting equivalent of the
preloader event bus when the host app prefers JS-driven configuration.

## 5. References (load on demand)

- `references/feature-workflow.md` — feature → function → feasibility →
  hook-decision guide with worked examples.
- `references/hook-techniques.md` — full hook technique reference for
  both runtimes: inline hooks, chains, head replacement, NOP/branch
  patches, vtable, GOT/PLT, dlopen/EGL hooks, signature format rules,
  and BreezeAPI symbol/offset/address hooks.
- `references/so-analysis.md` — analyze the `.so` on disk without a device.
- `references/build-deploy.md` — NDK+CMake build for both runtimes,
  manifest, `.levipack` packaging, `jniLibs` integration, deployment,
  logcat verification.
- `references/ida-workflow.md` — optional IDA / IDA Pro MCP guidance.
- `references/version-porting.md` — porting checklist for new MCPE
  versions (signatures for preloader, offsets for BreezeAPI).

## 6. Scripts

- `scripts/verify_signatures.py` — scan a `.so` for all signatures parsed
  from `Signatures.cpp`; report UNIQUE/AMBIGUOUS/MISSING (preloader).
- `scripts/elf_facts.py` — read-only ELF facts (header, segments, sections,
  dynamic symbols, version strings) for a fresh `.so` (both runtimes).
- `scripts/aarch64_enc.py` — encode AArch64 patch instructions
  (MOV/NOP/RET/BR/FMOV) for byte patches (both runtimes).
- `scripts/package_levipack.py` — package a mod into `.levipack`
  (manifest + `.so` + resources) and verify the result (preloader).

## 7. Notes

- This skill uses the shared `SKILL.md` frontmatter convention
  (`name` + `description`), so it is discoverable by Codex, Claude Code,
  Cursor, and other agents that support agent skills.
- Hook/patch only what the user explicitly authorized; keep to learning
  and personal use and respect the game's terms of service.
- Always keep a backup of the original `.so`; fail safely on version
  mismatch.
- When the user does not specify a runtime, ask which launcher/SDK the
  mod targets before writing code.
