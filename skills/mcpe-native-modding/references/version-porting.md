# Version Porting Checklist

When a new MCPE version ships, `libminecraftpe.so` changes: functions move,
prologues shift, member offsets and vtable slots drift. This checklist
makes porting mechanical and safe.

## 1. Snapshot the new binary

1. Pull the new `libminecraftpe.so` from the device.
2. Back it up: `cp <libminecraftpe.so> <libminecraftpe.so>.bak`.
3. Run `file` and `elf_facts.py` to confirm it is still `aarch64` +
   `stripped`, and note any header changes.

## 2. Re-verify every signature

```bash
python scripts/verify_signatures.py <new-libminecraftpe.so> \
    --sigs <path/to/Signatures.cpp> \
    --json sig_report.json
```

Classify each signature:

| Verdict | Action |
|---|---|
| `UNIQUE` | No change needed. |
| `AMBIGUOUS` | Lengthen the pattern or add a fixed anchor byte; re-verify. |
| `MISSING` | The function moved or its prologue changed; re-extract (see below). |

## 3. Re-extract MISSING signatures

For each `MISSING` signature:

1. Open the new `.so` in a disassembler (see `ida-workflow.md`).
2. Find the function via string xref (the same error/log message).
3. Copy the first 16-32 bytes of the new prologue.
4. Wildcard the low register byte of each instruction.
5. Replace the entry in your local `Signatures.cpp`.
6. Re-run `verify_signatures.py` — must be `UNIQUE`.

## 4. Re-derive member offsets and vtable slots

Member offsets and vtable slots are **not** in the signature dictionary;
they live in `offsets/*.hpp`. For each offset you use:

1. Decompile the function that reads/writes the member.
2. Confirm the offset is still the same byte count.
3. If it changed, update the constant in `offsets/*.hpp`.

For vtable slots:

1. Resolve the vtable by RTTI name
   (`pl::memory::resolveVtableFunction`).
2. Confirm the slot index still points at the expected function (compare
   the decompiled body).
3. If it shifted, update the slot constant.

## 5. Re-verify byte patches

Every byte patch has an `expected` original-byte array. On the new
binary:

1. `readBytes` the current bytes at the patch address.
2. If current == `expected` → patch still applies cleanly.
3. If current == `replacement` → already patched (unusual on a fresh
   binary; investigate).
4. Otherwise → the surrounding code changed; re-derive the patch from the
   new disassembly and update `expected` + `replacement`.

**Never** apply a patch when the current bytes do not match `expected`.
That is a version mismatch; writing the patch anyway corrupts the binary.

## 6. Smoke-test on device

1. Build the updated `.so`.
2. Deploy (see `build-deploy.md`).
3. `adb logcat | rg -i 'mymod\|preloader'`.
4. Confirm: `load()` ok, `GlossInit` ok, all signatures `UNIQUE`, all
   hooks installed, no `version mismatch` warnings.

## 7. Keep a porting log

Maintain a `PORTING.md` in your mod repo recording, per game version:

- Date of the port.
- Game version string (from `elf_facts.py` strings).
- Number of signatures: `UNIQUE` / `AMBIGUOUS` / `MISSING`.
- List of re-extracted signatures (id + new pattern).
- List of changed offsets / vtable slots.
- List of re-derived byte patches.

This makes the next port a diff against the last known-good state.

## 8. Common porting pitfalls

- Trusting that "only one function moved" → almost always several moved;
  re-verify the whole dictionary, not just the one you care about.
- Forgetting to update `expected` bytes on a patch → silent corruption on
  the new version.
- Reusing an old vtable slot index → hooks the wrong virtual method.
- Not bumping the mod version in `manifest.json` → launcher may skip the
  update.
- Shipping without a logcat smoke-test → first crash is on the user's
  device.
