# -*- coding: utf-8 -*-
"""
Loader des formats d'image Switch : NSO, NRO, NSP (détection + segments).

NSO : segments bruts ou compressés LZ4 (bloc lz4.org standard, zstd/bit7 noté
non supporté). NRO : segments directs. NSP : détection PFS0 + inventaire
(NCA en profondeur = phase suivante).
"""
from __future__ import annotations
import hashlib
from dataclasses import dataclass, field

MAG_NSO = b"NSO0"
MAG_NRO = b"NRO0"
MAG_PFS = b"PFS0"


@dataclass
class Segment:
    offset_file: int    # dans le fichier
    offset_mem: int     # dans l'espace mémoire du jeu
    size: int
    name: str
    payload: bytes | None = None   # contenu décompressé (None = brut dans le fichier)


@dataclass
class Image:
    kind: str = "?"          # NSO / NRO / NSP
    size: int = 0
    segments: list[Segment] = field(default_factory=list)
    build_id: bytes = b""
    notes: list[str] = field(default_factory=list)

    def text(self) -> Segment | None:
        return next((s for s in self.segments if s.name == ".text"), None)


def _u32(b: bytes, o: int) -> int:
    return int.from_bytes(b[o:o + 4], "little")


def lz4_decompress_block(src: bytes, dst_size: int) -> bytes:
    """Décompresse un bloc LZ4 brut (format lz4.org) vers EXACTEMENT dst_size.

    Décodage naïf octet par octet (fenêtre 64 Ko), sans dépendance externe.
    Lève ValueError si le flux est tronqué, l'offset invalide ou la taille
    produite différente de dst_size.
    """
    if dst_size < 0:
        raise ValueError("LZ4 : taille de sortie négative")
    dst = bytearray()
    p, n = 0, len(src)
    while len(dst) < dst_size:
        if p >= n:
            raise ValueError("LZ4 : flux tronqué (token)")
        token = src[p]
        p += 1
        # --- littéraux
        lit = token >> 4
        if lit == 15:
            while True:
                if p >= n:
                    raise ValueError("LZ4 : flux tronqué (longueur littéraux)")
                b = src[p]
                p += 1
                lit += b
                if b != 0xFF:
                    break
        if p + lit > n:
            raise ValueError("LZ4 : flux tronqué (littéraux)")
        dst += src[p:p + lit]
        p += lit
        if len(dst) > dst_size:
            raise ValueError(f"LZ4 : littéraux au-delà de {dst_size} octets")
        if len(dst) == dst_size:       # dernière séquence : littéraux seuls
            return bytes(dst)
        # --- match
        if p + 2 > n:
            raise ValueError("LZ4 : flux tronqué (offset)")
        off = src[p] | (src[p + 1] << 8)
        p += 2
        if off == 0 or off > len(dst):
            raise ValueError(f"LZ4 : offset de match invalide ({off})")
        mlen = token & 0x0F
        if mlen == 15:
            while True:
                if p >= n:
                    raise ValueError("LZ4 : flux tronqué (longueur match)")
                b = src[p]
                p += 1
                mlen += b
                if b != 0xFF:
                    break
        mlen += 4
        start = len(dst) - off
        if start + mlen > dst_size:
            raise ValueError("LZ4 : match au-delà de la taille de sortie")
        for k in range(mlen):          # copie octet par octet (chevauchement RLE)
            dst.append(dst[start + k])
    return bytes(dst)


def detect(data: bytes) -> str:
    if data[:4] == MAG_NSO:
        return "NSO"
    if data[:4] == MAG_NRO:
        return "NRO"
    if data[:4] == MAG_PFS:
        return "PFS0"
    return "?"


def parse_image(data: bytes) -> Image:
    kind = detect(data)
    img = Image(kind=kind, size=len(data))
    if kind == "NSO":
        img = _parse_nso(data, img)
    elif kind == "NRO":
        img = _parse_nro(data, img)
    elif kind in ("PFS0", "?"):
        img.notes.append("PFS0 (NSP) : support actuel = détection/inventaire "
                         "seulement ; décryptage NCA à venir.")
    return img


