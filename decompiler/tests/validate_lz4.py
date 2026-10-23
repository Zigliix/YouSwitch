# -*- coding: utf-8 -*-
"""Validation du décompresseur LZ4 (loader) contre python-lz4 — ORACLE DEV.

Ce script n'est PAS lancé par test_pipeline.py : il exige le paquet `lz4`
(pip install lz4) et ne fait pas partie du code livré.

Exécution :  python tests/validate_lz4.py
"""
from __future__ import annotations
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from loader import nsw_formats as nsw   # noqa: E402
import lz4.block                        # noqa: E402  (oracle uniquement)

rng = random.Random(0x5EED)


def patterns() -> list[bytes]:
    out: list[bytes] = []
    for n in (1, 4, 12, 100, 1000, 65536, 150_000):
        out.append(bytes(rng.randrange(256) for _ in range(n)))       # incompressible
        out.append(bytes([rng.randrange(256)]) * n)                   # RLE
        out.append((b"ABCDEFGH" * ((n // 8) + 1))[:n])                # périodique
        mixed = bytearray()
        while len(mixed) < n:
            if rng.random() < 0.5:
                mixed += bytes(rng.randrange(256) for _ in range(rng.randrange(1, 60)))
            else:
                mixed += b"SwitchRecomp" * rng.randrange(1, 30)
        out.append(bytes(mixed[:n]))
    return out


def main() -> int:
    fails = 0
    cases = patterns()
    for idx, data in enumerate(cases):
        blk = lz4.block.compress(data, store_size=False, mode="high_compression")
        try:
            got = nsw.lz4_decompress_block(blk, len(data))
        except ValueError as exc:
            print(f"[FAIL] cas {idx} ({len(data)} o) : {exc}")
            fails += 1
            continue
        if got != data:
            print(f"[FAIL] cas {idx} ({len(data)} o) : contenu différent")
            fails += 1
    print(f"== {len(cases)} cas LZ4, {fails} échec(s) ==")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
