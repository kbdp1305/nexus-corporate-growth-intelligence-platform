# Kartu Model — Klasifikasi Risiko Nasabah Korporasi (BNI EGI, data sintetis v8)
*Dibuat otomatis oleh NB06 · 11 Oct 2026 16:27 · kunci evaluasi 2026-10-11T16:27:02*

## Ringkasan
- **Model**: XGBoost ordinal monoton (2 model biner P(>Low), P(>Medium)), 40 fitur `set_core`; penyeimbangan `balanced`; kalibrasi temperature + prior.
- **Keputusan**: High bila P(High) ≥ 0.148 (recall High 90% di OOF); Low vs Medium dengan biaya harapan; conformal Mondrian per kelas (α 10%) → **Otomatis / Review analis**.
- **Pengguna**: Relationship Manager & analis risiko kredit korporasi. Model **mendukung**, bukan menggantikan, keputusan kredit.

## Kinerja di test (200 nasabah kredit, dinilai sekali)
| Metrik | Champion | Pembanding (M1_v0) |
|---|---|---|
| macro-F1 keputusan | 0.633 (0.558–0.701) | 0.574 |
| recall High | 0.89 (0.76–1.00) | 0.82 |
| flag High | 53 | 56 |
| biaya (matriks §5.4) | 93 | 108 |
| AUC High · Brier | 0.932 · 0.339 | 0.913 · 0.354 |
| % otomatis | 44% | 50% |

- Cakupan conformal: 91.5% (High 92.9%); kasus otomatis macro-F1 0.825.
- Terhadap kelas sebenarnya (label rating ±4–5% salah): macro-F1 0.660.
- Prospect (GT): macro-F1 0.566, recall High 0.96, flag High 54% vs High sebenarnya 29%.
- Anomali (aturan, perusahaan test, k = 5): presisi top-k 34%, lead time distress median 0 bln.

## Dampak bisnis (ilustrasi, asumsi di `assumptions.csv`)
Nilai bersih per 200 nasabah test: champion Rp 6,492 jt vs pembanding Rp 5,099 jt (selisih 95%: 141 … 3,112 jt).

## Batasan
- Data **sintetis**; angka tidak bisa diklaim berlaku di portofolio riil. Plafon realistis macro-F1 ±0,83 (driver risiko tak teramati).
- Test kecil (±28 High) → rentang lebar. Label rating berisik (±4–5%).
- Prospect bergeser dari nasabah (C2ST AUC 0.79); GT nasabah non-kredit tidak tersedia.
- Aturan anomali belum dioptimasi; presisi alarm beberapa jenis rendah (lihat NB04/NB06 H).

## Risiko & mitigasi
- **Salah tolak/flag** → semua kasus ragu (himpunan conformal > 1 kelas) diteruskan ke analis beserta 3 alasan.
- **Logika bisnis** → batasan monoton di 27 fitur; uji arah 100% lolos.
- **Drift** → champion vs challenger dalam mode shadow, log audit, kalibrasi ulang berkala.
- **Penyalahgunaan** → bukan dasar tunggal keputusan kredit; tidak memakai atribut pribadi.
