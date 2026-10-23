# -*- coding: utf-8 -*-
"""Sonde capstone — STP/LDP, TBZ/TBNZ, LDUR/STUR, barrières (oracle uniquement ;
le décodeur reste sans dépendance). Partie 2 : unscaled + barrières.
Exécution : python tests/probe_newins.py   (depuis decompiler/)
"""
import random
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN  # type: ignore

md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
random.seed(0xA64)


def cap(word):
    for ins in md.disasm(word.to_bytes(4, "little"), 0):
        return ins.mnemonic, ins.op_str
    return None, None


def rnd_regs(n=3):
    return [random.randint(0, 30) for _ in range(n)]


# --- famille unscaled : octet/haut-octet des préfixes 0x38/78/B8/F8 ------------
# mot = (pref<<24) | (k<<21) | (imm9<<12) | (Rn<<5) | Rt   k = bits 23-21
print("=== unscaled STUR/LDUR : pref x bits23-21 ===")


def uns_word(pref, k, imm9):
    return (pref << 24) | ((k & 7) << 21) | ((imm9 & 0x1FF) << 12) | \
           (rnd_regs(1)[0] << 5) | rnd_regs(1)[0]


uns = {}
for pref in (0x38, 0x78, 0xB8, 0xF8):
    # note: bits 23-21 dépendent de ; on balaye les 8, et pour les formes
    # hors STUR/LDUR (post/pre/exclusifs) on mémorise le mnémonique.
    for k in range(8):
        for imm9 in (0, -8, 16, 2047, -2048):
            w = (pref << 24) | ((k & 7) << 21) | ((imm9 & 0x1FF) << 12) | \
                ((random.randint(0, 30) << 5) | random.randint(0, 30))
            m, ops = cap(w)
            key = (m if m else "<invalide>", pref, k)
            uns.setdefault(key, [0, None])
            uns[key][0] += 1
            uns[key][1] = (w, ops, imm9)
for (m, pref, k), (n, ex) in sorted(uns.items()):
    w, ops, imm9 = ex
    print(f"  {m:10s} pref={pref:#04x} k={k:02d} n={n:5d} "
          f"ex {w:08x} {ops} (imm9={imm9})")

# --- barrières : exhaustif bits 23-12 × (CRm, opc2) × Rt=0x1F -----------------
print("\n=== barrières (exhaustif bits 23-12, CRm x opc2) ===")
fam = {"dmb": set(), "dsb": set(), "isb": set()}
for hi in range(0x1000):                 # bits 23-12
    for crm in range(16):
        for op2 in range(8):
            w = 0xD5030000 | (hi << 12) | (crm << 8) | (op2 << 5) | 0x1F
            m, ops = cap(w)
            if m in fam:
                fam[m].add((hi, crm, op2, ops))
for m in ("dmb", "dsb", "isb"):
    hits = fam[m]
    print(f"  {m}: {len(hits)} triplets (hi, CRm, opc2)")
    his = {h for h, _, _, _ in hits}
    print(f"    hi (bits 23-12) vus: {sorted(hex(h) for h in his)}")
    tab = {}
    for h, crm, op2, ops in hits:
        tab.setdefault((crm, op2), []).append(ops)
    for k, ops_list in sorted(tab.items()):
        base = sorted(set(ops_list))
        print(f"    CRm={k[0]:X} opc2={k[1]:X} -> {base} "
              f"(n hs={len(set(h for h, c, o, _ in hits if (c, o) == k))})")

# --- exclusifs / hybrides zone imm9 : repérage à ne pas capter comme STUR/LDUR
print("\n=== zone bits 25-21 ( groupes exclusivité / post / pre ) ===")
groups = {}
for _ in range(60000):
    size = random.randint(0, 3)
    k = random.randint(0, 31)            # bits 25-21
    imm9 = random.choice((-8, 0, 16, -1))
    w = (size << 30) | (0b111 << 27) | (0 << 26) | (k << 21) | \
        ((imm9 & 0x1FF) << 12) | (random.randint(0, 30) << 5) | \
        random.randint(0, 30)
    m, ops = cap(w)
    if m is None:
        continue
    key = (m.split(" ")[0][:6], k)
    groups.setdefault(key, 0)
    groups[key] += 1
for (mname, k), n in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0])):
    print(f"  k(bits25-21)={k:02d}: {mname:8s} n={n}")

# --- fumée : mots aléatoires --------------------------------------------------
print("\n=== fumée : mots aléatoires ===")
n_ok = n_unk = 0
mn = {}
for _ in range(20000):
    w = random.getrandbits(32)
    m, ops = cap(w)
    if m is not None:
        n_ok += 1
        mn[m] = mn.get(m, 0) + 1
    else:
        n_unk += 1
print(f"  capstone gère {n_ok}, NON gérée {n_unk}")
print("  top mnémoniques:", sorted(mn.items(), key=lambda kv: -kv[1])[:12])
