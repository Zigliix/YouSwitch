# HORIZON OS — SAVOIR PERSISTANT

Source : SwitchBrew (pages `SVC`, `Memory layout`, rev. 2024-2026). Fiche consolidée
pour les stubs HLE du recompilateur. Toute valeur non confirmée sur le wiki est
marquée « à calibrer ».

## 1. Modèle d'exécution

- Un jeu = **processus userland ARM64** (A64) ; le kernel expose ~0x80 syscalls
  (`SVC #num`). Appels en X0–X7, résultat (Result u32) en W0.
- IPC : le jeu se connecte aux **ports nommés** (`sm:`, `hid`, `vi`, …) via
  `ConnectToNamedPort` puis envoie des messages IPC écrits **directement dans le
  bloc TLS** du thread (`SendSyncRequest`).
- Threads : `CreateThread(out, func, arg, stack_bottom, prio, core)` →
  `StartThread`. **Thread Local Region (TLR) de 0x200 octets par thread**, dont
  la base vient de **TPIDRRO_EL0** (lecture seule) ; les TLRs partagent la page
  0x1000 (TLR #0 = contexte d'exception, TLR usuelle à page+0x200). En plus
  nnsdk assigne **TPIDR_EL0 au ThreadPointer** (OsResourceManager global) —
  notre émetteur doit traduire `MRS/MSR TPIDR_EL0` et `MRS TPIDRRO_EL0` en
  lecture/écriture de variables CPUState (priorité haute).
- `Result` = u32, bit `module` (bits 25-21) + `description` (20-0) ; 0 = succès.

## 2. Table SVC consolidée (SwitchBrew, ids exacts)

| Id | Nom | Signature (simplifiée) | Stub HLE proposé (Windows) |
|---|---|---|---|
| 0x01 | SetHeapSize | (out addr\*, size) | réservation heap du HLE (size multiple de 0x200000) |
| 0x02 | SetMemoryPermission | addr, size, perm | no-op / VirtualProtect |
| 0x03 | SetMemoryAttribute | addr, size, mask, attr | no-op (attrs cache) |
| 0x04 | MapMemory | dst, src, size | miroir de pages (heap→alias) dans la vm HLE |
| 0x05 | UnmapMemory | dst, src, size | inverse |
| 0x06 | QueryMemory | out info\*, addr | table de régions virtuelles HLE |
| 0x07 | ExitProcess | (void) | fin du jeu (ExitProcess) |
| 0x08 | CreateThread | (out\*, func, arg, stack_bottom, prio, core) | _beginthreadex ; le stack_bottom du jeu sert au rebase |
| 0x09 | StartThread | handle | le threadCreated démarre à start |
| 0x0A | ExitThread | (void) | _endthreadex |
| 0x0B | SleepThread | ns | sleep_until_timeout(ns) |
| 0x0C/0x0D | Get/SetThreadPriority | handle[, prio] | map 0–63 → Windows (détail à calibrer) |
| 0x0E/0x0F | Get/SetThreadCoreMask | handle[, core, mask] | no-op renvoyant 0b0000/S2 « multicoeur logique » |
| 0x10 | GetCurrentProcessorNumber | (void) | GetCurrentProcessorNumber() |
| 0x11/0x12 | SignalEvent/ClearEvent | handle | SetEvent/ResetEvent |
| 0x13/0x14 | Map/UnmapSharedMemory | handle, addr, size, perm | Viewfile miroir (CreateMappingView) |
| 0x15 | CreateTransferMemory | (out, addr, size, perm) | mémoire userland figée |
| 0x16 | CloseHandle | handle | CloseHandle/RC |
| 0x17 | ResetSignal | handle | WaitForSingleObject(timeout 0) |
| 0x18 | WaitSynchronization | handles\*, n, ns | WaitForMultipleObjects |
| 0x19 | CancelSynchronization | handle | no-op |
| 0x1A/0x1B | ArbitrateLock/Unlock | (handle, addr, tag) / (addr) | futex-impl (section 6) |
| 0x1C | WaitProcessWideKeyAtomic | addr, cv_key, tag, ns | CONDITION_VARIABLE-style |
| 0x1D | SignalProcessWideKey | cv_key, count | WakeConditionVariable(count) |
| 0x1E | GetSystemTick | (void)→X0 | compteur système (QPC ; fréq à calibrer, voir §7) |
| 0x1F | ConnectToNamedPort | (out\*, name) | résolution service HLE par nom |
| 0x20–0x23 | SendSyncRequest(Light/Buffer…) | handle\[, buf, size\] | dispatcher IPC → services (services.md) |
| 0x24/0x25 | GetProcessId/GetThreadId | (out\*, handle) | id HLE |
| 0x26 | Break | reason, arg, size | crash handler dédié |
| 0x27 | OutputDebugString | str, len | OutputDebugStringA / log |
| 0x28 | ReturnFromException | result | no-op HLE (crash → exit) |
| 0x29 | GetInfo | (out\*, type, handle, sub) | table des régions (§5) |
| 0x2A/0x2B | FlushEntireDataCache / FlushDataCache | addr, size | no-op (mémoire HLE unifiée) |
| 0x2C/0x2D | Map/UnmapPhysicalMemory | addr, size | hors jeu réel (applets) → stub fail |
| 0x2E/0x2F | GetDebugFutureThreadInfo / GetLastThreadInfo | ctx\* … | debug stubs |
| 0x30/0x31 | GetResourceLimit(Limit/Current)Value | (out\*, handle, which) | quotas fake |
| 0x32 | SetThreadActivity | handle, activity | no-op |
| 0x33 | GetThreadContext3 | (ctx\*, handle) | CPUState dump |
| 0x34 | WaitForAddress | addr, arbType, value, ns | futex-impl |
| 0x35 | SignalToAddress | addr, sigType, value, count | futex-impl |
| 0x36 | SynchronizePreemptionState | (void) | no-op |
| 0x37 | GetResourceLimitPeakValue | (out\*, handle, which) | quota fake |
| 0x39/0x3A | CreateIoPool/CreateIoRegion | … | stub fail (homebrew seulement) |
| 0x3C/0x3D | KernelDebug / ChangeKernelTraceState | — | stub fail (retail) |
| 0x40 | CreateSession | (outSrv\*, outCli\*, isLight, name) | sessions internes HLE |
| 0x41 | AcceptSession | (out\*, port) | idem |
| 0x42/0x43/0x44 | ReplyAndReceive(Light/WithUserBuffer) | (outIndex, handles\*, n, replyTarget, ns) | dispatcher IPC |
| 0x45 | CreateEvent | (outW\*, outR\*) | SetEvent pair |
| 0x46–0x4A | Map/UnmapIoRegion, PhysicalMemoryUnsafe, SetUnsafeLimit | — | stub fail |
| 0x4B/0x4C | CreateCodeMemory / ControlCodeMemory | (handle, op, addr, size, perm) | VirtualProtect (JIT des jeux !) |
| 0x4D | SleepSystem | (void) | no-op |
| 0x4E | ReadWriteRegister | … | fail hors matériel |
| 0x4F | SetProcessActivity | handle, activity | no-op |
| 0x50 | CreateSharedMemory | (out\*, size, ownerPerm, remotePerm) | heap partagé |
| 0x51/0x52 | Map/UnmapTransferMemory | handle, addr, size | idem |
| 0x53 | CreateInterruptEvent | … | stub fail |
| 0x54 | QueryPhysicalAddress | … | fail |
| 0x55 | QueryMemoryMapping/Q…IoMapping | … | fail |
| 0x56–0x5C | DeviceAddressSpace (create/attach/map/unmap…) | — | id pas de GPU physique ; rédirigé NVN |
| 0x5D–0x5F | Invalidate/Store/FlushProcessDataCache | handle, addr, size | no-op |
| 0x60–0x6D | Debug\* (DebugActiveProcess, GetDebugEvent, …) | — | debug stubs (partiel) |
| 0x6F | GetSystemInfo | (out\*, type, handle, sub) | mémoire physique (§Tableau SystemInfoType) |
| 0x70/0x71/0x72 | CreatePort / ManageNamedPort / ConnectToPort | (out\*[, name], …) | ports IPC HLE |
| 0x73 | SetProcessMemoryPermission | handle, addr, size, perm | VirtualProtect |
| 0x74/0x75 | Map/UnmapProcessMemory | dst, handle, src, size | no-op (1 process) |
| 0x76 | QueryProcessMemory | (info\*, page\*, handle, addr) | vm HLE |
| 0x77/0x78 | Map/UnmapProcessCodeMemory | handle, dst, src, size | loader des titres (pas du jeu lui-même) |
| 0x79–0x7B | CreateProcess / StartProcess / TerminateProcess | … | stub (le jeu NE crée de process) |
| 0x7C | GetProcessInfo | (out\*, handle, type) | id/stats |
| 0x7D | CreateResourceLimit | out\* | handle fake |
| 0x7E | SetResourceLimitLimitValue | handle, which, v | fake |
| 0x7F | CallSecureMonitor | args\* | fail (réservé TZ) |
| 0x80–0x82 | SetGpuMemoryAttribute / Lock/UnlockGpuSharableMemory | — | [S2] fail v1 |
| 0x90/0x91 | Map/UnmapInsecurePhysicalMemory | addr, size | [15.0.0+] fail v1 |

Signatures détaillées utiles (wiki) :
- `SetHeapSize(out_addr\*, size)` : size **multiple de 0x200000 (2 Mo)**.
- `MapMemory(dst, src, size)` : rouge « alias » du heap.
- `CreateThread(out\*, func, arg, stack_bottom, prio, core)`.
- `WaitSynchronization(handles\*, n, timeout_ns)`.
- `ArbitrateLock(handle, addr, tag)` ; `SignalToAddress(addr, type, value, count)`.
- `GetInfo(out\*, type, handle, sub)` — résultats 64 bits en X1.
- `WaitForAddress(addr, type, value, timeout_ns)` / `SignalToAddress`.
- `GetThreadContext3(ctx\*, thread_handle)` ; flags dans `ThreadContextFlags`.

## 3. Threads & TLR (TPIDRRO_EL0 / TPIDR_EL0)

- **TLR (Thread Local Region) : 0x200 octets par thread** ; base lisible via
  **TPIDRRO_EL0** (read-only userland). Les TLRs sont stockées dans la même
  page 0x1000, la première (page+0x0) est **réservée à l'exception
  userland**, les suivantes à page+0x200×k.
- TLR contents (nn::svc::ThreadLocalRegion) : 0x0 **MessageBuffer** (0x100,
  buffer IPC des services), 0x100 [8+] DisableCounter u16 / 0x102
  InterruptFlag (→ SynchronizePreemptionState), 0x180 Tls 0x50, 0x1D0
  LocalePtr, 0x1D8 ErrnoVal, 0x1F0 **ThreadPointer**, 0x1F8 ThreadType ptr —
  détail dans `services.md` §11.
- **TPIDR_EL0** = ThreadPointer nnsdk = adresse de l'OsResourceManager (état
  global du processus, utilisé en permanence : TickManager, threads, slots TLS).
  `MRS X0, TPIDR_EL0` ↔ nuestras variables CPUState (cpu.thread_pointer).
