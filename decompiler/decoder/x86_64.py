# -*- coding: utf-8 -*-
"""
Encodeur x86-64 minimal (émission de code machine natif).
Sous-ensemble initial : ALU reg-reg / reg-imm (64 et 32 bits), MOV imm,
saute/mouvement basique. Pas d'encodage mémoire complexe (phase suivante).
"""
from __future__ import annotations

# Registres GP dans l'ordre d'encodage ModRM (0..15)
REG64 = ("RAX", "RCX", "RDX", "RBX", "RSP", "RBP", "RSI", "RDI",
         "R8", "R9", "R10", "R11", "R12", "R13", "R14", "R15")
REG32 = tuple(r + ("D" if r not in ("AX", "CX", "DX", "BX", "SP", "BP", "SI", "DI")
                   else "") for r in ("EAX", "ECX", "EDX", "EBX", "ESP", "EBP", "ESI", "EDI")) \
        + tuple(f"R{i}D" for i in range(8, 16))

# Codes d'opération ALU r/m, reg  (ADD r/m, r ; ...)
OP_RM_REG = {"ADD": 0x01, "OR": 0x09, "AND": 0x21, "SUB": 0x29, "XOR": 0x31, "MOV": 0x89}

# Groupe 81 (imm32 signé) : extensions ModRM /n
GRP1_EXT = {"ADD": 0, "OR": 1, "ADC": 2, "SBB": 3, "AND": 4, "SUB": 5, "XOR": 6, "CMP": 7}

SHIFT_EXT = {"SHL": 4, "SHR": 5, "SAR": 7}


def _rex(w: int, r: int, b: int) -> list[int]:
    """Préfixe REX : W=1 (64 bits) ; R/B = bits 3 des registres reg/rm."""
    return [0x40 | (w << 3) | ((r >> 3) << 2) | (b >> 3)]


def modrm(mod: int, reg: int, rm: int) -> int:
    """ModRM : les champs reg/rm sont limités à 3 bits (REX.R/REX.B portent le 4e)."""
    return (mod << 6) | ((reg & 7) << 3) | (rm & 7)


def alu_rr(out: list[int], op: str, dst: int, src: int, wide: bool) -> None:
    """op rdst, rsrc  — add/sub/and/or/xor/mov entre registres."""
    if wide:
        out += _rex(1, src, dst)
    else:
        if src >= 8 or dst >= 8:
            out += _rex(0, src, dst)
    out.append(OP_RM_REG[op])
    out.append(modrm(0b11, src, dst))


def alu_imm32(out: list[int], op: str, dst: int, imm32: int, wide: bool) -> None:
    """op r/m, imm32 signé (C7..81) — l'immédiat 32 bits est étendu par le signe en 64 bits."""
    if wide:
        out += _rex(1, 0, dst)
    else:
        if dst >= 8:
            out += _rex(0, 0, dst)
    out.append(0x81)
    out.append(modrm(0b11, GRP1_EXT[op], dst))
    out += list((imm32 & 0xFFFFFFFF).to_bytes(4, "little"))


def mov_imm32_sext64(out: list[int], dst: int, imm32: int) -> None:
    """MOV r64, imm32 (extension signée) : REX.W C7 /0."""
    out += _rex(1, 0, dst)
    out.append(0xC7)
    out.append(modrm(0b11, 0, dst))
    out += list((imm32 & 0xFFFFFFFF).to_bytes(4, "little"))


def mov_imm64(out: list[int], dst: int, imm64: int) -> None:
    """MOV r64, imm64 : REX.W B8+rd iq (10 octets)."""
    out += _rex(1, 0, dst)
    out.append(0xB8 + (dst & 7))
    out += list((imm64 & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "little"))


def shift_imm(out: list[int], op: str, dst: int, amount: int, wide: bool) -> None:
    """SHL/SHR/SAR r/m, imm8 (C1 /n — D1/D3 pas nécessaire ici)."""
    if wide:
        out += _rex(1, 0, dst)
    else:
        if dst >= 8:
            out += _rex(0, 0, dst)
    out.append(0xC1)
    out.append(modrm(0b11, SHIFT_EXT[op], dst))
    out.append(amount & 0xFF)


