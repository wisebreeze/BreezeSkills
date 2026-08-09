#!/usr/bin/env python3
"""
Encode AArch64 patch instructions for MCPE byte patches.

Given a small set of intended instructions (MOV immediate, NOP, RET, BR,
FMOV), produce the 4-byte little-endian machine code to write into
libminecraftpe.so. Useful when constructing head-replace or constant-change
patches.

Usage examples:
    python aarch64_enc.py mov w0 0x40
    python aarch64_enc.py mov w9 0x3e7
    python aarch64_enc.py nop
    python aarch64_enc.py ret
    python aarch64_enc.py br x16
    python aarch64_enc.py fmov s0 1.0

Output: 4 hex bytes, space-separated, in the same format used by the
signature dictionary (e.g. "40 00 80 52").
"""

from __future__ import annotations

import argparse
import struct
import sys


def enc_mov_imm(rd: int, imm: int, width: int = 32) -> bytes:
    """MOV (immediate) — MOVZ form, 16-bit immediate + shift 0.

    For width=32: MOV W<d>, #imm  (sf=0)
    For width=64: MOV X<d>, #imm  (sf=1)

    Only handles 0 <= imm <= 0xffff with no shift. For larger immediates,
    use MOV + MOVK chains (not implemented here; use a disassembler).
    """
    if not (0 <= imm <= 0xFFFF):
        raise ValueError(f"imm {imm} out of 16-bit range; use MOV+MOVK chain")
    if not (0 <= rd <= 31):
        raise ValueError(f"register rd {rd} out of range")
    sf = 1 if width == 64 else 0
    # MOVZ: sf 10 100101 hw imm16 Rd
    instr = (sf << 31) | (0b10 << 29) | (0b100101 << 23) | (0 << 21) | \
            ((imm & 0xFFFF) << 5) | (rd & 0x1F)
    return struct.pack("<I", instr)


def enc_nop() -> bytes:
    # NOP = HINT #0 = 0xD503201F
    return struct.pack("<I", 0xD503201F)


def enc_ret(rn: int = 30) -> bytes:
    # RET Xn: 1101011 0 0 10 11111 000000 00000 Rn 00000
    # canonical RET (X30) = 0xD65F03C0
    instr = (0b1101011 << 25) | (0b0010111 << 21) | (0b11111 << 16) | \
            (0b000000 << 10) | ((rn & 0x1F) << 5) | 0
    # Build the standard RET encoding directly:
    instr = 0xD65F0000 | ((rn & 0x1F) << 5)
    return struct.pack("<I", instr)


def enc_br(rn: int) -> bytes:
    # BR Xn: 1101011 0 0 00 11111 000000 00000 Rn 00000
    instr = 0xD61F0000 | ((rn & 0x1F) << 5)
    return struct.pack("<I", instr)


def enc_fmov_imm(rd: int, value: float) -> bytes:
    """FMOV S<d>, #fimm — only the 8-bit immediate form (limited range).

    Most floats cannot be encoded this way; this is a best-effort encoder
    for the common small constants. For arbitrary floats, load from a
    literal pool instead.
    """
    # FMOV (scalar, immediate) single-precision:
    # 0001 1110 0 1 1 imm8 1 00 1 0000 Rd
    # We do not implement the imm8 -> float expansion here; raise.
    raise NotImplementedError(
        "FMOV imm8 form not implemented; use a literal load for arbitrary floats"
    )


def reg_id(name: str) -> int:
    name = name.strip().lower()
    if not name:
        raise ValueError("empty register name")
    if name[0] in ("w", "x", "s", "d", "v"):
        return int(name[1:])
    # allow bare numbers
    return int(name)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_mov = sub.add_parser("mov", help="MOV <Rd>, #imm (16-bit, no shift)")
    p_mov.add_argument("rd", help="register, e.g. w0 / x9")
    p_mov.add_argument("imm", help="immediate, e.g. 0x40 or 64")

    sub.add_parser("nop", help="NOP")
    p_ret = sub.add_parser("ret", help="RET [Xn]")
    p_ret.add_argument("rn", nargs="?", default="x30", help="register (default x30)")

    p_br = sub.add_parser("br", help="BR Xn")
    p_br.add_argument("rn", help="register, e.g. x16")

    p_fmov = sub.add_parser("fmov", help="FMOV S<d>, #float (limited)")
    p_fmov.add_argument("rd", help="register, e.g. s0")
    p_fmov.add_argument("value", help="float, e.g. 1.0")

    args = ap.parse_args()

    if args.cmd == "mov":
        rd = reg_id(args.rd)
        is_64 = args.rd.strip().lower().startswith("x")
        imm = int(args.imm, 0)
        b = enc_mov_imm(rd, imm, width=64 if is_64 else 32)
    elif args.cmd == "nop":
        b = enc_nop()
    elif args.cmd == "ret":
        b = enc_ret(reg_id(args.rn))
    elif args.cmd == "br":
        b = enc_br(reg_id(args.rn))
    elif args.cmd == "fmov":
        b = enc_fmov_imm(reg_id(args.rd), float(args.value))
    else:
        ap.error("unknown command")

    print(" ".join(f"{x:02X}" for x in b))
    return 0


if __name__ == "__main__":
    sys.exit(main())
