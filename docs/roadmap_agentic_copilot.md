# Roadmap pengembangan RM Copilot (agentic)

Status: **draf ide, untuk direview** · disusun 12 Okt 2026 · branch acuan `dharma-pg-2`

## Kondisi sekarang

RM Copilot (`app/egi/agent.py`, `app/egi/llm.py`, `app/views/6_copilot.py`) sudah bisa:

- percakapan dengan memori 12 pesan terakhir, ditambah konteks perusahaan yang sedang dibuka;
- 19 alat: 15 alat baca (portofolio, prioritas berfilter, profil 360°, perbandingan, peluang produk, katalog, arus kas, riwayat kunjungan, investigasi alarm, alarm terbaru, peringkat & detail kecamatan, jaringan prospect, jalur kenalan) dan 4 usulan aksi (rencana, catat kunjungan, eskalasi analis, draf pesan);
- usulan aksi yang baru dijalankan setelah RM menekan **Setujui**;
- progres langkah tampil langsung, saran pertanyaan lanjutan, dan pengecekan angka di jawaban;
- model default `gpt-5.4-mini`.

## Data yang belum dipakai agen

| Berkas (`data/raw/`) | Isi | Potensi untuk agen |
|---|---|---|
| `rm_visit_notes.csv` | 450 catatan kunjungan RM (teks bebas, siapa yang ditemui, tanggal) | memahami keluhan dan kebutuhan nasabah dari kata-kata RM sendiri |
| `issue_product_map.csv` | 12 jenis masalah nasabah + kata kunci + produk solusi + departemen | memetakan catatan kunjungan ke produk yang cocok |
| `credit_facilities.csv` | 1.000 fasilitas: limit, outstanding, utilisasi, kolektibilitas, DPD 12 bln, restrukturisasi, watchlist | analisis kredit lebih tajam (peluang tambah limit, tanda bahaya) |
| `counterparty_transactions.csv` | 5.500 baris transaksi mitra: arah, nilai 12 bln, **bank mitra**, bulan pertama/terakhir | bukti konkret perpindahan transaksi ke bank lain |

## Ide, diurutkan menurut prioritas

### Tingkat 1: alat baru dari data yang sudah ada (rekomendasi: kerjakan dulu)

- [ ] **1. Alat catatan kunjungan** (`visit_notes`, `issue_scan`)
  - Pertanyaan contoh: *"Apa keluhan nasabah saya bulan ini?"*, *"Siapa yang pernah bilang kasnya ketat?"*
  - Cara kerja: cari catatan per RM/perusahaan/periode; cocokkan kata kunci `issue_product_map` → ringkas per masalah beserta produk solusinya.
  - Nilai demo: agen mengutip kalimat RM yang asli sebagai bukti.

- [ ] **2. Alat bukti perpindahan bank** (`bank_shift`)
  - Pertanyaan contoh: *"Kenapa porsi wallet Graha Abadi turun?"*
  - Cara kerja: dari `counterparty_transactions`, bandingkan mitra yang memakai BNI vs bank lain, nilai transaksi, dan mitra yang baru pindah.
  - Nilai demo: alasan retensi berubah dari "porsi wallet turun 10 poin" menjadi "5 pemasok terbesar sekarang dibayar lewat bank X".

- [ ] **3. Alat fasilitas kredit** (`credit_facility`)
  - Isi: limit, outstanding, utilisasi, kolektibilitas, DPD, watchlist, pembatasan kebijakan.
  - Pemakaian: utilisasi ≥ 85% dan kolektibilitas 1 → peluang tambah limit; DPD/watchlist → tanda bahaya untuk analis.
  - Catatan: tetap tidak memberi keputusan kredit (aturan yang sudah ada).

- [ ] **4. Alat simulasi produk** (`simulate_product`)
  - Memakai `app/egi/sim.py` (rumus EV NB08, sudah cocok 6.747/6.747 baris).
  - Pertanyaan contoh: *"Kalau P03 ke Graha Abadi dengan deal 600 juta, EV-nya berapa? Titik impasnya?"*
  - Hasil: EV, nilai bila deal terjadi, titik impas, dan perbandingan dengan asumsi awal.

Perkiraan: ±6 alat baru di `agent.py` + entri `TOOL_LABEL` + kamus data di prompt. Tidak ada perubahan UI.

### Tingkat 2: agen yang bekerja lebih mandiri

- [ ] **5. Triase alarm massal**
  - *"Periksa semua alarm saya bulan ini."* → agen menjalankan investigasi untuk setiap nasabah beralarm, mengelompokkan distress vs retensi vs sinyal lemah, lalu membuat beberapa usulan eskalasi/rencana sekaligus.
  - Perlu: tombol **Setujui semua** / per baris di kartu usulan.

- [ ] **6. Rencana minggu dengan rute**
  - Urutkan kunjungan per hari berdasarkan jarak (lat/lon perusahaan & cabang), kelompokkan per kecamatan.
  - Hasil: satu usulan rencana lengkap (hari, jam, tujuan) yang disetujui sekali.

- [ ] **7. Kampanye anchor (rantai pasok)**
  - *"Nasabah mana yang paling banyak pemasok prospect-nya?"* → daftar anchor, pemasok prospect, perantara, draf pesan perkenalan per pemasok.

- [ ] **8. Briefing pra-kunjungan dalam PDF dari chat**
  - Gabungan profil, simulasi produk, catatan kunjungan terakhir, dan pertanyaan pembuka; memakai generator PDF yang sudah ada di `src/reports.py`.

### Tingkat 3: kualitas dan kepercayaan

- [ ] **9. Pemeriksa jawaban (critic)**
  - Sebelum jawaban tampil, agen memeriksa: angka yang tidak ada di data, rekomendasi kredit untuk risiko High, alat yang seharusnya dipanggil. Bila ada masalah, jawaban diperbaiki otomatis (sekarang baru ditandai).

- [ ] **10. Memori per nasabah antar sesi**
  - *"Minggu lalu Anda bilang Graha Abadi minta simulasi VA."*
  - Prasyarat: penyimpanan permanen (lihat catatan di bawah).

- [ ] **11. Mode Manajer**
  - *"RM mana yang paling banyak alarm belum ditangani?"*, *"Bandingkan konversi antar RM."*
  - Perlu peran pengguna (login RM vs manajer).

## Catatan & prasyarat

- **Penyimpanan permanen.** Catatan kunjungan, rencana, dan log audit sekarang ditulis ke `outputs/app/` (file lokal). Di Streamlit Cloud file ini hilang setiap kali app restart. Ide 10 dan 11 butuh penyimpanan di luar app (mis. Google Sheets, Supabase, atau SQLite di storage eksternal).
- **Biaya LLM.** Ide 5 dan 6 memanggil banyak alat per pertanyaan; tetap murah dengan `gpt-5.4-mini`, tetapi bila app publik sebaiknya akses dibatasi (Streamlit Cloud → Sharing → Only specific people).
- **Aturan yang tetap berlaku.** Agen tidak memutuskan kredit, nasabah risiko High hanya ditawari produk non-kredit, dan semua tindakan menunggu persetujuan RM.

## Keputusan yang perlu diambil saat review

1. Urutan pengerjaan: setuju Tingkat 1 (ide 1–4) dulu, lalu ide 5?
2. Ide mana yang tidak perlu?
3. Untuk ide 10/11: pilihan penyimpanan permanen.
