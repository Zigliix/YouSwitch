# -*- coding: utf-8 -*-
"""
SwitchRecomp — recompilateur statique Switch -> Windows natif.
CLI : analyse un fichier de jeu (NSO/NRO/NSP) et produit :
  - un rapport .md,
  - le code C++ traduit (decompiler/output/...),
  - une tentative d'émission x86-64 native.

Usage (depuis le dossier decompiler/) :
    python main.py ../input/jeu.nso --mode recomp
"""
from __future__ import annotations
import argparse
import sys
import os
import binascii

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from loader import nsw_formats as nsw            # noqa: E402
from decoder import arm64 as a64                 # noqa: E402
from decoder import x86_64 as x64                # noqa: E402
from translate.emitter import to_x86_64, CppEmitter, CPP_PRELUDE, ARM_TO_X64  # noqa: E402


def load(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def decode_segment(img, data: bytes, seg) -> list[a64.Ins]:
    body = nsw.segment_bytes(img, seg, data)
    n = min(len(body), seg.size) // 4
    return [a64.decode(int.from_bytes(body[4 * k:4 * k + 4], "little"),
                       seg.offset_mem + 4 * k) for k in range(n)]


def stats(insns: list[a64.Ins]) -> dict[str, int]:
    s: dict[str, int] = {}
    for i in insns:
        key = "UNKNOWN" if i.unknown else i.mnemonic
        s[key] = s.get(key, 0) + 1
    return dict(sorted(s.items(), key=lambda kv: -kv[1]))


def run(input_path: str, out_dir: str, mode: str) -> int:
    data = load(input_path)
    img = nsw.parse_image(data)
    print(nsw.summarize(img))
    seg = img.text()
    if seg is None:
        print("Pas de segment .text exploitable : arrêt.")
        return 1
    insns = decode_segment(img, data, seg)
    st = stats(insns)
    print(f"\nInstructions décodées : {len(insns)}")
    print("Familles (top 15) :")
    rank = list(st.items())[:15]
    for name, cnt in rank:
        print(f"  {name:12} {cnt:6}  ({100 * cnt / max(1, len(insns)):.1f}%)")
    unknown = st.get("UNKNOWN", 0)
    print(f"UNKNOWN total   : {unknown} ({100 * unknown / max(1, len(insns)):.1f}%)")

    if mode == "info":
        return 0

    base = os.path.splitext(os.path.basename(input_path))[0]
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "rapport.md"), "w", encoding="utf-8") as fh:
        fh.write(f"# Rapport SwitchRecomp — {base}\n\n")
        fh.write("```\n" + nsw.summarize(img) + "\n```\n\n")
        fh.write("## Couverture de décodage\n\n| Mnémonique | Occurrences |\n|---|---|\n")
        for name, cnt in st.items():
            fh.write(f"| {name} | {cnt} |\n")
        fh.write(f"\nTotal : {len(insns)} instructions, {unknown} inconnues.\n\n")
        fh.write("## Mapping registres ARM64 -> x86-64\n\n| Registre ARM | Registre x64 |\n|---|---|\n")
        for arm, x8 in sorted(ARM_TO_X64.items()):
            name = x64.REG64[x8]
            fh.write(f"| X{arm} | {name} |\n")
        fh.write("\nX14 et au-delà : spill en mémoire (emitter v1).\n\n")

    # C++ complet ; blocs de 4096 instructions pour éviter des fichiers géants
    chunk = 4096
    cpp_lines = [CPP_PRELUDE, "// --- code du jeu recompilé ---", ""]
    for k in range(0, len(insns), chunk):
        part = insns[k:k + chunk]
        cpp_lines += CppEmitter().emit(part, func_name=f"game_block_{k // chunk}")
        cpp_lines.append("")
    cpp_path = os.path.join(out_dir, f"{base}_recompiled.cpp")
    with open(cpp_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(cpp_lines))
    print(f"C++ écrit  : {cpp_path}")

    if mode == "recomp":
        code, notes = to_x86_64(insns)
        blob = os.path.join(out_dir, f"{base}_x86_64.bin")
        with open(blob, "wb") as fh:
            fh.write(code)
        print(f"Code natif : {blob} ({len(code)} octets), {len(notes)} notes.")
        if notes:
            with open(os.path.join(out_dir, "x86_64_notes.txt"), "w",
                      encoding="utf-8") as fh:
                fh.write("\n".join(notes))
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="SwitchRecomp — initial pipeline")
    p.add_argument("input", help="fichier .nso / .nro / .nsp")
    p.add_argument("--mode", choices=["info", "recomp"], default="info")
    p.add_argument("--out", default=os.path.join(os.path.dirname(
        os.path.abspath(__file__)), "output"))
    args = p.parse_args()
    sys.exit(run(args.input, args.out, args.mode))


if __name__ == "__main__":
    main()