- Priorité d'implémentation **haute** (accessible dans n'importe quel lock).
- Cas d'exception (UserExceptionContext @ TLS 0, cf GetInfo 20) :
  | Off. | Long. | Contenu |
  |---|---|---|
  | 0x0   | 0x148 | exception stack |
  | 0x148 | 0x78 (A64) | ExceptionFrameA64 |
  | 0x1C0 | 0x8 | DyingMessage addr |
  | 0x1C8 | 0x8 | DyingMessage size |

  ExceptionFrameA64 : 0x0 GPRs 0..8 (8×9), 0x48 lr, 0x50 sp, 0x58 pc (elr_el1),
  0x60 pstate&0xFF0FFE20, 0x64 afsr0, 0x68 afsr1, 0x6C esr, 0x70 far.
  Le retour crt0 reçoit `X0=code` (0x100 inst abort, 0x301 bad SVC, …),
  `X1=SP=frame=stack top`.

## 4. GetInfo / GetSystemInfo (régions)

| InfoType | Signification |
|---|---|
| 0/1 | CoreMask / PriorityMask du process |
| 2/3 | **AliasRegionAddress/Size** (miroirs heap, MapMemory) |
| 4/5 | **HeapRegionAddress/Size** (SetHeapSize) |
| 6/7 | Total/UsedMemorySize (codebin+stack+heap) |
| 8/9 | DebuggerAttached / ResourceLimit |
| 10 | IdleTickCount (sub = core) |
| 11 | RandomEntropy (seed PRNG userland) |
| 12/13 | AslrRegionAddress/Size |
| 14/15 | **StackRegionAddress/Size** |
| 16/17 | SystemResourceSize Total/Used |
| 18 | ProgramId |
| 20 | UserExceptionContextAddress |
| 21/22 | Total/UsedNonSystemMemorySize |
| 23 | IsApplication |
| 25 | ThreadTickCount (sub 0-3, -1) |
| 36/38 | AddressSpaceSize / ShadowStackRegion (23.0.0+, S2) |

