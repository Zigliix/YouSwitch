# -*- coding: utf-8 -*-
"""
Décodeur d'instructions ARM64 (AArch64) — a64, jeu fixe 32 bits.

Familles décodées (voir knowledge/arm64.md) :
  ADD/SUB (immédiat, shifted reg, extended reg), logiques (shifted reg,
  immédiat bitmask), MOV wide (MOVZ/MOVN/MOVK), ADR/ADRP, CBZ/CBNZ,
  B/BL, B.cond, RET, LDR/STR (unsigned imm, entier), NOP,
  paires STP/LDP/STNP/LDNP/LDPSW, TBZ/TBNZ,
  STUR/LDUR (B/H et charges signees SB/SH/SW), barrières DMB/DSB/ISB.
"""
from __future__ import annotations
from dataclasses import dataclass, field

# --- champs de bits -------------------------------------------------------
def bits(word: int, hi: int, lo: int) -> int:
    """Extrait les bits [hi..lo] (inclus) d'un mot."""
    return (word >> lo) & ((1 << (hi - lo + 1)) - 1)

def sval(value: int, width: int) -> int:
    """Étend un champ signé de `width` bits."""
    if value & (1 << (width - 1)):
        value -= 1 << width
    return value

# --- registres ------------------------------------------------------------
ARM_OPTION_NAMES = ("UXTB", "UXTH", "UXTW", "UXTX", "SXTB", "SXTH", "SXTW", "SXTX")
COND_NAMES = ("EQ", "NE", "HS", "LO", "MI", "PL", "VS", "VC",
              "HI", "LS", "GE", "LT", "GT", "LE", "AL", "NV")

def reg_x(r: int, sf: int, is_sp: bool = False) -> str:
    """Nom d'un registre 64 (sf=1) / 32 bits (sf=0). L'index 31 = ZR ou SP."""
    if r == 31:
        if sf and is_sp:
            return "SP"
        return "XZR" if sf else "WZR"
    return (f"X{r}" if sf else f"W{r}")

def hx_signed(v: int) -> str:
    """Hexadécimal signé : '-0x20' / '0x10' (rendus d'offsets mémoire)."""
    return f"-0x{-v:x}" if v < 0 else f"0x{v:x}"

# --- structure décodée ----------------------------------------------------
@dataclass
class Ins:
    addr: int          # adresse de l'instruction (offset segment + base)
    raw: int           # mot 32 bits brut
    group: str         # famille ('ADD_SUB_IMM', 'BRANCH', ...)
    mnemonic: str = "" # ADD, SUBS, MOVZ, B.EQ, LDR ...
    sf: int = 1        # 1 = 64 bits, 0 = 32 bits
    rd: int | None = None
    rn: int | None = None
    rm: int | None = None
    rt: int | None = None
    imm: int = 0             # immédiat principal (déjà décodé)
    shift_amt: int = 0       # décalage (imm6, hw*16, imm12 pour LDR/STR octets? -> bytes calculé)
    shift_type: str = ""     # '', LSL, LSR, ASR, ROR
    option: int | None = None  # extension (0..7) ADD/SUB ext. ; barrière : famille
    mode: str = ""           # accès mémoire : "" (offset/np), "post", "pre"
    cond: str = ""
    target: int | None = None  # cible de branchement adressée
    flags: bool = False        # l'instruction écrit NZCV
    unknown: bool = False

# --- immédiat logique (DecodeBitMasks, calibré empiriquement vs capstone) --
# Champs réels : N = bit 22 ; immr = bits 21-16 ; imms = bits 15-10.
# len (1..6) = index du bit le plus haut de x = (N<<6) | (~imms & 63)  [index 0-based]
# esize = 1 << len ; S = imms & (esize-1) ; R = immr & (esize-1)
# valeurs interdites : x == 0, len < 1, S == esize-1 (motif tout-à-1).
# Valeur : motif = ones(S+1) tourné à droite de R dans la fenêtre esize,
#          puis répété sur toute la largeur du registre (64 bits pour X).
def _ror_window(value: int, amount: int, width: int) -> int:
    amount %= width
    return ((value >> amount) | (value << (width - amount))) & ((1 << width) - 1)

