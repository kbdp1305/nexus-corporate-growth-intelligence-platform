# Dashboard RM — BNI Ecosystem & Growth Intelligence

Ruang kerja Relationship Manager di atas output notebook NB01–NB08 (data sintetis v8).
Dashboard **hanya membaca** output notebook. Yang ditulisnya hanya ke `outputs/app/`: catatan kunjungan, rencana yang disetujui, dan log audit.

## Menjalankan

Dari folder proyek (yang berisi `pyproject.toml`):

```bash
uv add streamlit plotly pydeck reportlab networkx python-dotenv
# opsional, sesuai LLM yang dipakai:
uv add anthropic        # atau: uv add openai
uv run streamlit run app/app.py
```

Kalau tidak memakai uv: `pip install -r requirements-dashboard.txt`, lalu `streamlit run app/app.py`.

Syarat: NB01–NB08 sudah dijalankan. Kalau ada berkas output yang belum ada, aplikasi menampilkan daftarnya.

## Login

Dashboard meminta login sebelum halaman mana pun terbuka.

- **Akun.** Satu akun per RM (`rm-001` … `rm-040`) dan satu akun `supervisor`. Akun dibuat otomatis saat dashboard pertama kali dibuka.
- **Password awal.** Kalau `APP_DEMO_PASSWORD` diisi di `.env` (atau `st.secrets` di Streamlit Cloud), semua akun baru memakai password itu. Kalau kosong, setiap akun mendapat password acak yang ditulis ke `outputs/app/akun_awal.csv`.
- **Hak akses.** RM hanya melihat portofolio dan kalendernya sendiri. Supervisor bisa memilih RM mana pun atau "Semua RM", dan bisa mengubah jadwal semua RM.
- **Ganti password.** Sidebar → **Akun**. Password disimpan sebagai hash PBKDF2 di `outputs/app/users.json`; file ini dan `akun_awal.csv` tidak masuk git.
- Lima kali salah password berturut-turut → login dikunci 1 menit untuk sesi itu.

## Kalender kunjungan

Halaman **Kalender kunjungan** menampilkan jadwal per bulan/minggu/hari (komponen `streamlit-calendar`).

- Klik tanggal/jam untuk menambah jadwal, klik jadwal untuk mengubah status (Terjadwal/Selesai/Dibatalkan) atau menghapus, seret jadwal untuk memindah.
- Rencana minggu yang disetujui di RM Copilot otomatis masuk ke kalender. Menyetujui ulang memperbarui jadwal yang sama, tidak menggandakan.
- Jadwal tersimpan di `outputs/app/calendar.csv` dan dipakai bersama oleh semua pengguna. Semua bisa diunduh sebagai `.ics` untuk Google Calendar / Outlook.
- Di Streamlit Cloud, isi `outputs/app/` hilang setiap kali aplikasi restart; untuk penyimpanan permanen ganti `egi/kalender.py` dan `egi/auth.py` ke database (mis. Google Sheets / Supabase).

## Tindak lanjut & koordinasi divisi

Halaman **Tindak lanjut kunjungan** dan **Koordinasi divisi** (menu "Kunjungan & koordinasi").

