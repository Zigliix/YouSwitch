// ---- Généré par SwitchRecomp (traduction ARM64 -> C++) ----
// Le résultat est compilé par MSVC/MinGW en .exe Windows natif : aucun
// émulateur générique n'est nécessaire à l'exécution.
#include <stdint.h>
#include <atomic>

struct CPUState {
    uint64_t X[31];        // X0..X30 (31 = ZR/SP, résolu au décodage)
    uint64_t SP;
    uint64_t PC_BASE;      // base mémoire Virtuelle de la section .text du jeu
    int      N, Z, C, V;   // drapeaux NZCV
};

// --- accès mémoire (stub naïf : - adresses intégrales transmises telles quelles,
//     remappage réel de la mémoire du jeu à venir) ---
static uint64_t mem_addr(uint64_t v) { return v; }   // TODO mapping mémoire réel

static uint64_t mem_load8 (CPUState& s, uint64_t a) { return *(volatile uint8_t*) mem_addr(a); }
static uint64_t mem_load16(CPUState& s, uint64_t a) { return *(volatile uint16_t*)mem_addr(a); }
static uint64_t mem_load32(CPUState& s, uint64_t a) { return *(volatile uint32_t*)mem_addr(a); }
static uint64_t mem_load64(CPUState& s, uint64_t a) { return *(volatile uint64_t*)mem_addr(a); }
static void mem_store8 (CPUState& s, uint64_t a, uint64_t v) { *(volatile uint8_t*) mem_addr(a) = (uint8_t)v; }
static void mem_store16(CPUState& s, uint64_t a, uint64_t v) { *(volatile uint16_t*)mem_addr(a) = (uint16_t)v; }
static void mem_store32(CPUState& s, uint64_t a, uint64_t v) { *(volatile uint32_t*)mem_addr(a) = (uint32_t)v; }
static void mem_store64(CPUState& s, uint64_t a, uint64_t v) { *(volatile uint64_t*)mem_addr(a) = v; }

// --- drapeaux NZCV (order Arm: N bit63, Z zero, C carry/borrow, V overflow) ---
static void set_flags_sub(CPUState& s, uint64_t a, uint64_t b) {
    uint64_t r = a - b;
    s.N = (int)((r >> 63) & 1); s.Z = (int)(r == 0);
    s.C = (int)(a >= b);
    s.V = (int)(((a ^ b) & (a ^ r)) >> 63) & 1;
}
static void set_flags_add(CPUState& s, uint64_t a, uint64_t b) {
    uint64_t r = a + b;
    s.N = (int)((r >> 63) & 1); s.Z = (int)(r == 0);
    s.C = (int)(r < a);
    s.V = (int)((~(a ^ b) & (a ^ r)) >> 63) & 1;
}
static void set_flags_logic(CPUState& s, uint64_t r, int width) {
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
    return; /* RET (X30) */
    return;
}