def decode_bitmask(sf: int, n: int, imms: int, immr: int) -> int | None:
    """Immédiat logique (N:immr:imms) — sf 1 = 64 bits, 0 = 32 bits."""
    if sf == 0 and n == 1:              # 32 bits : N doit rester à 0
        return None
    x = ((~imms) & 0x3F) | (n << 6)
    if x == 0:
        return None
    length = x.bit_length() - 1         # index du bit le plus haut
    if length < 1:
        return None
    esize = 1 << length
    S = imms & (esize - 1)
    R = immr & (esize - 1)
    if S == esize - 1:                  # motif tout-à-1 dans la fenêtre : interdit
        return None
    pattern = _ror_window((1 << (S + 1)) - 1, R, esize)
    out = 0
    blocks = 64 if sf else 32
    k = 0
    while esize * k < blocks:
        out |= pattern << (esize * k)
        k += 1
    return out

# --- décodeurs par famille ------------------------------------------------
def _decode_addsub_imm(i: Ins, w: int) -> Ins:
    """sf op S 100010 sh imm12 Rn Rd ; alias CMP/CMN (S=1, Rd=31)."""
    i.sf, op, setter = bits(w, 31, 31), bits(w, 30, 30), bits(w, 29, 29)
    sh = bits(w, 23, 23)
    imm12 = bits(w, 22, 10)
    i.imm = imm12 << 12 if sh else imm12          # LSL #12 possible
    i.rn, i.rd = bits(w, 9, 5), bits(w, 4, 0)
    if setter:
        i.flags = True
        i.mnemonic = ("CMN" if op == 0 and i.rd == 31 else
                      "CMP" if op == 1 and i.rd == 31 else
                      "ADDS" if op == 0 else "SUBS")
    else:
        i.mnemonic = "ADD" if op == 0 else "SUB"
    return i

# --- suite des familles ---------------------------------------------------
def _decode_addsub_reg(i: Ins, w: int) -> Ins:
    """Famille 01011 : shifted register (bit21=0) ou extended register (bit21=1)."""
    i.sf, op, setter = bits(w, 31, 31), bits(w, 30, 30), bits(w, 29, 29)
    i.rn, i.rd, i.rm = bits(w, 9, 5), bits(w, 4, 0), bits(w, 20, 16)
    if bits(w, 21, 21) == 1:                           # --- extended register
        i.option = bits(w, 15, 13)
        i.shift_amt = bits(w, 12, 10)
        if bits(w, 23, 22) != 0 or i.shift_amt > 4 \
                or (i.sf == 0 and i.option in (3, 7)):
            # opt != 00 (hors familles taguees) ; decalage > 4 ;
            # UXTX/SXTX interdits en 32 bits
            i.unknown = True
            return i
        i.mnemonic = ("ADDS" if op == 0 and setter else
                      "SUBS" if setter else "ADD" if op == 0 else "SUB")
    else:                                              # --- shifted register
        shift = bits(w, 23, 22)
        imm6 = bits(w, 15, 10)
        if shift == 0b11 or (i.sf == 0 and imm6 > 31):
            # ROR interdit en ADD/SUB ; W : decalage max 31
            i.unknown = True
            return i
        i.shift_type = ("LSL", "LSR", "ASR", "ROR")[shift]
        i.shift_amt = imm6
        i.mnemonic = ("ADDS" if op == 0 and setter else
                      "SUBS" if setter else "ADD" if op == 0 else "SUB")
    if setter:
        i.flags = True
        if i.rd == 31:
            i.mnemonic = "CMN" if op == 0 else "CMP"
    return i

_logical_bis = {"AND": ("BIC", 1), "ORR": ("ORN", 1), "EOR": ("EON", 1)}

