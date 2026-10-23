# SERVICES HORIZON (IPC) — SAVOIR PERSISTANT

Source : SwitchBrew (pages `HID_services`, `Display_services`, `PSC_services`,
`Applet_Manager_services`, rev. 2025-2026). Chaque entrée = service réel du
système Horizon + stub HLE Windows correspondant de notre runtime.
`Result` = u32 (cf `horizon.md` §1). Dates fw entre crochets [x.y.z+].

## 0. Modèle IPC & stratégie de stubs HLE

- Le jeu se connecte à un **port nommé** (`svcConnectToNamedPort`) : `sm:`,
  `hid`, `vi:u`, `appletOE`, `glue time:u` (ou `time:u` direct < [9.0.0+])… puis
  envoie des requêtes via `svcSendSyncRequest` : le message IPC est écrit
  **directement dans le bloc TLS** du thread (cf `horizon.md` §3), réponse
  écrite par le serveur dans le même buffer.
- Notre runtime HLE : `ConnectToNamedPort(nom)` → handle d'une session factice ;
  `SendSyncRequest` → parse le message TLS → dispatcher par (service, cmd id) →
  handler → éventuels out-params + `Result`=0. Fiche marshalling brut → §9
  (à capter : page `IPC_Marshalling` + `SM`).
- Kinds de handlers : (a) retour `Result` seul, (b) out-values scalaires/wxsd
  structs, (c) retour handle d'événement (événement Windows miroir), (d)
  no-op/absorbé, (e) fail (error) — v1 : jamais de crash silencieux, log + Result.

## 1. sm: (résolution des ports)

- `sm:` = gestionnaire de services. Le jeu appelle `sm:` `GetService("nom")` /
  `RegisterService`. Fiche SM à capter (page wiki `SM`). Stub v1 : retourner un
  handle pré-régistré pour chaque service implémenté (table en §5/§8) ; pour un
  nom inconnu → log + Result d'erreur explicite.

## 2. hid — entrées

Port `"hid"` → **IHidServer**. Les ports `hid:dbg`/`hid:sys` (menus système) ne
sont pas requis pour les jeux.

### 2.1 Flux type d'un jeu

1. IHidServer `CreateAppletResource` (cmd 0) → IAppletResource
   ; IAppletResource cmd 0 `GetSharedMemoryHandle` →
   `svcMapSharedMemory` de **0x40000 octets** (lecture seule, segment partagé).
2. Config Npad : `SetSupportedNpadStyleSet` (100), `SetSupportedNpadIdType`
   (102), `ActivateNpadWithRevision` (109, [5.0.0+] ; sinon `ActivateNpad` 103),
   `AcquireNpadStyleSetUpdateEventHandle` (106).
3. Optionnel : `ActivateTouchScreen` (11), `ActivateKeyboard` (31),
   `ActivateMouse` (21), `ActivateDebugPad` (1), `ActivateGesture` (91).
4. Le jeu lit les états **directement dans la mémoire partagée** (lifos) — pas
   d'IPC par frame. Vibration via `SendVibrationValue` (201) /
   `SendVibrationValues` (206).

### 2.2 Table IHidServer (extraits vérifiés)

| Cmd | Nom |
|---|---|
| 0 | CreateAppletResource |
| 1 / 11 / 21 / 31 | ActivateDebugPad / TouchScreen / Mouse / Keyboard |
| 22 | [19.0.0-22.5.0] AddMouseWheelDelta |
| 51 | ActivateXpad |
| 60-65 | [1.0.0-22.5.0] six-axis (Activate/Deactivate/LifoHandle/…) |
| 66-89 | six-axis fusion/callibration/params (66 Start, 73 SetAccel params, 79 GyroZeroDriftMode…) |
| 91 | ActivateGesture |
| 100/101 | Set/GetSupportedNpadStyleSet |
| 102 | SetSupportedNpadIdType |
| 103/104 | Activate/DeactivateNpad |
| 106 | AcquireNpadStyleSetUpdateEventHandle |
| 107/108 | DisconnectNpad / GetPlayerLedPattern |
| 109 | [5.0.0+] ActivateNpadWithRevision |
| 120-134 | NpadJoyHoldType (120/121), assignment (122-125, 133), LrAssignment (126/127), HandheldActivation (128/129), swap (130), home protection (131/132), [6.1+] stick clamp (134) |
| 135/136 | [8.0.0+] Set/ClearNpadCaptureButtonAssignment |
| 200-212 | vibration : 200 GetVibrationDeviceInfo, 201 SendVibrationValue, 202 GetActualVibrationValue, 203 CreateActiveVibrationDeviceList, 204/205 Permit/IsVibrationPermitted, 206 SendVibrationValues, 209/210 [4+] Begin/EndPermitVibrationSession, 211 [7+] IsVibrationDeviceMounted |
| 300-303 | [3.0.0+] Console/SevenSixAxisSensor (Activate/Start) |
| 403-407 | [4+] battery/InterfaceType infos |

