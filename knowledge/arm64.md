# ARM64 (AArch64) — SAVOIR PERSISTANT

Source de vérité : validé empiriquement contre capstone 5.0.7 (oracle de
référence uniquement — jamais une dépendance du code livré).

## 1. Registres

- `X0–X30` : registres généraux 64 bits. `W0–W30` = leurs moitiés basses 32 bits.
- Index 31 = `SP` ou `ZR` selon l'instruction :
  - ADD/SUB/SUBS immédiat : Rn=31, Rd=31 → **SP**.
  - ADD/SUB (registre, shifted/extended), logiques : index 31 → **XZR** (zéro).
- Alias compilateurs : X29 = FP (frame pointer), X30 = LR (link).
- Convention d'appel (Switch ABI) : X0–X7 args, X8 ret-struct, X30 LR,
  X29 FP, SP aligné 16 octets à l'appel.
- Registres `V0–V31` SIMD/FP (128 bits) — phase 2.

## 2. Format d'instruction : mot fixe 32 bits, little-endian en mémoire.

Longueur fixe : PC avance toujours de 4 octets.

## 3. Encodages implémentés dans `decoder/arm64.py` (validés)

| Famille | Bits fixes | Champs |
|---|---|---|
| ADD/SUB immédiat | 31=sf, 30=op(1=SUB), 29=S, 28–23=100010 | sh(23), imm12(21–10), Rn(9–5), Rd(4–0) |
| ADD/SUB shifted reg | 31=sf, 30=op, 29=S, 28–24=01011, **bit21=0** | shift(23–22), Rm(20–16), imm6(15–10), Rn(9–5), Rd(4–0) |
| ADD/SUB extended reg | 31=sf, 30=op, 29=S, 28–24=01011, **bit21=1**, 23–22=00 | Rm(20–16), option(15–13), imm3(12–10), Rn(9–5), Rd(4–0) |
| Logique shifted reg | 31=sf, 29–30=opc, 28–24=01010 | shift(23–22), N=bit21(BIC/ORN/EON/BICS), Rm(20–16), imm6(15–10), Rn(9–5), Rd(4–0) |
| MOV wide | 31=sf, 30–29=opc(00=N,10=Z,11=K), 28–23=100101 | **hw(22–21)**, imm16(20–5), Rd(4–0) |
| ADR/ADRP | 31=op(0=ADR,1=ADRP) | immlo(30–29), 28–24=10000, immhi(23–5), Rd(4–0) |
| CBZ/CBNZ | 31=sf, bit24=op(1=CBNZ), 0110100 | imm19(23–5), Rt(4–0) |
| B / BL | bits 31–26 = 000101(B) / 100101(BL) | imm26 → *(signed << 2)* |
| B.cond / BC.cond | bits 31–24 = 0x54 exact (bit4 : 0=B / 1=BC) | imm19(23–5), cond(3–0) |
| RET | mot ∨ (Rn<<5) == 0xD65F0000 | Rn(9–5) |
| LDR/STR unsigned | 29–27=111, 25–23=010, 26=V, 22=op(1=LDR) | size(31–30), imm12(21–10), Rn(9–5), Rt(4–0) |

### Gardes de validité (validées vs capstone)
- **ADD/SUB reg : bit21 = 0 → shifted, bit21 = 1 → extended** (l'ancienne
  heuristique « shift=00 && imm6≠0 ⇒ extended » était fausse : `ADD X0,X1,X2,
  LSL #3` a shift=00 et imm6=3).
  - shifted : LSL #0 valide (forme canonique) ; **ROR (shift=11) interdit** ;
    W : imm6 ≤ 31.
  - extended : bits 23–22 = 00 (tout autre opt est hors famille) ; imm3 ≤ 4 ;
    sf=0 → option ∉ {011=UXTX, 111=SXTX}.
- MOV wide : opc = 01 non alloué ; **W : hw = 0 seul** ; hw aux bits 22-21,
  imm16 aux bits 20–5 (pas 19-4).
- LDR/STR unsigned : exige bits 29–27 = 111, 25–23 = 010, bit26 = 0.
- immédiat logique 32 bits : N doit rester = 0.

### Drapeaux NZCV (ADD/SUB/S/logique-set)
Sémantique identique x86 : N=bit63(résultat), Z=zero, C=retenue (SUB :
`a >= b`), V=overflow signé. `set_flags_add/sub` en C++ généré.

