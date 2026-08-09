#!/usr/bin/env python3
"""
Read-only ELF facts for an MCPE libminecraftpe.so (ARM64, ELF64).

Reports: ELF header, program headers (segments), section headers, dynamic
symbols, and version strings. Pure standard library; no dependencies.

Usage:
    python elf_facts.py <libminecraftpe.so> [--sections] [--symbols] [--strings]
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path


def read_elf64_header(data: bytes) -> dict:
    if data[:4] != b"\x7fELF":
        raise ValueError("not an ELF file")
    e_ident = data[:16]
    ei_class = e_ident[4]      # 1=32bit, 2=64bit
    ei_data = e_ident[5]       # 1=LE, 2=BE
    e_type = struct.unpack_from("<H", data, 16)[0]
    e_machine = struct.unpack_from("<H", data, 18)[0]
    e_version = struct.unpack_from("<I", data, 20)[0]
    e_entry = struct.unpack_from("<Q", data, 24)[0]
    e_phoff = struct.unpack_from("<Q", data, 32)[0]
    e_shoff = struct.unpack_from("<Q", data, 40)[0]
    e_flags = struct.unpack_from("<I", data, 48)[0]
    e_ehsize = struct.unpack_from("<H", data, 52)[0]
    e_phentsize = struct.unpack_from("<H", data, 54)[0]
    e_phnum = struct.unpack_from("<H", data, 56)[0]
    e_shentsize = struct.unpack_from("<H", data, 58)[0]
    e_shnum = struct.unpack_from("<H", data, 60)[0]
    e_shstrndx = struct.unpack_from("<H", data, 62)[0]
    return {
        "ei_class": "ELF64" if ei_class == 2 else "ELF32",
        "ei_data": "LE" if ei_data == 1 else "BE",
        "e_type": e_type,
        "e_machine": e_machine,
        "e_machine_name": "AArch64" if e_machine == 183 else f"0x{e_machine:x}",
        "e_version": e_version,
        "e_entry": hex(e_entry),
        "e_phoff": e_phoff,
        "e_shoff": e_shoff,
        "e_flags": hex(e_flags),
        "e_ehsize": e_ehsize,
        "e_phentsize": e_phentsize,
        "e_phnum": e_phnum,
        "e_shentsize": e_shentsize,
        "e_shnum": e_shnum,
        "e_shstrndx": e_shstrndx,
    }


def read_program_headers(data: bytes, hdr: dict) -> list[dict]:
    segs = []
    pt_types = {1: "PT_LOAD", 2: "PT_DYNAMIC", 3: "PT_INTERP", 4: "PT_NOTE",
                6: "PT_PHDR", 7: "PT_TLS", 0x6474e550: "PT_GNU_EHFRAME",
                0x6474e551: "PT_GNU_STACK", 0x6474e552: "PT_GNU_RELRO"}
    for i in range(hdr["e_phnum"]):
        off = hdr["e_phoff"] + i * hdr["e_phentsize"]
        p_type = struct.unpack_from("<I", data, off)[0]
        p_flags = struct.unpack_from("<I", data, off + 4)[0]
        p_offset = struct.unpack_from("<Q", data, off + 8)[0]
        p_vaddr = struct.unpack_from("<Q", data, off + 16)[0]
        p_paddr = struct.unpack_from("<Q", data, off + 24)[0]
        p_filesz = struct.unpack_from("<Q", data, off + 32)[0]
        p_memsz = struct.unpack_from("<Q", data, off + 40)[0]
        p_align = struct.unpack_from("<Q", data, off + 48)[0]
        flags = ""
        if p_flags & 4: flags += "R"
        if p_flags & 2: flags += "W"
        if p_flags & 1: flags += "X"
        segs.append({
            "type": pt_types.get(p_type, f"0x{p_type:x}"),
            "flags": flags,
            "offset": hex(p_offset),
            "vaddr": hex(p_vaddr),
            "paddr": hex(p_paddr),
            "filesz": p_filesz,
            "memsz": p_memsz,
            "align": hex(p_align),
        })
    return segs


def read_section_headers(data: bytes, hdr: dict) -> list[dict]:
    if hdr["e_shnum"] == 0 or hdr["e_shoff"] == 0:
        return []
    shstr_off = hdr["e_shoff"] + hdr["e_shstrndx"] * hdr["e_shentsize"]
    shstr_offset = struct.unpack_from("<Q", data, shstr_off + 24)[0]
    shstr_size = struct.unpack_from("<Q", data, shstr_off + 32)[0]
    strtab = data[shstr_offset:shstr_offset + shstr_size]

    def name_at(off: int) -> str:
        end = strtab.find(b"\x00", off)
        return strtab[off:end].decode("utf-8", "replace") if end >= 0 else ""

    sh_types = {0: "SHT_NULL", 1: "SHT_PROGBITS", 2: "SHT_SYMTAB",
                3: "SHT_STRTAB", 4: "SHT_RELA", 5: "SHT_HASH",
                6: "SHT_DYNAMIC", 7: "SHT_NOTE", 8: "SHT_NOBITS",
                9: "SHT_REL", 11: "SHT_DYNSYM", 14: "SHT_INIT_ARRAY",
                15: "SHT_FINI_ARRAY"}
    secs = []
    for i in range(hdr["e_shnum"]):
        off = hdr["e_shoff"] + i * hdr["e_shentsize"]
        sh_name = struct.unpack_from("<I", data, off)[0]
        sh_type = struct.unpack_from("<I", data, off + 4)[0]
        sh_flags = struct.unpack_from("<Q", data, off + 8)[0]
        sh_addr = struct.unpack_from("<Q", data, off + 16)[0]
        sh_offset = struct.unpack_from("<Q", data, off + 24)[0]
        sh_size = struct.unpack_from("<Q", data, off + 32)[0]
        secs.append({
            "name": name_at(sh_name),
            "type": sh_types.get(sh_type, f"0x{sh_type:x}"),
            "flags": hex(sh_flags),
            "addr": hex(sh_addr),
            "offset": hex(sh_offset),
            "size": sh_size,
        })
    return secs


def read_dynamic_symbols(data: bytes, hdr: dict, secs: list[dict]) -> list[dict]:
    dynsym = next((s for s in secs if s["type"] == "SHT_DYNSYM"), None)
    if not dynsym:
        return []
    strtab_sec = None
    # find .dynstr by link field — we approximate by name
    strtab_sec = next((s for s in secs if s["name"] == ".dynstr"), None)
    if strtab_sec is None:
        return []
    sym_off = int(dynsym["offset"], 16)
    sym_size = dynsym["size"]
    str_off = int(strtab_sec["offset"], 16)
    str_size = strtab_sec["size"]
    strtab = data[str_off:str_off + str_size]

    def name_at(off: int) -> str:
        end = strtab.find(b"\x00", off)
        return strtab[off:end].decode("utf-8", "replace") if end >= 0 else ""

    syms = []
    entry = 24  # Elf64_Sym
    n = sym_size // entry
    for i in range(n):
        off = sym_off + i * entry
        st_name = struct.unpack_from("<I", data, off)[0]
        st_info = data[off + 4]
        st_other = data[off + 5]
        st_shndx = struct.unpack_from("<H", data, off + 6)[0]
        st_value = struct.unpack_from("<Q", data, off + 8)[0]
        st_size = struct.unpack_from("<Q", data, off + 16)[0]
        bind = st_info >> 4
        typ = st_info & 0xf
        bind_s = {0: "LOCAL", 1: "GLOBAL", 2: "WEAK"}.get(bind, str(bind))
        typ_s = {0: "NOTYPE", 1: "OBJECT", 2: "FUNC", 3: "SECTION",
                 4: "FILE"}.get(typ, str(typ))
        nm = name_at(st_name)
        if not nm:
            continue
        syms.append({
            "name": nm,
            "bind": bind_s,
            "type": typ_s,
            "shndx": st_shndx,
            "value": hex(st_value),
            "size": st_size,
        })
    return syms


def find_version_strings(data: bytes) -> list[str]:
    hits = []
    for m in re.finditer(rb"[ -~]{4,}", data):
        s = m.group().decode("utf-8", "replace")
        if re.search(r"(?i)minecraft|version|build|v\d+\.\d+", s):
            hits.append(s)
    # dedup, keep order
    seen = set()
    out = []
    for s in hits:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out[:50]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("so", help="path to libminecraftpe.so")
    ap.add_argument("--sections", action="store_true", help="print section headers")
    ap.add_argument("--symbols", action="store_true", help="print dynamic symbols")
    ap.add_argument("--strings", action="store_true", help="print version strings")
    args = ap.parse_args()

    path = Path(args.so)
    if not path.is_file():
        print(f"error: {path} not found", file=sys.stderr)
        return 2
    data = path.read_bytes()

    hdr = read_elf64_header(data)
    print("== ELF header ==")
    for k, v in hdr.items():
        print(f"  {k}: {v}")

    segs = read_program_headers(data, hdr)
    print(f"\n== Program headers ({len(segs)}) ==")
    for s in segs:
        print(f"  {s['type']:<16s} flags={s['flags']:<4s} "
              f"vaddr={s['vaddr']} filesz={s['filesz']}")

    secs = read_section_headers(data, hdr)
    if args.sections or True:
        print(f"\n== Section headers ({len(secs)}) ==")
        for s in secs:
            print(f"  {s['name']:<24s} {s['type']:<14s} "
                  f"addr={s['addr']} size={s['size']}")

    if args.symbols:
        syms = read_dynamic_symbols(data, hdr, secs)
        print(f"\n== Dynamic symbols ({len(syms)}) ==")
        for s in syms:
            print(f"  {s['bind']:<7s} {s['type']:<8s} {s['name']} "
                  f"value={s['value']} size={s['size']}")

    if args.strings:
        vs = find_version_strings(data)
        print(f"\n== Version-ish strings (first {len(vs)}) ==")
        for s in vs:
            print(f"  {s}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