### 2.3 SharedMemoryFormat (0x40000 octets)

| Offset | Taille | Segment |
|---|---|---|
| 0x0 | 0x400 | DebugPad |
| 0x400 | 0x3000 | TouchScreen |
| 0x3400 | 0x400 | Mouse |
| 0x3800 | 0x400 | Keyboard |
| 0x3C00 | 0x1000 | Digitizer ([1.0.0-9.2.0] BasicXpad) |
| 0x4C00 / 0x4E00 / 0x5000 | 0x200 ×3 | HomeButton / SleepButton / CaptureButton |
| 0x5200 | 0x800 | InputDetector |
| 0x5A00 | (0x4000) | UniquePad [1.0.0-4.1.0] |
| 0x9A00 | 0x32000 | **Npad** (ci-dessous) |
| 0x3BA00 | — | Gesture |
| 0x3C200 | — | [5.0.0+] ConsoleSixAxisSensor |
| 0x3DC00 | — | [16.0.0+] DebugMouse |

### 2.4 Motif RingLifo (tous les segments)

```
RingLifo : { RingLifoVptr u64, BufferCount u64, Tail u64, Count u64,
             AtomicStorage[17] }
AtomicStorage : { SamplingNumber u64, State }
```

- Le producteur (sysmodule → chez nous le runtime) pousse l'état courant à
  `Tail` (index cyclique), `Count` saturé (max 17) ; le jeu lit l'état le plus
  récent (entrée `Tail-1` ou scan par SamplingNumber max).
- Chez nous : le poll Windows (60 Hz par défaut) pousse à chaque frame un état
  `SamplingNumber` monotone.

Tailles vérifiées : DebugPadLifo **0x2C8** (State 0x20), TouchScreenLifo
**0x2C38** (TouchScreenState 0x290 : SamplingNumber u64, Count s32, Res u32,
Touches[16] de 0x28), MouseLifo **0x350** (MouseState 0x28 : X/Y/DeltaX/DeltaY/
DeltaWheelX/DeltaWheelY s32 + Buttons/Attributes u32), lifos Npad **0x350**
(NpadState 0x28).

### 2.5 NpadSharedMemoryFormat @0x9A00

- **NpadSharedMemoryFormat = 10 × 0x5000 octets** : entries 0-7 = joueurs 1-8,
  entry 8 = Handheld, entry 9 = Other.
- Entry = **NpadInternalState** (0x43F8 [13.0.0+] ; 0x43F0 [9.0.0-12.1.0] ;
  0x4410 [1.0.0-8.1.0]).

NpadInternalState (partie vérifiée) :

| Offset | Champ |
|---|---|
| 0x0 | StyleSet u32 (NpadStyleTag) |
| 0x4 | JoyAssignmentMode u32 |
| 0x8 / 0x14 | FullKeyColor (0xC) / JoyColor (0x14) |
| 0x28 / 0x378 / 0x6C8 / 0xA18 / 0xD68 | Lifos **0x350** : FullKey / Handheld / JoyDual / JoyLeft / JoyRight |
| 0x10B8 / 0x1408 | PalmaLifo / SystemExtLifo (0x350) |
| 0x1758+ | lifos six-axes 0x708 (nombre/positions exactes à re-calibrer sur dump) |
| 0x4228 | GcTriggerLifo 0x1B8 (à re-vérifier) |
| fin | battery/AppletFooter fields — à documenter au moment du portage |

### 2.6 NpadFullKeyState & boutons & styles

`NpadFullKeyState` = 0x28 : `SamplingNumber u64`, `Buttons NpadButtonSet u64`,
`AnalogStickL` 8 (X s32, Y s32, plage ±0x8000 signés), `AnalogStickR` 8,
`Attributes u32`, `Reserved u32`.

**NpadButton (u64) — carte des bits** :

