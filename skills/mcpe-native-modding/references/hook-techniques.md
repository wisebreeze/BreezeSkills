# Hook Techniques

Reference for every hooking / patching technique used in MCPE native mods.
Read the section that matches your feasibility verdict from
`feature-workflow.md`.

## 1. Signatures: locating functions without symbols

`libminecraftpe.so` is a stripped arm64 ELF. The methodology stores a
**byte pattern of the function head** for every function it uses, and
resolves it at runtime by scanning `.text`.

### 1.1 Pattern format

`pl::memory::resolveSignature` accepts hex strings like
`"FF 03 01 D1 FD 7B 02 A9 ..."`; `?` (or `??`) wildcards one byte.

Example (start of `VersionString`):

```
FF 03 01 D1 FD 7B 02 A9 F4 4F 03 A9 FD 83 00 91 ...
```

### 1.2 Why function heads work as signatures

arm64 functions begin with a fixed prologue. Register allocation can change
between builds, so the convention is to wildcard the **register-encoding
byte** (the low byte of each 4-byte instruction) and keep the opcode bytes:

```
?? 3C 00 13   ; SXTH W8, W1  (register byte wildcarded)
?? 08 80 52   ; MOV W9, #0x40
```

Rules:

- 4 bytes per AArch64 instruction, space-separated.
- Keep the opcode bytes (high 3); wildcard the low register byte when it can
  vary.
- Prefer patterns ≥ 16 bytes; longer patterns reduce AMBIGUOUS matches.
- Anchor on unique opcodes (e.g. a `MOV` with an unusual immediate) rather
  than generic prologue bytes.

### 1.3 Offline verification

Always run `scripts/verify_signatures.py` against the actual `.so` before
hooking. Only `UNIQUE` matches are safe.

## 2. Inline hooks

### 2.1 Low-level engine (Gloss)

- `GlossInit(true)` — must be called once before any hooking (the `true`
  also initializes linker-hook capability).
- `GlossHook(addr, new_func, &old_func)` — writes a trampoline at the target
  head; `old_func` becomes a callable copy of the original.
- `GlossHookAddrByName(lib, offset, ...)` — hook by library offset (waits
  for the library to load).
- `GlossHookByName(lib, sym, ...)` / `GlossPltHook(lib, sym, ...)` — hook
  by symbol name / PLT.
- `GlossGotHook(got_addr, new_func, &old_func)` — rewrite a GOT entry.
- `GlossHookDisable/Enable/Delete`, `GlossHookGetOldFunc`,
  `GlossHookReplaceNewFunc`.
- Instruction helpers: `MakeArm64B`, `MakeArm64BL`, `MakeArm64NOP`,
  `MakeArm64RET`, `MakeArm64AbsoluteJump` (emits `LDR X18,#8; BR X18; dest`).

Inline hook mechanics on arm64:

1. Copy the first instructions of the target (enough to fit a jump) into
   private memory (the trampoline), fixing any PC-relative instructions
   (ADRP / literal loads).
2. Patch the function head with a jump to your detour (near: `B +-128MB`;
   far: `LDR X18,#8; BR X18; <detour addr>`).
3. Your detour calls the saved original pointer to run the untouched logic.

### 2.2 Preloader wrapper: pl::memory::hook

```cpp
namespace pl::memory {
    void* hook(void* target, void* detour, void** original, int priority = 0);
    bool  unhook(void* handle);
}
```

Always store the handle so you can cleanly unhook in `unload()`.

### 2.3 Canonical inline-hook shape

```cpp
static std::string (*versionOriginal)(void*) = nullptr;
static std::string versionDetour(void* self) {
    std::string v = versionOriginal ? versionOriginal(self) : std::string{};
    return v + " | MyMod v1.0";
}
// in load():
uintptr_t addr = pl::memory::resolveSignature(pattern, "libminecraftpe.so");
pl::memory::hook((void*)addr, (void*)versionDetour, (void**)&versionOriginal);
```

## 3. Head-replace patches (return a constant / do nothing)

When the function should just return a fixed value or do nothing, replace
its head with a tiny stub instead of installing a full hook.

