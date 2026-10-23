# -*- coding: utf-8 -*-
"""SwitchRecomp -- compilation du C++ recompilé + stubs HLE en .exe natif.

Usage (depuis decompiler/) :
    python build_exe.py
    python build_exe.py --cpp output/e2e_switchrecomp_recompiled.cpp

Détecte MSVC (vswhere -> vcvars64.bat) ou MinGW g++, génère un runner de
validation pour le NSO synthétique (game_block_0), puis compile avec
/W4 /WX (zéro avertissement accepté).
"""
from __future__ import annotations

import argparse
import glob
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUBS = HERE / "stubs"

RUNNER = r'''// -*- coding: utf-8 -*-
// Runner de validation SwitchRecomp (généré par build_exe.py).
// Exécute game_block_0, vérifie la résolution de "sm:" puis les commandes
// RegisterClient (0) et GetServiceHandle (1) du service manager HLE.
#include <cstdio>
#include "horizon_os/horizon_os.h"

// Le code généré définit les blocs en static : on l'inclut dans cette unité.
#include "@@CPP@@"

static void put_u32(CPUState& s, uint64_t addr, uint32_t value) {
    mem_store32(s, addr, value);
}

static uint32_t get_u32(CPUState& s, uint64_t addr) {
    return (uint32_t)mem_load32(s, addr);
}

// Construit une requête TIPC minimale dans le MessageBuffer du TLR.
static void build_tipc(CPUState& s, uint32_t cmd, const char* name,
                       uint32_t pid) {
    for (uint32_t k = 0; k < 0x100u; ++k) {
        mem_store8(s, HLE_TLR_ADDR + (uint64_t)k, 0);
    }
    put_u32(s, HLE_TLR_ADDR + 0u, cmd);          // Header0 : tag = cmd
    uint32_t raw_words = 0;
    if (cmd == 0u) {                             // RegisterClient : PID u32
        raw_words = 1;
    } else if (cmd == 1u) {                      // GetServiceHandle : nom x8
        raw_words = 2;
    }
    put_u32(s, HLE_TLR_ADDR + 4u, raw_words);    // Header1 : RawCount
    if (cmd == 0u) {
        put_u32(s, HLE_TLR_ADDR + 8u, pid);
    } else {
        for (uint32_t k = 0; k < 8u; ++k) {
            const char c = (name != nullptr) ? name[k] : '\0';
            mem_store8(s, HLE_TLR_ADDR + 8u + (uint64_t)k, (uint8_t)c);
            if (c == '\0') {
                break;
            }
        }
    }
}

// Construit une requête CMIF minimale (SFCI à raw+0x10) dans le TLR.
static void build_cmif(CPUState& s, uint32_t method, const char* name) {
    for (uint32_t k = 0; k < 0x100u; ++k) {
        mem_store8(s, HLE_TLR_ADDR + (uint64_t)k, 0);
    }
    put_u32(s, HLE_TLR_ADDR + 0u, 0u);           // Header0
    put_u32(s, HLE_TLR_ADDR + 4u, 10u);          // RawCount : 10 mots
    const uint64_t sfci = HLE_TLR_ADDR + 0x18u;  // 8 (HIPC) + 0x10 (padding)
    put_u32(s, sfci + 0u, 0x49434653u);          // "SFCI"
    put_u32(s, sfci + 4u, 1u);                   // Version u16=1, reserved=0
    put_u32(s, sfci + 8u, method);               // MethodId
    put_u32(s, sfci + 12u, 0u);                  // Token
    for (uint32_t k = 0; k < 8u; ++k) {
        const char c = (name != nullptr) ? name[k] : '\0';
        mem_store8(s, sfci + 0x10u + (uint64_t)k, (uint8_t)c);
        if (c == '\0') {
            break;
        }
    }
}

int main() {
    CPUState s{};
    hle_init();

    // Nom du port à résoudre + bases mémoire du scénario précédent.
    const char* const port = "sm:";
    for (uint32_t k = 0; k < 4u; ++k) {
        mem_store8(s, 0x1000u + (uint64_t)k, (uint8_t)port[k]);
    }
    mem_store8(s, 0x1004u, 0);
    s.X[1] = 0x4000;   // base STP/LDP du scénario mémoire
    s.X[2] = 0x1122334455667788ULL;
    s.X[3] = 0x5000;   // base LDUR

    // Requête RegisterClient déjà présente : SVC 0x21 la dispatchera.
    build_tipc(s, 0u, nullptr, 0x1234u);

    hle_log("[RUN] execution de game_block_0 (SVC 0x1F puis SVC 0x21)");
    game_block_0(s);

    const uint32_t session = get_u32(s, HLE_OUT_ADDR);
    hle_log("[RUN] handle sm: = %u", (unsigned)session);
    hle_log("[RUN] reponse RegisterClient : client_handle=%u result=0x%x",
            (unsigned)get_u32(s, HLE_TLR_ADDR + 8u),
            (unsigned)get_u32(s, HLE_TLR_ADDR + 12u));

    // Deuxième commande sm: via le dispatcher IPC (GetServiceHandle "hid").
    build_tipc(s, 1u, "hid", 0u);
    hle_log("[RUN] dispatch GetServiceHandle(\"hid\") sur handle=%u",
            (unsigned)session);
    hle_ipc_dispatch(s, session, HLE_TLR_ADDR, 0x100u);
    hle_log("[RUN] reponse GetServiceHandle : handle=%u result=0x%x",
            (unsigned)get_u32(s, HLE_TLR_ADDR + 8u),
            (unsigned)get_u32(s, HLE_TLR_ADDR + 12u));

    // Même commande via le format CMIF (SFCI -> SFCO), nom "vi".
    build_cmif(s, 1u, "vi");
    hle_log("[RUN] dispatch CMIF GetServiceHandle(\"vi\") sur handle=%u",
            (unsigned)session);
    hle_ipc_dispatch(s, session, HLE_TLR_ADDR, 0x100u);
    const uint64_t sfco = HLE_TLR_ADDR + 0x18u;
    hle_log("[RUN] reponse CMIF : magic=0x%x result=0x%x handle=%u",
            (unsigned)get_u32(s, sfco + 0u),
            (unsigned)get_u32(s, sfco + 8u),
            (unsigned)get_u32(s, sfco + 0x10u));

    // SVC 0x30 GetResourceLimitValue (quota factice).
    s.X[0] = 0x3000u;
    s.X[1] = session;
    s.X[2] = 0u;
    hle_svc(s, 0x30u);
    hle_log("[RUN] GetResourceLimitValue -> 0x%llx",
            (unsigned long long)mem_load64(s, 0x3000u));

    hle_shutdown();
    hle_log("[RUN] validation terminee");
    return 0;
}
'''