| Bits | Boutons |
|---|---|
| 0/1/2/3 | A / B / X / Y |
| 4/5 | StickL (clic) / StickR (clic) |
| 6/7/8/9 | L / R / ZL / ZR |
| 10/11 | Plus / Minus |
| 12/13/14/15 | D-pad Left / Up / Right / Down |
| 16-19 / 20-23 | StickL Left/Up/Right/Down / StickR idem |
| 24/25 | LeftSL / LeftSR |
| 26/27 | RightSL / RightSR |
| 28 | Palma |
| 29 | Verification |
| 30 | HandheldLeftB |
| 31-34 | [12.0.0+] C-buttons N64 (Left/Up/Right/Down C) |
| 35-63 | réservés |

`NpadStyleTag` (u32) : bit0 FullKey (Pro), 1 Handheld, 2 JoyDual, 3 JoyLeft,
4 JoyRight, 5 Gc, 6 Palma, 7/8 Lark (NES — bit 8 à préciser), 9 Lucia (SNES),
10 Lagon (N64), 11 Lager (Genesis), 29 SystemExt, 30 System.

### 2.7 Mapping Windows (stub)

- Gamepad : poll **XInput/XUSER_MAX_COUNT 4** → entry 0 (FullKey) + entry 8
  (Handheld). A/X/B/Y → bits 0/2/1/3, LB/RB → 6/7, LT/RT → 8/9, Start/Select →
  10/11, D-pad → 12-15, stick clics → 4/5.
- Clavier/souris : fenêtre (WM_KEY* + GetAsyncKeyState / raw input) → Keyboard
  lifo + Mouse lifo ; souris → éventuellement TouchState (souris = doigt).
- Vibration 201/206 → `XINPUT SetState` (rumble).

## 3. vi — affichage

Ports : `vi:u` (jeu) / `vi:s` / `vi:m`.
- vi:u (IApplicationRootService) : cmd **0 GetDisplayService** →
  IApplicationDisplayService ; cmd **1** [9.0.0+]
  `GetDisplayServiceWithProxyNameExchange` (in u32 : 0 = vi:u, 1 = vi:s/vi:m).
- vi:s (ISystemRootService) : cmds **1** / **3**. vi:m (IManagerRootService) :
  **2** / **3**, [16+] 100-103 fatal.

### 3.1 IApplicationDisplayService (verbatim)

| Cmd | Nom |
|---|---|
| 100 | GetRelayService → IHOSBinderDriver "dispdrv" (Nvnflinger) |
| 101 | GetSystemDisplayService |
| 102 | GetManagerDisplayService (vi:m seulement) |
| 103 | [2.0.0+] GetIndirectDisplayTransactionService |
| 1000 | ListDisplays (DisplayInfo 0x60, cf §3.4) |
| 1010 / 1011 | OpenDisplay ("Default") / OpenDefaultDisplay → DisplayId |
| 1020 | CloseDisplay |
| 1101 / 1102 | SetDisplayEnabled / GetDisplayResolution (w+s64, h+s64) |
| 2020 / 2021 | OpenLayer / CloseLayer |
| 2030 / 2031 | CreateStrayLayer / DestroyStrayLayer |
| 2101 / 2102 | SetLayerScalingMode / [5.0.0+] ConvertScalingMode |
| 2450-2460 | indirect layer image maps |
| **5202** | **GetDisplayVsyncEvent → événement** |

Erreur 0xA72 si cmd non disponible pour la session ; cmds à AppletResourceUserId
doivent matcher le PID (0 refusé).

### 3.2 OpenLayer (flux jeu réel)

- profil jeu : ISelfController `CreateManagedDisplayLayer` (cmd 40,
  `appletABI`) → LayerId → vi `OpenLayer` → **NativeWindow** (Parcel) dans un
  out-buffer 0x100 → le jeu passe ce NativeWindow à NVN (surfaces).
- Sinon : AppletResourceUserId==0 → `CreateStrayLayer` (2030) à la place.

### 3.3 ISystemDisplayService (cmds clés)

1203 GetDisplayLogicalResolution ; 2201 SetLayerPosition ; 2203 SetLayerSize ;
2204/2205 Get/SetLayerZ ; 2207 SetLayerVisibility ; 2209 SetLayerAlpha ;
3200/3201 Get/SetDisplayMode ; 8225 [4+] GetSharedBufferMemoryHandleId ;
8250 OpenSharedLayer ; 8254/8255 [4+] Acquire/PresentSharedFrameBuffer ;
8256 GetSharedFrameBufferAcquirableEvent ; 8257 FillSharedFrameBufferColor.

### 3.4 DisplayInfo (0x60) & Parcel/NativeWindow

- `DisplayInfo` 0x60 : Name 0x40, HasLayerLimit 1 + 7 res, LayerCountMax 8,
  LayerWidthPixelCountMax 8, LayerHeightPixelCountMax 8. "Default" = **1080p**
  même en handheld.
