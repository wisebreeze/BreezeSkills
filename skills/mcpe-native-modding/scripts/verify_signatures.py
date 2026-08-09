#!/usr/bin/env python3
"""
Verify signature patterns against an MCPE libminecraftpe.so (ARM64, ELF64)
on disk.

This is the offline counterpart of the in-game resolveSignatures() step:
it scans the executable bytes of the ELF and reports, for every signature
parsed from a Signatures.cpp source file, the first match virtual address
(imagebase 0, same convention as IDA), the file offset, the number of
matches, and a UNIQUE / AMBIGUOUS / MISSING verdict.

Usage:
    python verify_signatures.py <libminecraftpe.so> \
        --sigs <path/to/Signatures.cpp> \
        [--json out.json]

Only UNIQUE matches are safe to hook.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

SIG_LINE_RE = re.compile(r'SignatureId::([A-Za-z0-9_]+)\s*,\s*"([0-9A-Fa-f? ]+)"')


def parse_signatures(cpp_path: Path) -> list[dict]:
    """Extract (id, pattern) pairs from a Signatures.cpp-style file."""
    text = cpp_path.read_text(encoding="utf-8", errors="replace")
    sigs = []
    for match in SIG_LINE_RE.finditer(text):
        pattern = " ".join(match.group(2).split()).upper()
        sigs.append({"id": match.group(1), "pattern": pattern})
    return sigs


def parse_pattern(pattern: str) -> tuple[bytes, list[bool]]:
    """Split a hex pattern into (fixed bytes, wildcard mask)."""
    tokens = pattern.split()
    fixed = bytearray()
    mask = []
    for token in tokens:
        if token in ("?", "??"):
            fixed.append(0)
            mask.append(True)
        else:
            # Only full-byte hex tokens (2 chars) are valid; reject half-byte
            # wildcards like "5?" which are not part of the signature format.
            if len(token) != 2 or any(c not in "0123456789abcdefABCDEF" for c in token):
                raise ValueError(
                    f"invalid pattern token {token!r}: use 2 hex digits or '?'"
                )
            fixed.append(int(token, 16))
            mask.append(False)
    return bytes(fixed), mask


def find_all(haystack: bytes, fixed: bytes, mask: list[bool]) -> list[int]:
    """Return all start offsets where the pattern matches."""
    n = len(fixed)
    if n == 0 or n > len(haystack):
        return []
    results = []
    last_start = len(haystack) - n
    i = 0
    while i <= last_start:
        ok = True
        for j in range(n):
            if mask[j]:
                continue
            if haystack[i + j] != fixed[j]:
                ok = False
                break
        if ok:
            results.append(i)
        i += 1
    return results


def parse_elf64_text_segment(path: Path) -> tuple[bytes, int, int]:
    """Return (executable_bytes, file_offset_of_text, vaddr_of_text).

    Walks program headers; returns the union of all executable PT_LOAD
    segments (which, for a stripped .so, is effectively .text and friends).
    """
    data = path.read_bytes()
    if data[:4] != b"\x7fELF":
        raise ValueError("not an ELF file")
    if data[4] != 2:
        raise ValueError("only ELF64 supported")
    e_phoff = struct.unpack_from("<Q", data, 0x20)[0]
    e_phentsize = struct.unpack_from("<H", data, 0x36)[0]
    e_phnum = struct.unpack_from("<H", data, 0x38)[0]

    segs = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type = struct.unpack_from("<I", data, off)[0]
        if p_type != 1:  # PT_LOAD
            continue
        p_flags = struct.unpack_from("<I", data, off + 4)[0]
        p_offset = struct.unpack_from("<Q", data, off + 8)[0]
        p_vaddr = struct.unpack_from("<Q", data, off + 16)[0]
        p_filesz = struct.unpack_from("<Q", data, off + 32)[0]
        if p_flags & 0x1:  # PF_X
            segs.append((p_offset, p_vaddr, p_filesz))

    if not segs:
        raise ValueError("no executable PT_LOAD segment found")

    segs.sort()
    base_off = segs[0][0]
    base_vaddr = segs[0][1]
    end_off = max(s[0] + s[2] for s in segs)
    text = data[base_off:end_off]
    return text, base_off, base_vaddr


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("so", help="path to libminecraftpe.so")
    ap.add_argument("--sigs", required=True,
                    help="path to Signatures.cpp")
    ap.add_argument("--json", help="write a JSON report to this path")
    args = ap.parse_args()

    so_path = Path(args.so)
    sigs_path = Path(args.sigs)
    if not so_path.is_file():
        print(f"error: {so_path} not found", file=sys.stderr)
        return 2
    if not sigs_path.is_file():
        print(f"error: {sigs_path} not found", file=sys.stderr)
        return 2

    sigs = parse_signatures(sigs_path)
    if not sigs:
        print("error: no signatures parsed from --sigs file", file=sys.stderr)
        return 2

    text, base_off, base_vaddr = parse_elf64_text_segment(so_path)

    report = []
    counts = {"UNIQUE": 0, "AMBIGUOUS": 0, "MISSING": 0}
    for s in sigs:
        fixed, mask = parse_pattern(s["pattern"])
        hits = find_all(text, fixed, mask)
        if len(hits) == 1:
            verdict = "UNIQUE"
        elif len(hits) > 1:
            verdict = "AMBIGUOUS"
        else:
            verdict = "MISSING"
        counts[verdict] += 1
        entry = {
            "id": s["id"],
            "pattern": s["pattern"],
            "verdict": verdict,
            "matches": len(hits),
        }
        if hits:
            entry["address"] = hex(base_vaddr + hits[0])
            entry["file_offset"] = base_off + hits[0]
        report.append(entry)

    if args.json:
        Path(args.json).write_text(
            json.dumps({"signatures": report, "counts": counts}, indent=2),
            encoding="utf-8",
        )

    print(f"scanned {len(sigs)} signatures against {so_path.name}")
    print(f"  UNIQUE:    {counts['UNIQUE']}")
    print(f"  AMBIGUOUS: {counts['AMBIGUOUS']}")
    print(f"  MISSING:   {counts['MISSING']}")
    print()
    for e in report:
        line = f"  [{e['verdict']:9s}] {e['id']:<40s} matches={e['matches']}"
        if "address" in e:
            line += f" addr={e['address']}"
        print(line)

    # Non-zero exit if anything is not UNIQUE, so CI can catch regressions.
    return 0 if counts["AMBIGUOUS"] == 0 and counts["MISSING"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
