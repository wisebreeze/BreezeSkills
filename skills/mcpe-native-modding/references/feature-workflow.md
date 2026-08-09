# Feature → Function → Feasibility → Hook Decision

The core thinking workflow. Use this **before** writing any code. Skipping
this pipeline is the most common cause of broken mods.

## The pipeline

```
User wants feature F
        |
        v
1. Name the game function(s) that implement the behavior F touches
        |
        v
2. Locate the function
   (a) signature dictionary already has it -> resolve
   (b) community knowledge / prior art
   (c) optional disassembler (IDA/Ghidra): string xref -> function
        |
        v
3. Analyze (optional but recommended for unknown functions):
   decompile, read what it returns / writes / calls
        |
        v
4. Feasibility check: can F be expressed as
   (a) change return value?           -> inline hook or head-replace
   (b) change argument/input?         -> inline hook (modify before orig)
   (c) change a constant/branch?      -> byte patch
   (d) change object state?           -> field offset write / call
   (e) change virtual dispatch?       -> vtable hook
   (f) change when it runs?           -> dlopen / EGL / tick hooks + events
        |
        v
5. Verify signature is UNIQUE on the actual .so
        |
        v
6. Implement with the canonical shapes (see hook-techniques.md)
        |
        v
7. Build -> package -> deploy -> logcat verify
```

## Worked examples

### Example A — "Show the game version in the HUD"

- Feature: append the MCPE version string to the HUD.
- Function: `VersionString` (returns `std::string`).
- Feasibility: change return value → inline hook.
- Implementation:

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

### Example B — "Fullbright (max light)"

- Feature: force fullbright lighting.
- Function: `Fullbright` (no args, returns a light value).
- Feasibility: function should just return max → head-replace patch.
- Implementation: back up the first 12 bytes, write a small stub that
  loads the max constant and returns. Always verify the original bytes
  first; on version mismatch, log and skip.

### Example C — "Cancel an attack under a condition"

- Feature: cancel the player's attack.
- Function: `GameModeAttack` / `SurvivalModeAttack`.
- Feasibility: needs to run before/after and possibly cancel → inline hook
  + cancellable event.
- Implementation: hook the function, run the original, publish an
  `AttackEvent` that subscribers can mark cancelled; if cancelled, return
  early without applying damage.

## Feasibility rules of thumb

- Prefer the smallest change: a 4-byte patch beats a hook; a hook beats
  reimplementing the function.
- Never patch without verifying the original bytes; a wrong-version patch
  is worse than no patch.
- If a signature is AMBIGUOUS, do not guess: lengthen it or find a better
  anchor instruction.
- If the target function is huge and complex, consider hooking one of its
  callees (a smaller helper) instead.
- Error/log strings are excellent anchors for finding undocumented parsers:
  search the message text, follow its xref, and decompile the referencing
  function.
- If the feature is per-frame or per-tick, reuse `FrameEvent` /
  `LocalPlayerTickEvent` instead of hooking another function.
- If the feature needs an object only available later (ClientInstance,
  local player), hook `ClientInstanceUpdate` / `NormalTick` and cache the
  pointer.