- **DisplayName** 0x40 NUL : "Default", "External", "Edid", "Internal", "Null".
- **NativeWindow** = **Parcel** (buffer ≤ 0x100) :
  | Off. | Champ |
  |---|---|
  | 0x0 / 0x4 / 0x8 / 0xC | ParcelDataSize / ParcelDataOffset / ParcelObjectsSize / ParcelObjectsOffset (u32 ×4) |
  | 0x10 | FlattenedBinder |
  ParcelData : @0 u32 = 2 ; @4 probable PID ; @8 **ID** (id binder → utilisé par
  les cmds binder de IHOSBinderDriver) ; @0x18 "dispdrv" (NUL-terminated) ;
  ParcelObjects = u32 0. Détail complet à re-capter au passage NVN (relay).

### 3.5 Mapping Windows

- Fenêtre + swapchain affine (framebuffer du jeu × layer). `GetDisplayVsyncEvent`
  = **événement Windows** signalé chaque présent de frame (60 Hz par défaut).
- `GetDisplayResolution` / `GetDefaultDisplayResolution` (@ appletABI 60) suivent
  la fenêtre (ou 1280×720 / 1920×1080 par défaut dock).

## 4. nvnflinger / nvdrv (rendu NVN) — phase dédiée

- Le relay "dispdrv" (§3.1 cmd 100) = IHOSBinderDriver de Nvnflinger ; le
  compositor nvnflinger flippe les layer frames vers l'écran.
- **Pas encore extrait** : pages `Nvnflinger_services`, `NVN` (API graphique jde
  Nintendo), `nvdrv` (commands GPU). Phase séparée : HLE graphique v2
  (traduction nvn→D3D12). En v1 : layer + vsync stub (§3.5) suffisent pour les
  vertical-slices sans rendu.

## 5. temps (time:u / time:su / time:s)

[9.0.0+] : `time:u/a/r` = services glue qui renvoient un **IStaticService**
obtenu via `time:m` (ITimeServiceManager : cmds 0/5/6/9 GetStaticServiceAs…).
< [9.0.0+] : `time:u`/`time:a`/`time:s` directs. Chez nous : enregistrer
`time:u` = IStaticService directement.

### 5.1 IStaticService (time:su / time:s) — verbatim

| Cmd | Nom |
|---|---|
| 0 / 1 | GetStandardUserSystemClock / GetStandardNetworkSystemClock → ISystemClock |
| 2 | GetStandardSteadyClock → ISteadyClock |
| 3 | GetTimeZoneService → ITimeZoneService |
| 4 / 5 | GetStandardLocalSystemClock / [4.0.0+] GetEphemeralNetworkSystemClock |
| 20 | [6.0.0+] GetSharedMemoryNativeHandle |
| 50/51 | [4+] SetStandardSteadyClockInternalOffset / [9+] GetStandardSteadyClockRtcValue |
| 100/101/102 | auto-correction us (Is/Set/InitialYear [5+] ) |
| 200/201 | [3+] IsStandardNetwork…Sufficient / [6+] …AutomaticCorrectionUpdatedTime |
| 300 | [4+] CalculateMonotonicSystemClockBaseTimePoint |
| 400 / 401 | [4+] GetClockSnapshot / GetClockSnapshotFromSystemClockContext |
| 500 / 501 | [4+] CalculateStandardUserSystemClockDifferenceByUser / CalculateSpanBetween |

### 5.2 ISystemClock (verbatim)

| Cmd | Nom |
|---|---|
| 0 | GetCurrentTime → **PosixTime s64 (UTC)** |
| 1 | SetCurrentTime (PosixTime) |
| 2 | GetSystemClockContext → SystemClockContext (0x20) |
| 3 | SetSystemClockContext |
| 4 | [9.0.0+] GetOperationEventReadableHandle |

### 5.3 ISteadyClock (verbatim)

0 GetCurrentTimePoint → **SteadyClockTimePoint** ; 2/3 Get/SetTestOffset
(TimeSpanType s64) ; 100 [2+] GetRtcValue ; 101/102 [2+] IsRtcResetDetected /
GetSetupResultValue ; 200 [3+] GetInternalOffset (TimeSpanType).

### 5.4 ITimeZoneService (verbatim)