def _decode_logical_reg(i: Ins, w: int) -> Ins:
    """Famille 01010 : AND/ORR/EOR/ANDS shifted register (+BIC/ORN/EON via N=1)."""
    # NB : ici bit21 est le champ N (formes négatives BIC/ORN/EON/BICS) — libre.
    i.sf, opc, N = bits(w, 31, 31), bits(w, 30, 29), bits(w, 21, 21)
    i.rn, i.rd, i.rm = bits(w, 9, 5), bits(w, 4, 0), bits(w, 20, 16)
    sh = bits(w, 23, 22)
    imm6 = bits(w, 15, 10)
    if i.sf == 0 and imm6 > 31:           # W reg : décalage max 31
        i.unknown = True
        return i
    i.shift_type = ("LSL", "LSR", "ASR", "ROR")[sh]
    i.shift_amt = imm6
    base = ("AND", "ORR", "EOR", "ANDS")[opc]
    if N:
        # BIC/ORN/EON pour opc 00/01/10 ; BICS pour opc 11 (ANDS + N=1).
        base = "BICS" if opc == 3 else _logical_bis[base][0]
    i.mnemonic = "TST" if (opc == 3 and not N and i.rd == 31) else base
    i.flags = (opc == 3)
    return i


def _decode_logical_imm(i: Ins, w: int) -> Ins:
    """sf opc 100100 N immr(21-16) imms(15-10) Rn Rd."""
    i.sf, opc, N = bits(w, 31, 31), bits(w, 30, 29), bits(w, 22, 22)
    immr, imms = bits(w, 21, 16), bits(w, 15, 10)
    i.rn, i.rd = bits(w, 9, 5), bits(w, 4, 0)
    val = decode_bitmask(i.sf, N, imms, immr)
    if val is None:
        i.unknown = True
        return i
    i.imm = val
    base = ("AND", "ORR", "EOR", "ANDS")[opc]
    i.mnemonic = "TST" if (opc == 3 and i.rd == 31) else base
    i.flags = (opc == 3)
    return i


def _decode_movwide(i: Ins, w: int) -> Ins:
    """MOVN/MOVZ/MOVK : sf opc(00,10,11) 100101 hw imm16 Rd."""
    i.sf = bits(w, 31, 31)
    opc = bits(w, 30, 29)
    if opc == 0b01:                       # MOV wide : grade 01 non alloué
        i.unknown = True
        return i
    i.rd = bits(w, 4, 0)
    hw = bits(w, 22, 21)                  # champ hw : bits 22-21 (calibré vs capstone)
    if i.sf == 0 and hw != 0:             # 32 bits : hw = 0 seulement
        i.unknown = True
        return i
    i.imm, i.shift_amt = bits(w, 20, 5), hw * 16
    i.mnemonic = ("MOVN", "MOVZ", "MOVK")[{0: 0, 2: 1, 3: 2}[opc]]
    return i


def _decode_adr(i: Ins, w: int) -> Ins:
    i.sf = 1
    i.rd = bits(w, 4, 0)
    immlo, immhi = bits(w, 30, 29), bits(w, 23, 5)
    i.imm = (immhi << 2) | immlo
    i.imm = sval(i.imm, 21) if (w >> 31) == 0 else sval(i.imm << 12, 33)
    i.mnemonic = "ADR" if (w >> 31) == 0 else "ADRP"
    return i


def _decode_cbz(i: Ins, w: int) -> Ins:
    i.sf = bits(w, 31, 31)
    i.mnemonic = "CBNZ" if bits(w, 24, 24) else "CBZ"
    i.rt = bits(w, 4, 0)
    i.imm = sval(bits(w, 23, 5), 19) * 4
    i.target = i.addr + i.imm
    return i


def _decode_branch(i: Ins, w: int) -> Ins:
    if (w >> 26) & 0x3F == 0b000101:
        i.mnemonic = "B"
    else:
        i.mnemonic = "BL"
    i.sf = 1
    i.imm = sval(bits(w, 25, 0), 26) * 4
    i.target = i.addr + i.imm
    i.conditional = False
    return i

