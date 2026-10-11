# BNI Ecosystem & Growth Intelligence

Capstone Kelompok 8, ODP BNI Data Analytics Batch 2. Seluruh data bersifat **sintetis** dan dibangkitkan oleh notebook 01.

## Struktur folder

```
bni-eccosystem-intelligence/
├── data/
│   ├── archive/                 # paket asli BNI_EGI_0x_*.zip (notebook + CSV + generator)
│   ├── interim/                 # OUTPUT notebook 02 = INPUT notebook 03
│   │   └── split.csv            # holdout test (dev / holdout / unlabeled)
│   ├── processed/               # OUTPUT notebook 03 = INPUT notebook 04–07
│   │   ├── features_risk.csv.gz          # 1 baris/perusahaan (2.000) + split, cv_fold, risk_class
│   │   ├── features_anomaly_panel.csv.gz # 1 baris/nasabah-bulan (1.400 × 30)
│   │   ├── split.csv, feature_dictionary.csv
│   │   ├── feature_sets.json    # daftar set fitur (NB04 menambahkan set_noncredit & set_prospect)
│   │   └── eval_targets/        # ground truth turunan, hanya untuk evaluasi
│   └── raw/                     # OUTPUT notebook 01 = INPUT notebook 02–07
│       ├── *.csv                # 27 tabel (gt_* = ground truth, hanya untuk evaluasi)
│       ├── data_dictionary.csv  # peran tiap kolom: fitur / id / label / proxy-label / outcome / ground-truth
│       ├── generator_config.json
│       └── DATASHEET.md         # datasheet dataset (Gebru dkk., 2021)
├── notebooks/
│   ├── 01_Dataset_Generation_and_Validation.ipynb
│   ├── 03_Feature_Engineering.ipynb  # split train/valid/test, dataset fitur final, uji nilai fitur
│   ├── 04_Modelling.ipynb       # model risiko M0–M4 (OOF), gerbang promosi v0, anomali, skor v0
│   ├── 05_Optimization.ipynb    # perbaikan LR, HPO Optuna, SMOTE vs bobot, ensemble, kalibrasi, conformal, prospect, skor v1
│   └── BNI_EGI_Analysis_v6.ipynb
├── outputs/
│   ├── 01_dataset_validation/   # OUTPUT notebook 01
│   │   ├── validation_report.csv     # 7 lapis validasi (+ kolom tautan rujukan)
│   │   ├── network_tests.csv         # F2b: uji statistik jaringan vs graf acak
│   │   ├── significance_tests.csv    # F8: uji signifikansi pola tertanam
│   │   ├── references.csv            # daftar rujukan (DOI/URL, uji yang memakainya)
│   │   ├── REFERENCES.md             # daftar rujukan versi bertautan
│   │   ├── catatan_uji_validasi.csv  # 98 uji (F1–F8): hasil, statistik, insight, rujukan + tautan
│   │   ├── catatan_uji_validasi.md   # catatan yang sama, versi bacaan
│   │   └── figures/*.png
│   ├── 03_fe/                   # OUTPUT notebook 03: ablation, tier fitur, sinyal anomali online, figures/
│   ├── 04_modelling/            # OUTPUT notebook 04: hasil OOF, registri model, SUMMARY.md, figures/, predictions/
│   ├── 05_optimization/         # OUTPUT notebook 05: HPO, kalibrasi, gerbang, model_registry.csv, SUMMARY.md, figures/
│   ├── scores/                  # skor dashboard: risk_scores (v1 NB05; arsip v0 NB04 *_v0_nb04.csv), anomaly_alerts, shadow_log
│   └── ...                      # hasil notebook analisis (csv, img/)
├── models/
│   ├── 04_modelling/            # OUTPUT notebook 04: 18 model final *.joblib (tidak masuk git), manifest.json, model_files.csv
│   └── 05_optimization/         # OUTPUT notebook 05: champion__<set>.joblib (terkalibrasi), domain_model.joblib, manifest.json
├── src/
│   ├── egi_generator.py         # generator yang sama dengan notebook 01, dalam bentuk modul
│   ├── features.py              # modul fitur notebook 03 (PeerZScaler, load_features) — dipakai notebook 04+
│   ├── modelling.py             # OrdinalMonotone + arah monoton; wajib ada di sys.path untuk joblib.load model
│   └── modelling_nb05.py        # RiskModel, EnsembleModel, kalibrator, metrik, conformal (notebook 05+)
├── scripts/
│   └── build_catatan_uji.py     # membuat catatan_uji_validasi.csv/.md dari output notebook 01
├── pages/                       # halaman Streamlit
├── requirements.txt             # versi pustaka terkunci (snapshot .venv)
├── .env.example                 # contoh variabel lingkungan (.env tidak masuk git)
└── app.py                       # dashboard Streamlit
```

Semua notebook mencari akar proyek (folder yang berisi `pyproject.toml`), jadi path tetap benar walaupun notebook dijalankan dari folder `notebooks/`.

## Menjalankan

```bash
uv sync                                   # pasang dependensi (atau tanpa uv: pip install -r requirements.txt)
cp .env.example .env                      # isi OPENAI_API_KEY bila memakai fitur LLM
# lalu jalankan notebooks/01_Dataset_Generation_and_Validation.ipynb (±5 menit), atau tanpa validasi:
python src/egi_generator.py --seed 2026   # hanya membangkitkan data ke data/raw/ (±1 menit)
python scripts/build_catatan_uji.py       # perbarui catatan uji setelah notebook 01 dijalankan ulang
# lalu notebooks/03_Feature_Engineering.ipynb (±3–5 menit) → data/processed/
# lalu notebooks/04_Modelling.ipynb (±2–5 menit)        → outputs/04_modelling/, models/04_modelling/, outputs/scores/ (v0)
# lalu notebooks/05_Optimization.ipynb (±5–10 menit)    → outputs/05_optimization/, models/05_optimization/, outputs/scores/ (v1)
```

`data/raw/transactions.csv` (±104 MB) tidak masuk git karena melebihi batas GitHub. Bangkitkan ulang dengan salah satu cara di atas, atau ekstrak dari `data/archive/`.

Notebook 02 (EDA) belum ada di repo. `data/interim/split.csv` diambil dari split paket `BNI_EGI_03_FE_v8` (test = holdout notebook 02), jadi notebook 03 menghasilkan split train/valid/test yang sama. `transactions_clean` tidak wajib karena notebook 03 membersihkan ulang dari `data/raw/transactions.csv`.

## Aturan pemakaian data (notebook 02–07)

- Pakai hanya kolom dengan `peran = fitur` di `data/raw/data_dictionary.csv`.
- `gt_*` hanya untuk evaluasi. `outcome_product_adoption` hanya untuk validasi karena terjadi setelah cutoff 30 Jun 2026.
- `collectibility`, `max_dpd_12m`, `watchlist_flag`, dan `restructuring_flag` adalah proxy label, jadi tidak boleh dipakai sebagai fitur model risiko.