0 GetDeviceLocationName (LocationName 0x24) ; 1 SetDeviceLocationName ;
2 GetTotalLocationNameCount ; 3 LoadLocationNameList ; 4 LoadTimeZoneRule →
TimeZoneRule 0x4000 ; 5 [2+] GetTimeZoneRuleVersion ; 8 [9+] ParseTimeZoneBinary ;
100 ToCalendarTime (PosixTime + rule → CalendarTime 0x8 + CalendarAdditionalInfo)
; 101 ToCalendarTimeWithMyRule ; 201 ToPosixTime ; 202 ToPosixTimeWithMyRule.

**TimeZoneRule (0x4000)** : 0x0 timecnt / 0x4 typecnt /
0x8 charcnt / 0xC goback / 0xD goahead / 0x10 ats (8×1000) / 0x1F50 types
(1×1000) / 0x2338 ttis (0x10×128, ttinfo : tt_gmtoff s32, tt_isdst u8, pad3,
tt_abbrind u32, tt_ttisstd u8, tt_ttisgmt u8) / 0x2B38 chars (0x200) /
0x2D38 defaulttype u32 / Reserved → 0x4000. Source = fichiers **Tzif2** sous
zoneinfo/ (RFC8536, conversion tz database sans leap seconds).
`CalendarTime` 0x8 : Year u16, Month/Day/Hour/Minute/Second u8, pad.
`CalendarAdditionalInfo` : 0x0 dow (0-based), 0x4 doy, 0x8 tz name...

### 5.5 Structs (all)

- **SteadyClockTimePoint** 0x18 : @0 u64 time (crypté ?non : temps point) + @8
  0x10 UUID de la source horloge.
- **SystemClockContext** 0x20 : @0 PosixTime (epoch UTC du clock) + @8
  SteadyClockTimePoint.
- **TimeSpanType** = s64 (ns).
- **ClockSnapshot** (cmd 400) : struct 0x70-ish (steady + network + contexts ×3)
  — **à recenser** (pas détaillée dans la page PSC — voir plus tard ou dumps
  Atmosphère).

### 5.6 Mapping Windows

- `GetCurrentTime` → epoch UTC courant (GetSystemTime / time());
- ISteadyClock.GetCurrentTimePoint → QPC (chronomètre monotonique) avec UUID fixe
  fictif ;aligner avec `svcGetSystemTick` (cf `horizon.md` §7, fréquence à calibrer).
- ToCalendarTime → localtime/localtime_s avec la règle du jeu si fournie,
  sinon timezone OS ;equal ToPosixTime via inverse.

## 6. appletABI (am : appletAE / appletOE)

Ports : `appletAE` (OpenSystemApplicationProxy cmd **350** → IApplicationProxy ;
aussi OpenLibraryAppletProxy 200, OpenOverlayProxy 300, etc.) ;
`appletOE` (IApplicationProxyService — OpenApplicationProxy, cmds 0/1 selon fw)
→ **IApplicationProxy** pour les jeux.

### 6.1 IApplicationProxy (verbatim)

0 GetCommonStateGetter ; 1 GetSelfController ; 2 GetWindowController ; 3
GetAudioController ; 4 GetDisplayController ; 10 GetProcessWindingController ;
11 GetLibraryAppletCreator ; **20 GetApplicationFunctions** ; 1000
GetDebugFunctions.

### 6.2 IApplicationFunctions (verbatim — cmds clés)

| Cmd | Nom |
|---|---|
| 1 | PopLaunchParameter (u32 kind → IStorage) |
| 20 | **EnsureSaveData** (u128 userID → u64, crée savedata selon NACP) |
| 21 | **GetDesiredLanguage** → LanguageCode ("en-US", "fr-FR"…, cf Settings) |
| 22 | SetTerminateResult (u32 Result ; situation de crash à loguer) |
| 23 | GetDisplayVersion |
| 25/26 | [3+] ExtendSaveData / GetSaveDataSize |
| 27 | [5+] CreateCacheStorage |
| 28/29 | [11+] GetSaveDataSizeMax / GetCacheStorageMax |
| 30/31 | Begin/EndBlockingHomeButtonShortAndLongPressed |
| 32/33 | Begin/EndBlockingHomeButton |
| 40 | **NotifyRunning** → u8 (retourner 1) |
| 50 | [2+] GetPseudoDeviceId (u64) |
| 65/66/67 | [3+] IsGamePlayRecordingSupported / InitializeGamePlayRecording / SetGamePlayRecordingState — **BOTW** : transfér memories 0x6000000 (96 MiB) + state 0x1 depuis nninitStartup |
| 70/71/72 | [3+] RequestToShutdown/Reboot/Sleep |
| 110/111 | [5+] QueryApplicationPlayStatistics(ByUid) |
| 120-123 | [5+] ExecuteProgram / ClearUserChannel / UnpopToUserChannel / GetPreviousProgramIndex |
| 130 | [4+] GetGpuErrorDetectedSystemEvent |
| 140/150 | [9+] events friend/notification storage |
| 1001 | [5+] PrepareForJit |

