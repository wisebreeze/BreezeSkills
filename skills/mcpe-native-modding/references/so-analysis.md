# `.so` Analysis Without a Device

How to inspect `libminecraftpe.so` on disk before any hooking. All steps
here are read-only and run on the host machine — no phone needed.

## 1. Confirm the file is the right target

```bash
file <libminecraftpe.so>
# expect: ELF 64-bit LSB shared object, ARM aarch64, stripped
```

If it is not `aarch64` or not `stripped`, you have the wrong file.

## 2. ELF facts (Python-only)

```bash
python scripts/elf_facts.py <libminecraftpe.so>
```

Reports:

- ELF header (class, data, machine, entry).
- Program headers (segments: type, flags, vaddr, filesz).
- Section headers (name, type, addr, offset, size).
- Dynamic symbols (imports the library needs).
- Version strings (searchable: `Minecraft`, version tags).

Use this to confirm the build before extracting signatures.

## 3. Signature verification

```bash
python scripts/verify_signatures.py <libminecraftpe.so> \
    --sigs <path/to/Signatures.cpp> \
    --json sig_report.json
```

Output per signature:

- `id` — the signature identifier.
- `pattern` — the hex pattern with `?` wildcards.
- `verdict` — `UNIQUE` / `AMBIGUOUS` / `MISSING`.
- `matches` — number of matches in `.text`.
- `address` — first match virtual address (imagebase 0, same as IDA).
- `file_offset` — first match file offset.

Only `UNIQUE` matches are safe to hook. For `AMBIGUOUS`, lengthen the
pattern or add fixed anchor bytes. For `MISSING`, the version is wrong;
re-extract with a disassembler.

## 4. Strings of interest

Quick scan for version / build tags:

```bash
strings <libminecraftpe.so> | rg -i 'minecraft|version|build' | head
```

Useful for confirming the game version before porting.

## 5. Section layout

The `.text` section is what signature scanning walks. Confirm its bounds:

```bash
python scripts/elf_facts.py <libminecraftpe.so> | rg -A2 '\.text'
```

If `.text` is unusually small or absent, the file is packed/encrypted and
the standard workflow does not apply.

## 6. Dynamic symbols (imports)

```bash
python scripts/elf_facts.py <libminecraftpe.so> | rg -A50 'Dynamic symbols'
```

Confirms which external functions (e.g. `eglSwapBuffers`, `dlopen`,
`__android_log_print`) the library imports — useful for picking GOT/PLT
hook targets.

## 7. Decision checklist

Before any hooking:

- [ ] `file` reports `aarch64` + `stripped`.
- [ ] `elf_facts.py` runs without error and shows a sane `.text`.
- [ ] `verify_signatures.py` reports `UNIQUE` for every signature you plan
      to hook.
- [ ] For any `AMBIGUOUS` signature: lengthen the pattern and re-verify.
- [ ] For any `MISSING` signature: stop; the version is wrong, port first
      (see `version-porting.md`).
- [ ] You have a backup of the original `.so`.

Only after every box is checked, proceed to `hook-techniques.md`.
