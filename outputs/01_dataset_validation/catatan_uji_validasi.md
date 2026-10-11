# Catatan uji validasi — Notebook 01 Dataset Generation & Validation

Dibuat otomatis oleh `scripts/build_catatan_uji.py` dari hasil notebook 01. Versi tabel: `catatan_uji_validasi.csv`.

**98 uji — 92 lolos, 0 gagal, 6 informasi** (informasi = angka konteks tanpa target lolos/gagal).

## Ringkasan per lapis

| Lapis | Pertanyaan | Lolos | Gagal | Info |
|---|---|---|---|---|
| F1 Verifikasi | Apakah aturan & integritas data terpenuhi? (Sargent 2013 — verifikasi) | 13 | 0 | 0 |
| F2 Kewajaran | Apakah pola statistiknya mirip dunia nyata (stylized facts)? | 16 | 0 | 1 |
| F2b Uji jaringan | Apakah struktur jaringan berbeda nyata dari graf acak dengan jumlah mitra yang sama? | 8 | 0 | 2 |
| F3 Kondisi ekstrem | Apakah generator bereaksi logis bila parameter diubah, dan stabil antar-seed? | 7 | 0 | 0 |
| F4 Sinyal | Apakah polanya bisa dipelajari tetapi tidak terlalu mudah (tidak trivial)? | 18 | 0 | 0 |
| F4b Pemulihan pola | Apakah pola yang ditanam bisa ditemukan kembali dari data teramati? | 9 | 0 | 1 |
| F5 Kebocoran | Apakah ada informasi masa depan / label yang menyusup ke fitur? | 7 | 0 | 1 |
| F6 Privasi | Apakah ada data pribadi riil? | 2 | 0 | 1 |
| F7 Dokumentasi | Apakah dataset terdokumentasi? | 2 | 0 | 0 |
| F8 Signifikansi | Apakah pola tertanam signifikan secara statistik (bukan kebetulan sampel)? | 10 | 0 | 0 |

## Cara membaca

- **Hasil**: nilai yang diamati pada data. **Statistik**: uji statistik, p-value, z, atau CI95% (hanya F2b & F8).
- **z** = seberapa jauh nilai nyata dari rata-rata graf/label acak, dalam satuan simpangan baku. **p** = peluang hasil sebesar itu muncul kebetulan.
- F8 memakai koreksi Bonferroni (α = 0,05/9 ≈ 0,0056) karena ada 9 uji beda sekaligus. Dengan ribuan perusahaan, efek kecil pun mudah signifikan, jadi lihat juga besar efek dan CI-nya.
- p-value permutasi F2b terbatas oleh jumlah graf acak (p terkecil = 1/(50+1) ≈ 0,02); z-nya yang menunjukkan seberapa ekstrem.

## F1 Verifikasi

*Apakah aturan & integritas data terpenuhi? (Sargent 2013 — verifikasi)*