```cpp
// Force Fullbright to return max light.
// arm64: MOV W0, #0x40 ; RET  (or whatever max constant applies)
std::array<uint8_t,8> expected   = { /* original first 8 bytes */ };
std::array<uint8_t,8> replacement = { 0x40,0x00,0x80,0x52, 0xC0,0x03,0x5F,0xD6 };
auto cur = pl::memory::readBytes(addr, 8);
if (cur == replacement) return;                  // already patched
if (cur == expected) pl::memory::writeBytes(addr, replacement, "fullbright");
// else: version mismatch -> log and skip
```

Use `scripts/aarch64_enc.py` to compute the encoded bytes for
`MOV`/`NOP`/`RET`/`BR`/`FMOV`.

## 4. Byte patches (change a constant / branch)

Smallest possible change. Typical cases:

- Change a `MOV` immediate (e.g. raise a cap from `0x40` to `0x3E7`).
- NOP a branch that limits behavior.
- Force a path by rewriting a conditional branch to unconditional (or
  vice versa).

```cpp
// Raise a cap: MOV W9, #0x40 -> MOV W9, #0x3E7
std::array<uint8_t,4> expected    = { 0x89,0x08,0x80,0x52 }; // MOV W9,#0x40
std::array<uint8_t,4> replacement = { 0xE9,0x7C,0x80,0x52 }; // MOV W9,#0x3E7
auto cur = pl::memory::readBytes(addr, 4);
if (cur == replacement) return;
if (cur == expected) pl::memory::writeBytes(addr, replacement, "raise-cap");
// else: version mismatch -> log and skip
```

**Safety rules (non-negotiable):**

1. Always `readBytes` the current bytes before patching.
2. If current == target → already patched, skip.
3. If current == expected original → apply patch.
4. Otherwise → version mismatch: log and skip. **Never write garbage.**

## 5. vtable hooks

For virtual methods, hook the slot in the vtable rather than the function
body. Resolve the slot by RTTI name:

```cpp
void* fn = pl::memory::resolveVtableFunction(
    "class LevelContainerManager",   // RTTI type info name
    0,                                // slot index
    "libminecraftpe.so");
pl::memory::hook(fn, (void*)myDetour, (void**)&original);
```

Member offsets and vtable slots are version-sensitive; keep them in a
single `offsets/` header so porting only touches one file.

## 6. GOT / PLT hooks

For library imports (e.g. `eglSwapBuffers` in `libEGL.so`):

```cpp
void* sym = dlsym(RTLD_DEFAULT, "eglSwapBuffers");
pl::memory::hook(sym, (void*)mySwapBuffers, (void**)&origSwap);
```

Or use the dedicated engine calls:

- `GlossGotHook(got_addr, new_func, &old_func)` — rewrite a GOT entry.
- `GlossPltHook(lib, sym, ...)` — hook the PLT stub.

## 7. dlopen hook (wait for the game library)

Your `.so` loads before `libminecraftpe.so`. Hook `dlopen` so you can finish
setup when the game library appears:

```cpp
static void* (*dlopenOriginal)(const char*, int) = nullptr;
static void* dlopenDetour(const char* name, int flags) {
    void* h = dlopenOriginal ? dlopenOriginal(name, flags) : nullptr;
    if (name && strstr(name, "libminecraftpe.so")) {
        // game library is now mapped -> resolve signatures, install hooks
        installGameHooks();
    }
    return h;
}
```

Alternative: poll with `RTLD_NOLOAD` until the handle is non-null.

## 8. EGL hook (per-frame event source)

`eglSwapBuffers` is the canonical per-frame anchor. Hook it (it is an
exported symbol in `libEGL.so`) and publish a `FrameEvent` from the detour.
This is how `FrameEvent` is sourced.

## 9. Signature extraction (new functions)

When the dictionary does not have a function:

1. Find the function via a string xref (search for an error/log message it
   emits, follow the xref to the referencing function).
2. In the disassembler, copy the first ~16-32 bytes of the function head.
3. Wildcard the low register byte of each instruction.
4. Add the entry to your local `Signatures.cpp` copy.
5. Run `verify_signatures.py` — must be `UNIQUE`.

## 10. Common pitfalls

- Forgetting `GlossInit(true)` → hooks silently fail.
- Hooking an AMBIGUOUS signature → wrong function patched, crash.
- Patching without verifying original bytes → wrong-version crash.
- Not storing the hook handle → cannot cleanly unhook in `unload()`.
- Reimplementing function logic instead of calling the original → drift,
  bugs.
- Baking in a hardcoded address → breaks on the next game version.
