// -*- coding: utf-8 -*-
// SwitchRecomp -- HLE Horizon OS (couche de compatibilité win32).
//
// Ce fichier est partagé par le code du jeu recompilé (C++) et par les stubs
// HLE. Il définit l'état CPU, la mémoire plate (arène) et les points d'entrée
// SVC / IPC. Aucun émulateur générique n'est utilisé : les SVC sont des appels
// C++ directs vers les services réimplémentés.
#pragma once
#include <stdint.h>

// État ARM64 minimal. X[31] n'existe pas : l'index 31 (ZR/SP) est résolu par
// l'émetteur (SP -> s.SP, ZR -> constante 0).
struct CPUState {
    uint64_t X[31];        // X0..X30
    uint64_t SP;
    uint64_t PC_BASE;      // base mémoire virtuelle de .text (ADR/ADRP)
    int      N, Z, C, V;   // drapeaux NZCV
};

// ---------------------------------------------------------------------------
// Mémoire plate de test : 16 Mo. Les adresses basses du jeu sont mappées
// linéairement. Une adresse hors arène est redirigée vers une page-guard
// (accès loggué, pas de crash) en attendant le vrai mapping VMM.
// ---------------------------------------------------------------------------
constexpr uint32_t HLE_ARENA_SIZE = 16u * 1024u * 1024u;

// TLR (Thread Local Region) de test, page 0x1000 + 0x200 (services.md §11).
// Le MessageBuffer IPC occupe les 0x100 premiers octets.
constexpr uint64_t HLE_TLR_ADDR = 0x1200;

// Adresse conventionnelle du handle de sortie pour le programme synthétique.
constexpr uint64_t HLE_OUT_ADDR = 0x2000;

uint8_t* mem_addr(uint64_t a);
uint64_t mem_load8(CPUState& s, uint64_t a);
uint64_t mem_load16(CPUState& s, uint64_t a);
uint64_t mem_load32(CPUState& s, uint64_t a);
uint64_t mem_load64(CPUState& s, uint64_t a);
void mem_store8(CPUState& s, uint64_t a, uint64_t v);
void mem_store16(CPUState& s, uint64_t a, uint64_t v);
void mem_store32(CPUState& s, uint64_t a, uint64_t v);
void mem_store64(CPUState& s, uint64_t a, uint64_t v);

// ---------------------------------------------------------------------------
// Journalisation (ASCII uniquement : la console Windows est en cp1252).
// ---------------------------------------------------------------------------
void hle_log(const char* fmt, ...);

void hle_init();
void hle_shutdown();

// ---------------------------------------------------------------------------
// Table de handles HLE (sessions IPC).
// ---------------------------------------------------------------------------
uint32_t hle_handle_alloc(const char* name);
const char* hle_handle_name(uint32_t handle);
void hle_handle_dump();

// ---------------------------------------------------------------------------
// Dispatch SVC (appelé par le code recompilé).
//   0x1F        ConnectToNamedPort (X0 = out*, X1 = name*)
//   0x20..0x23  SendSyncRequest / variantes (X0 = session)
//   0x30/0x31   GetResourceLimitValue (X0 = out*, X1 = handle, X2 = which)
// (numérotation SwitchBrew / knowledge/horizon.md §4)
// ---------------------------------------------------------------------------
void hle_svc(CPUState& s, uint32_t imm);

// ---------------------------------------------------------------------------
// Dispatcher IPC (implémenté dans ipc.cpp) : HIPC + CMIF (SFCI/SFCO) + TIPC.
// Lit/écrit le MessageBuffer à buf_addr (taille buf_size, <= 0x100).
// Retourne le Result Horizon (0 = succès).
// ---------------------------------------------------------------------------
uint32_t hle_ipc_dispatch(CPUState& s, uint32_t session, uint64_t buf_addr,
                          uint32_t buf_size);
