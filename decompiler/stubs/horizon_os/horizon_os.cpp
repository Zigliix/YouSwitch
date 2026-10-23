// -*- coding: utf-8 -*-
// SwitchRecomp -- HLE Horizon OS : mémoire plate, handles, dispatch SVC.
//
// Les SVC ARM64 (0x1F ConnectToNamedPort, 0x20-0x23 SendSyncRequest,
// 0x30/0x31 GetResourceLimitValue) sont traduites par l'émetteur en appels
// hle_svc() ; ce fichier les route vers les services C++ réimplémentés.
#include "horizon_os.h"

#include <cstdarg>
#include <cstdio>
#include <cstring>

// ---------------------------------------------------------------------------
// Mémoire plate
// ---------------------------------------------------------------------------
static uint8_t g_arena[HLE_ARENA_SIZE];

uint8_t* mem_addr(uint64_t a) {
    if (a < (uint64_t)HLE_ARENA_SIZE) {
        return g_arena + a;
    }
    // Page-guard : on ne crashe pas, mais l'accès est signalé.
    static uint8_t guard[0x1000];
    hle_log("[HLE][MEM] acces hors arene : 0x%llx (taille 0x%x) -> page-guard",
            (unsigned long long)a, (unsigned)HLE_ARENA_SIZE);
    return guard;
}

uint64_t mem_load8(CPUState& s, uint64_t a) {
    (void)s;
    uint8_t v = 0;
    std::memcpy(&v, mem_addr(a), sizeof(v));
    return v;
}

uint64_t mem_load16(CPUState& s, uint64_t a) {
    (void)s;
    uint16_t v = 0;
    std::memcpy(&v, mem_addr(a), sizeof(v));
    return v;
}

uint64_t mem_load32(CPUState& s, uint64_t a) {
    (void)s;
    uint32_t v = 0;
    std::memcpy(&v, mem_addr(a), sizeof(v));
    return v;
}

uint64_t mem_load64(CPUState& s, uint64_t a) {
    (void)s;
    uint64_t v = 0;
    std::memcpy(&v, mem_addr(a), sizeof(v));
    return v;
}

void mem_store8(CPUState& s, uint64_t a, uint64_t v) {
    (void)s;
    uint8_t b = (uint8_t)v;
    std::memcpy(mem_addr(a), &b, sizeof(b));
}

void mem_store16(CPUState& s, uint64_t a, uint64_t v) {
    (void)s;
    uint16_t b = (uint16_t)v;
    std::memcpy(mem_addr(a), &b, sizeof(b));
}

void mem_store32(CPUState& s, uint64_t a, uint64_t v) {
    (void)s;
    uint32_t b = (uint32_t)v;
    std::memcpy(mem_addr(a), &b, sizeof(b));
}

void mem_store64(CPUState& s, uint64_t a, uint64_t v) {
    (void)s;
    uint64_t b = v;
    std::memcpy(mem_addr(a), &b, sizeof(b));
}

// ---------------------------------------------------------------------------
// Journalisation
// ---------------------------------------------------------------------------
void hle_log(const char* fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    std::vfprintf(stdout, fmt, ap);
    va_end(ap);
    std::fputc('\n', stdout);
    std::fflush(stdout);
}

// ---------------------------------------------------------------------------
// Handles HLE
// ---------------------------------------------------------------------------
static constexpr uint32_t HLE_MAX_HANDLES = 64;
static char     g_handle_names[HLE_MAX_HANDLES][24];
static bool     g_handle_used[HLE_MAX_HANDLES];
static uint32_t g_handle_next = 1;

static void handle_copy_name(char* dst, size_t dst_size, const char* src) {
    size_t k = 0;
    if (dst_size == 0) {
        return;
    }
    while (src != nullptr && src[k] != '\0' && k + 1 < dst_size) {
        dst[k] = src[k];
        ++k;
    }
    dst[k] = '\0';
}

uint32_t hle_handle_alloc(const char* name) {
    for (uint32_t h = g_handle_next; h < HLE_MAX_HANDLES; ++h) {
        if (!g_handle_used[h]) {
            g_handle_used[h] = true;
            handle_copy_name(g_handle_names[h], sizeof(g_handle_names[h]), name);
            g_handle_next = h + 1;
            return h;
        }
    }
    hle_log("[HLE][HANDLE] table pleine : allocation de \"%s\" refusee",
            name != nullptr ? name : "?");
    return 0;
}

const char* hle_handle_name(uint32_t handle) {
    if (handle < HLE_MAX_HANDLES && g_handle_used[handle]) {
        return g_handle_names[handle];
    }
    return "(inconnu)";
}

