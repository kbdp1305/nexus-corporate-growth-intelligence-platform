# Datasheet — BNI EGI Synthetic Dataset v8

*Dibangkitkan oleh notebook `01_Dataset_Generation_and_Validation.ipynb` (seed 2026). Format: Gebru dkk. (2021). Seluruh data SINTETIS — tidak ada data nasabah riil atau data pribadi.*

## 1. Motivasi
Mendukung capstone BNI Ecosystem & Growth Intelligence: Opportunity Score, klasifikasi risiko, deteksi anomali "Why Now", white-space produk & geografis, analitik jaringan ekosistem, dan RM Copilot agentic. Setiap tugas punya ground truth (`gt_*`).

## 2. Komposisi
| File | Baris | Isi |
|---|---|---|
| `companies.csv` | 2,000 | Profil 2.000 perusahaan inti (nasabah kredit, nasabah non-kredit, prospect); kolom baru business_group |
| `financials.csv` | 3,672 | Laporan keuangan 2024–2025 (perusahaan tanpa laporan = hilang MNAR); kolom baru is_audited |
| `transactions.csv` | 1,078,362 | Transaksi per transaksi Jan 2024–Jun 2026 (prospect: hanya yang terlihat lewat counterparty BNI) |
| `product_master.csv` | 8 | Katalog 8 produk + segmen, manfaat, syarat, catatan harga, departemen (untuk grounding GenAI) |
| `product_holdings.csv` | 4,453 | Produk aktif nasabah per Jun 2026; open_month = bulan konversi untuk deal dari aksi RM |
| `geography.csv` | 40 | 40 kecamatan Jabodetabek; corporate_count & penetrasi diturunkan dari data |
| `branches.csv` | 40 | 40 cabang (tidak ada di kecamatan white-space) |
| `risk_labels.csv` | 1,000 | Rating internal nasabah kredit per Jun 2026 (mengandung ±5% kesalahan rating, lihat gt_client_risk) |
| `credit_facilities.csv` | 1,000 | Fasilitas kredit. PERINGATAN: collectibility, max_dpd_12m, watchlist_flag, restructuring_flag adalah PROXY LABEL — jangan dipakai sebagai fitur model risiko |
| `network_entities.csv` | 4,800 | Mitra non-inti (layer 1–2) dengan status nasabah BNI |
| `relationships.csv` | 20,104 | Relasi supplier/customer/distributor/subsidiary (rantai nilai + jarak + grup usaha); relationship_start & relationship_end |
| `bni_customer_master.csv` | 2,768 | Master nasabah BNI untuk modul company matching (opsional) |
| `external_company_registry.csv` | 5,400 | Registry eksternal untuk modul company matching (opsional) |
| `counterparty_transactions.csv` | 5,500 | Agregat 12 bln counterparty dengan nama mentah (typo, singkatan) untuk matching (opsional) |
| `rm_action_log.csv` | 2,000 | Aksi RM Jan–Jun 2026 + respons + feedback_note (bahan feedback loop & agent) |
| `outcome_product_adoption.csv` | 6,747 | Adopsi produk Jul–Sep 2026 (HANYA validasi; kolom baru deal_value_idr_mn) |
| `rm_visit_notes.csv` | 450 | BARU — catatan kunjungan RM (teks bebas, parafrase, ±40% berisi kalimat negasi) |
| `issue_product_map.csv` | 12 | BARU — 12 jenis masalah nasabah → produk solusi → departemen (dibaca agent, tidak di-hardcode) |
| `gt_prospect_risk.csv` | 600 | GT — kelas risiko prospect |
| `gt_anomaly_events.csv` | 1,130 | GT — 7 jenis kejadian (expansion, distress, early_warning, buyer_exit, contagion, wallet_erosion, spike) + arah & penyebab |
| `gt_counterparty_match.csv` | 5,500 | GT — identitas sebenarnya counterparty (matching) |
| `gt_client_risk.csv` | 1,000 | GT — kelas risiko nasabah sebelum kesalahan rating + penanda label salah |
| `gt_risk.csv` | 2,000 | GT — skor risiko laten, faktor tak teramati, kelas realisasi, oracle_class (plafon akurasi) |
| `gt_company_latent.csv` | 2,000 | GT — kesehatan, pertumbuhan, wallet share, regime, kejadian, legal, peluang laporan hilang, efek grup |
| `gt_product_need.csv` | 16,000 | GT — kebutuhan produk sebenarnya + apakah dilayani bank lain |
| `gt_visit_issues.csv` | 870 | GT — masalah yang benar-benar ada (present=1) / dinegasikan (present=0) di tiap catatan kunjungan |
| `gt_transaction_flags.csv` | 271 | GT — transaction_id lonjakan sesaat (spike) |

