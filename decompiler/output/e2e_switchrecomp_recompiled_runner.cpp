// -*- coding: utf-8 -*-
// Runner de validation SwitchRecomp (généré par build_exe.py).
// Exécute game_block_0, vérifie la résolution de "sm:" puis les commandes
// RegisterClient (0) et GetServiceHandle (1) du service manager HLE.
#include <cstdio>
#include "horizon_os/horizon_os.h"

// Le code généré définit les blocs en static : on l'inclut dans cette unité.
#include "e2e_switchrecomp_recompiled.cpp"

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