void hle_handle_dump() {
    hle_log("[HLE][HANDLE] table des sessions :");
    for (uint32_t h = 1; h < HLE_MAX_HANDLES; ++h) {
        if (g_handle_used[h]) {
            hle_log("[HLE][HANDLE]   handle %u -> %s", h, g_handle_names[h]);
        }
    }
}

// ---------------------------------------------------------------------------
// SVC 0x1F : ConnectToNamedPort(out*, name*)
//   Entrée : X0 = pointeur de sortie (Handle u32), X1 = pointeur du nom.
//   Sortie : X0 = Result (0 = succès).
// ---------------------------------------------------------------------------
static void svc_connect_to_named_port(CPUState& s) {
    const uint64_t out_ptr = s.X[0];
    const uint64_t name_ptr = s.X[1];
    char name[16];
    name[0] = '\0';
    for (size_t k = 0; k + 1 < sizeof(name); ++k) {
        const uint8_t c = (uint8_t)mem_load8(s, name_ptr + (uint64_t)k);
        name[k] = (char)c;
        name[k + 1] = '\0';
        if (c == 0) {
            break;
        }
    }

    if (std::strcmp(name, "sm:") == 0) {
        const uint32_t handle = hle_handle_alloc("sm:");
        mem_store32(s, out_ptr, handle);
        s.X[0] = 0;
        hle_log("[HLE][SVC] ConnectToNamedPort(\"%s\") -> handle=%u result=0x0",
                name, handle);
        return;
    }

    hle_log("[HLE][SVC] ConnectToNamedPort(\"%s\") -> service non implemente, "
            "result=0xE401", name);
    s.X[0] = 0xE401u;
}

// ---------------------------------------------------------------------------
// SVC 0x20-0x23 : SendSyncRequest (le message est dans le TLR de test).
//   Entrée : X0 = handle de session.
// ---------------------------------------------------------------------------
static void svc_send_sync_request(CPUState& s) {
    const uint32_t session = (uint32_t)s.X[0];
    hle_log("[HLE][SVC] SendSyncRequest(handle=%u, buffer=0x%llx)", session,
            (unsigned long long)HLE_TLR_ADDR);
    const uint32_t result = hle_ipc_dispatch(s, session, HLE_TLR_ADDR, 0x100);
    s.X[0] = result;
    hle_log("[HLE][SVC] SendSyncRequest -> result=0x%x", result);
}

// ---------------------------------------------------------------------------
// SVC 0x30/0x31 : GetResourceLimitValue(out*, handle, which)
//   Valeurs factices (quotas mémoire/threads) en attendant le VMM.
// ---------------------------------------------------------------------------
static void svc_get_resource_limit_value(CPUState& s, uint32_t imm) {
    const uint64_t out_ptr = s.X[0];
    const uint32_t handle = (uint32_t)s.X[1];
    const uint32_t which = (uint32_t)s.X[2];
    const uint64_t value = (imm == 0x30) ? 0x100000ULL : 0x40000ULL;
    mem_store64(s, out_ptr, value);
    s.X[0] = 0;
    hle_log("[HLE][SVC] GetResourceLimitValue(handle=%u, which=%u) -> "
            "0x%llx (quota factice)", handle, which,
            (unsigned long long)value);
}

// ---------------------------------------------------------------------------
// Dispatch SVC
// ---------------------------------------------------------------------------
void hle_svc(CPUState& s, uint32_t imm) {
    switch (imm) {
    case 0x1Fu:
        svc_connect_to_named_port(s);
        break;
    case 0x20u:
    case 0x21u:
    case 0x22u:
    case 0x23u:
        svc_send_sync_request(s);
        break;
    case 0x30u:
    case 0x31u:
        svc_get_resource_limit_value(s, imm);
        break;
    default:
        hle_log("[HLE][SVC] SVC 0x%x non implementee (X0=0x%llx, X1=0x%llx) "
                "-> result=0xE401", imm,
                (unsigned long long)s.X[0], (unsigned long long)s.X[1]);
        s.X[0] = 0xE401u;
        break;
    }
}

// ---------------------------------------------------------------------------
// Initialisation / arrêt
// ---------------------------------------------------------------------------
void hle_init() {
    std::memset(g_arena, 0, sizeof(g_arena));
    std::memset(g_handle_names, 0, sizeof(g_handle_names));
    std::memset(g_handle_used, 0, sizeof(g_handle_used));
    g_handle_next = 1;
    hle_log("[HLE] Horizon OS HLE initialise (arene 0x%x octets, TLR=0x%llx)",
            (unsigned)HLE_ARENA_SIZE, (unsigned long long)HLE_TLR_ADDR);
}

void hle_shutdown() {
    hle_handle_dump();
    hle_log("[HLE] arret du HLE Horizon OS");
}