### 6.3 ICommonStateGetter (verbatim)

| Cmd | Nom |
|---|---|
| 0 | **GetEventHandle → événement** (signalisé quand un AppletMessage attend à ReceiveMessage) |
| 1 | **ReceiveMessage → AppletMessage** (0x680 = aucun message) |
| 2 | GetThisAppletKind (stubbed → error) |
| 3/4 | AllowToEnterSleep / DisallowToEnterSleep |
| 5 | **GetOperationMode** (0 Handheld, 1 Console) |
| 6 | **GetPerformanceMode** (0 Normal, 1 Boost) |
| 7/8 | GetCradleStatus / GetBootMode |
| 9 | **GetCurrentFocusState** (0 Background, 1 ?, 2 InFocus?) |
| 10-13 | sleep lock (RequestToAcquire 10, Release 11, Transiently 12, GetAcquiredSleepLockEvent 13) |
| 14 | [11+] GetWakeupCount |
| 20 | PushToGeneralChannel |
| 30-32 | reader/writer lock accessors |
| 40 | [2+] GetCradleFwVersion |
| 50-55 | VR : IsVrModeEnabled 50, SetVrModeEnabled 51, [4+] SetLcdBacklighOffEnabled 52, [7+] Begin/EndVrModeEx 53/54, IsInControllerFirmwareUpdateSection 55 |
| **60/61** | [3+] **GetDefaultDisplayResolution** (1080p dock / 720p handheld) / …ChangeEvent |
| 62/63 | [4+] HDCP states |
| 64 | [5+] SetTvPowerStateMatchingMode |
| 66/67 | [7+] **SetCpuBoostMode** (0 Disabled, 1 Boost)/CancelCpuBoostMode [10+] |
| 68 | [11+] GetBuiltInDisplayType |
| 90/91 | [7+] perf config notification / GetCurrentPerformanceConfiguration |
| 200/300 | [7+] GetOperationModeSystemInfo / [9+] GetSettingsPlatformRegion |
| 500-503 | [11-12+] sleep disable states |

Note : la gestion des messages (ids AppletMessage) est faite **par le jeu
lui-même** — notre HLE n'émule que les événements de focus/sortie. Ids à
capter (page `AM_services#AppletMessage`) plus tard.

### 6.4 ISelfController (verbatim)

0 Exit ; 1/2 Lock/UnlockExit ; 3/4 [2+] Enter/LeaveFatalSection ;
9 GetLibraryAppletLaunchableEvent ; 10 SetScreenShotPermission ; 11/12 notif
operation/perf mode ; 13 SetFocusHandlingMode ; 14 SetRestartMessageEnabled ;
15/16 [2+] screenshot-applet / SetOutOfFocusSuspendingEnabled ; 17-24 fw extras
; **40 CreateManagedDisplayLayer → LayerId** ; 41-43 [4-5+] system buffer
sharing (IsSystemBufferSharingEnabled/GetSystemSharedLayerHandle/
GetSystemSharedBufferHandle) ; 44 [10+] CreateManagedDisplaySeparableLayer ;
50/51 SetHandlesRequestToDisplay / ApproveToDisplay ; 60-65 idle/sleep config ;
66-69 illuminance/auto-sleep ; 90/91 [6+]
GetAccumulatedSuspendedTick(Value/ChangedEvent) ; 120 [11+]
SaveCurrentScreenshot ; 1000 [7+] GetDebugStorageChannel.

### 6.5 Autres contrôleurs

- **IWindowController** (proxy cmd 2) : cmds dans page AM non capturés
  (`GetAppletResourceUserId` cmd 1? — à capter).
- **IAudioController** (3), **IDisplayController** (4),
  **IProcessWindingController** (10, RebootSystem…), **ILibraryAppletCreator**
  (11 — CreateLibraryApplet etc. ; stub fail en v1, appelé seulement dans des
  cas marginaux).
- **IStorage** (objets launch param) : stub minimal.

### 6.6 Mapping Windows / stratégie

- `GetEventHandle`/`ReceiveMessage` : événement Windows ;
  messages générés : changement de focus (fenêtre gagne/perd le focus),
  Home (quitté), operation mode figé à Console(1).
- `GetOperationMode` → 1 (Console) fixe ; `GetPerformanceMode` → 0 ;
  `GetDefaultDisplayResolution` → taille fenêtre (ou 1920×1080 / 1280×720).
