# Optional: IDA / IDA Pro MCP Guide

A disassembler is **optional** for the standard workflow because the
signature dictionary already covers ~80 common functions. You only need
IDA when:

- The function you want is **not** in the dictionary.
- A signature is `AMBIGUOUS` and you need a better anchor.
- You are porting to a new MCPE version and must re-extract patterns.

This guide is generic; any IDA version works.

## 1. Load the binary

1. Open `<libminecraftpe.so>` in IDA (auto-analyze).
2. Wait for auto-analysis to finish (large binary; can take minutes).
3. Confirm the processor is `ARM64` and the imagebase is `0`.

## 2. Find a function via string xref

For an undocumented function:

1. `View → Open subviews → Strings` (Shift+F12).
2. Search for a distinctive error/log message the function emits.
3. Double-click the string → `Jump to xref` (X).
4. The referencing function is your candidate.
5. Rename it (e.g. `MyTarget_Fn`) for the session.

## 3. Extract a signature

1. Place the cursor on the **first instruction** of the function.
2. Select the first 16-32 bytes (4-8 instructions).
3. In the hex view, copy the bytes.
4. Wildcard the low register byte of each instruction (the byte that
   encodes the destination register).
5. Format as space-separated hex with `?` for wildcards:

   ```
   FF 03 01 D1 FD 7B 02 A9 F4 4F 03 A9 FD 83 00 91
   ```

6. Add the entry to your local `Signatures.cpp` copy.
7. Run `verify_signatures.py` — must report `UNIQUE`.

## 4. Decompile (optional analysis)

For understanding what a function does:

1. `F5` (Hex-Rays decompiler) on the function.
2. Read: what it returns, what it writes, what it calls, calling convention.
3. arm64 calling convention: integer args in `X0..X7`, return in `X0`/`W0`,
   float args in `S0..S7` / `D0..D7`, return in `S0`/`D0`.

## 5. IDA Pro MCP (optional automation)

If you run an IDA Pro MCP service, the included `ida_mcp_client.py`
provides a JSON-RPC client for batch operations:

- Resolve addresses by name.
- Batch-decompile a list of targets.
- Export a JSON report.

Usage (generic):

```bash
python scripts/ida_mcp_client.py --host 127.0.0.1 --port 13337 \
    --targets targets.json --out decomp_report.json
```

Where `targets.json` is a list of `{ "name": "...", "address": "0x..." }`
objects. This is purely optional; the standard workflow does not require
it.

## 6. When to skip IDA entirely

You can skip IDA if **all** of these are true:

- The function you want is in the signature dictionary.
- `verify_signatures.py` reports `UNIQUE` for it.
- You only need to hook/patch, not understand the function body.

In that case, the standard 7-step workflow in `SKILL.md` is sufficient.

## 7. Pitfalls

- Pasting a signature with the register byte **not** wildcarded → breaks
  on the next build that uses a different register.
- Copying bytes from the middle of the function instead of the head →
  signature matches the wrong place.
- Trusting auto-analysis names → they are guesses; verify with xrefs.
- Forgetting to re-run `verify_signatures.py` after editing the
  dictionary → silent drift.
