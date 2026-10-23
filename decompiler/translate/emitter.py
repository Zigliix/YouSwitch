# -*- coding: utf-8 -*-
"""
Traducteur SwitchRecomp : ARM64 décodé -> C++ portable / code x86-64 natif.
"""
from __future__ import annotations
from decoder import arm64 as a64
from decoder import x86_64 as x64

ARM_TO_X64: dict[int, int] = {
    0: x64.REG64.index("RAX"), 1: x64.REG64.index("RCX"), 2: x64.REG64.index("RDX"),
    3: x64.REG64.index("RBX"), 4: x64.REG64.index("RSI"), 5: x64.REG64.index("RDI"),
    6: x64.REG64.index("R8"), 7: x64.REG64.index("R9"), 8: x64.REG64.index("R10"),
    9: x64.REG64.index("R11"), 10: x64.REG64.index("R12"), 11: x64.REG64.index("R13"),
    12: x64.REG64.index("R14"), 13: x64.REG64.index("R15"),
}
M32 = "0xFFFFFFFFULL"

CPP_PRELUDE = r'''// ---- Généré par SwitchRecomp (traduction ARM64 -> C++) ----
// Le résultat est compilé par MSVC/MinGW en .exe Windows natif : aucun
// émulateur générique n'est nécessaire à l'exécution.
#include <stdint.h>
#include <atomic>
#include "horizon_os/horizon_os.h"   // CPUState, mémoire plate, HLE (SVC/IPC)

// --- drapeaux NZCV (order Arm: N bit63, Z zero, C carry/borrow, V overflow) ---
static inline void set_flags_sub(CPUState& s, uint64_t a, uint64_t b) {
    uint64_t r = a - b;
    s.N = (int)((r >> 63) & 1); s.Z = (int)(r == 0);
    s.C = (int)(a >= b);
    s.V = (int)(((a ^ b) & (a ^ r)) >> 63) & 1;
}
static inline void set_flags_add(CPUState& s, uint64_t a, uint64_t b) {
    uint64_t r = a + b;
    s.N = (int)((r >> 63) & 1); s.Z = (int)(r == 0);
    s.C = (int)(r < a);
    s.V = (int)((~(a ^ b) & (a ^ r)) >> 63) & 1;
}
static inline void set_flags_logic(CPUState& s, uint64_t r, int width) {
    r &= (width == 32) ? 0xFFFFFFFFULL : ~0ULL;
    s.N = (int)((r >> (width - 1)) & 1); s.Z = (int)(r == 0);
    s.C = 0; s.V = 0;
}
'''


def label(addr: int) -> str:
    return f"L_{addr:08x}"