- `GetDesiredLanguage` → valeur de configuration (défaut "en-US" ; auto depuis
  GetSystemDefaultLCID → LanguageCode).
- `EnsureSaveData` → crée le dossier de sauvegarde du titre (%APPDATA%/titre/
  saves) et retourne 0.
- `NotifyRunning` → retourne 1 ; `GetDisplayVersion` / `GetSaveDataSizeMax` →
  constantes du manifeste ; `SetCpuBoostMode` → no-op ; `SetTerminateResult` →
  log ; `Exit` → fin propre du processus.

## 7. Erreurs & conventions remarquables

- vi : 0xA72 = session cmd non-dispo ; stéréo 0xC72 = retail stubbed (underscan).
- Allocation out-params : les struct out scalaires se remplissent dans le
  marshalling (voir §9) ; les buffers type-0x6 etc. sont des pointeurs physiques
  du message (fiche marshalling).
- Events (handles) tous mappés sur un mutex dédié Windows WaitEvent ; nos
  événements = WaitHandle réels quand possible.

## 8. Priorités de stub v1 (verticale raisonnable)

1. `sm:` GetService + table de ports préchargés.
2. **appletABI** : IApplicationProxy (0/1/2/20), ICommonStateGetter (0/1/5/6/9/60),
   ISelfController (40), IApplicationFunctions (20/21/22/23/40) — c'est par là
   que les jeux nnsdk bootent (nn::oe).
3. **time** : ISystemClock.GetCurrentTime + SteadyClock (QPC), TimeZone stub.
4. **hid** : CreateAppletResource + shared memory + lifos Npad/TouchScreen
   (cmd 0 + poll XInput/WndProc) ; Activate* cmds acceptés.
5. **vi** : GetDisplayService + OpenDisplay/CloseDisplay + OpenLayer + vsync
   event ; 1102/60 résolutions fenêtre.
6. Reste → fail explicite.

## 10. HIPC / CMIF — format brut (dispatcher SendSyncRequest)

Page wiki `IPC_Marshalling`/`HIPC`. CMIF = universel ; TIPC = seul `sm:`
([12.0.0+]) et `pgl`. Buffer = **Thread Local Region** (voir §11).

### 10.1 Buffer HIPC (dans le TLR)

| Off. | Taille | Contenu |
|---|---|---|
| 0x0 | 0x8 | HeaderData |
| 0x8 | 0x4 | SpecialHeaderData (si SpecialCount) |
| 0xC | 0x8 | ProcessId (si bit Pid) |
| vary | | CopyHandle[] puis MoveHandle[] (u32) |
| vary | | PointerData[PointerCount] (0x8 chacun) |
| vary | | SendData[SendCount] (0xC chacun) |
| vary | | ReceiveData / ExchangeData (0xC chacun) |
| vary | | **RawData** (RawCount u32) |
| vary | | ReceiveListData[ReceiveListCount] |

- **Header0 u32** : bits 0-15 Tag/MessageType ; 16-19 PointerCount ; 20-23
  SendCount ; 24-27 ReceiveCount ; 28-31 ExchangeCount.
- **Header1 u32** : bits 0-9 RawCount (mots u32) ; 10-13 ReceiveListCount ;
  20-30 ReceiveListOffset ; 31 SpecialCount.
- **SpecialHeaderData** : bit 0 Pid ; bits 1-4 CopyHandleCount ; 5-8
  MoveHandleCount. Handle 0 = « pas de handle ».
- **MapData 0xC** : Map0 = size bits 0-31 ; Map1 = addr bits 0-31 ; Map2 =
  bits 0-1 attrs (AllowsNonSecure/NonDevice), 2-4 addr36, 24-27 sizeHi,
  28-31 addr32.
- **PointerData 0x8** : Pointer0 = bits 0-3 PointerIndex (ReceiveIndex),
  6-8 addr36, 12-15 addr32, 16-31 size ; Pointer1 = addr bits 0-31.
- Réponse : **jamais** de Send/Receive/Exchange (kernel → 0xE801).

### 10.2 CMIF (RawData)

- Padding total dans la section raw = **0x10 octets** (alignement 16 : si rien
  avant le message, 0x10 après) ; puis per-entrée **OutPointer lengths** (u16,
  padded au mot) à la fin.
- **CmifInHeader 0x10** : "SFCI" / Version u16 (0 avant [5.0.0+], 1 depuis) /
  Reserved u16 / **MethodId u32** / Token u32 ([5.0.0+] inline-context, sinon
  reserved). Params après, générés par **tri stable par alignement croissant**
  (low→high) des paramètres de la fonction.