def _decode_bcond(i: Ins, w: int) -> Ins:
    i.sf = 1
    cond = bits(w, 3, 0)
    # bit4=1 : variante "branch-consistent" FEAT_HBC -> BC.<cond> (capstone).
    i.mnemonic = ("BC." if bits(w, 4, 4) else "B.") + COND_NAMES[cond]
    i.cond = COND_NAMES[cond]
    i.imm = sval(bits(w, 23, 5), 19) * 4
    i.target = i.addr + i.imm
    return i


def _decode_ret(i: Ins, w: int) -> Ins:
    i.sf = 1
    i.mnemonic = "RET"
    i.rn = bits(w, 9, 5)
    return i


_LDR_STR_SIZES = {0: "b", 1: "h", 2: "w", 3: "d"}

def _decode_ldrstr_imm(i: Ins, w: int) -> Ins:
    """size 111 V 01 imm12 Rn Rt (unsigned offset, entier uniquement)."""
    size, _v, op = bits(w, 31, 30), bits(w, 26, 26), bits(w, 22, 22)
    i.sf = 1 if size >= 2 else 0
    i.mnemonic = ("LDR" if op else "STR") + ("" if size >= 2 else _LDR_STR_SIZES[size])
    i.rn, i.rt = bits(w, 9, 5), bits(w, 4, 0)
    i.imm = bits(w, 21, 10) << (size)      # échelle naturelle : size=3 -> *8
    i.shift_amt = size
    return i


# --- paires STP/LDP/STNP/LDNP/LDPSW (layouts verrouillés vs capstone 5.0.7) --
# Cas : STNP imm réel est conservé (capstone affiche l'offset, V=1 exclu au
# dispatch). opc 01 = LDPSW uniquement avec L=1 et sans forme NP ; opc 11
# réservé. Writeback (post/pre) avec Rn=31 (SP) **légal** (contrairement aux
# formes où Rn ∈ {Rt,Rt2} hors SP, refusées par capstone = UNPREDICTABLE).
# Convention Ins : rt = Rt, rm = Rt2.
_PAIR_MODES = ("np", "post", "off", "pre")   # bits 24-23 -> forme d'accès

def _decode_pair(i: Ins, w: int) -> Ins:
    """opc(31-30) 101 V01 mode(24-23) L(22) imm7(21-15) Rt2 Rn Rt."""
    opc, L, mode = bits(w, 31, 30), bits(w, 22, 22), bits(w, 24, 23)
    if opc == 0b11:                            # famille non allouée
        i.unknown = True
        return i
    if opc == 0b01 and (L == 0 or mode == 0b00):   # LDPSW : L=1, pas de NP
        i.unknown = True
        return i
    i.sf = 1 if opc in (0b01, 0b10) else 0     # LDPSW : dest X (ext. signée)
    scale = 8 if opc == 0b10 else 4            # LDPSW/32b : *4 ; 64b : *8
    i.imm = sval(bits(w, 21, 15), 7) * scale
    i.rn, i.rm, i.rt = bits(w, 9, 5), bits(w, 14, 10), bits(w, 4, 0)
    form = _PAIR_MODES[mode]
    # Rn=31 (SP) est LEGAL en writeback ; rules UNPREDICTABLE capstone :
    #  - LDP : Rt == Rt2 duplique -> refuse ;
    #  - writeback : Rt/Rt2 == Rn refusé sauf Rn=31 (SP, base anti-alias conforme)
    if L == 1 and i.rt == i.rm:
        i.unknown = True
        return i
    if form in ("post", "pre") and i.rn != 31 and i.rn in (i.rt, i.rm):
        i.unknown = True
        return i
    if form == "np":                           # [base, #imm] sans writeback
        i.mnemonic = ("STNP", "LDNP")[L]
    elif opc == 0b01:
        i.mnemonic = "LDPSW"
    else:
        i.mnemonic = ("STP", "LDP")[L]         # offset / post / pre
    if form == "post":
        i.mode = "post"
    elif form == "pre":
        i.mode = "pre"
    return i


