# Rapport SwitchRecomp — e2e_switchrecomp

```
Format: NSO  (290 octets)
build_id: 59f5e9ee037f047aceb8c3c1ba7062a8f9311246704d66841262c58bda5cfceb
Segments:
  .text    file @0x100 -> mem @0x0 (32 octets) [LZ4->décompressé]
[note] Segments LZ4 décompressés.
```

## Couverture de décodage

| Mnémonique | Occurrences |
|---|---|
| STP | 1 |
| MOVZ | 1 |
| ADD | 1 |
| LDUR | 1 |
| DMB | 1 |
| TBZ | 1 |
| LDP | 1 |
| RET | 1 |

Total : 8 instructions, 0 inconnues.

## Mapping registres ARM64 -> x86-64

| Registre ARM | Registre x64 |
|---|---|
| X0 | RAX |
| X1 | RCX |
| X2 | RDX |
| X3 | RBX |
| X4 | RSI |
| X5 | RDI |
| X6 | R8 |
| X7 | R9 |
| X8 | R10 |
| X9 | R11 |
| X10 | R12 |
| X11 | R13 |
| X12 | R14 |
| X13 | R15 |

X14 et au-delà : spill en mémoire (emitter v1).