- **CmifOutHeader 0x10** : "SFCO" / Version u16 / Reserved u16 / **Result u32**
  / Reserved ou [14.0.0+] InterfaceId.
- **Domaines** : CmifDomainMessageInHeader 0x10 (RequestKind u8 : 1
  InvokeMethod, 2 Release ; InObjectCount u8 ; InRawSize u16 ;
  TargetObjectId u32) puis CmifMessage puis ObjectId[] ; réponse :
  CmifDomainMessageOutHeader (OutObjectCount u32) avant CmifOutHeader.
- MessageType (Header0 bits 0-15) : 1 InvokeMethod (déprécié), 2 Release,
  3 InvokeManagerMethod (0 ConvertCurrentObjectToDomain, 1 CopyFromCurrentDomain,
  2 CloneCurrentObject, **3 QueryPointerBufferSize → u16**, 4
  CloneCurrentObjectEx), 4 Invoke2MethodOld, 5 Invoke2ManagerMethodOld,
  6 [5.0.0+] Invoke2Method, 7 Invoke2ManagerMethod.
- Dispatcher : lire Header0/1 → sauter spécial/descripteurs → RawData = SFCI @0
  → MethodId (ou Header0.tag directement en TIPC).

## 11. TLR (Thread Local Region, 0x200) & sm:

### 11.1 TLR — structure (nn::svc::ThreadLocalRegion, verbatim)

| Off. | Taille | Champ |
|---|---|---|
| 0x0 | 0x100 | **MessageBuffer** (IPC §10) |
| 0x100/0x102 | 2/2 | [8+] DisableCounter / InterruptFlag (SynchronizePreemptionState) |
| 0x104 | 1 | [14+] CacheMaintenanceFlag |
| 0x108 | 8 | [21+] ThreadCpuTime |
| 0x110 | 4 | [22+] CurrentThreadHandle |
| 0x180 | 0x50 | Tls (slots nnsdk) |
| 0x1D0/0x1D8/0x1E0 | 8×3 | LocalePtr / ErrnoVal / ThreadData |
| 0x1E8/0x1F0/0x1F8 | 8/8/8 | EhGlobals / **ThreadPointer** / ThreadType ptr |

- TLRs multiples **dans la même page** 0x1000 ; premier spot (page+0x0)
  réservé à l'**exception** (UserExceptionContext, cf `horizon.md` §3) ;
  TLR normale à **page+0x200**.
- **tpidrro_el0** = adresse du TLR du thread (0x200) — LECTURE utilisateur.
- **tpidr_el0** = ThreadPointer nnsdk = adresse de l'**OsResourceManager**
  (state global process : RngManager 0x14, AslrSpaceManager 0x28,
  StackGuardManager 0x28, ThreadManager 0x1F0, TlsManager 0x110, TickManager,
  MemoryHeapManager 0x30, VammManager 0x48 — totale ≈ 0x3E8). Les jeux
  nnsdk s'en servent **constamment** (tick, threads, tls slots) → nos stubs
  MRS tpidr_el0/tpidrro_el0 écrivent ces variables ({
    cpu.tls_ptr = TLR ; cpu.thread_pointer = OsResourceMgr }).

### 11.2 sm: (nn::sm::detail::IUserInterface) — verbatim

| Cmd | Nom |
|---|---|
| 0 | **RegisterClient** (PID-descriptor + reserved u64) |
| 1 | **GetServiceHandle** (ServiceName → handle) |
| 2 | RegisterService (ServiceName, IsLight, MaxSessions) |
| 3 | UnregisterService |
| 4 | [11.0.0-11.0.1] DetachClient |

[12.0.0+] sm: passe en **TIPC** (n° de cmds décalés −16). `ServiceName` =
u64 codé depuis une chaîne NUL-padded **max 8 chars**. Stub : GetServiceHandle
→ handle HLE pré-régistré (table §8) ; service inconnu → log + Result 0xD401-ish
explicit.

## 12. À capter ensuite (fiches suivantes)

- `NVN` + `Nvnflinger_services` (dispdrv/IHOSBinderDriver cmds) + `nvdrv` —
  phase rendu.
- `AM_services#AppletMessage` (ids des messages), `NACP_Format`
  (EnsureSaveData/desired language), `Error_codes`.
- ClockSnapshot struct (détail, hors page PSC), KeyboardState/MouseState
  complets + battery/AppletFooter fields de NpadInternalState (extraire du
  cache HID au portage).

