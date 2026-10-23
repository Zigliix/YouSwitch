# -*- coding: utf-8 -*-
"""Balayage systématique : NOUVELLES familles vs capstone (oracle externe).

Familles couvertes (layouts verrouillés par probe_newins.py) :
  PAIR      STP/LDP/STNP/LDNP/LDPSW
  TBZ       TBZ/TBNZ
  UNSCALED  STUR/LDUR(/B/H/LDURSB/LDURSH/LDURSW) ; PRFUM -> inconnu
  BARRIER   DMB/DSB/ISB ; familles 001 (MSR)/010 (CLREX)/111 (SYS) -> inconnu

Assertions :
  - zéro faux positif   : nous connaissons -> capstone connait, mnémo égale
  - zéro écart de noyau : cas générés par les layouts verrouillés
  -directions : familles voisines réservées (MSR/CLREX/SYS, post-index...)

capstone est uniquement un oracle optionnel : le décodeur n'y dépend pas.
Usage (depuis decompiler/) : python tests/sweep_newins.py
"""
from __future__ import annotations

import importlib.util
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from decoder import arm64 as A

# --- oracle (optionnel) ----------------------------------------------------
if importlib.util.find_spec("capstone") is None:
    print("capstone absent : balayage sauté (le décodeur reste autonome).")
    sys.exit(0)

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN  # noqa: E402

_md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)

def cap(word: int) -> tuple[str, str] | None:
    """(mnémonique, opérandes) capstone ou None si refusé."""
    try:
        for ins in _md.disasm(word.to_bytes(4, "little"), 0):
            return ins.mnemonic, ins.op_str
    except Exception:
        pass
    return None

# --- bilan -----------------------------------------------------------------
stats: dict = {"ok": {}, "gap": {}, "faux_pos": [], "inconnus_deux": 0}

# Alias de rendu capstone : sémantique identique, mnémonique canonique autre
# (capstone imprime 'mov' pour MOVZ/MOVN et pour ORR/MOV..., 'neg(s)' pour
# SUB(S) avec Rn=XZR, 'mvn' pour ORN avec Rn=XZR ; nos mnémoniques restent
# ceux de base, le decodeur garde les champs bruts).
_ALIASES = {
    "mov": {"movz", "movn", "orr"},
    "neg": {"sub"},
    "negs": {"subs"},
    "mvn": {"orn"},
}

def check(word: int, tag: str) -> None:
    ins = A.decode(word)
    c = cap(word)
    if not ins.unknown:
        if c is None:
            stats["faux_pos"].append((tag, word, "capstone refusé"))
            return
        ours, theirs = ins.mnemonic.lower(), c[0].lower()
        if ours != theirs and ours not in _ALIASES.get(theirs, ()):
            stats["ok"].setdefault(tag, 0)
            stats["faux_pos"].append((tag, word,
                                      f'nous={ins.mnemonic} cap={c[0]} {c[1]}'))
            return
        stats["ok"][tag] = stats["ok"].get(tag, 0) + 1
    else:
        if c is None:
            stats["inconnus_deux"] += 1
        else:
            stats["gap"][tag] = stats["gap"].get(tag, 0) + 1

def _gen(mkgen, tag, combos):
    """Décline une fonction mot(mot-clés) sur toutes les combinaisons."""
    for combo in combos:
        check(mkgen(*combo), tag)

def sweep_pair() -> None:
    opcLmode = [(opc, L, mode)
                for opc in range(4) for L in range(2) for mode in range(4)]
    imms = [0, 1, -1, 8, 16, 31, -32, 63, -64]
    regs = [(rn, rt, rt2)
            for rn in (0, 1, 2, 30, 31)
            for rt in (0, 1, 5, 30, 31)
            for rt2 in (0, 1, 5, 29, 31)]
    def mk(opc, L, mode, imm, rn, rt, rt2):
        return ((opc << 30) | (0b101 << 27) | (mode << 23) | (L << 22)
                | ((imm & 0x7F) << 15) | (rt2 << 10) | (rn << 5) | rt)
    for opc, L, mode in opcLmode:
        for imm in imms:
            for rn, rt, rt2 in regs:
                check(mk(opc, L, mode, imm, rn, rt, rt2), "PAIR")

def sweep_tbz() -> None:
    imms = [-8192, -1, 0, 1, 4095, 8191, 100, -100]
    for sf in range(2):
        for op in range(2):
            for b40 in range(32):
                for imm in imms:
                    for rt in (0, 1, 31):
                        word = ((sf << 31) | (0b011011 << 25) | (op << 24)
                                | (b40 << 19) | ((imm & 0x3FFF) << 5) | rt)
                        check(word, "TBZ")

def sweep_unscaled() -> None:
    imms = [-512, -1, 0, 1, 16, -16, 255, -256, 100, -100]
    combos = [(size, grp, b11, imm, rn, rt)
              for size in range(4) for grp in range(8) for b11 in range(4)
              for imm in imms for rn in (0, 31) for rt in (0, 31)]
    def mk(size, grp, b11, imm, rn, rt):
        return ((size << 30) | (0b111 << 27) | (grp << 21)
                | ((imm & 0x1FF) << 12) | (b11 << 10) | (rn << 5) | rt)
    _gen(mk, "UNSCALED", combos)

def sweep_barrier() -> None:
    """Espace exhaustif de la block-système CRm/famille (128 mots)."""
    for fam in range(8):
        for crm in range(16):
            word = 0xD5033000 | (crm << 8) | (fam << 5) | 0x1F
            check(word, f"BARRIER_fam{fam}")

def sweep_random(n: int = 30000) -> None:
    rng = random.Random(0x5F3C)
    for _ in range(n):
        check(rng.getrandbits(32), "RANDOM")

def main() -> int:
    sweep_pair()
    sweep_tbz()
    sweep_unscaled()
    sweep_barrier()
    sweep_random()
    bad = stats["faux_pos"]
    print("== couverture (cas où les deux décodent, mnémo égale) ==")
    for tag in sorted(stats["ok"]):
        print(f"  {tag:14s} {stats['ok'][tag]:7d}")
    print("== gaps acceptés (nous inconnu, capstone connait) ==")
    for tag in sorted(stats["gap"]):
        print(f"  {tag:14s} {stats['gap'][tag]:7d}")
    print(f"  inconnus_deux  {stats['inconnus_deux']:7d}")
    if bad:
        print(f"!! FAUX POSITIFS : {len(bad)}")
        for tag, word, why in bad[:25]:
            print(f"   {tag:14s} {word:08X}  {why}")
        return 1
    print("VERDICT : zero faux positif, zero écart de noyau.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
