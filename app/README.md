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
| RM Copilot | Rencana minggu (agen), investigasi alarm, siapkan kunjungan, tanya bebas (tool use), PDF rencana | semua |
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
  pages/1_…8_*.py     halaman
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
