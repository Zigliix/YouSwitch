# -*- coding: utf-8 -*-
"""Génère un NSO synthétique compressé LZ4 pour le test de bout en bout.

Écrit  <racine>/input/e2e_switchrecomp.nso  (segment .text LZ4 + SHA-256).

Programme (14 instructions) : ancien scénario mémoire (PAIR/LDUR/DMB/TBZ)
puis entrée IPC Horizon :
    STP  X2,X3,[X1,#16]
    MOVZ X0,#48
    ADD  X0,X0,X1
    LDUR X2,[X3,#-8]
    DMB  SY
    TBZ  X0,#3,+8
    LDP  X2,X3,[X1,#16]
    MOVZ X0,#0x2000        ; pointeur de sortie du handle (X0)
    MOVZ X1,#0x1000        ; pointeur du nom "sm:" (X1)
    SVC  #0x1F             ; ConnectToNamedPort(out=X0, name=X1)
    MOVZ X0,#0x2000        ; recharge l'adresse (X0 = Result après SVC)
    LDR  W0,[X0]           ; handle de session sm:
    SVC  #0x21             ; SendSyncRequest(handle) -> sm: IPC
    RET

Exécution (depuis decompiler/) :  python tests/make_synthetic_nso.py
"""
from __future__ import annotations
import hashlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def enc_pair(opc, L, mode, imm7, Rt2, Rn, Rt):
    return ((opc << 30) | (0b101 << 27) | (mode << 23) | (L << 22) |
            ((imm7 & 0x7F) << 15) | (Rt2 << 10) | (Rn << 5) | Rt)


def enc_movwide(sf, opc, hw, imm16, Rd):
    return ((sf << 31) | (opc << 29) | (0b100101 << 23) | (hw << 21) |
            (imm16 << 5) | Rd)


def enc_addsub_reg(sf, op, S, shift, Rm, imm6, Rn, Rd):
    return ((sf << 31) | (op << 30) | (S << 29) | (0b01011 << 24) |
            (shift << 22) | (Rm << 16) | (imm6 << 10) | (Rn << 5) | Rd)


def enc_unscaled(size, grp, imm9, Rn, Rt):
    return ((size << 30) | (0b111 << 27) | (grp << 21) |
            ((imm9 & 0x1FF) << 12) | (Rn << 5) | Rt)


def enc_tbz(b5, op, b40, imm14, Rt):
    return ((b5 << 31) | (0b011011 << 25) | (op << 24) |
            ((b40 & 0x1F) << 19) | ((imm14 & 0x3FFF) << 5) | Rt)


PROGRAM = [
    enc_pair(0b10, 0, 0b10, 2, 3, 1, 2),      # STP X2,X3,[X1,#16]
    enc_movwide(1, 0b10, 0, 48, 0),           # MOVZ X0,#48
    enc_addsub_reg(1, 0, 0, 0, 1, 0, 0, 0),   # ADD X0,X0,X1
    enc_unscaled(3, 0b00010, -8, 3, 2),       # LDUR X2,[X3,#-8]
    0xD5033FBF,                               # DMB SY
    enc_tbz(0, 0, 3, 2, 0),                   # TBZ X0,#3,+8 (0x14 -> 0x1C)
    enc_pair(0b10, 1, 0b10, 2, 3, 1, 2),      # LDP X2,X3,[X1,#16]
    enc_movwide(1, 0b10, 0, 0x2000, 0),       # MOVZ X0,#0x2000 (out handle)
    enc_movwide(1, 0b10, 0, 0x1000, 1),       # MOVZ X1,#0x1000 ("sm:")
    0xD40003E1,                               # SVC #0x1F ConnectToNamedPort
    enc_movwide(1, 0b10, 0, 0x2000, 0),       # MOVZ X0,#0x2000 (recharge)
    0xB9400000,                               # LDR W0,[X0]
    0xD4000421,                               # SVC #0x21 SendSyncRequest
    0xD65F03C0,                               # RET
]


def lz4_literals(blob: bytes) -> bytes:
    """Bloc LZ4 valide à littéraux seuls (aucun match)."""
    n = len(blob)
    if n < 15:
        return bytes([n << 4]) + blob
    out = bytearray([0xF0])
    rem = n - 15
    while rem >= 255:
        out.append(255)
        rem -= 255
    out.append(rem)
    return bytes(out) + blob


def main() -> int:
    text = b"".join(w.to_bytes(4, "little") for w in PROGRAM)
    blk = lz4_literals(text)
    hdr = bytearray(0x100)
    hdr[0:4] = b"NSO0"
    hdr[0x0C:0x10] = (1 | 8).to_bytes(4, "little")   # .text LZ4 + hash
    hdr[0x10:0x14] = (0x100).to_bytes(4, "little")   # TextFileOffset
    hdr[0x14:0x18] = (0).to_bytes(4, "little")       # TextMemoryOffset
    hdr[0x18:0x1C] = (len(text)).to_bytes(4, "little")
    hdr[0x1C:0x20] = (0x100).to_bytes(4, "little")   # ModuleNameOffset
    hdr[0x40:0x60] = hashlib.sha256(b"SwitchRecomp-e2e").digest()[:0x20]
    hdr[0x60:0x64] = (len(blk)).to_bytes(4, "little")  # TextFileSize
    hdr[0xA0:0xC0] = hashlib.sha256(text).digest()     # TextHash
    path = os.path.join(ROOT, "input", "e2e_switchrecomp.nso")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(bytes(hdr) + blk)
    print(f"écrit : {path} ({0x100 + len(blk)} octets, .text {len(text)} o)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