| Kode | Uji | Hasil | Target | Status | Insight | Rujukan |
|---|---|---|---|---|---|---|
| F1-01 | kunci utama unik | semua unik | 0 duplikat | ✅ LOLOS | Setiap baris master bisa dirujuk tanpa ambigu; join antartabel di EDA/feature engineering tidak akan menggandakan baris. | [Sargent (2013)](https://ideas.repec.org/a/taf/tjsmxx/v7y2013i1p12-24.html) |
| F1-02 | foreign key valid | semua valid | 0 pelanggaran | ✅ LOLOS | Semua relasi antartabel menunjuk ke entitas yang ada, jadi tidak ada "transaksi yatim" yang hilang saat join. | [Sargent (2013)](https://ideas.repec.org/a/taf/tjsmxx/v7y2013i1p12-24.html) |
| F1-03 | koordinat di dalam Jabodetabek | 0 di luar | 0 | ✅ LOLOS | Peta dan analisis jarak (gravitasi, white-space) tidak tercemar titik yang salah lokasi. | [Sargent (2013)](https://ideas.repec.org/a/taf/tjsmxx/v7y2013i1p12-24.html) |
| F1-04 | berdiri ≤ 2023 & onboarding ≥ tahun berdiri | 0 pelanggaran | 0 | ✅ LOLOS | Kronologi perusahaan masuk akal: tidak ada nasabah yang onboarding sebelum perusahaannya berdiri. | logika bisnis |
| F1-05 | aset = utang + ekuitas; aset lancar ≤ aset; laba ≤ omzet | 0.0% / 0.0% / 0.0% | 0% / 0% / 0% | ✅ LOLOS | Identitas neraca terpenuhi sehingga rasio keuangan (DER, current ratio, margin) bisa dihitung tanpa koreksi. | identitas akuntansi |
| F1-06 | DQ disengaja: duplikat & nominal nol | 3,225 (0.30%) / 105 | duplikat 0,1–0,6% | ✅ LOLOS | Masalah kualitas data sengaja ditanam dalam dosis yang terdokumentasi; notebook 02 wajib mendeduplikasi dan membuang nominal nol. | datasheet §4 |
| F1-07 | prospect tidak memiliki produk BNI | 0 baris | 0 | ✅ LOLOS | Definisi prospect konsisten: belum punya produk, jadi aman dipakai sebagai populasi akuisisi. | logika bisnis |
| F1-08 | fasilitas & rating hanya (dan selalu) untuk nasabah kredit | cocok | cocok 1:1 | ✅ LOLOS | Label risiko hanya ada untuk nasabah kredit, dan setiap nasabah kredit punya label; populasi modelling risiko jelas (1:1). | logika bisnis |
| F1-09 | semua nasabah memiliki Giro (rekening operasional) | 100% | 100% | ✅ LOLOS | Sesuai praktik bank: rekening operasional adalah produk dasar setiap nasabah. | logika bisnis |
| F1-10 | rentang tanggal transaksi | 2024-01-01 s.d. 2026-06-30 | 2024-01-01 s.d. 2026-06-30 | ✅ LOLOS | Tidak ada transaksi setelah cutoff, sehingga data fitur bersih dari informasi masa depan. | [Sargent (2013)](https://ideas.repec.org/a/taf/tjsmxx/v7y2013i1p12-24.html) |
| F1-11 | tidak ada transaksi dengan mitra sebelum relasi dimulai | 0 pasangan dari 13,135 | 0 | ✅ LOLOS | Urutan sebab-akibat terjaga: transaksi baru muncul setelah relasi dagang dimulai. | urutan sebab–akibat |
| F1-12 | pembeli yang keluar tidak membayar lagi setelah bulan keluar | 0 transaksi | 0 | ✅ LOLOS | Kejadian "buyer keluar" benar-benar memutus arus kas, jadi sinyalnya bisa dideteksi dari transaksi. | urutan sebab–akibat |
| F1-13 | produk dibuka antara onboarding dan cutoff | 0 pelanggaran | 0 | ✅ LOLOS | Tanggal pembukaan produk logis; tidak ada produk dibuka sebelum jadi nasabah atau setelah cutoff. | urutan sebab–akibat |

## F2 Kewajaran

*Apakah pola statistiknya mirip dunia nyata (stylized facts)?*

| Kode | Uji | Hasil | Target | Status | Insight | Rujukan |
|---|---|---|---|---|---|---|
| F2-01 | Benford digit pertama (MAD) | 0.0004 (close) | ≤ 0,012 | ✅ LOLOS | Sebaran digit pertama nominal transaksi sangat mirip data keuangan riil (kategori "close" menurut Nigrini), tanda angka tidak dibangkitkan secara seragam/artifisial. | [Nigrini (2012)](https://doi.org/10.1002/9781119203094) |
| F2-02 | ekor tebal nominal: p99 / median | 31× | ≥ 20× | ✅ LOLOS | Nominal transaksi berekor tebal seperti dunia nyata: sedikit transaksi sangat besar. Implikasi: pakai log-transform/median, bukan mean. | stylized fact |
| F2-03 | puncak Lebaran (indeks inflow 2025-03 / 2026-03) | 1.17 / 1.24 | > 1,05 | ✅ LOLOS | Inflow naik di bulan Lebaran pada kedua tahun; fitur tren harus dikoreksi musiman agar lonjakan Lebaran tidak dikira anomali. | [Bank Indonesia — Survei Penjualan Eceran](https://www.google.com/search?q=Survei%20Penjualan%20Eceran%20%28Indeks%20Penjualan%20Riil%29%20Bank%20Indonesia) |
| F2-04 | puncak Desember konstruksi (indeks) | 1.34 | > 1,10 | ✅ LOLOS | Konstruksi memuncak di Desember (realisasi proyek akhir tahun); musiman berbeda per industri sehingga koreksi harus per industri. | pola realisasi proyek akhir tahun |
| F2-05 | payroll di akhir bulan (tgl ≥ 25) | 100% | ≥ 80% | ✅ LOLOS | Pola gajian sesuai praktik (akhir bulan); pergeseran tanggal gaji menjadi sinyal dini yang bermakna. | pola gajian |
| F2-06 | THR: payroll Maret vs bulan lain | 1.88× | 1,6–2,2× | ✅ LOLOS | Payroll bulan Lebaran ±2× bulan biasa, sesuai kewajiban THR; lonjakan ini wajar dan bukan anomali. | [PP No. 36 Tahun 2021](https://www.google.com/search?q=Peraturan%20Pemerintah%20tentang%20Pengupahan%20%28termasuk%20THR%29%20Republik%20Indonesia) |
| F2-07 | volatilitas inflow menurun dengan ukuran (median CV 2024) | Kecil 0.21 > Menengah 0.18 > Besar 0.13 | monoton turun | ✅ LOLOS | Perusahaan besar lebih stabil (Stanley dkk.); ambang anomali sebaiknya relatif terhadap ukuran. | [Stanley dkk. (1996)](https://doi.org/10.1038/379804a0) |
| F2-08 | omzet ~ karyawan (Spearman) | 0.93 | ≥ 0,5 | ✅ LOLOS | Omzet dan jumlah karyawan sangat berkorelasi, jadi ukuran perusahaan konsisten antartabel. | kewajaran |
| F2-09 | median omzet Kecil < Menengah < Besar (Rp miliar) | 9 < 35 < 176 | monoton | ✅ LOLOS | Kelas ukuran sesuai omzet; segmentasi Kecil/Menengah/Besar bermakna. | kewajaran |
| F2-10 | proporsi Low / Medium / High | 61% / 25% / 14% | High 8–22% | ✅ LOLOS | Kelas tidak seimbang (High minoritas) seperti portofolio riil; modelling perlu stratified split dan metrik macro-F1/recall High. | kewajaran portofolio |
| F2-11 | derajat berekor tebal (maks / median) | 18× (maks 144) | ≥ 10× | ✅ LOLOS | Ada sedikit anchor dengan sangat banyak mitra; anchor ini titik kritis efek berantai dan target prioritas ekosistem. | [Barabási & Albert (1999)](https://doi.org/10.1126/science.286.5439.509) |
| F2-12 | indeks ekor (Hill, 5% teratas) derajat | α = 2.13 | informasi (jaringan produksi Jepang ±1,3) | ℹ️ info | Informasi: ekor derajat lebih "ringan" dari jaringan produksi Jepang (α ±1,3); wajar untuk 2.000 perusahaan di satu wilayah. | [Fujiwara & Aoyama (2010)](https://doi.org/10.1140/epjb/e2010-00275-2) |
| F2-13 | asortativitas derajat | -0.138 | < 0 (disasortatif) | ✅ LOLOS | Jaringan disasortatif: perusahaan kecil terhubung ke anchor besar, seperti rantai pasok riil. | [Newman (2002)](https://doi.org/10.1103/PhysRevLett.89.208701) |
| F2-14 | resiprositas (A jual ke B dan B jual ke A) | 2.4% | < 10% | ✅ LOLOS | Arah jual-beli jelas (jarang dua arah), sehingga peran pemasok vs pembeli bisa dibaca dari graf. | struktur rantai pasok |
| F2-15 | relasi mengikuti rantai nilai (porsi jalur kuat vs acak) | 74% vs 37% | ≥ 1,5× acak | ✅ LOLOS | Relasi dagang mengikuti logika input-output antarindustri, bukan acak; rekomendasi produk berbasis rantai nilai masuk akal. | [BPS — Tabel Input–Output](https://www.google.com/search?q=Tabel%20Input%E2%80%93Output%20Indonesia%20Badan%20Pusat%20Statistik) |
| F2-16 | mitra dagang berdekatan (median jarak nyata vs acak) | 5.1 km vs 14.7 km | nyata < 0,8 × acak | ✅ LOLOS | Mitra cenderung berdekatan (efek gravitasi); fitur jarak dan klaster lokasi informatif. | [Bernard, Moxnes & Saito (2019)](https://doi.org/10.1086/700764) |
| F2-17 | modularitas Louvain vs graf acak berderajat sama | Q = 0.487 vs 0.289 (8 komunitas) | Q > Q_acak + 0,05 | ✅ LOLOS | Jaringan punya komunitas yang jauh lebih kuat dari graf acak; deteksi komunitas layak dipakai untuk segmentasi ekosistem. | [Blondel dkk. (2008)](https://doi.org/10.1088/1742-5468/2008/10/P10008); [Newman (2006)](https://doi.org/10.1073/pnas.0601602103) |

## F2b Uji jaringan

*Apakah struktur jaringan berbeda nyata dari graf acak dengan jumlah mitra yang sama?*

| Kode | Uji | Hasil | Statistik | Target | Status | Insight | Rujukan |
|---|---|---|---|---|---|---|---|
| F2b-01 | modularitas Louvain vs graf acak berderajat sama | 0.4871 | observasi 0.4871 vs acak 0.2848 (sd 0.002108); z = 96.0; p = 0.01961 | lebih tinggi, p < 0,05 | ✅ LOLOS | Komunitas jauh lebih kuat daripada graf acak dengan jumlah mitra sama (z sangat besar); struktur komunitas bukan artefak derajat. | [Newman (2006)](https://doi.org/10.1073/pnas.0601602103); [Blondel dkk. (2008)](https://doi.org/10.1088/1742-5468/2008/10/P10008) |
| F2b-02 | koefisien klastering rata-rata vs graf acak | 0.02218 | observasi 0.02218 vs acak 0.01301 (sd 8.11e-04); z = 11.3; p = 0.01961 | lebih tinggi, p < 0,05 | ✅ LOLOS | Mitra-mitra saling terhubung lebih sering daripada acak (klaster lokal), sesuai jaringan produksi riil. | [Watts & Strogatz (1998)](https://doi.org/10.1038/30918) |
| F2b-03 | transitivitas (klastering global) vs graf acak | 0.02014 | observasi 0.02014 vs acak 0.01522 (sd 4.82e-04); z = 10.2; p = 0.01961 | lebih tinggi, p < 0,05 | ✅ LOLOS | Konfirmasi klastering global: segitiga relasi lebih banyak dari acak. | [Watts & Strogatz (1998)](https://doi.org/10.1038/30918) |
| F2b-04 | asortativitas derajat vs graf acak berderajat sama | -0.1378 | observasi -0.1378 vs acak -0.02385 (sd 0.006348); z = -17.9; p = 0.01961 | lebih disasortatif, p < 0,05 | ✅ LOLOS | Disasortativitas nyata, bukan sekadar konsekuensi distribusi derajat. | [Newman (2002)](https://doi.org/10.1103/PhysRevLett.89.208701); [Maslov & Sneppen (2002)](https://doi.org/10.1126/science.1065103) |
| F2b-05 | ekor derajat: lognormal vs eksponensial (k ≥ 8, n = 1734) | 243.8 | rasio log-likelihood R = 243.81 (uji Vuong); p = 3.26e-17 | R > 0 & p < 0,05 (ekor lebih berat dari eksponensial) | ✅ LOLOS | Ekor distribusi derajat lebih berat dari eksponensial: ada hub/anchor sungguhan. | [Clauset, Shalizi & Newman (2009)](https://doi.org/10.1137/070710111) |
| F2b-06 | ekor derajat: power-law (α = 2.97) vs lognormal | -0.151 | rasio log-likelihood R = -0.15 (uji Vuong); p = 0.7183 | informasi (R < 0 → lognormal lebih cocok) | ℹ️ info | Informasi: lognormal lebih cocok daripada power-law murni, sama seperti jaringan produksi riil. | [Clauset, Shalizi & Newman (2009)](https://doi.org/10.1137/070710111) |
| F2b-07 | komunitas sejalan dengan kota/kabupaten (NMI) | 0.5478 | observasi 0.5478 vs acak 0.003398 (sd 7.67e-04); z = 709.4; p = 0.004975 | lebih tinggi dari label acak, p < 0,05 | ✅ LOLOS | Komunitas jaringan sangat sejalan dengan kota/kabupaten (efek gravitasi), sehingga segmentasi ekosistem punya makna geografis. | [Danon dkk. (2005)](https://doi.org/10.1088/1742-5468/2005/09/P09008) |
| F2b-08 | komunitas sejalan dengan industri (NMI) | 0.01216 | observasi 0.01216 vs acak 0.004407 (sd 6.75e-04); z = 11.5; p = 0.004975 | lebih tinggi dari label acak, p < 0,05 | ✅ LOLOS | Komunitas hanya sedikit sejalan dengan industri (komunitas lintas industri = rantai nilai), signifikan tetapi kecil. | [Danon dkk. (2005)](https://doi.org/10.1088/1742-5468/2005/09/P09008) |
| F2b-09 | homophily grup: kemiripan indeks kesehatan (DER, CR, NPM relatif-peer) sesama anggota (n = 154) | 0.471 | observasi 0.471 vs acak 0.3375 (sd 0.06559); z = 2.0; p = 0.03393 | p < 0,05 | ✅ LOLOS | Anggota grup usaha memiliki kesehatan keuangan yang mirip (signifikan), jadi fitur agregat grup layak dicoba. | [Khanna & Yafeh (2007)](https://doi.org/10.1257/jel.45.2.331) |
| F2b-10 | homophily grup pada label High (n = 93 nasabah kredit dalam grup) | 0.004444 | observasi 0.004444 vs acak 7.25e-04 (sd 0.1284); z = 0.0; p = 0.5435 | informasi (sampel kecil) | ℹ️ info | Informasi: pada label High efek grup belum signifikan karena sampel kecil (±90 nasabah). | [Khanna & Yafeh (2007)](https://doi.org/10.1257/jel.45.2.331) |

## F3 Kondisi ekstrem

*Apakah generator bereaksi logis bila parameter diubah, dan stabil antar-seed?*

| Kode | Uji | Hasil | Target | Status | Insight | Rujukan |
|---|---|---|---|---|---|---|
| F3-01 | porsi High: boom < normal < krisis | boom 6% < normal 18% < krisis 41% | monoton naik | ✅ LOLOS | Generator bereaksi logis: krisis menaikkan porsi risiko tinggi, boom menurunkannya. Bisa dipakai untuk stress test model. | [Sargent (2013)](https://ideas.repec.org/a/taf/tjsmxx/v7y2013i1p12-24.html) |
| F3-02 | krisis: DER naik & current ratio turun (median) | DER 1.22→1.81; CR 1.41→1.17 | DER↑ CR↓ | ✅ LOLOS | Saat krisis leverage naik dan likuiditas turun, sesuai intuisi analis kredit. | [Sargent (2013)](https://ideas.repec.org/a/taf/tjsmxx/v7y2013i1p12-24.html) |
| F3-03 | krisis menambah kejadian distress | 6.2% → 9.0% | naik | ✅ LOLOS | Kejadian distress bertambah saat krisis; label anomali ikut bergerak bersama kondisi ekonomi. | [Sargent (2013)](https://ideas.repec.org/a/taf/tjsmxx/v7y2013i1p12-24.html) |
| F3-04 | σ faktor tak teramati ↑ → plafon macro-F1 ↓ | 0.90 > 0.83 > 0.73 > 0.66 | monoton turun | ✅ LOLOS | Makin banyak faktor yang tidak terekam, makin rendah akurasi maksimum. Plafon akurasi model memang terkendali oleh desain. | [Sargent (2013)](https://ideas.repec.org/a/taf/tjsmxx/v7y2013i1p12-24.html) |
| F3-05 | skala gravitasi ↑ → jarak mitra ↑ (median km) | λ4: 2.6 < λ12: 6.9 < λ40: 9.7 | monoton naik | ✅ LOLOS | Parameter jarak bekerja sesuai arah yang diharapkan; struktur jaringan bisa diatur dan diuji. | [Sargent (2013)](https://ideas.repec.org/a/taf/tjsmxx/v7y2013i1p12-24.html) |
| F3-06 | multi-seed (3 seed): plafon macro-F1 stabil | 0.824 ± 0.005 | sd ≤ 0,03 | ✅ LOLOS | Plafon akurasi stabil antar-seed, jadi hasil tidak bergantung pada satu keberuntungan acak. | [Sargent (2013)](https://ideas.repec.org/a/taf/tjsmxx/v7y2013i1p12-24.html) |
| F3-07 | pola tertanam tetap muncul di seed lain | anchor 2/2 · dosis–respons -20% · pajak telat High/Low 3.3× | anchor 2/2, dosis ≤ −10 poin, rasio ≥ 2× | ✅ LOLOS | Pola bisnis (anchor, dosis-respons, pajak telat) muncul juga di seed lain; bukan kebetulan satu dataset. | [Sargent (2013)](https://ideas.repec.org/a/taf/tjsmxx/v7y2013i1p12-24.html) |

## F4 Sinyal

*Apakah polanya bisa dipelajari tetapi tidak terlalu mudah (tidak trivial)?*

| Kode | Uji | Hasil | Target | Status | Insight | Rujukan |
|---|---|---|---|---|---|---|
| F4-01 | plafon macro-F1 (oracle: tahu skor laten) | 0.833 | 0,78–0,88 | ✅ LOLOS | Bahkan model yang tahu skor laten tidak sempurna (ada faktor tak teramati + salah rating). Target realistis model nyata berada di bawah angka ini. | Bayes error |
| F4-02 | risiko dari laporan keuangan saja (LR, 5-fold) | macro-F1 0.634 | 0,50–0,75 (tidak trivial) | ✅ LOLOS | Laporan keuangan saja memberi sinyal sedang; perlu fitur transaksi dan jaringan untuk mendekati plafon. Data tidak trivial. | [Wu & Keogh (2021)](https://doi.org/10.1109/TKDE.2021.3112126) |
| F4-03 | risiko dari laporan keuangan saja (RF, 5-fold) | macro-F1 0.610 | 0,50–0,75 (tidak trivial) | ✅ LOLOS | Model non-linear pun tidak jauh lebih baik dengan fitur keuangan saja, jadi nilai tambah harus datang dari feature engineering. | [Wu & Keogh (2021)](https://doi.org/10.1109/TKDE.2021.3112126) |
| F4-04 | kesalahan rating tercatat | 4.4% | 2–6% | ✅ LOLOS | Sekitar 4% label salah (seperti kesalahan analis riil) dan tercatat di GT; berguna untuk analisis kesalahan di notebook 07. | [Northcutt, Jiang & Chuang (2021)](https://doi.org/10.1613/jair.1.12125) |
| F4-05 | laporan hilang MNAR: % hilang High vs Low (prospect) | 40% vs 9% | High ≥ 2× Low | ✅ LOLOS | Laporan keuangan lebih sering hilang pada perusahaan berisiko tinggi; ketiadaan laporan itu sendiri adalah sinyal (buat indikator missing, jangan sekadar imputasi). | [Rubin (1976)](https://doi.org/10.1093/biomet/63.3.581) |
| F4-06 | prospect vs nasabah: AUC propensity / pMSE | AUC 0.693 / pMSE 0.0244 | AUC 0,60–0,80 (beda wajar) | ✅ LOLOS | Prospect dan nasabah berbeda secara wajar (tidak identik, tidak terpisah sempurna); model yang dilatih di nasabah masih relevan untuk prospect. | [Woo dkk. (2009)](https://doi.org/10.29012/jpc.v1i1.568); [Snoke dkk. (2018)](https://doi.org/10.1111/rssa.12358) |
| F4-07 | aturan 1 baris menemukan anomali NAIK (AUC) | 0.763 | < 0,80 | ✅ LOLOS | Aturan sederhana hanya menangkap sebagian anomali naik; masih ada ruang bagi model anomali yang lebih baik. | [Wu & Keogh (2021)](https://doi.org/10.1109/TKDE.2021.3112126) |
| F4-08 | aturan 1 baris menemukan anomali TURUN (AUC) | 0.780 | < 0,80 | ✅ LOLOS | Sama untuk anomali turun: tidak trivial, sehingga deteksi "Why Now" layak dimodelkan. | [Wu & Keogh (2021)](https://doi.org/10.1109/TKDE.2021.3112126) |
| F4-09 | jenis kejadian | expansion 330, spike 198, contagion 142, distress 125, early_warning 125, wallet_erosion 115, buyer_exit 95 | ≥ 6 jenis | ✅ LOLOS | Tujuh jenis kejadian tersedia dengan jumlah memadai untuk evaluasi deteksi anomali per jenis. | Why Now |
| F4-10 | tingkat adopsi produk Jul–Sep | 10.6% | 8–18% | ✅ LOLOS | Tingkat adopsi realistis (minoritas), jadi model rekomendasi perlu dievaluasi dengan precision@k/lift, bukan akurasi. | kewajaran |
| F4-11 | adopsi bila butuh vs tidak | 42.6% vs 5.8% | lift ≥ 3× | ✅ LOLOS | Kebutuhan produk benar-benar mendorong adopsi (lift besar); opportunity score yang menebak kebutuhan akan berguna. | konsistensi kausal |
| F4-12 | produk dimiliki tanpa kebutuhan | 3.9% | ≤ 5% | ✅ LOLOS | Sedikit sekali produk yang dimiliki tanpa kebutuhan, jadi kepemilikan produk konsisten dengan kebutuhan laten. | konsistensi kausal |
| F4-13 | konversi RM tercatat sebagai produk baru (bulan sama) | 100% | 100% | ✅ LOLOS | Setiap aksi RM yang berhasil tercatat sebagai produk baru; feedback loop RM bisa ditelusuri. | konsistensi kausal |
| F4-14 | counterparty transaksi ada di jaringan | 100% | ≥ 95% | ✅ LOLOS | Transaksi dan graf jaringan saling konsisten; fitur graf bisa diturunkan dari transaksi. | konsistensi kausal |
| F4-15 | payroll rutin (≥ 27 dari 30 bulan) | 100% nasabah | ≥ 95% | ✅ LOLOS | Hampir semua nasabah menggaji rutin, jadi absen atau telat gaji adalah sinyal kuat. | pola gajian |
| F4-16 | catatan dengan kalimat negasi (spesifikasi 40%) | 46% (n=450) | 40% ± 3 SE (33%–47%) | ✅ LOLOS | Catatan kunjungan mengandung negasi ("tidak ada masalah ..."), sehingga ekstraksi isu tidak bisa sekadar mencari kata kunci. | verifikasi spesifikasi |
| F4-17 | baseline kata kunci mengekstrak isu (F1) | P 0.61 · R 0.83 · F1 0.70 | 0,40–0,85 (ada ruang untuk LLM) | ✅ LOLOS | Baseline kata kunci recall-nya tinggi tetapi presisi rendah (tertipu negasi); ada ruang perbaikan untuk LLM/NLP. | ruang perbaikan GenAI |
| F4-18 | kecamatan penetrasi terendah tanpa cabang | 75% dari 8 terendah | ≥ 50% | ✅ LOLOS | White-space geografis tertanam dan bisa ditemukan dari data: kecamatan industri dengan penetrasi rendah tanpa cabang. | white-space tertanam |

## F4b Pemulihan pola

*Apakah pola yang ditanam bisa ditemukan kembali dari data teramati?*

| Kode | Uji | Hasil | Target | Status | Insight | Rujukan |
|---|---|---|---|---|---|---|
| F4b-01 | DER relatif-peer lebih informatif daripada DER mentah (AUC High) | 0.827 → 0.888 | naik ≥ 0,03 | ✅ LOLOS | DER yang dibandingkan dengan peer industri dan ukuran lebih prediktif daripada DER mentah; gunakan rasio relatif-peer di feature engineering. | pola level struktural |
| F4b-02 | % pajak telat (6 bln): High vs Low | 35% vs 8% | High ≥ 2× Low | ✅ LOLOS | Nasabah High jauh lebih sering telat bayar pajak; fitur keterlambatan pajak adalah early-warning yang kuat. | early-warning system |
| F4b-03 | % payroll ≥ tgl 28 (12 bln): High vs Low | 40% vs 14% | High ≥ 2× Low | ✅ LOLOS | Nasabah High lebih sering menggaji di akhir bulan (kas ketat); fitur tanggal gaji layak dipakai. | early-warning system |
| F4b-04 | event study distress: t−3…t−1 vs baseline | tgl payroll +1.64 hari; inflow +1% | payroll bergeser > 0,5 hari, inflow belum turun > 5% | ✅ LOLOS | Tanggal gaji sudah bergeser sebelum omzet turun, jadi sinyal dini muncul lebih dulu dan model bisa memberi peringatan sebelum kejadian. | [MacKinlay (1997)](https://www.jstor.org/stable/2729691) |
| F4b-05 | % High: pembeli terbesar < 20% vs ≥ 50% | 8% vs 27% | naik ≥ 2× | ✅ LOLOS | Ketergantungan pada satu pembeli besar menaikkan risiko; buat fitur porsi pembeli terbesar/HHI. | risiko konsentrasi |
| F4b-06 | anchor bermasalah terdeteksi dari inflow | ['C0299', 'C0409'] — cocok 2/2 | 2/2 | ✅ LOLOS | Anchor yang bermasalah bisa ditemukan hanya dari penurunan inflow, tanpa melihat GT. | efek berantai |
| F4b-07 | dosis–respons: Δ inflow pemasok terpapar ≥ 20% vs tidak terpapar | -18% vs +8% (n=47) | selisih ≤ −10 poin | ✅ LOLOS | Pemasok yang bergantung pada anchor bermasalah ikut turun inflow-nya (efek berantai); fitur eksposur ke anchor bermakna. | [Battiston dkk. (2012)](https://doi.org/10.1038/srep00541) |
| F4b-08 | inflow BNI turun > 25% & omzet naik → memang pindah bank | 67% dari 66 nasabah | ≥ 50% | ✅ LOLOS | Divergensi omzet naik tapi inflow BNI turun sebagian besar memang pindah bank (wallet erosion); aturan sederhana ini sudah jadi sinyal retensi. | erosi wallet share |
| F4b-09 | % High: punya rekan grup High vs tidak | 11% vs 11% (n=93) | informasi (sampel kecil) | ℹ️ info | Informasi: pada label, efek grup belum terlihat karena hanya ±90 nasabah kredit dalam grup (sampel kecil). | [Khanna & Yafeh (2007)](https://doi.org/10.1257/jel.45.2.331) |
| F4b-10 | korelasi kesehatan dalam grup (ICC kasar) | 0.41 | 0,15–0,50 | ✅ LOLOS | Di dunia laten, kesehatan anggota grup berkorelasi; fitur agregat grup berpotensi berguna walau sinyal di label masih lemah. | [Khanna & Yafeh (2007)](https://doi.org/10.1257/jel.45.2.331) |

## F5 Kebocoran

*Apakah ada informasi masa depan / label yang menyusup ke fitur?*

| Kode | Uji | Hasil | Target | Status | Insight | Rujukan |
|---|---|---|---|---|---|---|
| F5-01 | tidak ada data setelah cutoff 30 Jun 2026 | semua ≤ cutoff | semua ≤ cutoff | ✅ LOLOS | Tidak ada informasi masa depan di tabel fitur. | [Kaufman dkk. (2012)](https://doi.org/10.1145/2382577.2382579) |
| F5-02 | tanggal label = cutoff | 2026-06-30 | 2026-06-30 | ✅ LOLOS | Label diambil tepat di cutoff, sehingga fitur dan label sejajar waktunya. | [Kaufman dkk. (2012)](https://doi.org/10.1145/2382577.2382579) |
| F5-03 | outcome terjadi setelah cutoff (Jul–Sep 2026) | observation_end 2026-06 → kolom adopted_jul_sep_2026 | setelah cutoff | ✅ LOLOS | Adopsi produk terjadi setelah cutoff; evaluasi rekomendasi bersifat out-of-time yang jujur. | [Kaufman dkk. (2012)](https://doi.org/10.1145/2382577.2382579) |
| F5-04 | kolom ground truth tidak muncul di tabel teramati | tidak ada | tidak ada | ✅ LOLOS | Kolom GT tidak bocor ke tabel teramati. | [Kaufman dkk. (2012)](https://doi.org/10.1145/2382577.2382579) |
| F5-05 | AUC tunggal tertinggi di antara kolom berperan fitur | 0.815 (ebit_idr_bn) | < 0,90 | ✅ LOLOS | Tidak ada satu kolom fitur yang terlalu prediktif (indikasi bocor); performa tinggi harus datang dari kombinasi fitur. | [Kaufman dkk. (2012)](https://doi.org/10.1145/2382577.2382579) |
| F5-06 | kolom proxy-label memang sangat prediktif → dilarang | collectibility 0.85, max_dpd_12m 0.83, watchlist_flag 0.69, restructuring_flag 0.69 | ditandai di kamus data | ℹ️ info | Informasi: collectibility/DPD/watchlist/restrukturisasi hampir sama dengan label. Kolom-kolom ini DILARANG sebagai fitur model risiko. | [Kaufman dkk. (2012)](https://doi.org/10.1145/2382577.2382579) |
| F5-07 | nomor urut company_id tidak terkait label (AUC, uji Mann–Whitney) | 0.551 (z = 1.93) | \|z\| < 2,58 (p > 0,01) | ✅ LOLOS | Urutan ID tidak membawa informasi label, jadi aman (tidak ada kebocoran lewat ID). | [Kaufman dkk. (2012)](https://doi.org/10.1145/2382577.2382579); [Hanley & McNeil (1982)](https://doi.org/10.1148/radiology.143.1.7063747) |
| F5-08 | uji permutasi label (30×): F1 asli vs label acak | 0.634 vs 0.255 ± 0.004; p = 0.032 | acak ≈ 0,33; p < 0,05 | ✅ LOLOS | Model jauh lebih baik dari label acak, jadi sinyalnya nyata dan bukan hasil overfitting/kebetulan. | [Ojala & Garriga (2010)](https://jmlr.org/papers/v11/ojala10a.html) |

## F6 Privasi

*Apakah ada data pribadi riil?*

| Kode | Uji | Hasil | Target | Status | Insight | Rujukan |
|---|---|---|---|---|---|---|
| F6-01 | tidak ada kolom data pribadi (NIK/NPWP/telepon/email/alamat) | tidak ada | tidak ada | ✅ LOLOS | Tidak ada PII, sehingga sesuai pedoman capstone dan prinsip UU PDP. | [UU No. 27 Tahun 2022](https://www.google.com/search?q=Undang-Undang%20tentang%20Pelindungan%20Data%20Pribadi%20Republik%20Indonesia) |
| F6-02 | semua nama entitas berakhiran "(dummy)" | ya | ya | ✅ LOLOS | Semua nama jelas fiktif, tidak bisa tertukar dengan perusahaan riil. | [Jordon dkk. (2022)](https://arxiv.org/abs/2205.03257) |
| F6-03 | koordinat = pusat kecamatan + derau (bukan alamat) | median 1.6 km dari pusat | informasi | ℹ️ info | Informasi: koordinat hanya pusat kecamatan + derau, bukan alamat riil. | [Jordon dkk. (2022)](https://arxiv.org/abs/2205.03257) |

## F7 Dokumentasi

*Apakah dataset terdokumentasi?*

| Kode | Uji | Hasil | Target | Status | Insight | Rujukan |
|---|---|---|---|---|---|---|
| F7-01 | datasheet tersedia (motivasi, komposisi, proses, aturan, keterbatasan, validasi) | 7 KB | ada | ✅ LOLOS | Dataset terdokumentasi (motivasi, komposisi, aturan pakai); baca DATASHEET.md sebelum analisis. | [Gebru dkk. (2021)](https://doi.org/10.1145/3458723) |
| F7-02 | kamus data mencakup semua tabel & memberi peran tiap kolom | 213 kolom · 8 peran | semua tabel | ✅ LOLOS | Setiap kolom punya peran (fitur/id/label/proxy/GT); pakai kolom `peran` sebagai pagar anti-kebocoran. | [Gebru dkk. (2021)](https://doi.org/10.1145/3458723) |

## F8 Signifikansi

*Apakah pola tertanam signifikan secara statistik (bukan kebetulan sampel)?*

| Kode | Uji | Hasil | Statistik | Target | Status | Insight | Rujukan |
|---|---|---|---|---|---|---|---|
| F8-01 | Δ inflow pemasok terpapar ≥ 20% − tidak terpapar (selisih median) | -25.5% | Mann–Whitney U: statistik = 1.15e+04; p = 1.06e-12; n = 47 vs 1255; CI95% [-30.8%; -20.3%] | p < α Bonferroni (0,05/9) | ✅ LOLOS | Efek berantai signifikan dan besar: pemasok yang bergantung ≥ 20% pada anchor bermasalah turun inflow-nya jauh lebih dalam; CI tidak memuat nol. | [Mann & Whitney (1947)](https://doi.org/10.1214/aoms/1177730491); [Efron & Tibshirani (1993)](https://doi.org/10.1201/9780429246593) |
| F8-02 | korelasi eksposur ke anchor vs Δ inflow | -0.1541 | Spearman: statistik = -0.1541; p = 7.05e-09; n = 1398 | p < α Bonferroni (0,05/9) | ✅ LOLOS | Makin besar eksposur, makin besar penurunan (dosis-respons) — signifikan walau korelasinya lemah karena banyak pemasok tak terpapar. | [Spearman (1904)](https://doi.org/10.2307/1412159) |
| F8-03 | % pajak dibayar setelah tgl 15 (6 bln): High − Low | +26.7% | Mann–Whitney U: statistik = 6.68e+04; p = 1.74e-33; n = 137 vs 614; CI95% [+21.3%; +32.3%] | p < α Bonferroni (0,05/9) | ✅ LOLOS | Selisih High−Low besar dan sangat signifikan; fitur pajak telat kuat untuk model risiko. | [Mann & Whitney (1947)](https://doi.org/10.1214/aoms/1177730491); [Efron & Tibshirani (1993)](https://doi.org/10.1201/9780429246593) |
| F8-04 | % gaji dibayar ≥ tgl 28 (12 bln): High − Low | +26.6% | Mann–Whitney U: statistik = 7.18e+04; p = 3.74e-40; n = 137 vs 614; CI95% [+22.3%; +30.9%] | p < α Bonferroni (0,05/9) | ✅ LOLOS | Selisih High−Low besar dan sangat signifikan; fitur tanggal gaji kuat untuk model risiko. | [Mann & Whitney (1947)](https://doi.org/10.1214/aoms/1177730491); [Efron & Tibshirani (1993)](https://doi.org/10.1201/9780429246593) |
| F8-05 | % High naik dengan porsi pembeli terbesar (<20% → ≥50%): 8% → 11% → 12% → 17% → 27% | +19.0% | Cochran–Armitage: statistik = 4.796; p = 1.62e-06; n = 1000 | p < α Bonferroni (0,05/9) | ✅ LOLOS | Tren monoton dan signifikan: makin terkonsentrasi pembelinya, makin tinggi porsi High. | [Cochran (1954)](https://doi.org/10.2307/3001616); [Armitage (1955)](https://doi.org/10.2307/3001775) |
| F8-06 | presisi kuadran "inflow BNI turun > 25%, omzet naik" (porsi dasar 6.3%) | +66.7% | Binomial: statistik = 44; p = 5.91e-37; n = 66; CI95% [+54.0%; +77.8%] | p < α Bonferroni (0,05/9) | ✅ LOLOS | Aturan kuadran menemukan pindah bank dengan presisi jauh di atas porsi dasar; sinyal wallet erosion nyata. | [Clopper & Pearson (1934)](https://doi.org/10.1093/biomet/26.4.404) |
| F8-07 | event study: pergeseran tanggal gaji t−3…t−1 vs baseline (berpasangan) | 1.645 hari | Wilcoxon signed-rank: statistik = 89.5; p = 6.32e-12; n = 73; CI95% [1.357; 1.931] | p < α Bonferroni (0,05/9) | ✅ LOLOS | Gaji bergeser ±1–2 hari menjelang distress (berpasangan, signifikan), sehingga early warning bisa memberi lead time ±3 bulan. | [Wilcoxon (1945)](https://doi.org/10.2307/3001968); [MacKinlay (1997)](https://www.jstor.org/stable/2729691) |
| F8-08 | indeks inflow Lebaran 2025-03 (median; 1 = bulan normal) | 1.165 indeks | Wilcoxon (median > 1): statistik = 1.13e+05; p = 1.68e-137; n = 1400; CI95% [1.152; 1.178] | p < α Bonferroni (0,05/9) | ✅ LOLOS | Lonjakan Lebaran signifikan, jadi perlu koreksi musiman di fitur tren. | [Wilcoxon (1945)](https://doi.org/10.2307/3001968); [Efron & Tibshirani (1993)](https://doi.org/10.1201/9780429246593) |
| F8-09 | indeks inflow Lebaran 2026-03 (median; 1 = bulan normal) | 1.241 indeks | Wilcoxon (median > 1): statistik = 1.18e+05; p = 1.48e-133; n = 1400; CI95% [1.219; 1.264] | p < α Bonferroni (0,05/9) | ✅ LOLOS | Lonjakan Lebaran 2026 juga signifikan dan konsisten antartahun. | [Wilcoxon (1945)](https://doi.org/10.2307/3001968); [Efron & Tibshirani (1993)](https://doi.org/10.1201/9780429246593) |
| F8-10 | nominal transaksi berdistribusi lognormal (sampel 5.000) | -0.15 skew log | Kolmogorov–Smirnov: statistik = 0.01342; p = 0.3261; n = 5000 | p ≥ 0,05 (distribusi sesuai) | ✅ LOLOS | Uji kecocokan: tidak ada bukti menyimpang dari lognormal (p > 0,05). Log-transform nominal membuatnya mendekati normal. | [Massey (1951)](https://doi.org/10.1080/01621459.1951.10500769) |

## Implikasi untuk notebook 02–07

- **Pembersihan (02):** deduplikasi transaksi, buang nominal nol, tangani `channel`/`counterparty_id` kosong (F1-06).
- **Musiman (02–03):** koreksi Lebaran & Desember per industri sebelum menghitung tren/anomali (F2-03, F2-04, F8-08/09).
- **Fitur risiko (03):** rasio relatif-peer, % pajak telat, % gaji ≥ tgl 28, pergeseran tanggal gaji, porsi pembeli terbesar, indikator laporan hilang (F4-05, F4b, F8).
- **Fitur jaringan (03):** derajat/anchor, eksposur ke anchor bermasalah, komunitas, agregat grup usaha (F2, F2b, F4b-07, F8-01/02).
- **Modelling (04–05):** kelas tidak seimbang → stratified CV & macro-F1/recall High; target realistis di bawah plafon oracle (F2-10, F4-01).
- **Larangan:** jangan pakai kolom proxy-label (`collectibility`, `max_dpd_12m`, `watchlist_flag`, `restructuring_flag`) dan `gt_*` sebagai fitur (F5-06, F5-04).
- **Evaluasi (06–07):** adopsi Jul–Sep 2026 sebagai out-of-time; `label_flipped` untuk analisis kesalahan; skenario krisis/boom untuk stress test (F4-04, F5-03, F3).

## Rujukan yang dipakai

- **R01** Sargent, R. G. (2013). *Verification and validation of simulation models*. Journal of Simulation, 7(1), 12–24. [doi:10.1057/jos.2012.20](https://ideas.repec.org/a/taf/tjsmxx/v7y2013i1p12-24.html) — dipakai di F1-01, F1-02, F1-03, F1-10, F3-01, F3-02, F3-03, F3-04, F3-05, F3-06, F3-07
- **R02** Nigrini, M. J. (2012). *Benford's Law: Applications for Forensic Accounting, Auditing, and Fraud Detection*. Wiley. [doi:10.1002/9781119203094](https://doi.org/10.1002/9781119203094) — dipakai di F2-01
- **R03** Barabási, A.-L.; Albert, R. (1999). *Emergence of scaling in random networks*. Science, 286(5439), 509–512. [doi:10.1126/science.286.5439.509](https://doi.org/10.1126/science.286.5439.509) — dipakai di F2-11
- **R04** Newman, M. E. J. (2002). *Assortative mixing in networks*. Physical Review Letters, 89(20), 208701. [doi:10.1103/PhysRevLett.89.208701](https://doi.org/10.1103/PhysRevLett.89.208701) — dipakai di F2-13, F2b-04
- **R05** Newman, M. E. J. (2006). *Modularity and community structure in networks*. PNAS, 103(23), 8577–8582. [doi:10.1073/pnas.0601602103](https://doi.org/10.1073/pnas.0601602103) — dipakai di F2-17, F2b-01
- **R06** Fujiwara, Y.; Aoyama, H. (2010). *Large-scale structure of a nation-wide production network*. The European Physical Journal B, 77(4), 565–580. [doi:10.1140/epjb/e2010-00275-2](https://doi.org/10.1140/epjb/e2010-00275-2) — dipakai di F2-12
- **R07** Bernard, A. B.; Moxnes, A.; Saito, Y. U. (2019). *Production networks, geography, and firm performance*. Journal of Political Economy, 127(2), 639–688. [doi:10.1086/700764](https://doi.org/10.1086/700764) — dipakai di F2-16
- **R08** Blondel, V. D.; Guillaume, J.-L.; Lambiotte, R.; Lefebvre, E. (2008). *Fast unfolding of communities in large networks*. Journal of Statistical Mechanics, P10008. [doi:10.1088/1742-5468/2008/10/P10008](https://doi.org/10.1088/1742-5468/2008/10/P10008) — dipakai di F2-17, F2b-01
- **R09** Stanley, M. H. R.; Amaral, L. A. N.; Buldyrev, S. V.; dkk. (1996). *Scaling behaviour in the growth of companies*. Nature, 379, 804–806. [doi:10.1038/379804a0](https://doi.org/10.1038/379804a0) — dipakai di F2-07
- **R10** Rubin, D. B. (1976). *Inference and missing data*. Biometrika, 63(3), 581–592. [doi:10.1093/biomet/63.3.581](https://doi.org/10.1093/biomet/63.3.581) — dipakai di F4-05
- **R11** Wu, R.; Keogh, E. (2021). *Current time series anomaly detection benchmarks are flawed and are creating the illusion of progress*. IEEE Transactions on Knowledge and Data Engineering. [doi:10.1109/TKDE.2021.3112126](https://doi.org/10.1109/TKDE.2021.3112126) — dipakai di F4-02, F4-03, F4-07, F4-08
- **R12** Woo, M.-J.; Reiter, J. P.; Oganian, A.; Karr, A. F. (2009). *Global measures of data utility for microdata masked for disclosure limitation*. Journal of Privacy and Confidentiality, 1(1). [doi:10.29012/jpc.v1i1.568](https://doi.org/10.29012/jpc.v1i1.568) — dipakai di F4-06
- **R13** Snoke, J.; Raab, G. M.; Nowok, B.; Dibben, C.; Slavkovic, A. (2018). *General and specific utility measures for synthetic data*. Journal of the Royal Statistical Society: Series A, 181(3), 663–688. [doi:10.1111/rssa.12358](https://doi.org/10.1111/rssa.12358) — dipakai di F4-06
- **R16** MacKinlay, A. C. (1997). *Event studies in economics and finance*. Journal of Economic Literature, 35(1), 13–39. [tautan](https://www.jstor.org/stable/2729691) — dipakai di F4b-04, F8-07
- **R17** Battiston, S.; Puliga, M.; Kaushik, R.; Tasca, P.; Caldarelli, G. (2012). *DebtRank: Too central to fail? Financial networks, the FED and systemic risk*. Scientific Reports, 2, 541. [doi:10.1038/srep00541](https://doi.org/10.1038/srep00541) — dipakai di F4b-07
- **R18** Khanna, T.; Yafeh, Y. (2007). *Business groups in emerging markets: Paragons or parasites?*. Journal of Economic Literature, 45(2), 331–372. [doi:10.1257/jel.45.2.331](https://doi.org/10.1257/jel.45.2.331) — dipakai di F2b-09, F2b-10, F4b-09, F4b-10
- **R19** Kaufman, S.; Rosset, S.; Perlich, C.; Stitelman, O. (2012). *Leakage in data mining: Formulation, detection, and avoidance*. ACM Transactions on Knowledge Discovery from Data, 6(4), 15. [doi:10.1145/2382577.2382579](https://doi.org/10.1145/2382577.2382579) — dipakai di F5-01, F5-02, F5-03, F5-04, F5-05, F5-06, F5-07
- **R20** Ojala, M.; Garriga, G. C. (2010). *Permutation tests for studying classifier performance*. Journal of Machine Learning Research, 11, 1833–1863. [tautan](https://jmlr.org/papers/v11/ojala10a.html) — dipakai di F5-08
- **R21** Hanley, J. A.; McNeil, B. J. (1982). *The meaning and use of the area under a receiver operating characteristic (ROC) curve*. Radiology, 143(1), 29–36. [doi:10.1148/radiology.143.1.7063747](https://doi.org/10.1148/radiology.143.1.7063747) — dipakai di F5-07
- **R22** Northcutt, C. G.; Jiang, L.; Chuang, I. L. (2021). *Confident learning: Estimating uncertainty in dataset labels*. Journal of Artificial Intelligence Research, 70, 1373–1411. [doi:10.1613/jair.1.12125](https://doi.org/10.1613/jair.1.12125) — dipakai di F4-04
- **R23** Gebru, T.; Morgenstern, J.; Vecchione, B.; dkk. (2021). *Datasheets for datasets*. Communications of the ACM, 64(12), 86–92. [doi:10.1145/3458723](https://doi.org/10.1145/3458723) — dipakai di F7-01, F7-02
- **R24** Jordon, J.; Szpruch, L.; Houssiau, F.; dkk. (2022). *Synthetic Data – what, why and how?*. arXiv:2205.03257 (Royal Society / Alan Turing Institute). [tautan](https://arxiv.org/abs/2205.03257) — dipakai di F6-02, F6-03
- **R27** Mann, H. B.; Whitney, D. R. (1947). *On a test of whether one of two random variables is stochastically larger than the other*. Annals of Mathematical Statistics, 18(1), 50–60. [doi:10.1214/aoms/1177730491](https://doi.org/10.1214/aoms/1177730491) — dipakai di F8-01, F8-03, F8-04
- **R28** Wilcoxon, F. (1945). *Individual comparisons by ranking methods*. Biometrics Bulletin, 1(6), 80–83. [doi:10.2307/3001968](https://doi.org/10.2307/3001968) — dipakai di F8-07, F8-08, F8-09
- **R29** Cochran, W. G. (1954). *Some methods for strengthening the common χ² tests*. Biometrics, 10(4), 417–451. [doi:10.2307/3001616](https://doi.org/10.2307/3001616) — dipakai di F8-05
- **R30** Armitage, P. (1955). *Tests for linear trends in proportions and frequencies*. Biometrics, 11(3), 375–386. [doi:10.2307/3001775](https://doi.org/10.2307/3001775) — dipakai di F8-05
- **R31** Clopper, C. J.; Pearson, E. S. (1934). *The use of confidence or fiducial limits illustrated in the case of the binomial*. Biometrika, 26(4), 404–413. [doi:10.1093/biomet/26.4.404](https://doi.org/10.1093/biomet/26.4.404) — dipakai di F8-06
- **R33** Efron, B.; Tibshirani, R. J. (1993). *An Introduction to the Bootstrap*. Chapman & Hall/CRC. [doi:10.1201/9780429246593](https://doi.org/10.1201/9780429246593) — dipakai di F8-01, F8-03, F8-04, F8-08, F8-09
- **R34** Massey, F. J. (1951). *The Kolmogorov–Smirnov test for goodness of fit*. Journal of the American Statistical Association, 46(253), 68–78. [doi:10.1080/01621459.1951.10500769](https://doi.org/10.1080/01621459.1951.10500769) — dipakai di F8-10
- **R36** Spearman, C. (1904). *The proof and measurement of association between two things*. American Journal of Psychology, 15(1), 72–101. [doi:10.2307/1412159](https://doi.org/10.2307/1412159) — dipakai di F8-02
- **R37** Republik Indonesia (2022). *Undang-Undang tentang Pelindungan Data Pribadi*. Lembaran Negara RI. [tautan](https://www.google.com/search?q=Undang-Undang%20tentang%20Pelindungan%20Data%20Pribadi%20Republik%20Indonesia) — dipakai di F6-01
- **R38** Republik Indonesia (2021). *Peraturan Pemerintah tentang Pengupahan (termasuk THR)*. Lembaran Negara RI. [tautan](https://www.google.com/search?q=Peraturan%20Pemerintah%20tentang%20Pengupahan%20%28termasuk%20THR%29%20Republik%20Indonesia) — dipakai di F2-06
- **R40** Badan Pusat Statistik (2021). *Tabel Input–Output Indonesia*. BPS. [tautan](https://www.google.com/search?q=Tabel%20Input%E2%80%93Output%20Indonesia%20Badan%20Pusat%20Statistik) — dipakai di F2-15
- **R41** Bank Indonesia (2024). *Survei Penjualan Eceran (Indeks Penjualan Riil)*. Bank Indonesia. [tautan](https://www.google.com/search?q=Survei%20Penjualan%20Eceran%20%28Indeks%20Penjualan%20Riil%29%20Bank%20Indonesia) — dipakai di F2-03
- **R42** Watts, D. J.; Strogatz, S. H. (1998). *Collective dynamics of 'small-world' networks*. Nature, 393, 440–442. [doi:10.1038/30918](https://doi.org/10.1038/30918) — dipakai di F2b-02, F2b-03
- **R43** Maslov, S.; Sneppen, K. (2002). *Specificity and stability in topology of protein networks*. Science, 296(5569), 910–913. [doi:10.1126/science.1065103](https://doi.org/10.1126/science.1065103) — dipakai di F2b-04
- **R44** Clauset, A.; Shalizi, C. R.; Newman, M. E. J. (2009). *Power-law distributions in empirical data*. SIAM Review, 51(4), 661–703. [doi:10.1137/070710111](https://doi.org/10.1137/070710111) — dipakai di F2b-05, F2b-06
- **R45** Danon, L.; Díaz-Guilera, A.; Duch, J.; Arenas, A. (2005). *Comparing community structure identification*. Journal of Statistical Mechanics, P09008. [doi:10.1088/1742-5468/2005/09/P09008](https://doi.org/10.1088/1742-5468/2005/09/P09008) — dipakai di F2b-07, F2b-08

Rujukan non-paper (logika bisnis, konsistensi kausal, pola gajian, dll.) adalah aturan desain dataset; penjelasannya ada di notebook 01 bagian B–D.
Status pengecekan tiap tautan ada di `references.csv` (kolom `status_tautan`) — cek dahulu sebelum dikutip di laporan.
