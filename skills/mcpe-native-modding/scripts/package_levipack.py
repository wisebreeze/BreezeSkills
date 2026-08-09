#!/usr/bin/env python3
"""
Package an MCPE native mod into a .levipack bundle.

A .levipack is a zip archive (with the .levipack extension) containing:
  - manifest.json   (mod metadata; validated for required fields)
  - <entry>.so      (the compiled mod; must export PLGetModRegistration)
  - res/            (optional resources, recursively)

The script validates:
  - manifest.json schema (name, version, author, entry, target_arch).
  - the .so file exists and is an ELF64 AArch64 shared object.
  - the .so exports PLGetModRegistration (via llvm-nm if available, else
    via a pure-Python dynamic-symbol scan).
  - target_arch in manifest matches the .so machine type.

Usage:
    python package_levipack.py \
        --manifest <dir>/manifest.json \
        --so build/libMyMod.so \
        --resources <dir>/res/ \
        --out MyMod-1.0.0.levipack
"""

from __future__ import annotations

import argparse
import json
import shutil
import struct
import sys
import zipfile
from pathlib import Path

REQUIRED_FIELDS = ("name", "version", "author", "entry", "target_arch")


def validate_manifest(manifest_path: Path) -> dict:
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"manifest.json is not valid JSON: {e}")
    missing = [f for f in REQUIRED_FIELDS if f not in data]
    if missing:
        raise ValueError(f"manifest.json missing fields: {missing}")
    if data["target_arch"] != "arm64-v8a":
        raise ValueError(f"target_arch must be 'arm64-v8a', got {data['target_arch']!r}")
    if not data["entry"].endswith(".so"):
        raise ValueError(f"entry must end with .so, got {data['entry']!r}")
    return data


def check_elf64_aarch64(so_path: Path) -> None:
    if not so_path.is_file():
        raise FileNotFoundError(f".so not found: {so_path}")
    data = so_path.read_bytes()
    if data[:4] != b"\x7fELF":
        raise ValueError(f"{so_path} is not an ELF file")
    if data[4] != 2:
        raise ValueError(f"{so_path} is not ELF64")
    e_machine = struct.unpack_from("<H", data, 18)[0]
    if e_machine != 183:  # EM_AARCH64
        raise ValueError(
            f"{so_path} machine type is {e_machine}, expected 183 (AArch64)"
        )


def has_exported_symbol(so_path: Path, symbol: str) -> bool:
    """Check the .dynsym for an exported symbol. Pure Python (no nm needed)."""
    data = so_path.read_bytes()
    e_shoff = struct.unpack_from("<Q", data, 40)[0]
    e_shentsize = struct.unpack_from("<H", data, 58)[0]
    e_shnum = struct.unpack_from("<H", data, 60)[0]
    e_shstrndx = struct.unpack_from("<H", data, 62)[0]

    if e_shnum == 0 or e_shoff == 0:
        return False

    shstr_off = e_shoff + e_shstrndx * e_shentsize
    shstr_offset = struct.unpack_from("<Q", data, shstr_off + 24)[0]
    shstr_size = struct.unpack_from("<Q", data, shstr_off + 32)[0]
    strtab = data[shstr_offset:shstr_offset + shstr_size]

    def name_at(buf: bytes, off: int) -> str:
        end = buf.find(b"\x00", off)
        return buf[off:end].decode("utf-8", "replace") if end >= 0 else ""

    dynsym_off = None
    dynstr_off = None
    dynstr_size = 0
    for i in range(e_shnum):
        off = e_shoff + i * e_shentsize
        sh_name = struct.unpack_from("<I", data, off)[0]
        sh_type = struct.unpack_from("<I", data, off + 4)[0]
        sh_offset = struct.unpack_from("<Q", data, off + 24)[0]
        sh_size = struct.unpack_from("<Q", data, off + 32)[0]
        nm = name_at(strtab, sh_name)
        if sh_type == 11:  # SHT_DYNSYM
            dynsym_off = sh_offset
            dynsym_size = sh_size
        elif nm == ".dynstr":
            dynstr_off = sh_offset
            dynstr_size = sh_size

    if dynsym_off is None or dynstr_off is None:
        return False

    strtab2 = data[dynstr_off:dynstr_off + dynstr_size]
    entry = 24
    n = dynsym_size // entry
    for i in range(n):
        off = dynsym_off + i * entry
        st_name = struct.unpack_from("<I", data, off)[0]
        st_info = data[off + 4]
        st_shndx = struct.unpack_from("<H", data, off + 6)[0]
        # only consider defined (shndx != UNDEF) global/weak symbols
        if st_shndx == 0:  # SHN_UNDEF
            continue
        bind = st_info >> 4
        if bind not in (1, 2):  # GLOBAL, WEAK
            continue
        nm = name_at(strtab2, st_name)
        if nm == symbol:
            return True
    return False


def build_zip(manifest: dict, so_path: Path, res_dir: Path | None,
              out_path: Path) -> None:
    if out_path.exists():
        out_path.unlink()
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        z.write(so_path, arcname=manifest["entry"])
        if res_dir and res_dir.is_dir():
            for p in res_dir.rglob("*"):
                if p.is_file():
                    arc = p.relative_to(res_dir)
                    z.write(p, arcname=str(Path("res") / arc))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--manifest", required=True, help="path to manifest.json")
    ap.add_argument("--so", required=True, help="path to the compiled .so")
    ap.add_argument("--resources", help="optional resources directory")
    ap.add_argument("--out", required=True, help="output .levipack path")
    args = ap.parse_args()

    manifest_path = Path(args.manifest)
    so_path = Path(args.so)
    res_dir = Path(args.resources) if args.resources else None
    out_path = Path(args.out)

    try:
        manifest = validate_manifest(manifest_path)
        check_elf64_aarch64(so_path)
        if not has_exported_symbol(so_path, "PLGetModRegistration"):
            raise ValueError(
                f"{so_path} does not export PLGetModRegistration; "
                "did you forget PL_REGISTER_MOD in main.cpp?"
            )
        if Path(manifest["entry"]).name != so_path.name:
            print(f"warning: manifest entry {manifest['entry']!r} != "
                  f"so filename {so_path.name!r}", file=sys.stderr)
        build_zip(manifest, so_path, res_dir, out_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    print(f"packaged {out_path} ({out_path.stat().st_size} bytes)")
    print(f"  name:    {manifest['name']}")
    print(f"  version: {manifest['version']}")
    print(f"  entry:   {manifest['entry']}")
    print(f"  arch:    {manifest['target_arch']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