def find_vcvars64() -> Path | None:
    """Localise vcvars64.bat via vswhere, puis par motifs usuels."""
    pf86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    vswhere = pf86 / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if vswhere.is_file():
        try:
            res = subprocess.run(
                [str(vswhere), "-latest", "-products", "*",
                 "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                 "-property", "installationPath"],
                capture_output=True, text=True, timeout=60)
            for line in res.stdout.splitlines():
                line = line.strip()
                if line:
                    cand = Path(line) / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
                    if cand.is_file():
                        return cand
        except (OSError, subprocess.SubprocessError):
            pass

    patterns = [
        r"C:\Program Files\Microsoft Visual Studio\*\*\VC\Auxiliary\Build\vcvars64.bat",
        r"C:\Program Files (x86)\Microsoft Visual Studio\*\*\VC\Auxiliary\Build\vcvars64.bat",
        r"C:\BuildTools\VC\Auxiliary\Build\vcvars64.bat",
    ]
    for pattern in patterns:
        for hit in sorted(glob.glob(pattern), reverse=True):
            return Path(hit)
    return None


def find_gpp() -> str | None:
    for name in ("g++", "clang++"):
        path = shutil.which(name)
        if path:
            return path
    return None


def run_cmd(cmd: list[str], cwd: Path) -> int:
    print("[build] " + " ".join(cmd))
    res = subprocess.run(cmd, cwd=str(cwd), text=True,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if res.stdout:
        print(res.stdout.rstrip())
    return res.returncode


def build_msvc(vcvars: Path, runner: Path, exe: Path, objdir: Path) -> int:
    sources = [
        STUBS / "horizon_os" / "horizon_os.cpp",
        STUBS / "horizon_os" / "ipc.cpp",
    ]
    flags = ("/nologo /std:c++17 /EHsc /W4 /WX /utf-8 /permissive- /MT /O2 "
             f'/I "{STUBS}"')
    quoted = " ".join(f'"{p}"' for p in [runner, *sources])
    batch = objdir / "build_msvc.bat"
    batch.write_text(
        "@echo off\r\n"
        f'call "{vcvars}" >nul\r\n'
        f'cl {flags} {quoted} /Fe:"{exe}"\r\n'
        "exit /b %ERRORLEVEL%\r\n",
        encoding="utf-8")
    print(f"[build] compilateur : MSVC ({vcvars})")
    return run_cmd(["cmd", "/c", str(batch)], cwd=objdir)


def build_mingw(gpp: str, runner: Path, exe: Path, objdir: Path) -> int:
    sources = [
        STUBS / "horizon_os" / "horizon_os.cpp",
        STUBS / "horizon_os" / "ipc.cpp",
    ]
    cmd = [gpp, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
           "-I", str(STUBS), str(runner), *[str(p) for p in sources],
           "-o", str(exe)]
    print(f"[build] compilateur : {gpp}")
    return run_cmd(cmd, cwd=objdir)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile le C++ recompilé SwitchRecomp en .exe Windows.")
    parser.add_argument("--cpp",
                        default=str(HERE / "output" /
                                    "e2e_switchrecomp_recompiled.cpp"),
                        help="fichier C++ généré par main.py --mode recomp")
    parser.add_argument("--exe", default=None,
                        help="chemin du .exe de sortie")
    args = parser.parse_args()

    cpp = Path(args.cpp).resolve()
    if not cpp.is_file():
        print(f"[build] ERREUR : C++ introuvable : {cpp}", file=sys.stderr)
        return 2

    out_dir = cpp.parent
    exe = Path(args.exe).resolve() if args.exe else \
        out_dir / (cpp.stem.replace("_recompiled", "") + ".exe")
    runner = out_dir / (cpp.stem + "_runner.cpp")
    runner.write_text(RUNNER.replace("@@CPP@@", cpp.name), encoding="utf-8")
    objdir = out_dir / "obj"
    objdir.mkdir(parents=True, exist_ok=True)

    print(f"[build] source     : {cpp}")
    print(f"[build] runner     : {runner}")

    vcvars = find_vcvars64()
    if vcvars is not None:
        rc = build_msvc(vcvars, runner, exe, objdir)
    else:
        gpp = find_gpp()
        if gpp is None:
            print("[build] ERREUR : ni MSVC (vcvars64.bat) ni g++/clang++.",
                  file=sys.stderr)
            return 3
        rc = build_mingw(gpp, runner, exe, objdir)

    if rc != 0:
        print(f"[build] ÉCHEC (code {rc})", file=sys.stderr)
        return rc
    if not exe.is_file():
        print(f"[build] ÉCHEC : {exe} non produit", file=sys.stderr)
        return 4

    print(f"[build] OK : {exe} ({exe.stat().st_size} octets)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
