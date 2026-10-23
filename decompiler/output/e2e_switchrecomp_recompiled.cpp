// ---- Généré par SwitchRecomp (traduction ARM64 -> C++) ----
// Le résultat est compilé par MSVC/MinGW en .exe Windows natif : aucun
// émulateur générique n'est nécessaire à l'exécution.
#include <stdint.h>
#include <atomic>
#include "horizon_os/horizon_os.h"   // CPUState, mémoire plate, HLE (SVC/IPC)

// --- drapeaux NZCV (order Arm: N bit63, Z zero, C carry/borrow, V overflow) ---
static inline void set_flags_sub(CPUState& s, uint64_t a, uint64_t b) {
    uint64_t r = a - b;
    s.N = (int)((r >> 63) & 1); s.Z = (int)(r == 0);
    s.C = (int)(a >= b);
    s.V = (int)(((a ^ b) & (a ^ r)) >> 63) & 1;
}
static inline void set_flags_add(CPUState& s, uint64_t a, uint64_t b) {
    uint64_t r = a + b;
    s.N = (int)((r >> 63) & 1); s.Z = (int)(r == 0);
    s.C = (int)(r < a);
    s.V = (int)((~(a ^ b) & (a ^ r)) >> 63) & 1;
}
static inline void set_flags_logic(CPUState& s, uint64_t r, int width) {
    r &= (width == 32) ? 0xFFFFFFFFULL : ~0ULL;
    s.N = (int)((r >> (width - 1)) & 1); s.Z = (int)(r == 0);
    s.C = 0; s.V = 0;
}

// --- code du jeu recompilé ---

// Bloc game_block_0: début
static void game_block_0(CPUState& s) {
    { mem_store64(s, (s.X[1] + (uint64_t)(int64_t)16), s.X[2]); mem_store64(s, (s.X[1] + (uint64_t)(int64_t)16) + 8, s.X[3]); }
    s.X[0] = (uint64_t)48ULL << 0;
    s.X[0] = s.X[0] + s.X[1];
    s.X[2] = mem_load64(s, (s.X[3] + (uint64_t)(int64_t)-8));
    std::atomic_thread_fence(std::memory_order_seq_cst);
    if (((s.X[0] >> 3) & 1) == 0) goto L_0000001c;
    { s.X[2] = mem_load64(s, (s.X[1] + (uint64_t)(int64_t)16)); s.X[3] = mem_load64(s, (s.X[1] + (uint64_t)(int64_t)16) + 8); }
    L_0000001c: ;
    s.X[0] = (uint64_t)8192ULL << 0;
    s.X[1] = (uint64_t)4096ULL << 0;
    hle_svc(s, 0x1f);
    s.X[0] = (uint64_t)8192ULL << 0;
    s.X[0] = mem_load32(s, (s.X[0] + (uint64_t)0ULL));
    hle_svc(s, 0x21);
    return; /* RET (X30) */
}