def _parse_nso(data: bytes, img: Image) -> Image:
    """En-tête NSO (libnx nso.h) : flags de compression, segments .text/.ro/.data.
       Les tailles fichier (0x60-0x68) donnent la taille compressée ; les tailles
       d'en-tête (0x18/0x28/0x38) la taille décompressée attendue."""
    flags = _u32(data, 0x0C)
    compressed = [bool(flags & (1 << b)) for b in range(3)]
    hashed = [bool(flags & (1 << (3 + b))) for b in range(3)]
    names = (".text", ".rodata", ".data")
    file_sizes = (_u32(data, 0x60), _u32(data, 0x64), _u32(data, 0x68))
    hashes = (data[0xA0:0xC0], data[0xC0:0xE0], data[0xE0:0x100])
    if flags & 0x80:
        img.notes.append("Flag 7 (Zbic/zstd, [22.0.0+]) : non supporté par cette "
                         "version ; segments compressés illisibles.")
    for k in range(3):
        o = 0x10 + k * 12
        off, moff, sz = _u32(data, o), _u32(data, o + 4), _u32(data, o + 8)
        if not sz:
            continue
        seg = Segment(off, moff, sz, names[k])
        if compressed[k] and not (flags & 0x80):
            csz = file_sizes[k]
            blob = data[off:off + csz] if csz else data[off:off + sz]
            try:
                raw = lz4_decompress_block(blob, sz)
            except ValueError as exc:
                raise ValueError(f"NSO {names[k]} : bloc LZ4 invalide : {exc}") from exc
            seg.payload = raw
        if hashed[k]:
            body = seg.payload if seg.payload is not None else data[off:off + sz]
            if hashlib.sha256(body).digest() != hashes[k]:
                img.notes.append(f"{names[k]} : SHA-256 invalide (en-tête).")
        img.segments.append(seg)
    img.build_id = data[0x40:0x60]
    if any(compressed):
        img.notes.append("Segments LZ4 décompressés." if not (flags & 0x80)
                         else "Compression zstd non décompressée.")
    else:
        img.notes.append("Segments non compressés : chargables directement.")
    return img


def segment_bytes(img: Image, seg: Segment, data: bytes) -> bytes:
    """Octets du segment : payload décompressé s'il existe, sinon tranche fichier."""
    if seg.name == ".bss":
        return bytes(seg.size)
    if seg.payload is not None:
        return seg.payload
    return data[seg.offset_file:seg.offset_file + seg.size]


def _parse_nro(data: bytes, img: Image) -> Image:
    """En-tête NRO (libnx nro.h) : segments .text/.ro/.data + bss_head."""
    size, bss = _u32(data, 0x10), _u32(data, 0x18)
    names = (".text", ".rodata", ".data")
    for k in range(3):
        o = 0x20 + k * 8
        off, sz = _u32(data, o), _u32(data, o + 4)
        if sz:
            img.segments.append(Segment(off, off, sz, names[k]))
    if bss:
        img.segments.append(Segment(0, 0, bss, ".bss"))
    img.notes.append("NRO : segment .text chargé ; heap ASLR/externalité traités plus tard.")
    return img


def summarize(img: Image) -> str:
    """Rapport multi-lignes pour le CLI."""
    L = [f"Format: {img.kind}  ({img.size} octets)",
         f"build_id: {img.build_id.hex()}"]
    if img.segments:
        L.append("Segments:")
        for s in img.segments:
            tag = " [LZ4->décompressé]" if s.payload is not None else ""
            L.append(f"  {s.name:8} file @0x{s.offset_file:x} -> mem @0x{s.offset_mem:x} ({s.size} octets){tag}")
    for n in img.notes:
        L.append(f"[note] {n}")
    return "\n".join(L)