GetSystemInfo : 0/1 = Total/UsedPhysicalMemorySize (sub 0=Application,
1=Applet, 2=System, 3=SystemUnsafe) ; 2 = InitialProcessIdRange.

## 5. Carte mémoire processus (Memory layout)

- Espace virtuel userland **32 / 36 / [2.0.0+] 38 bits**.
- Régions randomisées et imposées par le kernel, chacune **alignée 2 Mo** :
  `ReservedHeapRegion`, `ReservedMapRegion`, [2.0.0+] `NewReservedMapRegion`,
  `TlsIoRegion` (non exposée userspace). Adresses obtenues via GetInfo (2-15).
- Binaire principal placé à l'adresse fournie par Loader ; aléa sur les bits
  **37–21** (2.0.0+) ; sur 1.0.0 32 bits de moins de random.
- NRO (mappés par RO) : base entièrement aléatoire, alignée **4 K** (bits 37-12).
- Pour tous les binaires : **R-- juste après R-X ; RW- juste après R--**
  (pas de guard-pages entre sections).
- Empilement ExeFS : `rtld` → `main` → `subsdk\*` → `sdk`.
- Stack : userland randomise un **offset de page** dans la région StackRegion
  (GetInfo 14/15) ; entropie supplémentaire.
- ASLR 1.0.0 (pseudocode wiki) :
  - type 2 : base 0x80000000, random max 0x6400 (« 36-bit ») ;
    sinon base 0x40000000 random max 0x200 (« 32-bit »).
  - MapRegionSize 0x40000000 & HeapRegionSize 0x40000000
    (type 4 : Map=0, Heap=0x80000000).
  - `MapBase = Base + min(rnd0,rnd1)` ;
    `HeapBase = MapBase + MapRegionSize + max(rnd0,rnd1) - min(rnd0,rnd1)`
    (rnd n = random & RandomMax << 21).