# --- TBZ/TBNZ --------------------------------------------------------------
def _decode_tbz(i: Ins, w: int) -> Ins:
    """x 011011 op b40(23-19) imm14(18-5) Rt — bit testé = (b5<<5)|b40."""
    i.sf = bits(w, 31, 31)                     # b5 haut : bit 31
    i.mnemonic = "TBNZ" if bits(w, 24, 24) else "TBZ"
    i.shift_amt = (i.sf << 5) | bits(w, 23, 19)
    i.imm = sval(bits(w, 18, 5), 14) * 4
    i.rt = bits(w, 4, 0)
    i.target = i.addr + i.imm
    return i


# --- STUR/LDUR (offset non mis à l'échelle) --------------------------------
def _decode_unscaled(i: Ins, w: int) -> Ins:
    """size(31-30) 111 0 {0b00000|00010|00100|00110} imm9(20-12) 00 Rn Rt.

    Grp bits 25-21 : 00000 store / 00010 load / 00100 signé dest X
    (size 11 = PRFUM -> inconnu) / 00110 signé dest W (size >= 2 -> inconnu).
    bits 11-10 = 01/11 (post/pre-index) et 10 (reg. étendu) : autres familles,
    non prises (dispatch les laisse tomber).
    """
    size, grp = bits(w, 31, 30), bits(w, 25, 21)
    i.sf = 1 if size == 3 else 0
    i.imm = sval(bits(w, 20, 12), 9)
    i.rn, i.rt = bits(w, 9, 5), bits(w, 4, 0)
    if grp == 0b00100:                         # charge signée, dest X
        if size == 3:                          # PRFUM : preload store
            i.unknown = True
            return i
        i.mnemonic = ("LDURSB", "LDURSH", "LDURSW")[size]
    elif grp == 0b00110:                       # charge signée, dest W
        i.sf = 0
        if size >= 2:                          # non alloué
            i.unknown = True
            return i
        i.mnemonic = ("LDURSB", "LDURSH")[size]
    else:                                      # 00000 store / 00010 load
        if size >= 2:                          # 2 = 32 bits (W), 3 = 64 bits (X)
            i.sf = 1 if size == 3 else 0
            i.mnemonic = "STUR" if bits(w, 22, 22) == 0 else "LDUR"
        else:
            i.sf = 0
            i.mnemonic = ("STUR", "LDUR")[bits(w, 22, 22)] \
                         + ("B" if size == 0 else "H")
    return i


# --- barrières DMB/DSB/ISB -------------------------------------------------
# Famille bits 7-5 : 100 DSB / 101 DMB / 110 ISB. 001 = MSR (bloc système,
# renommé DSB NXSy en 9.0.0+), 010 = CLREX, 111 = SYS : hors barrières.
_BARRIER_DOMAINS = {0xF: "SY", 0xE: "ST", 0xD: "LD", 0xB: "ISH",
                    0xA: "ISHST", 0x9: "ISHLD", 0x7: "NSH", 0x6: "NSHST",
                    0x5: "NSHLD", 0x3: "OSH", 0x2: "OSHST", 0x1: "OSHLD"}

def _decode_barrier(i: Ins, w: int) -> Ins:
    """D503 3 CRm op2 1F ; CRm hors table (4/8/C-DSB...) : rendu '#n', no-op."""
    i.imm = bits(w, 11, 8)                     # CRm : domaine
    i.option = bits(w, 7, 5)                   # famille : 4 DSB / 5 DMB / 6 ISB
    if i.option == 4 and i.imm in (0x0, 0x4, 0xC):   # DSB à domaines nommés
        i.mnemonic = {0x0: "SSBB", 0x4: "PSSBB", 0xC: "DFB"}[i.imm]
        return i
    i.mnemonic = ("DSB", "DMB", "ISB")[i.option - 4]
    return i


