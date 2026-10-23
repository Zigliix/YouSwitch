# FICHIER D'ANCRAGE — PROJET SWITCH RECOMPILER

> **Ce fichier est la référence absolue du projet. En cas de perte de contexte, le relire en premier.**

## 1. Objectif suprême

Développer un logiciel (recompilateur statique) capable de prendre un fichier de jeu
Nintendo Switch (`.nsp`, `.nro` ou `.nso`) et de le traduire automatiquement en un
jeu PC natif Windows (`.exe`) jouable, **sans émulateur générique**.

Approche : **recompilation statique** — les instructions ARM64 du jeu sont décodées,
traduites une à une en code x86-64/C++ natif, puis reliées à une couche d'abstraction
système (HLE de Horizon OS) implémentant les services de la Switch sur Windows.

## 2. Structure du workspace (3 dossiers stricts)

| Dossier | Rôle |
|---|---|
| `input/` | Fichiers de jeu Switch déposés par l'utilisateur (.nsp, .nro, .nso) |
| `knowledge/` | Mémoire persistante Markdown (objectif, architecture, apprentissages) |
| `decompiler/` | Code source du traducteur + `decompiler/output/` (jeu Windows généré) |

Fichiers de mémoire :
- `knowledge/project.md` — ce fichier (ancrage).
- `knowledge/arm64.md` — savoir accumulé sur l'ISA ARM64 et l'état du décodeur.
- `knowledge/horizon.md` — correspondances Horizon OS (Switch) → Windows.

## 3. Architecture cible du pipeline

```
input/*.nsp|.nro|.nso
   │
   ▼
[1] LOADER  (loader/nsw_formats.py)
    Détection du format, extraction des segments (.text / .rodata / .data),
    décompression LZ4 (à faire), base_id.
   │
   ▼
[2] DECODEUR ARM64  (decoder/arm64.py)
    Mots 32 bits → instruction décodée (mnémonique, registres X0–X30,
    immédiats, shifts, extensions, drapeaux de condition).
   │
   ▼
[3] TRADUCTEUR  (translate/emitter.py)
    a. Émission C++ portable (CPUState, mémoire, sauts étiquetés).
    b. Émission binaire x86-64 directe (decoder/x86_64.py) pour le sous-ensemble sûr.
   │
   ▼
[4] GÉNÉRATEUR WINDOWS  (decompiler/output/ + stubs/horizon_os/)
    Source C++ compilable + stubs HLE Horizon → .exe natif (build_exe.py).
```

## 4. Décisions d'architecture (journal)

- Python 3.14 (disponible sur la machine) comme langage des outils internes ;
  le code **généré** est du C++ (MSVC/MinGW) → .exe.
- Registres ARM64 X0–X30 mappés directement sur 14 registres x86-64
  (X0→RAX … X13→R15) ; au-delà (X14–X30) : émulation mémoire (spill slots).
- Drapeaux NZCV : calculés via fonctions dédiées `set_flags_add/sub` (compatibles
  sémantique x86 EFLAGS).
- Les instructions non encore traduites sont signalées explicitement dans le
  code généré (jamais silencieusement ignorées).
- **SVC — numérotation SwitchBrew** (horizon.md §4) : 0x1F =
  `ConnectToNamedPort`, 0x20–0x23 = `SendSyncRequest`/variantes, 0x30/0x31 =
  `GetResourceLimitValue`. La mention initiale « SVC 0x21 = GetResourceLimit »
  est corrigée : 0x21 est le dispatcher IPC (indispensable à `sm:`) ; les
  quotas sont câblés sur 0x30/0x31.

## 5. Vérités techniques à ne pas oublier

1. Un jeu Switch n'est pas qu'ARM64 : il utilise intensivement les services
   Horizon (sm:, fsp-s, NVN, audren, HID, solo…). La partie « jouable » dépendra
   de la couche HLE (voir `horizon.md`).
