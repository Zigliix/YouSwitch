# -*- coding: utf-8 -*-
"""Tests unitaires du pipeline SwitchRecomp (sans dépendance externe).

Exécution :  python tests/test_pipeline.py   (depuis le dossier decompiler/)
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from decoder import arm64 as a64       # noqa: E402
from decoder import x86_64 as x64      # noqa: E402
from translate.emitter import to_x86_64, CppEmitter  # noqa: E402
from loader import nsw_formats as nsw  # noqa: E402

# -- mini-assembleur ARM64 (encodages dérivés des layouts doctorés dans
#    knowledge/arm64.py de mémoire ; invalides <=> round-trip decoder) --
def i_add_sf(rd, rn, rm, imm6=0, shift=0, op=0, S=0):      # ADD/SUB shifted reg
    return 0x1 << (26 + 0) | 0x0
def enc_addsub_reg(sf, op, S, shift, Rm, imm6, Rn, Rd, ext=0):
    return ((sf << 31) | (op << 30) | (S << 29) | (0b01011 << 24) |
            (shift << 22) | (ext << 21) | (Rm << 16) | (imm6 << 10) |
            (Rn << 5) | Rd)

def enc_addsub_imm(sf, op, S, sh, imm12, Rn, Rd):
    return ((sf << 31) | (op << 30) | (S << 29) | (0b100010 << 23) |
            (sh << 22) | (imm12 << 10) | (Rn << 5) | Rd)

def enc_movwide(sf, opc, hw, imm16, Rd):
    return (sf << 31) | (opc << 29) | (0b100101 << 23) | (hw << 21) | \
           (imm16 << 5) | Rd

def enc_b(offs4):
    return 0x14000000 | ((offs4 // 4) & 0x3FFFFFF)

def enc_bcond(cond, offs4):
    return (0x54 << 24) | (((offs4 // 4) & 0x7FFFF) << 5) | cond

def enc_cbz(sf, opn, offs4, Rt):
    return ((sf << 31) | (0b110100 << 24) | (opn << 24) |
            ((offs4 // 4) & 0x7FFFF) << 5 | Rt)

def enc_ret(rn=30):
    return 0xD65F0000 | (rn << 5)

def enc_ldrstr(sf, opn, size, imm12, Rn, Rt):
    if sf == 1:
        size = 3
    return (size << 30) | (0b111 << 27) | (0b01 << 24) | (opn << 22) | \
           (imm12 << 10) | (Rn << 5) | Rt

def enc_pair(opc, L, mode, imm7, Rt2, Rn, Rt):
    return ((opc << 30) | (0b101 << 27) | (mode << 23) | (L << 22) |
            ((imm7 & 0x7F) << 15) | (Rt2 << 10) | (Rn << 5) | Rt)

def enc_tbz(b5, op, b40, imm14, Rt):
    return ((b5 << 31) | (0b011011 << 25) | (op << 24) |
            ((b40 & 0x1F) << 19) | ((imm14 & 0x3FFF) << 5) | Rt)

def enc_unscaled(size, grp, imm9, Rn, Rt):
    return ((size << 30) | (0b111 << 27) | (grp << 21) |
            ((imm9 & 0x1FF) << 12) | (Rn << 5) | Rt)


CHECKS = []


def check(name, cond):
    CHECKS.append((name, bool(cond)))
    flag = "OK " if cond else "FAIL"
    print(f"[{flag}] {name}")


def test_decode():
    # 0x8B020020 = ADD X0, X1, X2 (forme shifted LSL#0, encodage canonique)
    i = a64.decode(0x8B020020)
    check("ADD X0,X1,X2 canonique", (i.mnemonic, i.rn, i.rm, i.rd) ==
          ("ADD", 1, 2, 0))
    check("ADD non-flags", i.flags is False)
    # SUBS avec Rd=31 = CMP : 0xEB03005F = CMP X2, X3
    i = a64.decode(0xEB03005F)
    check("CMP = SUBS XZR", i.mnemonic == "CMP" and i.flags and i.rn == 2 and i.rm == 3)
    # MOVZ : 0xD2800602 = MOVZ X2, #48
    i = a64.decode(0xD2800602)
    check("MOVZ X2,#48", i.mnemonic == "MOVZ" and i.imm == 48 and i.rd == 2)
    # RET : 0xD65F03C0
    check("RET canonique", a64.decode(0xD65F03C0).mnemonic == "RET")
    # ADD immédiat : encodage ADD X0, X0, #64 avec Rn=Rd=0
    w = enc_addsub_imm(1, 0, 0, 0, 64, 0, 0)
    i = a64.decode(w)
    check(f"ADD imm 64 ({w:08x})", i.mnemonic == "ADD" and i.imm == 64)
    # CMP immédiat : SUBS XZR, X0, #128
    w = enc_addsub_imm(1, 1, 1, 0, 128, 0, 31)
    i = a64.decode(w)
    check("CMP immédiat", i.mnemonic == "CMP" and i.imm == 128)
    # shifted register : ADD X0, X1, X2, LSL #3 (shift=00, bit21=0)
    w = enc_addsub_reg(1, 0, 0, 0b00, 2, 3, 1, 0)
    i = a64.decode(w)
    check("ADD shifted LSL#3", i.mnemonic == "ADD" and i.shift_type == "LSL"
          and i.shift_amt == 3)
    # extended : ADD X0, X1, W2, UXTW (option=010, imm3=0, bit21=1) — bits 15-10 != 0
    w = enc_addsub_reg(1, 0, 0, 0b00, 2, (0b010 << 3) | 0, 1, 0, ext=1)
    i = a64.decode(w)
    check("ADD extended UXTW", i.mnemonic == "ADD" and i.option == 0b010)
    # B/BL/B.cond/CBZ
    check("B imm26", a64.decode(enc_b(16)).target == 16
          and a64.decode(enc_b(16)).mnemonic == "B")
    check("B.cond LT", a64.decode(enc_bcond(0b1011, 8)).mnemonic == "B.LT")
    check("CBZ 64", a64.decode(enc_cbz(1, 0, 8, 0)).mnemonic == "CBZ"
          and a64.decode(enc_cbz(1, 0, 8, 0)).target == 8)
    # LDR/STR : LDR X4, [X1] (offset 0) ; STR W8 [X1, #16] (imm12=4, échelle *4)
    check("LDR X4", a64.decode(enc_ldrstr(1, 1, 3, 0, 1, 4)).mnemonic == "LDR")
    check("STR W8 off16", a64.decode(enc_ldrstr(0, 0, 2, 4, 1, 8)).mnemonic == "STR"
          and a64.decode(enc_ldrstr(0, 0, 2, 4, 1, 8)).imm == 16)
    # NOP
    check("NOP", a64.decode(0xD503201F).group == "NOP")
    # immédiat logique : AND X0, X1, #0xF -> motif ones(4) : (N=1, S=3, R=0)
    li = a64.decode_bitmask(1, 1, 3, 0)
    check("bitmask #0xF 64", li == 0xF)
    li = a64.decode_bitmask(1, 1, 31, 0)   # ones(32) -> 0xFFFFFFFF (64 bits)
    check("bitmask #0xFFFFFFFF", li == 0xFFFFFFFF)
    li = a64.decode_bitmask(0, 0, 3, 0)    # 32 bits : motif 4 dans 32 bits
    check("bitmask #0xF 32", li == 0xF)


def test_x86_64():
    # MOVZ X0, #5  ->  mov rax, 5 (48 C7 C0 05 00 00 00)
    code, _ = to_x86_64([a64.decode(enc_movwide(1, 2, 0, 5, 0))])
    check("MOVZ -> mov rax,[5]", code == bytes([0x48, 0xC7, 0xC0, 5, 0, 0, 0]))
    # ADD X0, X1, X2 -> mov rax, rcx ; add rax, rdx
    code, _ = to_x86_64([a64.decode(0x8B020020)])
    check("ADD reg -> mov/add", code == bytes([0x48, 0x89, 0xC8, 0x48, 0x01, 0xD0]))
    # ADD X0, X0, #10 -> add rax, 10 (48 81 C0 ..)
    w = enc_addsub_imm(1, 0, 0, 0, 10, 0, 0)
    code, _ = to_x86_64([a64.decode(w)])
    check("ADD imm -> add rax,10", code == bytes([0x48, 0x81, 0xC0, 10, 0, 0, 0]))
    # SUB X3, X3, X1 : RBX=3, RCX=1 : sub rbx, rcx = 48 29 CB
    code, _ = to_x86_64([a64.decode(enc_addsub_reg(1, 1, 0, 0, 1, 0, 3, 3))])
    check("SUB reg -> sub rbx,rcx", code == bytes([0x48, 0x29, 0xCB]))
    # RET -> C3
    code, _ = to_x86_64([a64.decode(enc_ret())])
    check("RET -> C3", code == bytes([0xC3]))


def test_loader():
    # NSO minimal : entête 0x60 + taille text 0x10, non compressé
    hdr = bytearray(0x60)
    hdr[0:4] = b"NSO0"
    hdr[0x10:0x14] = (0x60).to_bytes(4, "little")   # text file offset
    hdr[0x14:0x18] = (0).to_bytes(4, "little")      # mem offset
    hdr[0x18:0x1C] = (8).to_bytes(4, "little")      # size 8 -> 2 instr
    hdr[0x1C:0x20] = (0).to_bytes(4, "little")
    body = (0x52800602).to_bytes(4, "little") + (0xD65F03C0).to_bytes(4, "little")
    img = nsw.parse_image(bytes(hdr) + body)
    check("NSO détecté", img.kind == "NSO")
    check("NSO segment .text", img.text() and img.text().size == 8)
    ins = [a64.decode(int.from_bytes(body[4 * k:4 * k + 4], "little"))
           for k in range(2)]
    check("NSO décode MOVZ+RET", ins[0].mnemonic == "MOVZ" and ins[1].mnemonic == "RET")


def test_lz4():
    # littéraux seuls : token 0x80 + 8 octets
    blk = bytes([0x80]) + b"ABCDEFGH"
    check("LZ4 littéraux", nsw.lz4_decompress_block(blk, 8) == b"ABCDEFGH")
    # match chevauchant (RLE) : 'A' + offset 1 + match 9 -> 10 x 'A'
    blk = bytes([0x15]) + b"A" + (1).to_bytes(2, "little")
    check("LZ4 overlap", nsw.lz4_decompress_block(blk, 10) == b"A" * 10)
    # offset 0 interdit
    try:
        nsw.lz4_decompress_block(bytes([0x10]) + b"A" + b"\x00\x00", 5)
        ok = False
    except ValueError:
        ok = True
    check("LZ4 offset invalide rejeté", ok)
    # NSO compressé LZ4 + hash valide
    import hashlib
    prog = (0x52800602).to_bytes(4, "little") + (0xD65F03C0).to_bytes(4, "little")
    blk = bytes([0x80]) + prog                       # 9 octets
    hdr = bytearray(0x100)
    hdr[0:4] = b"NSO0"
    hdr[0x0C:0x10] = (1 | 8).to_bytes(4, "little")   # .text LZ4 + hash
    hdr[0x10:0x14] = (0x100).to_bytes(4, "little")   # text file offset
    hdr[0x18:0x1C] = (8).to_bytes(4, "little")       # taille décompressée
    hdr[0x60:0x64] = (len(blk)).to_bytes(4, "little")  # TextFileSize
    hdr[0xA0:0xC0] = hashlib.sha256(prog).digest()
    data = bytes(hdr) + blk
    img = nsw.parse_image(data)
    seg = img.text()
    raw = nsw.segment_bytes(img, seg, data)
    check("NSO LZ4 décompressé", raw == prog and seg.payload == prog)
    check("NSO LZ4 hash vérifié", not any("SHA-256 invalide" in n for n in img.notes))
    ins = [a64.decode(int.from_bytes(raw[4 * k:4 * k + 4], "little"))
           for k in range(2)]
    check("NSO LZ4 décode MOVZ+RET", ins[0].mnemonic == "MOVZ" and ins[1].mnemonic == "RET")


def test_new_families():
    # --- PAIR : STP X2,X3,[X1,#16] (offset) ---
    i = a64.decode(enc_pair(0b10, 0, 0b10, 2, 3, 1, 2))
    check("STP X2,X3 off16", (i.mnemonic, i.mode, i.imm, i.rn, i.rt, i.rm) ==
          ("STP", "", 16, 1, 2, 3))
    cpp = "\n".join(CppEmitter().emit([i], func_name="t"))
    check("C++ STP", "mem_store64(s, (s.X[1] + (uint64_t)(int64_t)16), s.X[2]);" in cpp
          and "s.X[3]" in cpp)
    code, notes = to_x86_64([i])
    want = bytes([0x48, 0x89, 0x91, 0x10, 0, 0, 0,
                  0x48, 0x89, 0x99, 0x18, 0, 0, 0])
    check("x86 STP", notes == [] and code == want)
    # --- PAIR : STP X29,X30,[SP,#-16]! (pre-index, ABI) ---
    i = a64.decode(enc_pair(0b10, 0, 0b11, -2, 30, 31, 29))
    cpp = "\n".join(CppEmitter().emit([i], func_name="t"))
    check("C++ STP preindex SP", i.mode == "pre" and i.imm == -16
          and "mem_store64(s, (s.SP + (uint64_t)(int64_t)-16), s.X[29]);" in cpp
          and "s.SP = (s.SP + (uint64_t)(int64_t)-16);" in cpp)
    # --- TBZ X1, #3, +8 ---
    i = a64.decode(enc_tbz(0, 0, 3, 2, 1), addr=0x1000)
    check("TBZ bit3 cible", i.mnemonic == "TBZ" and i.shift_amt == 3
          and i.target == 0x1008)
    insns = [i, a64.decode(enc_ret(), 0x1008)]
    cpp = "\n".join(CppEmitter().emit(insns, func_name="t"))
    check("C++ TBZ", "if (((s.X[1] >> 3) & 1) == 0) goto L_00001008;" in cpp
          and "L_00001008: ;" in cpp)
    code, notes = to_x86_64(insns)
    check("x86 TBZ", notes == [] and code == bytes(
        [0x48, 0x0F, 0xBA, 0xE1, 0x03, 0x0F, 0x83, 0, 0, 0, 0, 0xC3]))
    # --- LDUR X2,[X3,#-8] (unscaled) ---
    i = a64.decode(enc_unscaled(3, 0b00010, -8, 3, 2))
    check("LDUR X2,[X3,#-8]", (i.mnemonic, i.imm, i.rn, i.rt) ==
          ("LDUR", -8, 3, 2))
    cpp = "\n".join(CppEmitter().emit([i], func_name="t"))
    check("C++ LDUR", "s.X[2] = mem_load64(s, (s.X[3] + (uint64_t)(int64_t)-8));" in cpp)
    code, notes = to_x86_64([i])
    check("x86 LDUR", notes == [] and
          code == bytes([0x48, 0x8B, 0x93, 0xF8, 0xFF, 0xFF, 0xFF]))
    # --- DMB SY / ISB ---
    i = a64.decode(0xD5033FBF)
    check("DMB SY", i.group == "BARRIER" and i.mnemonic == "DMB" and i.imm == 0xF)
    cpp = "\n".join(CppEmitter().emit([i], func_name="t"))
    check("C++ DMB", "std::atomic_thread_fence(std::memory_order_seq_cst);" in cpp)
    code, notes = to_x86_64([i])
    check("x86 DMB", notes == [] and code == bytes([0x0F, 0xAE, 0xF0]))
    i = a64.decode(0xD5033FDF)
    cpp = "\n".join(CppEmitter().emit([i], func_name="t"))
    check("C++ ISB no-op", i.mnemonic == "ISB" and "atomic" not in cpp)
    # --- BICS X0,X1,X2 ---
    i = a64.decode(0xEA220020)
    cpp = "\n".join(CppEmitter().emit([i], func_name="t"))
    check("C++ BICS", i.mnemonic == "BICS"
          and "uint64_t t = (s.X[1] & ~s.X[2]);" in cpp
          and "set_flags_logic(s, t, 64);" in cpp)
    # --- BC.cond (bit4=1) ---
    i = a64.decode(0x54000011)
    check("BC.NE bit4", i.mnemonic == "BC.NE" and i.cond == "NE")
    # --- SVC #0x1F / #0x21 (HLE Horizon) ---
    for imm in (0x1F, 0x21):
        word = 0xD4000001 | (imm << 5)
        i = a64.decode(word, 0x100)
        check(f"SVC #{imm:#x}", i.group == "SVC" and i.imm == imm
              and a64.disassemble_one(word) == f"SVC #0x{imm:x}")
        cpp = "\n".join(CppEmitter().emit([i], func_name="t"))
        check(f"C++ SVC #{imm:#x}", f"hle_svc(s, 0x{imm:x});" in cpp)
        code, notes = to_x86_64([i])
        check(f"x86 SVC #{imm:#x} -> note", code == b"" and len(notes) == 1)


def test_block():
    # bloc : MOVZ X0,#48 ; MOVZ X1,#24 ; SUB X0,X0,X1 ; RET
    prog = [enc_movwide(1, 2, 0, 48, 0), enc_movwide(1, 2, 0, 24, 1),
            enc_addsub_reg(1, 1, 0, 0, 1, 0, 0, 0), enc_ret()]
    cpp = CppEmitter().emit([a64.decode(w) for w in prog], func_name="t")
    src = "\n".join(cpp)
    ok = "s.X[0] = (uint64_t)48ULL << 0;" in src and \
         "s.X[0] = s.X[0] - s.X[1];" in src and "return;" in src
    check("C++ bloc MOVZ/SUB/RET", ok)
    code, notes = to_x86_64([a64.decode(w) for w in prog])
    ok = notes == [] and code.startswith(bytes([0x48]))
    check("x86-64 bloc complet", ok)


if __name__ == "__main__":
    test_decode()
    test_x86_64()
    test_loader()
    test_lz4()
    test_new_families()
    test_block()
    n_fail = sum(1 for _, ok in CHECKS if not ok)
    print(f"\n== {len(CHECKS)} tests, {n_fail} échec(s) ==")
    sys.exit(1 if n_fail else 0)
