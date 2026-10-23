# FORMATS SWITCH — SAVOIR PERSISTANT

Source : SwitchBrew (pages `NSO0`, `NRO0`, `NCA`, `MOD`, `ExeFS`, rev. 2025-2026).
Chaîne de chargement d'un jeu : **NSP → NCA → PFS0 → ExeFS → NSO**(+ NPDM),
ou **NRO** direct (homebrew / modules RO).

## 1. NSO (executable principal)

L'en-tête décrit .text/.rodata/.data (mini-ELF program headers). Segments
compressés en **LZ4** (voir §7).

### NsoHeader (verbatim wiki)

| Off. | Taille | Champ |
|---|---|---|
| 0x0   | 4 | Signature "NSO0" |
| 0x4   | 4 | Version |
| 0x8   | 4 | Reserved |
| 0xC   | 4 | Flags (§Flags) |
| 0x10  | 4 | TextFileOffset |
| 0x14  | 4 | TextMemoryOffset |
| 0x18  | 4 | TextSize (taille décompressée) |
| 0x1C  | 4 | ModuleNameOffset (= sizeof(header)) |
| 0x20  | 4 | RoFileOffset |
| 0x24  | 4 | RoMemoryOffset |
| 0x28  | 4 | RoSize |
| 0x2C  | 4 | ModuleNameSize |
| 0x30  | 4 | DataFileOffset |
| 0x34  | 4 | DataMemoryOffset |
| 0x38  | 4 | DataSize |
| 0x3C  | 4 | BssSize |
| 0x40  | 0x20 | ModuleId (build id, digest ≤32 octets) |
| 0x60  | 4 | TextFileSize (text compressé) |
| 0x64  | 4 | RoFileSize (ro compressé) |
| 0x68  | 4 | DataFileSize (data compressé) |
| 0x6C  | 0x1C | Reserved |
| 0x88  | 4 | EmbeddedOffset (relatif à .rodata) |
| 0x8C  | 4 | EmbeddedSize |
| 0x90  | 4 | DynStrOffset (relatif à .rodata) |
| 0x94  | 4 | DynStrSize |
| 0x98  | 4 | DynSymOffset (relatif à .rodata) |
| 0x9C  | 4 | DynSymSize |
| 0xA0  | 0x20 | TextHash (SHA-256 du .text DÉCOMPRESSÉ) |
| 0xC0  | 0x20 | RoHash (idem .rodata) |
| 0xE0  | 0x20 | DataHash (idem .data) |
| 0x100 | var | Sections compressées |

### Flags NSO

| Bit | Signification |
|---|---|
| 0/1/2 | .text/.rodata/.data compressés (LZ4) |
| 3/4/5 | hash correspondant à vérifier au chargement |
| 6 | [20.0.0+] ExecuteOnlyMemory |
| 7 | [22.0.0+] UseZbicCompression (zstd au lieu de LZ4) |

Note : offsets **Fichier** listés des segments ; les segments se suivent à
0x100 ; **MemoryOffset/Size** = mapping dans l'image virtuelle du processus.

### Arguments (argdata) — écrit par le Loader en fin de rwdata

| Off. | Taille | Champ |
|---|---|---|
| 0x0 | 4 | taille totale allouée (≈0x9000) |
| 0x4 | 4 | taille réelle de la chaîne argdata |
| 0x8 | 0x18 | unused |
| 0x20 | var | chaîne argdata |
Copie de args + tableau argv juste après (copie alignée +0x9 & ~0x7).

## 2. NRO (modules / homebrew)

### NroHeader (verbatim wiki)

| Off. | Taille | Champ |
|---|---|---|
| 0x0 | 0x10 | Rocrt (ModuleHeaderLocation) |
| 0x10 | 4 | Signature "NRO0" |
| 0x14 | 4 | Version |
| 0x18 | 4 | Size (taille totale du fichier) |
| 0x1C | 4 | Flags |
| 0x20/0x24 | 4/4 | TextMemoryOffset / TextSize |
| 0x28/0x2C | 4/4 | RoMemoryOffset / RoSize |
| 0x30/0x34 | 4/4 | DataMemoryOffset / DataSize |
| 0x38 | 4 | BssSize |
| 0x3C | 4 | AdditionalHeaderOffset ([23.0.0+]) |
| 0x40 | 0x20 | ModuleId |
| 0x60 | 4 | DsoHandleOffset |
| 0x64 | 4 | Reserved |
| 0x68/0x6C | 4/4 | EmbeddedOffset/Size |
| 0x70/0x74 | 4/4 | DynStrOffset/Size |
| 0x78/0x7C | 4/4 | DynSymOffset/Size |