2. Le format NSP (PFS0 → NCA → XCI) requiert cryptographie (AES-XTS) : les NSP
   déchiffrés/sortis d'un dump propriétaire seront traités séparément. Priorité
   pipeline : NSO/NRO > NSP.
3. LZ4 : les segments NSO sont souvent compressés LZ4 — **supporté** (loader +
   oracle python-lz4) ; restent zstd/Zbic [22.0.0+].
4. Simd/NEON (registres V0-V31) sera une phase 2.

## 6. État courant (mis à jour à chaque session)

- [x] Structure des dossiers créée.
- [x] `knowledge/` initialisé (project.md, arm64.md, horizon.md, formats.md, services.md).
- [x] Décodeur ARM64 (`decoder/arm64.py`) : familles de base (ADD/SUB/logique/MOV/
      branches/LDR-STR).
- [x] **Validation exhaustive contre capstone (oracle de référence)** :
      immédiat logique 11 328 encodages = 0 mismatch ; balayage aléatoire
      30 000 mots = 0 faux positif sur les familles couvertes.
  - Gardes corrigées : bit21=0/1 = shifted/extended (ADD/SUB reg), bit23=0
    (LDR/STR), ROR interdit ADD/SUB, imm6≤31 (W), imm3≤4 & option∉{3,7}
    (extended W), opc=01/hw non alloués (MOV wide), hw aux bits 22-21,
    B.cond top 0x54 exact.
- [x] Encodeur x86-64 minimal (`decoder/x86_64.py`) — REX/ModRM corrigés
      (R/B = bit3 du registre, opcode `mov r64` = 0xB8+(dst&7)).
- [x] Émetteur C++ + x86-64 (`translate/emitter.py`).
- [x] Loader NSO/NRO/NSP (`loader/nsw_formats.py`) : détection + segments.
- [x] CLI `main.py` (`--mode info|disasm|recomp`) + tests (`tests/test_pipeline.py`).
- [x] **Décodeur — 4 nouvelles familles validées vs capstone** :
      STP/LDP/STNP/LDNP/LDPSW (17 433 cas), TBZ/TBNZ (3 072), LDUR/STUR
      (520), DMB/DSB/ISB + SSBB/PSSBB/DFB (48) ; sweep systématique + 30 000
      mots aléatoires = **0 faux positif, 0 écart de noyau**. Corrections
      associées : BC.cond (bit4), BICS (ANDS N=1), conditions HS/LO, alias
      oracle `mov`/`neg(s)`/`mvn`. Spécifications : arm64.md §5–8.
- [x] Tests `tests/test_pipeline.py` verts (**28/28**) : attentes bitmask
      corrigées, encodages ADD/SUB/STR alignés sur l'ISA (bit21 extended,
      LSL=shift 00, imm12 scallé), REX/ModRM et opcode mov_imm64 x86 fixés.
- [x] Pipeline de bout en bout sur un NSO synthétique dans `input/` :
      `tests/make_synthetic_nso.py` (LZ4 + SHA-256) → `main.py --mode recomp`
      → 8/8 instructions décodées, **0 UNKNOWN, 0 note x86** ; blob natif
      confirmé au désassembleur capstone x86 (adressage/REX/saut rel32 exacts).
- [x] STP/LDP + TBZ/TBNZ + LDUR/STUR décodés et validés (arm64.md §5–7).
- [x] LZ4 bloc (formats.md §7) dans `loader/nsw_formats.py` :
      `lz4_decompress_block` (stdlib pur, copie chevauchante) + hash SHA-256 +
      `segment_bytes` ; **validé vs python-lz4 (oracle, 28/28)** et test NSO
      compressé dans la suite.
- [x] Émetteur PAIR/TBZ/UNSCALED/BARRIER (+ BC./BICS/ANDS/TST, drapeaux
      logiques) : C++ complet ; x86-64 étendu (mémoire [base+disp32],
      `movsx`, `bt`, `test`, sauts rel32 patchés en 2 passes, `mfence`).
      **Compilé par MSVC 19.44 (/W4 /WX) sans erreur ni avertissement.**
