// -*- coding: utf-8 -*-
// SwitchRecomp -- gestionnaire IPC Horizon (HIPC + CMIF SFCI/SFCO + TIPC).
//
// Références : knowledge/services.md §10 (buffer HIPC, CMIF) et §11 (TLR/sm:).
//
// Le dispatcher est appelé par SVC 0x20..0x23 (SendSyncRequest) avec le
// MessageBuffer du TLR de test (HLE_TLR_ADDR). Il expose deux commandes du
// service manager `sm:` :
//   cmd 0 RegisterClient   (PID + réservé u64) -> handle client
//   cmd 1 GetServiceHandle (ServiceName u64)   -> handle de session
//
// Le format CMIF est détecté en scannant le début de la zone RawData à la
// recherche du magic "SFCI" (un padding d'alignement de 0x10 octets peut
// précéder l'en-tête selon la version). Sans SFCI, on traite le message comme
// du TIPC : l'identifiant de commande est alors le Tag (Header0 bits 0..15).
#include "horizon_os.h"

#include <cstring>

namespace {

constexpr uint32_t CMIF_IN_MAGIC  = 0x49434653u;  // "SFCI" (LE)
constexpr uint32_t CMIF_OUT_MAGIC = 0x4F434653u;  // "SFCO" (LE)
constexpr uint32_t RESULT_OK      = 0u;
constexpr uint32_t RESULT_NOT_FOUND = 0xE401u;

uint32_t rd32(const uint8_t* p) {
    uint32_t v = 0;
    std::memcpy(&v, p, sizeof(v));
    return v;
}

void wr32(uint8_t* p, uint32_t v) {
    std::memcpy(p, &v, sizeof(v));
}

struct IpcRequest {
    bool     valid = false;
    bool     cmif = false;
    uint32_t hdr0 = 0;
    uint32_t hdr1 = 0;
    uint32_t method = 0;
    uint32_t raw_off = 8;
    uint32_t raw_words = 0;
    uint32_t cmif_off = 0;
    uint32_t param_off = 8;
};

// Décode l'en-tête HIPC et localise la zone de paramètres (RawData).
IpcRequest parse_request(const uint8_t* msg, uint32_t size) {
    IpcRequest req;
    if (size < 8u) {
        return req;
    }
    req.valid = true;
    req.hdr0 = rd32(msg);
    req.hdr1 = rd32(msg + 4u);
    req.raw_words = req.hdr1 & 0x3FFu;

    uint32_t off = 8u;
    const uint32_t special = (req.hdr1 >> 31) & 1u;
    if (special) {
        if (off + 4u > size) {
            req.valid = false;
            return req;
        }
        const uint32_t sp = rd32(msg + off);
        off += 4u;
        const uint32_t has_pid = sp & 1u;
        const uint32_t copy_handles = (sp >> 1) & 0xFu;
        const uint32_t move_handles = (sp >> 5) & 0xFu;
        if (has_pid) {
            off += 8u;                       // ProcessId u64
        }
        off += (copy_handles + move_handles) * 4u;
    }

    const uint32_t pointers = (req.hdr0 >> 16) & 0xFu;
    const uint32_t send = (req.hdr0 >> 20) & 0xFu;
    const uint32_t recv = (req.hdr0 >> 24) & 0xFu;
    const uint32_t exch = (req.hdr0 >> 28) & 0xFu;
    off += pointers * 8u + (send + recv + exch) * 0xCu;
    if (off > size) {
        req.valid = false;
        return req;
    }
    req.raw_off = off;

    // CMIF : chercher "SFCI" dans la zone raw (padding <= 0x40 octets).
    for (uint32_t o = off; o + 4u <= size && o < off + 0x40u; o += 4u) {
        if (rd32(msg + o) == CMIF_IN_MAGIC) {
            req.cmif = true;
            req.cmif_off = o;
            req.param_off = o + 0x10u;
            req.method = (o + 0xCu <= size) ? rd32(msg + o + 8u) : 0u;
            return req;
        }
    }

    // TIPC : Header0 bits 0..15 = tag = commande.
    req.method = req.hdr0 & 0xFFFFu;
    req.param_off = off;
    return req;
}

// Écrit la réponse dans le MessageBuffer (SFCO pour CMIF, en-tête + payload
// brut pour TIPC). Le buffer est remis à zéro avant écriture.
void write_reply(CPUState& s, uint64_t buf_addr, uint32_t buf_size,
                 const IpcRequest& req, uint32_t result,
                 const uint8_t* payload, uint32_t payload_size) {
    uint8_t out[0x100];
    std::memset(out, 0, sizeof(out));
    uint32_t total = 0;

    if (req.cmif) {
        const uint32_t off = req.cmif_off;
        if (off + 0x10u > sizeof(out)) {
            hle_log("[HLE][IPC] reponse CMIF hors buffer (off=0x%x)", off);
            return;
        }
        wr32(out + off, CMIF_OUT_MAGIC);
        out[off + 4u] = 1u;                  // Version u16 = 1 ([5.0.0+])
        out[off + 5u] = 0u;
        out[off + 6u] = 0u;
        out[off + 7u] = 0u;
        wr32(out + off + 8u, result);        // Result u32
        wr32(out + off + 0xCu, 0u);          // Reserved / InterfaceId
        total = off + 0x10u;
    } else {
        wr32(out, 0u);                       // Header0 (réponse)
        wr32(out + 4u, (payload_size + 3u) / 4u);  // RawCount (mots)
        total = 8u;
    }

    if (payload != nullptr && payload_size != 0u) {
        if (total + payload_size > sizeof(out)) {
            payload_size = static_cast<uint32_t>(sizeof(out)) - total;
        }
        std::memcpy(out + total, payload, payload_size);
        total += payload_size;
    }
    if (total > buf_size) {
        total = buf_size;
    }
    for (uint32_t k = 0; k < total; ++k) {
        mem_store8(s, buf_addr + (uint64_t)k, out[k]);
    }
}

bool service_known(const char* name) {
    static const char* const kKnown[] = {
        "sm:", "hid", "vi", "time", "fsp-srv", "nvdrv",
        "audren", "aoc:u", "ldr", "pm:shell"
    };
    for (const char* const candidate : kKnown) {
        if (std::strcmp(name, candidate) == 0) {
            return true;
        }
    }
    return false;
}

uint32_t sm_register_client(CPUState& s, uint64_t buf_addr, uint32_t buf_size,
                            const IpcRequest& req, const uint8_t* msg) {
    uint32_t pid = 0;
    if (req.param_off + 4u <= buf_size) {
        pid = rd32(msg + req.param_off);
    }
    const uint32_t client = hle_handle_alloc("sm:client");

    uint8_t payload[8];
    wr32(payload, client);
    wr32(payload + 4u, RESULT_OK);
    write_reply(s, buf_addr, buf_size, req, RESULT_OK, payload,
                req.cmif ? 4u : 8u);

    hle_log("[HLE][IPC] sm: RegisterClient(cmd 0, %s) pid=0x%x -> "
            "client_handle=%u result=0x0",
            req.cmif ? "CMIF" : "TIPC", pid, client);
    return RESULT_OK;
}

uint32_t sm_get_service_handle(CPUState& s, uint64_t buf_addr, uint32_t buf_size,
                               const IpcRequest& req, const uint8_t* msg) {
    char name[9];
    std::memset(name, 0, sizeof(name));
    uint32_t avail = (buf_size > req.param_off) ? (buf_size - req.param_off) : 0u;
    if (avail > 8u) {
        avail = 8u;
    }
    if (avail != 0u) {
        std::memcpy(name, msg + req.param_off, avail);
    }

    uint32_t handle = 0;
    uint32_t result = RESULT_NOT_FOUND;
    if (service_known(name)) {
        handle = hle_handle_alloc(name);
        result = RESULT_OK;
    }

    uint8_t payload[8];
    wr32(payload, handle);
    wr32(payload + 4u, result);
    write_reply(s, buf_addr, buf_size, req, result, payload,
                req.cmif ? 4u : 8u);

    if (result == RESULT_OK) {
        hle_log("[HLE][IPC] sm: GetServiceHandle(cmd 1, %s) \"%s\" -> "
                "handle=%u result=0x0", req.cmif ? "CMIF" : "TIPC",
                name, handle);
    } else {
        hle_log("[HLE][IPC] sm: GetServiceHandle(cmd 1, %s) \"%s\" -> "
                "service inconnu result=0x%x", req.cmif ? "CMIF" : "TIPC",
                name, result);
    }
    return result;
}

}  // namespace