def nop(i: Ins) -> Ins:
    i.group = "NOP"
    i.mnemonic = "NOP"
    return i

# --- dispatch -------------------------------------------------------------
def decode(word: int, addr: int = 0) -> Ins:
    """Décode un mot ARM64 => Ins (flag unknown si famille non supportée)."""
    i = Ins(addr=addr, raw=word, group="?")
    if word == 0xD503201F:
        return nop(i)
    top24 = (word >> 24) & 0xFF
    grp = (word >> 24) & 0x1F
    if ((word >> 26) & 0x3F) in (0b000101, 0b100101):
        i.group, i.flags = "BRANCH", False
        return _decode_branch(i, word)
    if top24 in (0x34, 0x35, 0xB4, 0xB5):
        i.group, i.flags = "CBZ", False
        return _decode_cbz(i, word)
    if top24 == 0x54:
        i.group, i.flags = "BRANCH_COND", False
        return _decode_bcond(i, word)
    if (word & 0xFFFFFC1F) == 0xD65F0000:     # RET : fixes + Rn libre bits 9-5
        i.group, i.flags = "BRANCH_REG", False
        return _decode_ret(i, word)
    if grp == 0b01011:        # 28-24 = 01011 : ADD/SUB registre
        i.group = "ADD_SUB_REG"
        return _decode_addsub_reg(i, word)
    if grp == 0b01010:        # 01010 : logique registre
        i.group = "LOGICAL_REG"
        return _decode_logical_reg(i, word)
    if (word >> 23) & 0x3F == 0b100010:   # immédiat
        i.group = "ADD_SUB_IMM"
        return _decode_addsub_imm(i, word)
    if (word >> 23) & 0x3F == 0b100101:
        i.group = "MOV_WIDE"
        return _decode_movwide(i, word)
    if (word >> 23) & 0x3F == 0b100100:
        i.group = "LOGICAL_IMM"
        return _decode_logical_imm(i, word)
    if (word >> 24) & 0x1F == 0b10000:
        i.group, i.flags = "PCREL", False
        return _decode_adr(i, word)
    if ((word >> 27) & 7) == 0b111 and ((word >> 24) & 3) == 0b01 \
            and bits(word, 26, 26) == 0 and bits(word, 23, 23) == 0:
        i.group, i.flags = "LDR_STR_IMM", False
        return _decode_ldrstr_imm(i, word)
    if ((word >> 25) & 0x3F) == 0b011011:       # TBZ/TBNZ (bits 30-25)
        i.group, i.flags = "TBZ", False
        return _decode_tbz(i, word)
    if (word & 0xFFFFF01F) == 0xD503301F and bits(word, 7, 5) in (4, 5, 6):
        i.group, i.flags = "BARRIER", False
        return _decode_barrier(i, word)
    if (word & 0xFFE0001F) == 0xD4000001:      # SVC #imm16 (appel superviseur)
        i.group, i.flags = "SVC", False
        i.mnemonic = "SVC"
        i.imm = bits(word, 20, 5)
        return i
    if ((word >> 27) & 7) == 0b101 and bits(word, 26, 25) == 0:
        i.group, i.flags = "PAIR", False
        return _decode_pair(i, word)
    if ((word >> 27) & 7) == 0b111 and bits(word, 26, 26) == 0 \
            and bits(word, 11, 10) == 0 \
            and bits(word, 25, 21) in (0b00000, 0b00010, 0b00100, 0b00110):
        i.group, i.flags = "UNSCALED", False
        return _decode_unscaled(i, word)
    i.unknown = True
    i.mnemonic = "UNK"
    return i