- [x] **horizon.md** : table SVC 0x01-0x91 consolidée + signatures, stubs HLE
      Windows proposés, TLS/TPIDR_EL0 (0x200 + exception frame), GetInfo/InfoType
      0-38, carte mémoire (régions 2MB-alignées, ordre ExeFS, ASLR), futex
      ArbitrationType/SignalType, priorités d'implémentation.
- [x] **formats.md** : NsoHeader/NroHeader/MOD0 verbatim, NCA (en-tête, sections,
      PFS0), ExeFS, DynSym/RELA, algorithme LZ4 + vérification SHA-256.
- [x] **services.md** : hid (IHidServer + SharedMemoryFormat + RingLifo + Npad
      interne + NpadButton/NpadStyleTag), vi (vi:u/s/m + IApplicationDisplay**
      Service + Parcel/NativeWindow/DisplayInfo), temps (IStaticService/
      ISystemClock/ISteadyClock/ITimeZoneService + SystemClockContext/
      TimeZoneRule), appletABI (IApplicationProxy + IApplicationFunctions +
      ICommonStateGetter + ISelfController, IDs vérifiés) + mapping Windows.
- [x] **§10-12 services.md** : HIPC/CMIF verbatim (HeaderData/SpecialTag/
      MapData/PointerData, SFCI/SFCO, domaines, MessageTypes, TIPC) + TLR
      0x200 (MessageBuffer 0x100, ThreadPointer, tpidrro vs tpidr) + sm:
      (RegisterClient/GetServiceHandle → TIPC [12.0.0+]).
- [x] **Correction horizon.md** : TLR = 0x200/TPIDRRO_EL0 ; TPIDR_EL0 =
      ThreadPointer nnsdk (OsResourceManager) — nuance appliquée.
- [x] Assise SwitchBrew intégrée dans knowledge/ (SVC, formats, services).
- [x] **Compilation native (VS2022 Community, MSVC 19.44)** : `build_exe.py`
      localise `vcvars64.bat` (vswhere), génère le runner de validation et
      compile le C++ recompilé + les stubs HLE en `.exe` — **0 erreur,
      0 avertissement** (`/W4 /WX /MT`). Premier binaire :
      `decompiler/output/e2e_switchrecomp.exe`.
- [x] **Décodeur SVC** : encodage `0xD4000001 | (imm16 << 5)` décodé et rendu
      (`SVC #0x1f`), émission C++ `hle_svc(s, 0x..)` ; x86-64 = note explicite.
- [x] **HLE `sm:` / IPC** (`stubs/horizon_os/`) : parseur HIPC + CMIF
      (magic SFCI/SFCO, scan du padding) + TIPC ; commandes `RegisterClient`
      (cmd 0) et `GetServiceHandle` (cmd 1) ; SVC 0x1F ConnectToNamedPort,
      0x20–0x23 SendSyncRequest, 0x30/0x31 GetResourceLimitValue (quotas factices).
      Validation à l'exécution : `sm:` résolu (handle 1), RegisterClient →
      client 2, GetServiceHandle("hid") → 3, CMIF("vi") → 4, quota 0x100000.
- [x] Tests `tests/test_pipeline.py` : **56/56** (SVC inclus) ; sweep capstone
      0 faux positif / 0 écart ; LZ4 28/28.

### Prochaines étapes (ordre recommandé)

1. Étendre le HLE aux services de base : hid/vi/time/fsp-srv (services.md),
   MRS/MSR TPIDR_EL0/TPIDRRO_EL0 + TLS réelle, threads/futex.
2. Mémoire virtuelle réelle (mapping `mem_addr`, régions 2 MB-alignées, ASLR).
3. Décodeur : MUL/SDIV/UDIV/CSEL/CSINC/BFI/BFM/EXTR/MRS/MSR ; puis NEON.
4. NSP/NCA (AES-XTS) après stabilisation NSO/NRO.

