
**Risiko (OOF 5-fold, 800 nasabah kredit, set_core 40 fitur)**
- Champion **M1** (Logistic regression (scorecard)): macro-F1 0.688 (95%: 0.652–0.725), recall High 0.79, Brier 0.360. Patokan NB03: 0,677 (CV) / 0,698 (train→valid).
- Challenger terbaik M4 (LightGBM ordinal monoton): ΔF1 +0.014, p = 0.24 → belum lolos gerbang.
- Uji logika: model pohon ordinal monoton lolos 100%; LR lolos 15/23 arah (efek kolinearitas antar-fitur timing/arus kas) → bahan NB05.
- Lapis 3: recall High 90% dicapai dengan ambang P(High) 0.159; macro-F1 turun ke 0.614.
- Conformal v0 (α = 10%): cakupan 90.1%; 50% kasus otomatis dengan macro-F1 0.765, sisanya Review analis.
- Skor v0: flag High 28% nasabah kredit, 35% non-kredit, **60% prospect** → tanda pergeseran distribusi; prioritas NB05 (*importance weighting* + *weighted conformal*), dinilai ke GT prospect di NB06.

**Anomali (perusahaan non-test, 24 bulan)**
- Champion aturan: presisi top-30 30.4%, alarm palsu 5.75 per 100 nasabah per bulan, lead distress median 1 bln.
- Challenger skor gabungan: presisi top-30 26.7%, lead distress median 1 bln → shadow.
- Challenger 2 Isolation Forest (anggaran alarm = champion): presisi top-30 jenis apa pun 37.6% (champion 47.5%), lead distress median 0 bln → tidak lolos, tetap pembanding.

**Catatan implementasi:** XGBoost & LightGBM asli.