- RocrtHeader [nn::rocrt]: 0x0 ModuleHeaderLocation — [17.0.0+] 0xC
  ([1.0.0-16.1.0] 0x8) ; 0xC Reserved.
- Flags NRO : bit0 AlignedHeader ; bit1 [23.0.0+] Compress.
- **Assets homebrew** : optionnel à {NroHeader.size} :
  AssetHeader ("ASET", version 0): 0x8 icon (16B), 0x18 NACP (16B),
  0x28 romfs (16B) ; AssetSection = {offset u64 @0, size u64 @8} (0=vide).
- AdditionalNroHeader ("NRA0", [23.0.0+]) : 0x10 CompressedSize, 0x18 HashSize,
  0x1C HashOffset, 0x60 Hash (0x20).

## 3. MOD — module object (remplace PT_DYNAMIC)

- ModuleHeaderLocation (dans Rocrt) : 0x0 [17.0.0+] Version ; 0x4
  **HeaderOffset** (vers ModuleHeader) ; 0x8 [17.0.0+] VersionOffset.
- **ModuleHeader "MOD0"** : 0x4 DynamicOffset ; 0x8/0xC BssStart/EndOffset ;
  0x10/0x14 ExceptionInfoStart/EndOffset ; 0x18 ModuleOffset (vers l'objet
  module runtime, souvent base .bss) ; [19.0.0+] 0x1C RelroStart,
  0x20 FullRelroEnd, 0x24 NxDebugLinkStart, 0x28 NxDebugLinkEnd,
  0x2C NoteGnuBuildIdStart, 0x30 NoteGnuBuildIdEnd.
- ModuleVersion (après ModuleHeader si [17.0.0+]) : Major/Minor/Micro (3×u32) —
  version nnsdk utile pour choisir les conventions services.

## 4. NCA (conteneur de contenu)

**Tout le NCA brut est chiffré** (les 0xC00 premiers octets en AES-XTS secteur
0x200, tweak à endianness inversé — dump SciresM ; seul logo en clair si
présent). Nos .nsp d'entrée : NCAs chiffrés → *clés tiers requises pour décrypter
(phase dédiée ; HLE final accepte aussi NCAs déjà décryptés / jeux NRO test)*.

### Header "NCA3" (0x400)

| Off. | Taille | Champ |
|---|---|---|
| 0x0/0x100 | 2×0x100 | RSA-2048 signatures sur 0x200-0x400 (fixe / NPDM) |
| 0x200 | 4 | Magic "NCA3" (pré-1.0.0 : NCA0/1/2) |
| 0x204/0x205 | 1/1 | DistributionType (0 DL, 1 Carte) / ContentType (0 Program, 1 Meta, 2 Control, 3 Manual, 4 Data, 5 PublicData) |
| 0x206/0x207 | 1/1 | KeyGenerationOld (≤2) / KeyAreaKeyIndex (0 App, 1 Ocean, 2 System) |
| 0x208/0x210 | 8/8 | ContentSize / ProgramId (-1 = everyone) |
| 0x218/0x21C | 4/4 | ContentIndex / SdkAddonVersion |
| 0x220/0x221 | 1/1 | KeyGeneration (0x03=3.0.1 … 0x17=23.0.0 ; = MasterKeyVersion+1 ; 0xFF invalid) / [9.0.0+] SignatureKeyGen |
| 0x230 | 0x10 | RightsId |
| 0x240 | 4×0x10 | FsEntry (start/end secteurs 0x200 + reserved) |
| 0x280 | 4×0x20 | SHA-256 de chaque FsHeader |
| 0x300 | 4×0x10 | EncryptedKeyArea |

### FsHeader (par section, à 0x400 + sectionid×0x200)

0x0 Version(=2) ; FsType (0 RomFS, 1 PartitionFS) ; HashType (1 none,
2 HierSha256, 3 HierIntegrity, [12+/14+] SHA3…) ; EncryptionType (1 none,
2 AesXts, 3 AesCtr, 4 AesCtrEx, [14+] skip-layer) ; 0x8 HashData 0xF8
(MasterHash+BlockSize+Regions / IVFC levels) ; 0x100 PatchInfo 0x40 (BKTR
updates RomFS : relocation/subsection buckets) ; 0x140 Generation/SecureValue ;
0x148 SparseInfo 0x30 ; [12+] 0x178 CompressionInfo 0x28 ; [14+]
0x1A0 MetaDataHashDataInfo 0x30. BucketTreeHeader = "BKTR"+EntryCount.