uint32_t hle_ipc_dispatch(CPUState& s, uint32_t session, uint64_t buf_addr,
                          uint32_t buf_size) {
    if (buf_size > 0x100u) {
        buf_size = 0x100u;
    }
    uint8_t msg[0x100];
    std::memset(msg, 0, sizeof(msg));
    for (uint32_t k = 0; k < buf_size; ++k) {
        msg[k] = (uint8_t)mem_load8(s, buf_addr + (uint64_t)k);
    }

    const IpcRequest req = parse_request(msg, buf_size);
    if (!req.valid) {
        hle_log("[HLE][IPC] requete HIPC invalide (taille=%u)", buf_size);
        return RESULT_NOT_FOUND;
    }

    const char* const target = hle_handle_name(session);
    hle_log("[HLE][IPC] requete recue : handle=%u (%s) format=%s cmd=0x%x "
            "raw=%u mots", session, target, req.cmif ? "CMIF/SFCI" : "TIPC",
            req.method, req.raw_words);

    if (std::strcmp(target, "sm:") != 0) {
        hle_log("[HLE][IPC] service \"%s\" non implemente -> result=0x%x",
                target, RESULT_NOT_FOUND);
        write_reply(s, buf_addr, buf_size, req, RESULT_NOT_FOUND, nullptr, 0u);
        return RESULT_NOT_FOUND;
    }

    // TIPC [12.0.0+] : les numéros de commande sm: sont décalés de +0x10
    // (knowledge/services.md §11.2). On accepte les deux encodages.
    uint32_t cmd = req.method;
    if (!req.cmif && cmd >= 0x10u && cmd <= 0x10u + 4u) {
        cmd -= 0x10u;
    }

    switch (cmd) {
    case 0u:
        return sm_register_client(s, buf_addr, buf_size, req, msg);
    case 1u:
        return sm_get_service_handle(s, buf_addr, buf_size, req, msg);
    default:
        hle_log("[HLE][IPC] sm: commande 0x%x non implementee -> result=0x%x",
                cmd, RESULT_NOT_FOUND);
        write_reply(s, buf_addr, buf_size, req, RESULT_NOT_FOUND, nullptr, 0u);
        return RESULT_NOT_FOUND;
    }
}