### Aliases traités au décodage
- CMP Rn, X = SUBS XZR ; CMN = ADDS XZR ; TST = ANDS XZR (Rd implicite,
  **seulement ANDS N=0 & Rd=31**).
- **ANDS avec N=1 → BICS** (alias ARM, y compris Rd=31 : capstone imprime
  `bics xzr, …`, jamais `tstn`).
- MOV Xd, Xm = ORR Xd, XZR, Xm (LSL #0) ; MOV imm = ORR imm avec Rn=XZR ;
  MVN = ORN Rn=XZR ; NEG/NEGS = SUB/SUBS Rn=XZR — rendus **capstone**.
  Le décodeur garde les mnémoniques de base (SUB/SUBS/ORR/ORN) ; l'oracle de
  sweep normalise ces alias (`mov`↔{MOVZ,MOVN,ORR}, `neg(s)`↔SUB(S),
  `mvn`↔ORN).
- Capstone imprime `mov` pour MOVZ **et** MOVN (tout hw) ; MOVK reste `movk`.
- Conditions : noms canoniques **HS/LO** (pas CS/CC).
- B.cond bit4=1 → **BC.&lt;cond&gt;** (variante branch-consistent FEAT_HBC),
  bit4=0 → B.&lt;cond&gt;.

## 4. Immédiat logique — ALGORITHME VALIDÉ (remplace l'ancien TODO)

**11 328 encodages testés contre capstone → 0 mismatch.**

```
Champs : N = bit 22 ; immr = bits 21–16 ; imms = bits 15–10.
x      = (N << 6) | (~imms & 63)
invalide si x == 0, ou (sf == 0 et N == 1)
len    = index du bit le plus haut de x (bit_length()-1) ; invalide si len < 1
esize  = 1 << len ;  S = imms & (esize - 1) ;  R = immr & (esize - 1)
invalide si S == esize - 1 (motif tout-à-1)
motif  = ROR_fenêtre(ones(S+1), R, esize)   # rotation à droite DANS esize
valeur = motif répété sur TOUTE la largeur du registre (64 si sf=1, 32 si sf=0)
```

Ancres empiriques : `AND X0,X1,#0xF` ⇔ (N=1, imms=3, immr=0) ; 32 bits
⇔ (N=0, imms=3, immr=0) ; `#0xFF..` impossible pour X (assemblers utilisent
MOVZ/ORR) ; `#0x300000003` ⇔ (N=0, imms=1, immr=0).

## 5. Paires STP/LDP — VALIDÉ vs capstone (17 433 cas, 0 écart)

Encodage :
```
opc(31–30) | 101 | V(26) | 0 | mode(24–23) | L(22) | imm7(21–15) | Rt2(14–10) | Rn(9–5) | Rt(4–0)
```
- mode : **00 = STNP/LDNP** (no-allocate), **01 = post-index**, **10 = offset**,
  **11 = pre-index** ; V=1 → paires SIMD/FP (non prises).
- opc : 00 = 32 bits (W, ×4) ; 01 = **LDPSW** (dest X, ×4, L=1 uniquement,
  mode 00 interdit) ; 10 = 64 bits (X, ×8) ; 11 = non alloué (refusé).
- **STNP/LDNP impriment bien leur imm7×scale** (ce n'est pas un offset nul).
- Refus UNPREDICTABLE reproduits : `L=1 && Rt==Rt2` → unknown ;
  writeback (post/pre) avec `Rn!=31 && Rn∈{Rt,Rt2}` → unknown.
  **Rn=31 (SP) en writeback est légal.**
- Sémantique writeback : pré-index → adresse = base+imm puis base += imm ;
  post-index → accès à base puis base += imm.
- ABI Switch typique : `STP X29,X30,[SP,#-imm]!` / `LDP X29,X30,[SP],#imm`.

## 6. TBZ/TBNZ — VALIDÉ vs capstone (3 072 cas, 0 écart)

```
b5(31) | 011011 | op(24) | b40(23–19) | imm14(18–5) | Rt(4–0)
```
- op = 0 → TBZ (branche si bit=0) ; op = 1 → TBNZ (bit=1).
- bit testé = `(b5<<5)|b40` (0–63) ; cible = PC + sval(imm14)×4.
- Tête 32 bits : 0x36/0x37 (b5=0) ; 64 bits : 0xB6/0xB7 (b5=1).

## 7. LDUR/STUR (offset non-scalé, imm9) — VALIDÉ vs capstone (520 cas)

```
size(31–30) | 111 | 0 | grp(25–21) | 0 | imm9(20–12) | 00 | Rn(9–5) | Rt(4–0)
```
- grp : `00000` store, `00010` load, `00100` chargé signé dest X
  (LDURSB/H/SW ; size=11 = PRFUM → refusé), `00110` chargé signé dest W
  (LDURSB/LDURSH seuls ; size ≥ 2 refusé).
- imm9 **signé, SANS échelle** (contrairement à LDR/STR unsigned).
- **bits 11–10 doivent être 00** : post-index (01), pre-index (11) et
  registre étendu (10) sont d'autres familles (le dispatch les ignore).
- Têtes typiques : 0xF8… (store) / 0xF9… (load) — ne pas s'y fier, filtrer
  par grp + bits 11–10.

## 8. Barrières mémoire — VALIDÉ vs capstone (48 cas : fam. 4/5/6 × 16)

Motif : `(word & 0xFFFFF01F) == 0xD503301F` ⇒ `D503 3xxx 1F`.
CRm = bits 11–8 (domaine), op2 = bits 7–5 (famille), Rt = 11111.

| op2 | Instr | Traduction v1 |
|---|---|---|
| 100 | DSB | `std::atomic_thread_fence(seq_cst)` |
| 101 | DMB | idem |
| 110 | ISB | no-op (récompilation statique) |

- **Seules les familles 100/101/110 sont des barrières** : 001 = MSR/SPSel,
  010 = CLREX, 111 = SYS → hors barrières (laissés en inconnu).
- DSB + CRm spécial : `0x0 → SSBB`, `0x4 → PSSBB`, `0xC → DFB`.
- Domaines : F=SY, E=ST, D=LD, B=ISH, A=ISHST, 9=ISHLD, 7=NSH, 6=NSHST,
  5=NSHLD, 3=OSH, 2=OSHST, 1=OSHLD ; hors table → rendu `#n` (no-op).

## 9. SVC — appels superviseur Horizon

Encodage : `1101 0100 000 imm16 00001` ; garde `(word & 0xFFE0001F) == 0xD4000001`,
imm16 = bits 20–5. Rendu texte `SVC #0x1f` ; émission C++ `hle_svc(s, 0x1f);`
(x86-64 : note explicite, la résolution passe par le HLE).

| SVC | Nom | Entrées (ABI 64 bits) |
|---|---|---|
| 0x1F | ConnectToNamedPort | X0 = Handle* out, X1 = const char* name |
| 0x20 | SendSyncRequestLight | X0 = handle |
| 0x21 | SendSyncRequest | X0 = handle |
| 0x22 | SendSyncRequestWithUserBuffer | X0 = buffer, X1 = size, X2 = handle |
| 0x23 | SendAsyncRequestWithUserBuffer | X0 = event*, X1 = buffer, X2 = size, X3 = handle |
| 0x30 | GetResourceLimitLimitValue | X0 = int64* out, X1 = handle, X2 = LimitableResource |
| 0x31 | GetResourceLimitCurrentValue | idem |

- **0x21 = SendSyncRequest**, pas GetResourceLimit (SwitchBrew SVC). Les quotas
  sont 0x30/0x31 ; 0x37 = GetResourceLimitPeakValue.
- HLE actuel : 0x20–0x23 routés vers le MessageBuffer du TLR de test
  (0x22/0x23 devront lire leur buffer utilisateur plus tard) ; 0x30/0x31
  renvoient des quotas factices.

## 10. À implémenter ensuite

- MOV composé Z+K (chargement immédiat 64 bits en 2-4 instructions).
- MUL/SDIV/UDIV/CSEL/CSINC/BFI/BFM/EXTR/MRS/MSR.
- NEON (V0–V31) — phase 2.
- HLE : MRS/MSR TPIDR_EL0/TPIDRRO_EL0 (TLS réelle), GetInfo (0x29),
  WaitSynchronization (0x18), CloseHandle (0x16), threads/futex.