- Section 0 = ExeFS, section 1 = RomFS (jeu), jeu ncatype1 RomFS → crypto
  type 0x4 section data ; updates = BKTR (combinaison base+patch).
- Sections ExeFS et Logo = **PFS0** :

### PFS0

| Off. | Taille | Champ |
|---|---|---|
| 0x0 | 4 | Magic "PFS0" |
| 0x4 | 4 | EntryCount |
| 0x8 | 4 | StringTableSize |
| 0xC | 4 | Reserved |
| 0x10 | X | PartitionEntryTable |
| … | Y | StringTable |
| … | Z | FileData |

PartitionEntry : offset u64, size u64, stringOffset u32, reserved u32.
Précédé (superblock) d'une table de SHA-256 par bloc, puis alignement zéro.
NSP = PFS0 de NCAs (+ .cnmt) — déjà géré dans `loader/nsw_formats.py`.

### ExeFS (contenu)

`/main` + `/main.npdm` obligatoires ; optionnels `/rtld`, `/sdk` ;
jeux : `/subsdk0..6` (tous NSO). Ordre de chargement en mémoire :
**rtld → main → subsdk\* → sdk** (cf horizon.md §5).

## 5. Symboles (DynSym/DynStr)

NSO/NRO embarquent `.dynsym`/`.dynstr` (offsets relatifs à .rodata) au format
**ELF64 SysV standard** :
- DynSym (24 octets/entrée) : st_name u32, st_info u8, st_other u8,
  st_shndx u16, st_value u64, st_size u64.
- DynStr : table de chaînes C standard.
- Usage recomp : résoudre les imports entre modules (rtld/sdk/subsdk) et
  identifier les noms des saltos services (build_id / nsdk mappings).

## 6. Réallocations dynamiques

Format **ELF64 RELA** standard (24 octets/entrée) : `r_offset u64`,
`r_info u64` (sym<<32 | type), `r_addend u64` ; trouvées via la section
.dynamic pointée par `MOD0.DynamicOffset` (DT_RELA, DT_RELASZ…).
Types AArch64 livrés dans les binaires Switch (standard, à valider sur
un dump réel) : R_AARCH64_ABS64 (257), GLOB_DAT (1025), JUMP_SLOT (1026),
RELATIVE (1027), IRELATIVE (1032) ; des types nnsdk privés dans la plage
0x400+ sont possibles — à recenser empiriquement.
rtld applique chaque RELA au load-time ; IRELATIVE = trampes PLT/IFUNC.
Priorité v1 : RELATIVE + ABS64 + JUMP_SLOT.

## 7. LZ4 — segments NSO compressés

Format **bloc LZ4 standard** (identique à lz4.org ; Switch ne modifie rien) :
- Séquence = token octet : nibble haut = taille littéraux (15 → +octets 0xFF…),
  littéraux bruts ; ensuite offset little-endian 16 bits (0 = fin/erreur),
  puis nibble bas + 15 → taille match (min 4).
- Copie match : recopie octet à octet jusqu'à 64 Ko de fenêtre (un
  décompresseur naïf 1-octet est acceptable en v1).
- Fin de flux : la dernière séquence se termine tronquée (littéral final sans
  match). La taille décompressée étant connue (TextSize/RoSize/DataSize),
  on s'arrête dès qu'elle est atteinte.
- Vérification d'intégrité : si flag hash (bits 3-5), SHA-256 du résultat
  décompressé = NsoHeader hash correspondant.
- À venir : [22.0.0+] Zstd/Zbic (bit 7) — à étudier plus tard.
- **Statut** : implémenté dans `loader/nsw_formats.py::lz4_decompress_block`
  (stdlib pur, copie chevauchante, arrêt à la taille connue) + vérification
  SHA-256 ; validé contre python-lz4 (oracle dev, 28/28).

## 8. Glossaire pipeline recompiler

- Loader (`loader/nsw_formats.py`) : détecte NSO/NRO/PFS0 → décompresse LZ4 →
  concatène segments (text+rodata+data+bss) → Calcule l'image virtuelle.
- Cartographie exec : point d'entrée = start du .text de **rtld** (si présent)
  sinon main ; les autres modules base suivent (cf horizon.md §5).
- La traduction suit le .text par blocs + résolution des ADR/ADRP *dans
  l'image virtuelle reconstruite* (pas au fichier !).