- **Feedback kunjungan.** Jadwal kunjungan/telepon yang sudah lewat muncul sebagai "menunggu feedback" (juga tombol *Isi feedback & tindak lanjut* di Kalender). RM mengisi hasil, produk yang dibahas, catatan, dan keberatan. Saat disimpan: jadwal ditandai Selesai, hasil masuk ke riwayat nasabah (`visit_log.csv`), dan bila dipilih, jadwal tindak lanjut otomatis masuk kalender.
- **Agen Tindak Lanjut** (`egi/agen_tindak.py`). Setelah catatan hasil kunjungan diisi, agen (LLM + tool use) memahami konteks catatan (PIC, tahap minat, permintaan, kebutuhan tersirat, keberatan, waktu), lalu memanggil alat: `profil_nasabah`, `info_produk`, `penanganan_keberatan` (playbook + kasus serupa), `kebutuhan_dari_catatan`, `kasus_serupa`, `riwayat_kunjungan`, `produk_alternatif`, `cari_slot`, dan menutup dengan `ajukan_rencana` (keluaran terstruktur: pemahaman, langkah + pemilik + tenggat, respon keberatan, jadwal, divisi, pesan divisi, pertanyaan kunci). Langkah yang memuat angka di luar catatan/hasil alat dibuang. Tanpa LLM, alat yang sama dijalankan berurutan (agen deterministik). Jejak pemanggilan alat bisa dilihat di halaman.
- **Saran rencana lanjutan** (`egi/saran.py`, dipakai agen deterministik). Langkah berikutnya, jadwal, dan permintaan ke divisi terisi otomatis dari analisis per nasabah: model risiko, peluang konversi produk yang dibahas + produk alternatif terbaik, arus kas & alarm, riwayat kunjungan, dan *kasus serupa* di log RM (TF-IDF atas hasil & catatan → kanal dan jeda yang paling sering berujung konversi di kontak berikutnya). Bila LLM aktif, LLM menulis ulang saran dari paket analisis itu; angka yang tidak ada di paket ditolak. Nasabah yang perlu pertimbangan ulang otomatis dijadwalkan ulang di slot kosong kalender RM. Semua isian tetap bisa diubah manual.
- **Progress kegiatan.** Kegiatan selanjutnya yang disimpan (saran AI yang dicentang + kegiatan manual) dicatat per baris di `outputs/app/kegiatan.csv` dengan tenggat berupa tanggal. Tab *Progress kegiatan* menampilkan flowchart per perusahaan (satu alur per kunjungan): hijau = selesai, merah = lewat tenggat & belum selesai, abu-abu = berjalan, putus-putus tercoret = dibatalkan; tahap aktif disorot. RM menandai tahap selesai, dan untuk perubahan mendadak bisa **menjadwal ulang** tahap (dengan alasan; jadwal kalender ikut bergeser), **membatalkan** tahap (dengan alasan; bisa diaktifkan lagi), atau **menambah rapat/kegiatan dadakan** yang disisipkan ke alur, masuk kalender, dan mengundang divisi lewat tiket. Setiap perubahan tercatat di *Riwayat perubahan*; jumlah kegiatan lewat tenggat muncul di sidebar.
- **Koordinasi dengan divisi.** Dari catatan RM, isu dideteksi lewat `data/raw/issue_product_map.csv` (kata kunci → isu → divisi) dan pemilik produk di `product_master.csv`; divisi yang disarankan bisa diubah. Setiap divisi menerima tiket berisi ringkasan kunjungan, prioritas, dan tenggat. Isu legal / tekanan likuiditas memunculkan peringatan bahwa produk kredit ditahan.
- **Pengajuan kunjungan.** RM mengajukan kunjungan (dari halaman ini atau tombol *Ajukan kunjungan* di Profil 360°) beserta tujuan, produk, dan divisi pendamping. Supervisor menyetujui atau menolak (ada peringatan bila bentrok dengan jadwal RM). Bila disetujui, jadwal masuk Kalender dan divisi pendamping menerima tiket "Pendampingan kunjungan".
- **Akun divisi** (`div-kredit`, `div-corporate`, `div-risiko`, `div-transaksi`, `div-trade`, `div-funding`, `div-legal`, `div-wealth`, `div-pricing`) hanya melihat kotak masuk tiketnya, membalas, dan mengubah status (Baru → Diproses → Selesai / Ditolak). RM melihat balasan di halaman yang sama.
- Pemberitahuan di sidebar: feedback tertunda (RM), pengajuan menunggu (supervisor), tiket baru (divisi).
- Data: `outputs/app/feedback.csv` dan `outputs/app/requests.csv`.

## LLM (opsional)

Salin `.env.example` menjadi `.env`, lalu isi penyedianya. Ada tiga pilihan:

- **Anthropic.** Set `LLM_PROVIDER=anthropic`.
- **Penyedia yang kompatibel dengan OpenAI.** Set `LLM_PROVIDER=openai`. Ini mencakup OpenAI, Gemini, Groq, dan Ollama lokal lewat `OPENAI_BASE_URL`.
- **Tanpa LLM.** Set `LLM_PROVIDER=none`, atau jangan buat `.env` sama sekali. Semua fitur tetap jalan dengan teks template.

