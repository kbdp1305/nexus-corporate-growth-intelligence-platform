
**Champion XGBoost di test**: macro-F1 keputusan 0.633 vs M1_v0 0.574 (Δ +0.058, 95% -0.010…+0.127); recall High 0.89; flag High 53 vs 56; biaya 93 vs 108.
**OOF → test**: macro-F1 keputusan 0.653 → 0.633.
**Conformal di test**: cakupan 91.5%, High 92.9%; 44% otomatis.
**Label berisik**: pada label yang salah, model menebak kelas sebenarnya 68%.
**Prospect**: flag High 54% vs High sebenarnya 29%; macro-F1 0.566.
**Anomali (test)**: presisi top-5 34%; Isolation Forest sebagai pembanding di `anomaly_isolation_forest_vs_rules.csv`.
**Dampak**: nilai bersih champion − pembanding Rp 1,375 jt per 200 nasabah (asumsi ilustratif).