Satuan: transaksi & saldo Rp juta (`_idr_mn`), laporan keuangan Rp miliar (`_idr_bn`). Periode fitur 2024-01–2026-06 (cutoff 2026-06-30); outcome 2026-07–2026-09.

## 3. Proses pembuatan
Model kausal 18 tahap (lihat notebook bagian B & D): kondisi tersembunyi (kesehatan, pertumbuhan, efek grup, kejadian, kebutuhan) → semua tabel teramati.
Parameter utama: σ faktor tak teramati 0.25, kesalahan rating 4%, ambang kelas kuantil (0.57, 0.82), grup usaha 8%, skala gravitasi 8.0 km, relasi baru 7%.

### Pola yang ditanam (dapat dipulihkan dari data teramati — lihat F4b)
| Pola | Fitur/analisis yang menangkap |
|---|---|
| Level rasio struktural per industri × ukuran (tidak sejalan dengan risiko) | rasio relatif-peer |
| Laporan keuangan hilang MNAR | indikator tidak melapor / tidak diaudit |
| Kas ketat kronis + sinyal dini 3 bulan sebelum distress (payroll, pajak, supplier) | pergeseran tgl payroll, % pajak telat, % payroll ≥ tgl 28 |
| Erosi wallet share (omzet tetap, inflow BNI turun) | divergensi omzet vs inflow BNI |
| Konsentrasi pembeli (porsi > 30% menambah risiko) | porsi pembeli terbesar, HHI |
| Efek berantai 2 anchor (Jul 2025, lag 2 bln, ∝ ketergantungan) | eksposur ke pembeli yang inflow-nya turun |
| Grup usaha dengan kesehatan berkorelasi | agregat risiko rekan grup (graf) |
| Rantai nilai + gravitasi + preferential attachment | derajat, PageRank, komunitas, jarak mitra |
| Musiman per industri (Lebaran, Desember) | inflow terkoreksi musiman |
| White-space: 6 kecamatan industri tanpa cabang | penetrasi per kecamatan |

## 4. Masalah kualitas data yang disengaja
- Duplikat transaksi ±0.3%, nominal nol, `channel` kosong ±0.5%, `counterparty_id` kosong ±1%; EBIT/bunga kosong ±1.2%.
- Laporan keuangan tidak tersedia untuk sebagian perusahaan (MNAR — bukan acak).
- Nama counterparty mentah (typo, singkatan, huruf kapital, kota kosong).

## 5. Aturan pemakaian (lihat kolom `peran` di `data_dictionary.csv`)
- `gt_*` = **hanya evaluasi**. `outcome_product_adoption` = **hanya validasi** (terjadi setelah cutoff).
- `credit_facilities`: collectibility, max_dpd_12m, watchlist_flag, restructuring_flag = **proxy label** → dilarang sebagai fitur model risiko.
- Hasil model pada data ini membuktikan cara kerja pipeline, bukan performa pada data riil BNI.

## 6. Keterbatasan
- Distribusi dikalibrasi agar wajar (Benford, ekor tebal, musiman, struktur jaringan), bukan direplikasi dari data riil; metrik fidelitas berbasis data riil (α-precision/β-recall, Alaa dkk. 2022) tidak dapat dihitung.
- Koordinat ilustratif (pusat kecamatan + derau). Catatan kunjungan dari templat parafrase — variasi bahasanya lebih sempit daripada catatan RM sungguhan.

## 7. Validasi
7 lapis (F1–F7) + uji statistik jaringan (F2b) + uji signifikansi (F8): 98 uji — 92 lolos, 0 gagal, 6 informasi. Rincian: `outputs/01_dataset_validation/validation_report.csv`, `outputs/01_dataset_validation/network_tests.csv`, `outputs/01_dataset_validation/significance_tests.csv`.

## 8. Pemeliharaan
Generator deterministik (seed). Ubah parameter di `CFG`, jalankan ulang notebook; seluruh validasi ikut dijalankan ulang.