Aturan untuk LLM:

- LLM tidak menghitung. Angka datang dari paket fakta (`src/reports.py: fact_pack`).
- Setiap bagian narasi dicocokkan angkanya. Bagian yang memuat angka asing diganti teks template.

## Halaman

| Halaman | Isi | Terhubung ke |
|---|---|---|
| Overview | KPI bank/portofolio, peta peluang (pydeck + CARTO), kecamatan teratas, 3 segmen, penetrasi produk, celah produk, industri, alarm terbaru | Wilayah, Profil |
| Daftar prioritas | Tab per segmen + playbook, filter kecamatan/produk/Why Now, alasan & komponen skor | Profil, Rencana, Copilot |
| Profil 360° | Ringkasan AI, Keuangan vs peer, Anomali & arus kas, Jaringan (graf ego), Produk & EV, Riwayat & catat kunjungan, PDF ringkasan eksekutif | Copilot, Prospect |
| Potensi wilayah | Bobot skor bisa diatur, peta, ranking, drill-down kecamatan, saran kanal | Prioritas, Profil, Rencana |
| Prospect lewat jaringan | Prospect yang bertransaksi dengan nasabah RM, jalur kenalan, draf pesan perkenalan | Profil, Rencana |
| RM Copilot | Rencana minggu (agen), investigasi alarm, siapkan kunjungan, tanya bebas (tool use), PDF rencana, rencana yang disetujui masuk ke Kalender kunjungan | semua |
| Kalender kunjungan | Kalender bersama (bulan/minggu/hari), tambah/ubah/hapus/geser jadwal, jadwal dari rencana Copilot, unduh .ics | Profil, Copilot |
| Tindak lanjut kunjungan | Feedback setelah kunjungan, rencana lanjutan ke kalender, tiket ke divisi; pengajuan kunjungan + persetujuan supervisor | Kalender, Koordinasi, Profil |
| Koordinasi divisi | Tiket hasil kunjungan & pendampingan per divisi, balasan, status, tenggat | Profil, Tindak lanjut |
| Kinerja saya | Aksi & konversi vs median RM, kanal, segmen, pipeline, prioritas yang belum disentuh | Profil, Rencana |
| Data & metodologi | Metrik model, conformal, alarm v1 vs v2, pemilihan k, validasi, asumsi EV, kendali | — |

Konteks bersama (sidebar):

- **RM aktif.**
- **Fokus perusahaan atau kecamatan.** Fokus perusahaan juga muncul di URL, misalnya `?company=C1195`.
- **Keranjang rencana minggu.** Keranjang ini dipakai Copilot.

## Struktur

```
app/
  app.py              navigasi + sidebar
  egi/data.py         Store: memuat output notebook sekali (st.cache_resource), tabel turunan
  egi/state.py        konteks bersama antar-halaman
  egi/ui.py           tema, kartu, badge
  egi/viz.py          Plotly + pydeck
  egi/llm.py          penyedia LLM, narasi tervalidasi, ekstraksi catatan, draf pesan, loop tool use
  egi/agent.py        alat Copilot, alur rencana minggu & investigasi alarm
  views/1_…9_*.py     halaman (bukan pages/: nama itu memicu multipage lama Streamlit)
src/reports.py        paket fakta, validasi angka, PDF (reportlab)
.streamlit/config.toml, .env.example, requirements-dashboard.txt
```

## Kendali

- Semua tindakan tulis menunggu persetujuan RM: catatan kunjungan, rencana, dan pesan.
- Tindakan dicatat di `outputs/app/audit_log.jsonl`.
- Pesan tidak dikirim otomatis.
- Copilot tidak memutuskan kredit:
  - risiko High → produk kredit ditunda;
  - alarm distress → diteruskan ke analis.
- Catatan kunjungan dari dashboard disimpan di `outputs/app/visit_log.csv`. Skor baru ikut berubah setelah notebook dijalankan ulang.