def disassemble_one(word: int, addr: int = 0) -> str:
    """Rendu texte d'une instruction (diassambly lisible)."""
    i = decode(word, addr)
    if i.unknown:
        return f"UNK 0x{word:08x}"
    if i.group == "NOP":
        return "NOP"
    if i.mnemonic in ("B", "BL"):
        return f"{i.mnemonic} 0x{i.target:x}"
    if i.group == "BRANCH_COND":
        return f"{i.mnemonic} 0x{i.target:x}"
    if i.group == "CBZ":
        return f"{i.mnemonic} {reg_x(i.rt, i.sf)}, 0x{i.target:x}"
    if i.group == "BRANCH_REG":
        return "RET" if i.rn == 30 else f"RET {reg_x(i.rn, 1, is_sp=True)}"
    if i.group == "PCREL":
        return f"{i.mnemonic} {reg_x(i.rd, 1)}, #0x{i.imm:x}"
    if i.group == "MOV_WIDE":
        return f"{i.mnemonic} {reg_x(i.rd, i.sf)}, #0x{i.imm:x}, LSL #{i.shift_amt}"
    if i.group == "ADD_SUB_IMM":
        if i.flags and i.rd == 31:  # CMP/CMN : Rd implicite = XZR
            return f"{i.mnemonic} {reg_x(i.rn, i.sf, True)}, #0x{i.imm:x}"
        return f"{i.mnemonic} {reg_x(i.rd, i.sf, is_sp=True)}, {reg_x(i.rn, i.sf, True)}, #0x{i.imm:x}"
    if i.group in ("ADD_SUB_REG", "LOGICAL_REG"):
        if i.mnemonic in ("CMP", "CMN", "TST"):     # Rd implicite
            s = f"{i.mnemonic} {reg_x(i.rn, i.sf)}"
        else:
            s = f"{i.mnemonic} {reg_x(i.rd, i.sf)}"
        if i.option is not None:
            ext_w = "X" if i.option in (3, 7) else "W"
            s += f", {ext_w}{i.rm}, {ARM_OPTION_NAMES[i.option]}"
            if i.shift_amt:
                s += f" #{i.shift_amt}"
        else:
            s += f", {reg_x(i.rn, i.sf, True)}, {reg_x(i.rm, i.sf)}"
            if i.shift_amt:
                s += f", {i.shift_type} #{i.shift_amt}"
        return s
    if i.group == "LOGICAL_IMM":
        return f"{i.mnemonic} {reg_x(i.rd, i.sf)}, {reg_x(i.rn, i.sf, True)}, #0x{i.imm:x}"
    if i.group == "LDR_STR_IMM":
        return f"{i.mnemonic} {reg_x(i.rt, i.sf)}, [{reg_x(i.rn, i.sf, True)} + 0x{i.imm:x}]"
    if i.group == "TBZ":
        return f"{i.mnemonic} {reg_x(i.rt, i.sf)}, #0x{i.shift_amt:x}, 0x{i.target:x}"
    if i.group == "PAIR":
        base = reg_x(i.rn, 1, is_sp=True)
        regs = f"{reg_x(i.rt, i.sf)}, {reg_x(i.rm, i.sf)}"
        if i.mode == "post":
            return f"{i.mnemonic} {regs}, [{base}], #{hx_signed(i.imm)}"
        if i.mode == "pre":
            return f"{i.mnemonic} {regs}, [{base}, #{hx_signed(i.imm)}]!"
        return f"{i.mnemonic} {regs}, [{base}, #{hx_signed(i.imm)}]"
    if i.group == "UNSCALED":
        return (f"{i.mnemonic} {reg_x(i.rt, i.sf)}, "
                f"[{reg_x(i.rn, 1, is_sp=True)}, #{hx_signed(i.imm)}]")
    if i.group == "BARRIER":
        if i.mnemonic in ("SSBB", "PSSBB", "DFB"):
            return i.mnemonic
        dom = _BARRIER_DOMAINS.get(i.imm)
        if i.mnemonic == "ISB":
            return "ISB" if i.imm == 0xF else f"ISB #0x{i.imm:x}"
        return f"{i.mnemonic} {dom}" if dom is not None else f"{i.mnemonic} #0x{i.imm:x}"
    if i.group == "SVC":
        return f"SVC #0x{i.imm:x}"
    return i.mnemonic