# --- accès mémoire [base + disp32] (SIB obligatoire si base = RSP/R12) ------
def _modrm_mem(reg: int, base: int, disp: int) -> list[int]:
    if (base & 7) == 4:
        modrm_byte = (0b10 << 6) | ((reg & 7) << 3) | 0b100
        sib = (0b100 << 3) | 0b100          # index = aucun, base = RSP
        return [modrm_byte, sib] + list((disp & 0xFFFFFFFF).to_bytes(4, "little"))
    return [(0b10 << 6) | ((reg & 7) << 3) | (base & 7)] + \
           list((disp & 0xFFFFFFFF).to_bytes(4, "little"))


def mov_load(out: list[int], dst: int, base: int, disp: int, bits: int) -> None:
    """MOV r(dst), [base+disp] ; bits ∈ {8,16,32,64}."""
    if bits == 16:
        out.append(0x66)
    need_rex = (bits == 64 or dst >= 8 or base >= 8
                or (bits == 8 and dst >= 4))     # SPL/BPL/SIL/DIL exigent REX
    if need_rex:
        out += _rex(1 if bits == 64 else 0, dst, base)
    out.append(0x8A if bits == 8 else 0x8B)
    out += _modrm_mem(dst, base, disp)


def mov_store(out: list[int], base: int, disp: int, src: int, bits: int) -> None:
    """MOV [base+disp], r(src) ; bits ∈ {8,16,32,64}."""
    if bits == 16:
        out.append(0x66)
    need_rex = (bits == 64 or src >= 8 or base >= 8
                or (bits == 8 and src >= 4))
    if need_rex:
        out += _rex(1 if bits == 64 else 0, src, base)
    out.append(0x88 if bits == 8 else 0x89)
    out += _modrm_mem(src, base, disp)


def movsx_load(out: list[int], dst: int, base: int, disp: int,
               src_bits: int, dst_wide: bool = True) -> None:
    """MOVSX/MOVSXD r(dst), [base+disp] (8/16 -> 0F BE/BF ; 32 -> 63)."""
    need_rex = dst_wide or dst >= 8 or base >= 8
    if need_rex:
        out += _rex(1 if dst_wide else 0, dst, base)
    if src_bits == 8:
        out += [0x0F, 0xBE]
    elif src_bits == 16:
        out += [0x0F, 0xBF]
    else:
        out.append(0x63)
    out += _modrm_mem(dst, base, disp)


# --- contrôle de flux (rel32 patché en second passage) ---------------------
CC_CODES = {"EQ": 4, "NE": 5, "HS": 2, "LO": 3, "MI": 8, "PL": 9,
            "VS": 0, "VC": 1, "HI": 7, "LS": 6, "GE": 13, "LT": 12,
            "GT": 15, "LE": 14}


def test_rr(out: list[int], reg: int, bits: int = 64) -> None:
    """TEST r, r (met ZF ; pas de modification)."""
    if bits == 64 or reg >= 8:
        out += _rex(1 if bits == 64 else 0, reg, reg)
    out.append(0x85)
    out.append(modrm(0b11, reg, reg))


def bt_imm(out: list[int], reg: int, bit: int) -> None:
    """BT r64, imm8 (met CF = bit testé)."""
    out += _rex(1, 0, reg)
    out += [0x0F, 0xBA]
    out.append(modrm(0b11, 4, reg))
    out.append(bit & 0x3F)


def jmp32(out: list[int]) -> int:
    """JMP rel32 ; retourne la position du déplacement à patcher."""
    out.append(0xE9)
    pos = len(out)
    out += b"\x00\x00\x00\x00"
    return pos


def jcc32(out: list[int], cc: str) -> int:
    """Jcc rel32 ; retourne la position du déplacement à patcher."""
    out += [0x0F, 0x80 + CC_CODES[cc]]
    pos = len(out)
    out += b"\x00\x00\x00\x00"
    return pos


def patch_rel32(code, pos: int, target: int) -> None:
    rel = target - (pos + 4)
    code[pos:pos + 4] = list((rel & 0xFFFFFFFF).to_bytes(4, "little"))


def mfence(out: list[int]) -> None:
    out += [0x0F, 0xAE, 0xF0]


def ret(out: list[int]) -> None:
    out.append(0xC3)