- Lecture recompilation : nos stubs HLE reproduisent une carte *évidente* dans
  la vm x64 du jeu (rebase des pointeurs via les bases GetInfo) — le jeu ne
  repose PAS sur les adresses absolues réelles (bases toujours via GetInfo), ce
  qui nous autorise un rebasePath arbitrable.

## 6. Synchronisation (sémantique futex Switch)

- `WaitForAddress(addr, type∈{0 WaitIfLessThan, 1 DecrementAndWaitIfLessThan,
  2 WaitIfEqual}, value, ns)` ↔ attente conditionnelle atomique.
- `SignalToAddress(addr, type∈{0 Signal, 1 SignalAndIncrementIfEqual,
  2 SignalAndModifyByWaitingThreadCountIfEqual}, value, count)`.
- Mutex : `ArbitrateLock(handle, addr, tag)` (resume si tag=0 ; CAS vers tag)
  / `ArbitrateUnlock(addr)` (CAS vers 0, réveille un waiter).
- CondVAR : `WaitProcessWideKeyAtomic(addr, cv_key, tag, ns)` /
  `SignalProcessWideKey(cv_key, count)`.
- Implémentation Windows cible : table de futex maison (hash addr →
  {waiters, count}) + SRWLOCK/CONDITION_VARIABLE ; ordre de réveil à mesurer
  (Le binary Switch attend FIFO/LIFO : à calibrer avec les tests nn::os).

## 7. Temps

- `GetSystemTick` : compteur 64 bits système (cnvct_el0) ; fréquence système
  réelle non renseignée sur la page SVC — **à calibrer** (documents Ryujinx :
  614,4 MHz de horloge système ; userland fréq. = valeur lue via CNTFRQ_ELO).
  Stub QPC mappé avec la même unité de temps — les jeux en dérivent les secondes.
- `SleepThread(ns)` ; `timeout_ns` des primitives ↑ sleep_conditionnel.

## 8. Priorités d'implémentation v1 (stubs HLE)

1. `GetSystemTick`, `SleepThread` (timing sous-jacent à tout titre).
2. `GetInfo` (4/5, 11, 14/15, 18…) : les jeux paramètrent l'allocateur.
3. `SetHeapSize` + MapMemory/QueryMemory : gestion heap.
4. `WaitSynchronization` / `DisconnectWait`.
5. `ConnectToNamedPort("sm:")` + SendSyncRequest : entrée IPC services.
6. TLS (TPIDR_EL0 dans CPUState) : lecture MRS/MSR obligatoire.
7. futex (§6) : d'abord mutex propre, puis condVAR.
