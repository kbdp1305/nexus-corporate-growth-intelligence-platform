
**Champion v1: M1_v0** (M1_v0 100%; kalibrasi temperature+prior)

| | M1_v0 (NB04) | M1_v0 (v1) |
|---|---|---|
| log-loss seimbang (OOF eval) | 0.677 | 0.677 |
| macro-F1 argmax | 0.681 | 0.681 |
| macro-F1 keputusan (recall High 90%) | 0.612 | 0.612 |
| Brier terkalibrasi | 0.316 | 0.316 |
| % otomatis (conformal Mondrian) | 50% | 50% |
| uji logika | 15/23 | 15/23 |

- **HPO** (Optuna TPE): log-loss tuning default → terbaik: M3 0.711 → 0.631, M4 0.779 → 0.631, M2 0.738 → 0.725.
- **Imbalance** (7 skema, dipilih dari biaya di recall High 90%): M1_P: smote, M3_t: balanced; termurah per model: M1_P → smote (Δ -24), M3_t → balanced^0.5 (Δ -12).
- **Prospect % High**: 60% (v0 NB04) → 56% (v1 set_prospect) → 56% (v1 set_prospect_IW). ESS bobot 70%, C2ST AUC 0.79.
- **Kelompok fitur terpenting**: keuangan, timing bayar, konsentrasi pembeli.