class CppEmitter:
    """Émission d'un bloc C++ depuis des instructions ARM64 décodées."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def _r(self, i: a64.Ins, r: int, sp_ok: bool) -> str:
        if r == 31:
            return "s.SP" if (sp_ok and i.sf) else "0"
        name = f"s.X[{r}]"
        return name

    def _dst(self, i: a64.Ins, expr: str, sp_ok: bool = False,
             dst: int | None = None) -> str:
        """Affectation à Rd (ou dst explicite) avec masque 32 bits si W.
        ZR (cible 31) : écriture ignorée."""
        reg = i.rd if dst is None else dst
        lhs = self._r(i, reg, sp_ok=sp_ok)
        if lhs == "0":
            return f"/* écriture XZR ignorée : {expr} */"
        if not i.sf:
            expr = f"(({expr}) & {M32})"
        return f"{lhs} = {expr};"

    def emit(self, insns: list[a64.Ins], func_name: str = "block") -> list[str]:
        targets = {i.target for i in insns
                   if i.target is not None and i.mnemonic != "BL"}
        out = [f"// Bloc {func_name}: début", f"static void {func_name}(CPUState& s) {{"]
        for i in insns:
            ind = "    "
            if i.unknown:
                out.append(ind + f"/* NON TRADUIT : 0x{i.raw:08x} */")
                continue
            if i.addr in targets:
                out.append(ind + f"{label(i.addr)}: ;")
            b = self._line(i)
            if b:
                out.append(ind + b)
        # Évite le C4702 (code inaccessible) quand le bloc se termine déjà par
        # un retour/goto inconditionnel.
        terminated = bool(insns) and not insns[-1].unknown and (
            insns[-1].group == "BRANCH_REG" or
            (insns[-1].group == "BRANCH" and insns[-1].mnemonic == "B"))
        if not terminated:
            out.append("    return;")
        out.append("}")
        return out

    def _line(self, i: a64.Ins) -> str | None:
        g = i.group
        r, w = self._r, self._dst
        if g == "NOP":
            return None
        if g == "SVC":
            # Appel superviseur : le HLE Horizon (stubs/horizon_os) traite
            # l'appel et met à jour X0..X7 / la mémoire partagée.
            return f"hle_svc(s, 0x{i.imm:x});"
        if g == "ADD_SUB_IMM":
            if i.flags and i.rd == 31:
                fn = "sub" if i.mnemonic == "CMP" else "add"
                return f"set_flags_{fn}(s, {r(i, i.rn, True)}, (uint64_t){i.imm}ULL);"
            return self._dst(i, f"{r(i, i.rn, True)} + (uint64_t){i.imm}ULL"
                             if i.mnemonic == "ADD" else
                             f"{r(i, i.rn, True)} - (uint64_t){i.imm}ULL", sp_ok=True)
        if g == "ADD_SUB_REG":
            rhs = self._reg_operand(i)
            sp = i.option is not None          # extended : Rn=31 = SP ; shifted : ZR
            base = r(i, i.rn, sp)
            if i.flags:
                fn = "sub" if i.mnemonic.startswith("SUB") else "add"
                if i.rd == 31:   # CMP/CMN registres
                    return f"set_flags_{fn}(s, {base}, {rhs});"
                if not i.sf:
                    return f"/* TODO drapeaux W {i.mnemonic} reg */"
                lhs = self._r(i, i.rd, True)
                op = "+" if fn == "add" else "-"
                return (f"{{ uint64_t t = {base} {op} {rhs}; {lhs} = t; "
                        f"set_flags_{fn}(s, {base}, {rhs}); }}")
            ex = (f"{base} + {rhs}" if i.mnemonic == "ADD"
                  else f"{base} - {rhs}")
            return w(i, ex)
        if g == "LOGICAL_REG":
            ops = {"AND": ("&", ""), "ORR": ("|", ""), "EOR": ("^", ""),
                   "BIC": ("&", "!"), "ORN": ("|", "!"), "EON": ("^", "!")}
            # ANDS/BICS/TST : résultat + drapeaux (C=V=0)
            if i.mnemonic in ("ANDS", "BICS", "TST"):
                rhs = r(i, i.rm, False)
                if i.mnemonic == "BICS":
                    rhs = f"~{rhs}"
                if i.shift_amt:
                    op = {"LSL": "<<", "LSR": ">>", "ASR": ">>"}.get(i.shift_type)
                    if op is None:
                        return f"/* TODO {i.mnemonic} shift ROR */"
                    rhs = f"({rhs} {op} {i.shift_amt})"
                expr = f"{r(i, i.rn, False)} & {rhs}"
                width = 64 if i.sf else 32
                if i.mnemonic == "TST" or i.rd == 31:
                    return f"{{ uint64_t t = {expr}; set_flags_logic(s, t, {width}); }}"
                lhs = self._r(i, i.rd, False)
                mask = "" if i.sf else f" & {M32}"
                return (f"{{ uint64_t t = ({expr}){mask}; {lhs} = t; "
                        f"set_flags_logic(s, t, {width}); }}")
            if i.mnemonic in ops:
                o, notp = ops[i.mnemonic]
                rhs = r(i, i.rm, False)
                if notp:
                    rhs = f"~{rhs}"
                if i.shift_amt:
                    op = {"LSL": "<<", "LSR": ">>", "ASR": ">>"}.get(i.shift_type)
                    if op is None:
                        return f"/* TODO {i.mnemonic} shift ROR */"
                    rhs = f"({rhs} {op} {i.shift_amt})"
                return w(i, f"{r(i, i.rn, False)} {o} {rhs}")
            return f"/* TODO {i.mnemonic} logique */"
        if g == "LOGICAL_IMM":
            o = {"AND": "&", "ORR": "|", "EOR": "^"}[i.mnemonic] if i.mnemonic in \
                ("AND", "ORR", "EOR") else None
            if o:
                return w(i, f"{r(i, i.rn, True)} {o} (uint64_t){i.imm}ULL")
            return f"/* TODO {i.mnemonic} imm */"
        if g == "MOV_WIDE":
            if i.mnemonic == "MOVZ":
                return w(i, f"(uint64_t){i.imm}ULL << {i.shift_amt}")
            if i.mnemonic == "MOVN":
                return w(i, f"~((uint64_t){i.imm}ULL << {i.shift_amt})")
            mask = (~(0xFFFF << i.shift_amt)) & 0xFFFFFFFFFFFFFFFF
            cur = f"({r(i, i.rd, True)} & 0x{mask:016x}ULL)"
            return w(i, f"{cur} | ((uint64_t){i.imm}ULL << {i.shift_amt})")
        if g == "PCREL":
            return w(i, f"s.PC_BASE + 0x{i.addr:x}ULL + (uint64_t)({i.imm})/* {i.mnemonic} */")
        if g == "CBZ":
            cond = "== 0" if i.mnemonic == "CBZ" else "!= 0"
            return f"if ({r(i, i.rt, False)} {cond}) goto {label(i.target)};"
        if g == "BRANCH":
            if i.mnemonic == "B":
                return f"goto {label(i.target)};"
            return f"/* TODO BL 0x{i.target:08x} */"
        if g == "BRANCH_COND":
            t = {"EQ": "s.Z", "NE": "!s.Z", "HS": "s.C", "LO": "!s.C", "MI": "s.N",
                 "PL": "!s.N", "VS": "s.V", "VC": "!s.V",
                 "HI": "(s.C && !s.Z)", "LS": "(!s.C || s.Z)",
                 "GE": "(s.N == s.V)", "LT": "(s.N != s.V)",
                 "GT": "(!s.Z && s.N == s.V)", "LE": "(s.Z || s.N != s.V)"}.get(i.cond, "false")
            return f"if ({t}) goto {label(i.target)};"
        if g == "TBZ":
            src = r(i, i.rt, False)
            if i.rt == 31:                     # XZR : bit toujours 0
                taken = i.mnemonic == "TBZ"
                return f"if ({'true' if taken else 'false'}) goto {label(i.target)};"
            zero = "== 0" if i.mnemonic == "TBZ" else "!= 0"
            return f"if ((({src} >> {i.shift_amt}) & 1) {zero}) goto {label(i.target)};"
        if g == "PAIR":
            return self._pair_line(i)
        if g == "UNSCALED":
            return self._unscaled_line(i)
        if g == "BARRIER":
            if i.mnemonic == "ISB":
                return None
            return "std::atomic_thread_fence(std::memory_order_seq_cst);"
        if g == "LDR_STR_IMM":
            bits_wallpaper = {0: 8, 1: 16, 2: 32, 3: 64}[i.shift_amt]
            if i.mnemonic.startswith("LDR"):
                return self._dst(i, f"mem_load{bits_wallpaper}(s, "
                                    f"({r(i, i.rn, True)} + (uint64_t){i.imm}ULL))",
                                 dst=i.rt)
            return (f"mem_store{bits_wallpaper}(s, ({r(i, i.rn, True)} + (uint64_t){i.imm}ULL), "
                    f"{r(i, i.rt, False)});")
        if g == "BRANCH_REG":
            return "return; /* RET (X30) */"
        return f"/* TODO {i.mnemonic} */"

    def _pair_line(self, i: a64.Ins) -> str:
        """STP/LDP/STNP/LDNP/LDPSW : deux accès mémoire + writeback éventuel."""
        r = self._r
        base = "s.SP" if i.rn == 31 else f"s.X[{i.rn}]"
        addr = base if i.imm == 0 else f"({base} + (uint64_t)(int64_t){i.imm})"
        elem = 32 if (i.mnemonic == "LDPSW" or not i.sf) else 64
        step = elem // 8
        stmts: list[str] = []
        if i.mnemonic == "LDPSW":
            if i.rt != 31:
                stmts.append(f"s.X[{i.rt}] = (uint64_t)(int64_t)(int32_t)mem_load32(s, {addr});")
            if i.rm != 31:
                stmts.append(f"s.X[{i.rm}] = (uint64_t)(int64_t)(int32_t)"
                             f"mem_load32(s, {addr} + {step});")
        elif i.mnemonic in ("LDP", "LDNP"):
            if i.rt != 31:
                stmts.append(f"s.X[{i.rt}] = mem_load{elem}(s, {addr});")
            if i.rm != 31:
                stmts.append(f"s.X[{i.rm}] = mem_load{elem}(s, {addr} + {step});")
        else:                                   # STP/STNP
            stmts.append(f"mem_store{elem}(s, {addr}, {r(i, i.rt, False)});")
            stmts.append(f"mem_store{elem}(s, {addr} + {step}, {r(i, i.rm, False)});")
        if i.mode in ("pre", "post"):
            # pre : base = base+imm APRÈS l'accès ; post : idem (mnémotechnique
            # inverse mais même valeur finale).
            dst = "s.SP" if i.rn == 31 else f"s.X[{i.rn}]"
            stmts.append(f"{dst} = {addr};")
        return "{ " + " ".join(stmts) + " }"

    def _unscaled_line(self, i: a64.Ins) -> str:
        """LDUR/STUR + variantes B/H/SB/SH/SW : offset signé imm9."""
        r = self._r
        base = "s.SP" if i.rn == 31 else f"s.X[{i.rn}]"
        addr = base if i.imm == 0 else f"({base} + (uint64_t)(int64_t){i.imm})"
        mn = i.mnemonic
        if mn.startswith("STUR"):
            bits = 8 if mn.endswith("B") else 16 if mn.endswith("H") else \
                (64 if i.sf else 32)
            return f"mem_store{bits}(s, {addr}, {r(i, i.rt, False)});"
        if i.rt == 31:                              # chargement vers XZR : ignoré
            return f"/* {mn} vers XZR ignoré */"
        if mn == "LDURSB":
            val = f"(uint64_t)(int64_t)(int8_t)mem_load8(s, {addr})"
        elif mn == "LDURSH":
            val = f"(uint64_t)(int64_t)(int16_t)mem_load16(s, {addr})"
        elif mn == "LDURSW":
            val = f"(uint64_t)(int64_t)(int32_t)mem_load32(s, {addr})"
        else:
            val = f"mem_load{64 if i.sf else 32}(s, {addr})"
        return self._dst(i, val, dst=i.rt)

    def _reg_operand(self, i: a64.Ins) -> str:
        """Opérande-right (Rm + extension/décalage) en C++."""
        rm = self._r(i, i.rm, False)
        if i.option is not None:
            # extension signée/nulle sur la largeur native puis décalage imm3
            base = {0: "(uint8_t)", 1: "(uint16_t)", 2: "(uint32_t)", 3: "",
                    4: "(int64_t)(int8_t)", 5: "(int64_t)(int16_t)",
                    6: "(int64_t)(int32_t)", 7: ""}[i.option]
            rm = f"{base}({rm})" if base else rm
        if i.shift_amt:
            st = i.shift_type or "LSL"
            if st == "LSL":
                rm = f"({rm} << {i.shift_amt})"
            elif st == "LSR":
                rm = f"((uint64_t)({rm}) >> {i.shift_amt})"
            elif st == "ASR":
                if i.sf:
                    rm = f"((int64_t)({rm}) >> {i.shift_amt})"
                else:
                    rm = f"((int64_t)(int32_t)({rm}) >> {i.shift_amt})"
        return rm

def _can_imm32(v: int) -> bool:
    """Immédiat représentable immédiatement en x86 (32 bits signé)."""
    return -0x80000000 <= v <= 0x7FFFFFFF


def to_x86_64(insns: list[a64.Ins]) -> tuple[bytes, list[str]]:
    """Émet le code machine x86-64 pour le sous-ensemble sûr. Retour
    (code, notes) : les instructions non traduisibles restent en notes.
    Branches : rel32 patchés en second passage (cibles internes au bloc)."""
    out: list[int] = []
    notes: list[str] = []
    labels: dict[int, int] = {}
    known = {i.addr for i in insns}
    fixups: list[tuple[int, int]] = []      # (position rel32, adresse ARM cible)

    def target_of(i: a64.Ins) -> int:
        if i.target is None or i.target not in known:
            raise NotImplementedError(f"cible hors bloc (0x{(i.target or 0):x})")
        return i.target

    for i in insns:
        labels.setdefault(i.addr, len(out))
        if i.unknown:
            notes.append(f"0x{i.addr:x}: UNK -> non émis")
            continue
        rd = ARM_TO_X64.get(i.rd) if i.rd is not None else None
        rn = ARM_TO_X64.get(i.rn) if i.rn is not None else None
        rm = ARM_TO_X64.get(i.rm) if i.rm is not None else None
        rt = ARM_TO_X64.get(i.rt) if i.rt is not None else None
        try:
            g = i.group
            if g == "MOV_WIDE" and i.sf and rd is not None:
                val = i.imm << i.shift_amt
                if i.mnemonic == "MOVZ":
                    if _can_imm32(val):
                        x64.mov_imm32_sext64(out, rd, val)
                    else:
                        x64.mov_imm64(out, rd, val & 0xFFFFFFFFFFFFFFFF)
                elif i.mnemonic == "MOVN":
                    val = (~(i.imm << i.shift_amt)) & 0xFFFFFFFFFFFFFFFF
                    x64.mov_imm64(out, rd, val)
                else:
                    raise NotImplementedError
            elif (g == "ADD_SUB_REG" and not i.flags and i.sf and not i.shift_amt
                    and i.option is None and rd is not None and rn is not None
                    and rm is not None):
                if rd != rn:
                    x64.alu_rr(out, "MOV", rd, rn, wide=True)
                x64.alu_rr(out, i.mnemonic, rd, rm, wide=True)
            elif (g == "ADD_SUB_IMM" and not i.flags and i.sf and rd is not None
                    and rn is not None):
                if rd != rn:
                    x64.alu_rr(out, "MOV", rd, rn, wide=True)
                if _can_imm32(i.imm):
                    x64.alu_imm32(out, i.mnemonic, rd, i.imm, wide=True)
                else:
                    x64.mov_imm64(out, rd, i.imm & 0xFFFFFFFFFFFFFFFF)
                    x64.alu_rr(out, i.mnemonic, rd, rd, wide=True)
            elif (g == "LOGICAL_IMM" and i.sf and rd is not None and rn is not None
                    and i.mnemonic in ("AND", "ORR", "EOR") and _can_imm32(i.imm)):
                if rd != rn:
                    x64.alu_rr(out, "MOV", rd, rn, wide=True)
                x64.alu_imm32(out, {"AND": "AND", "ORR": "OR", "EOR": "XOR"}[i.mnemonic],
                              rd, i.imm, wide=True)
            elif g == "PAIR" and i.rn != 31 and rn is not None:
                elem = 32 if (i.mnemonic == "LDPSW" or not i.sf) else 64
                step = elem // 8
                if i.mnemonic in ("LDP", "LDNP", "LDPSW"):
                    if i.rt != 31:
                        if rt is None:
                            raise NotImplementedError
                        if i.mnemonic == "LDPSW":
                            x64.movsx_load(out, rt, rn, i.imm, 32)
                        else:
                            x64.mov_load(out, rt, rn, i.imm, elem)
                    if i.rm != 31:
                        if rm is None:
                            raise NotImplementedError
                        if i.mnemonic == "LDPSW":
                            x64.movsx_load(out, rm, rn, i.imm + step, 32)
                        else:
                            x64.mov_load(out, rm, rn, i.imm + step, elem)
                else:
                    if rt is None or rm is None:
                        raise NotImplementedError
                    x64.mov_store(out, rn, i.imm, rt, elem)
                    x64.mov_store(out, rn, i.imm + step, rm, elem)
                if i.mode in ("pre", "post") and i.imm:
                    if i.imm > 0:
                        x64.alu_imm32(out, "ADD", rn, i.imm, wide=True)
                    else:
                        x64.alu_imm32(out, "SUB", rn, -i.imm, wide=True)
            elif g == "UNSCALED" and i.rn != 31 and rn is not None:
                mn = i.mnemonic
                if mn.startswith("STUR"):
                    if rt is None:
                        raise NotImplementedError
                    bits = 8 if mn.endswith("B") else 16 if mn.endswith("H") else \
                        (64 if i.sf else 32)
                    x64.mov_store(out, rn, i.imm, rt, bits)
                elif i.rt != 31:                 # chargement vers XZR : sans effet
                    if rt is None:
                        raise NotImplementedError
                    if mn == "LDURSB":
                        x64.movsx_load(out, rt, rn, i.imm, 8, dst_wide=bool(i.sf))
                    elif mn == "LDURSH":
                        x64.movsx_load(out, rt, rn, i.imm, 16, dst_wide=bool(i.sf))
                    elif mn == "LDURSW":
                        x64.movsx_load(out, rt, rn, i.imm, 32, dst_wide=True)
                    else:
                        x64.mov_load(out, rt, rn, i.imm, 64 if i.sf else 32)
            elif g == "TBZ" and rt is not None:
                tgt = target_of(i)
                x64.bt_imm(out, rt, i.shift_amt)
                cc = "HS" if i.mnemonic == "TBNZ" else "LO"   # CF=1 si bit posé
                fixups.append((x64.jcc32(out, cc), tgt))
            elif g == "CBZ" and rt is not None:
                tgt = target_of(i)
                x64.test_rr(out, rt, 64)
                fixups.append((x64.jcc32(out, "NE" if i.mnemonic == "CBNZ" else "EQ"),
                               tgt))
            elif g == "BRANCH" and i.mnemonic == "B":
                fixups.append((x64.jmp32(out), target_of(i)))
            elif g == "BRANCH_REG":
                x64.ret(out)
            elif g == "BARRIER":
                if i.mnemonic != "ISB":
                    x64.mfence(out)
            else:
                raise NotImplementedError
        except NotImplementedError as exc:
            reason = f" ({exc})" if str(exc) else ""
            notes.append(f"0x{i.addr:x}: {i.mnemonic} -> C++ seulement{reason}")
    for pos, tgt in fixups:
        x64.patch_rel32(out, pos, labels[tgt])
    return bytes(out), notes
