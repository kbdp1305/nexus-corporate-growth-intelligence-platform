
**Analisis kesalahan (1.000 nasabah kredit):** 296 kesalahan; penyebab terbesar menurut biaya: **kasus perbatasan** (67% biaya).
Porsi per penyebab: kasus perbatasan 77%, label rating salah 10%, tak teramati 12%, data tidak lengkap 0%. **77% kesalahan masuk antrean Review analis** (jaring pengaman).
**Audit label:** top-30 antrean memuat 19 label yang benar-benar salah (presisi 63%, 14.4× acak).
**Prospect (shadow):** aturan dipilih tanpa label = V1 keputusan biaya. Terhadap GT: flag High 54% → 47% (sebenarnya 29%), presisi High 0.52 → 0.56, recall 0.96 → 0.91, biaya 347 → 358.
**Anomali (shadow):** {'buyer_exit': {'buyer_exit_share_min': 0.2}, 'distress': {'confirm_out_in_delta_min': None, 'confirm_cusum_down_min': None}, 'wallet_erosion': {'chg_3v6_monthly_pct_max': 0.02, 'capture_chg_6m_le': 0.0}}. Test: presisi top-5 34% → 34%; alarm palsu/100/bln 5.75 → 4.88.
*Semua usulan berstatus shadow (pasca-evaluasi); angka resmi tetap NB06.*
