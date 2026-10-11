"""Catatan uji validasi notebook 01: gabungan F1–F7 + F2b + F8, lengkap dengan statistik, insight, dan rujukan.

Input  : outputs/01_dataset_validation/{validation_report, network_tests, significance_tests, references}.csv
Output : outputs/01_dataset_validation/catatan_uji_validasi.csv dan catatan_uji_validasi.md
Pakai  : python scripts/build_catatan_uji.py   (jalankan ulang setiap kali notebook 01 dijalankan ulang)
"""
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'outputs' / '01_dataset_validation'

# Insight per uji, dicocokkan dengan awalan teks kolom `uji` (F1–F7, F2b) atau `yang_diuji` (F8)
INSIGHT = {
    # ---------- F1 Verifikasi
    'kunci utama unik': 'Setiap baris master bisa dirujuk tanpa ambigu; join antartabel di EDA/feature engineering tidak akan menggandakan baris.',
    'foreign key valid': 'Semua relasi antartabel menunjuk ke entitas yang ada, jadi tidak ada "transaksi yatim" yang hilang saat join.',
    'koordinat di dalam Jabodetabek': 'Peta dan analisis jarak (gravitasi, white-space) tidak tercemar titik yang salah lokasi.',
    'berdiri ≤ 2023': 'Kronologi perusahaan masuk akal: tidak ada nasabah yang onboarding sebelum perusahaannya berdiri.',
    'aset = utang + ekuitas': 'Identitas neraca terpenuhi sehingga rasio keuangan (DER, current ratio, margin) bisa dihitung tanpa koreksi.',
    'DQ disengaja': 'Masalah kualitas data sengaja ditanam dalam dosis yang terdokumentasi; notebook 02 wajib mendeduplikasi dan membuang nominal nol.',
    'prospect tidak memiliki produk BNI': 'Definisi prospect konsisten: belum punya produk, jadi aman dipakai sebagai populasi akuisisi.',
    'fasilitas & rating hanya': 'Label risiko hanya ada untuk nasabah kredit, dan setiap nasabah kredit punya label; populasi modelling risiko jelas (1:1).',
    'semua nasabah memiliki Giro': 'Sesuai praktik bank: rekening operasional adalah produk dasar setiap nasabah.',
    'rentang tanggal transaksi': 'Tidak ada transaksi setelah cutoff, sehingga data fitur bersih dari informasi masa depan.',
    'tidak ada transaksi dengan mitra sebelum': 'Urutan sebab-akibat terjaga: transaksi baru muncul setelah relasi dagang dimulai.',
    'pembeli yang keluar tidak membayar': 'Kejadian "buyer keluar" benar-benar memutus arus kas, jadi sinyalnya bisa dideteksi dari transaksi.',
    'produk dibuka antara onboarding': 'Tanggal pembukaan produk logis; tidak ada produk dibuka sebelum jadi nasabah atau setelah cutoff.',
    # ---------- F2 Kewajaran
    'Benford digit pertama': 'Sebaran digit pertama nominal transaksi sangat mirip data keuangan riil (kategori "close" menurut Nigrini), tanda angka tidak dibangkitkan secara seragam/artifisial.',
    'ekor tebal nominal': 'Nominal transaksi berekor tebal seperti dunia nyata: sedikit transaksi sangat besar. Implikasi: pakai log-transform/median, bukan mean.',
    'puncak Lebaran': 'Inflow naik di bulan Lebaran pada kedua tahun; fitur tren harus dikoreksi musiman agar lonjakan Lebaran tidak dikira anomali.',
    'puncak Desember konstruksi': 'Konstruksi memuncak di Desember (realisasi proyek akhir tahun); musiman berbeda per industri sehingga koreksi harus per industri.',
    'payroll di akhir bulan': 'Pola gajian sesuai praktik (akhir bulan); pergeseran tanggal gaji menjadi sinyal dini yang bermakna.',
    'THR: payroll Maret': 'Payroll bulan Lebaran ±2× bulan biasa, sesuai kewajiban THR; lonjakan ini wajar dan bukan anomali.',
    'volatilitas inflow menurun dengan ukuran': 'Perusahaan besar lebih stabil (Stanley dkk.); ambang anomali sebaiknya relatif terhadap ukuran.',
    'omzet ~ karyawan': 'Omzet dan jumlah karyawan sangat berkorelasi, jadi ukuran perusahaan konsisten antartabel.',
    'median omzet Kecil < Menengah < Besar': 'Kelas ukuran sesuai omzet; segmentasi Kecil/Menengah/Besar bermakna.',
    'proporsi Low / Medium / High': 'Kelas tidak seimbang (High minoritas) seperti portofolio riil; modelling perlu stratified split dan metrik macro-F1/recall High.',
    'derajat berekor tebal': 'Ada sedikit anchor dengan sangat banyak mitra; anchor ini titik kritis efek berantai dan target prioritas ekosistem.',
    'indeks ekor (Hill': 'Informasi: ekor derajat lebih "ringan" dari jaringan produksi Jepang (α ±1,3); wajar untuk 2.000 perusahaan di satu wilayah.',
    'asortativitas derajat': 'Jaringan disasortatif: perusahaan kecil terhubung ke anchor besar, seperti rantai pasok riil.',
    'resiprositas': 'Arah jual-beli jelas (jarang dua arah), sehingga peran pemasok vs pembeli bisa dibaca dari graf.',
    'relasi mengikuti rantai nilai': 'Relasi dagang mengikuti logika input-output antarindustri, bukan acak; rekomendasi produk berbasis rantai nilai masuk akal.',
    'mitra dagang berdekatan': 'Mitra cenderung berdekatan (efek gravitasi); fitur jarak dan klaster lokasi informatif.',
    'modularitas Louvain': 'Jaringan punya komunitas yang jauh lebih kuat dari graf acak; deteksi komunitas layak dipakai untuk segmentasi ekosistem.',
    # ---------- F3 Kondisi ekstrem
    'porsi High: boom < normal < krisis': 'Generator bereaksi logis: krisis menaikkan porsi risiko tinggi, boom menurunkannya. Bisa dipakai untuk stress test model.',
    'krisis: DER naik': 'Saat krisis leverage naik dan likuiditas turun, sesuai intuisi analis kredit.',
    'krisis menambah kejadian distress': 'Kejadian distress bertambah saat krisis; label anomali ikut bergerak bersama kondisi ekonomi.',
    'σ faktor tak teramati': 'Makin banyak faktor yang tidak terekam, makin rendah akurasi maksimum. Plafon akurasi model memang terkendali oleh desain.',
    'skala gravitasi': 'Parameter jarak bekerja sesuai arah yang diharapkan; struktur jaringan bisa diatur dan diuji.',
    'multi-seed': 'Plafon akurasi stabil antar-seed, jadi hasil tidak bergantung pada satu keberuntungan acak.',
    'pola tertanam tetap muncul': 'Pola bisnis (anchor, dosis-respons, pajak telat) muncul juga di seed lain; bukan kebetulan satu dataset.',
    # ---------- F4 Sinyal
    'plafon macro-F1': 'Bahkan model yang tahu skor laten tidak sempurna (ada faktor tak teramati + salah rating). Target realistis model nyata berada di bawah angka ini.',
    'risiko dari laporan keuangan saja (LR': 'Laporan keuangan saja memberi sinyal sedang; perlu fitur transaksi dan jaringan untuk mendekati plafon. Data tidak trivial.',
    'risiko dari laporan keuangan saja (RF': 'Model non-linear pun tidak jauh lebih baik dengan fitur keuangan saja, jadi nilai tambah harus datang dari feature engineering.',
    'kesalahan rating tercatat': 'Sekitar 4% label salah (seperti kesalahan analis riil) dan tercatat di GT; berguna untuk analisis kesalahan di notebook 07.',
    'laporan hilang MNAR': 'Laporan keuangan lebih sering hilang pada perusahaan berisiko tinggi; ketiadaan laporan itu sendiri adalah sinyal (buat indikator missing, jangan sekadar imputasi).',
    'prospect vs nasabah': 'Prospect dan nasabah berbeda secara wajar (tidak identik, tidak terpisah sempurna); model yang dilatih di nasabah masih relevan untuk prospect.',
    'aturan 1 baris menemukan anomali NAIK': 'Aturan sederhana hanya menangkap sebagian anomali naik; masih ada ruang bagi model anomali yang lebih baik.',
    'aturan 1 baris menemukan anomali TURUN': 'Sama untuk anomali turun: tidak trivial, sehingga deteksi "Why Now" layak dimodelkan.',
    'jenis kejadian': 'Tujuh jenis kejadian tersedia dengan jumlah memadai untuk evaluasi deteksi anomali per jenis.',
    'tingkat adopsi produk': 'Tingkat adopsi realistis (minoritas), jadi model rekomendasi perlu dievaluasi dengan precision@k/lift, bukan akurasi.',
    'adopsi bila butuh vs tidak': 'Kebutuhan produk benar-benar mendorong adopsi (lift besar); opportunity score yang menebak kebutuhan akan berguna.',
    'produk dimiliki tanpa kebutuhan': 'Sedikit sekali produk yang dimiliki tanpa kebutuhan, jadi kepemilikan produk konsisten dengan kebutuhan laten.',
    'konversi RM tercatat': 'Setiap aksi RM yang berhasil tercatat sebagai produk baru; feedback loop RM bisa ditelusuri.',
    'counterparty transaksi ada di jaringan': 'Transaksi dan graf jaringan saling konsisten; fitur graf bisa diturunkan dari transaksi.',
    'payroll rutin': 'Hampir semua nasabah menggaji rutin, jadi absen atau telat gaji adalah sinyal kuat.',
    'catatan dengan kalimat negasi': 'Catatan kunjungan mengandung negasi ("tidak ada masalah ..."), sehingga ekstraksi isu tidak bisa sekadar mencari kata kunci.',
    'baseline kata kunci': 'Baseline kata kunci recall-nya tinggi tetapi presisi rendah (tertipu negasi); ada ruang perbaikan untuk LLM/NLP.',
    'kecamatan penetrasi terendah tanpa cabang': 'White-space geografis tertanam dan bisa ditemukan dari data: kecamatan industri dengan penetrasi rendah tanpa cabang.',
    # ---------- F4b Pemulihan pola
    'DER relatif-peer': 'DER yang dibandingkan dengan peer industri dan ukuran lebih prediktif daripada DER mentah; gunakan rasio relatif-peer di feature engineering.',
    '% pajak telat': 'Nasabah High jauh lebih sering telat bayar pajak; fitur keterlambatan pajak adalah early-warning yang kuat.',
    '% payroll ≥ tgl 28': 'Nasabah High lebih sering menggaji di akhir bulan (kas ketat); fitur tanggal gaji layak dipakai.',
    'event study distress': 'Tanggal gaji sudah bergeser sebelum omzet turun, jadi sinyal dini muncul lebih dulu dan model bisa memberi peringatan sebelum kejadian.',
    '% High: pembeli terbesar': 'Ketergantungan pada satu pembeli besar menaikkan risiko; buat fitur porsi pembeli terbesar/HHI.',
    'anchor bermasalah terdeteksi': 'Anchor yang bermasalah bisa ditemukan hanya dari penurunan inflow, tanpa melihat GT.',
    'dosis–respons': 'Pemasok yang bergantung pada anchor bermasalah ikut turun inflow-nya (efek berantai); fitur eksposur ke anchor bermakna.',
    'inflow BNI turun > 25% & omzet naik': 'Divergensi omzet naik tapi inflow BNI turun sebagian besar memang pindah bank (wallet erosion); aturan sederhana ini sudah jadi sinyal retensi.',
    '% High: punya rekan grup High': 'Informasi: pada label, efek grup belum terlihat karena hanya ±90 nasabah kredit dalam grup (sampel kecil).',
    'korelasi kesehatan dalam grup': 'Di dunia laten, kesehatan anggota grup berkorelasi; fitur agregat grup berpotensi berguna walau sinyal di label masih lemah.',
    # ---------- F5 Kebocoran
    'tidak ada data setelah cutoff': 'Tidak ada informasi masa depan di tabel fitur.',
    'tanggal label = cutoff': 'Label diambil tepat di cutoff, sehingga fitur dan label sejajar waktunya.',
    'outcome terjadi setelah cutoff': 'Adopsi produk terjadi setelah cutoff; evaluasi rekomendasi bersifat out-of-time yang jujur.',
    'kolom ground truth tidak muncul': 'Kolom GT tidak bocor ke tabel teramati.',
    'AUC tunggal tertinggi': 'Tidak ada satu kolom fitur yang terlalu prediktif (indikasi bocor); performa tinggi harus datang dari kombinasi fitur.',
    'kolom proxy-label': 'Informasi: collectibility/DPD/watchlist/restrukturisasi hampir sama dengan label. Kolom-kolom ini DILARANG sebagai fitur model risiko.',
    'nomor urut company_id': 'Urutan ID tidak membawa informasi label, jadi aman (tidak ada kebocoran lewat ID).',
    'uji permutasi label': 'Model jauh lebih baik dari label acak, jadi sinyalnya nyata dan bukan hasil overfitting/kebetulan.',
    # ---------- F6 Privasi
    'tidak ada kolom data pribadi': 'Tidak ada PII, sehingga sesuai pedoman capstone dan prinsip UU PDP.',
    'semua nama entitas berakhiran': 'Semua nama jelas fiktif, tidak bisa tertukar dengan perusahaan riil.',
    'koordinat = pusat kecamatan': 'Informasi: koordinat hanya pusat kecamatan + derau, bukan alamat riil.',
    # ---------- F7 Dokumentasi
    'datasheet tersedia': 'Dataset terdokumentasi (motivasi, komposisi, aturan pakai); baca DATASHEET.md sebelum analisis.',
    'kamus data mencakup semua tabel': 'Setiap kolom punya peran (fitur/id/label/proxy/GT); pakai kolom `peran` sebagai pagar anti-kebocoran.',
    # ---------- F2b Uji jaringan
    'F2b:modularitas Louvain vs graf acak': 'Komunitas jauh lebih kuat daripada graf acak dengan jumlah mitra sama (z sangat besar); struktur komunitas bukan artefak derajat.',
    'F2b:koefisien klastering rata-rata': 'Mitra-mitra saling terhubung lebih sering daripada acak (klaster lokal), sesuai jaringan produksi riil.',
    'F2b:transitivitas': 'Konfirmasi klastering global: segitiga relasi lebih banyak dari acak.',
    'F2b:asortativitas derajat vs graf acak': 'Disasortativitas nyata, bukan sekadar konsekuensi distribusi derajat.',
    'F2b:ekor derajat: lognormal vs eksponensial': 'Ekor distribusi derajat lebih berat dari eksponensial: ada hub/anchor sungguhan.',
    'F2b:ekor derajat: power-law': 'Informasi: lognormal lebih cocok daripada power-law murni, sama seperti jaringan produksi riil.',
    'F2b:komunitas sejalan dengan kota': 'Komunitas jaringan sangat sejalan dengan kota/kabupaten (efek gravitasi), sehingga segmentasi ekosistem punya makna geografis.',
    'F2b:komunitas sejalan dengan industri': 'Komunitas hanya sedikit sejalan dengan industri (komunitas lintas industri = rantai nilai), signifikan tetapi kecil.',
    'F2b:homophily grup: kemiripan indeks kesehatan': 'Anggota grup usaha memiliki kesehatan keuangan yang mirip (signifikan), jadi fitur agregat grup layak dicoba.',
    'F2b:homophily grup pada label High': 'Informasi: pada label High efek grup belum signifikan karena sampel kecil (±90 nasabah).',
    # ---------- F8 Signifikansi
    'Δ inflow pemasok terpapar': 'Efek berantai signifikan dan besar: pemasok yang bergantung ≥ 20% pada anchor bermasalah turun inflow-nya jauh lebih dalam; CI tidak memuat nol.',
    'korelasi eksposur ke anchor': 'Makin besar eksposur, makin besar penurunan (dosis-respons) — signifikan walau korelasinya lemah karena banyak pemasok tak terpapar.',
    '% pajak dibayar setelah tgl 15': 'Selisih High−Low besar dan sangat signifikan; fitur pajak telat kuat untuk model risiko.',
    '% gaji dibayar ≥ tgl 28': 'Selisih High−Low besar dan sangat signifikan; fitur tanggal gaji kuat untuk model risiko.',
    '% High naik dengan porsi pembeli terbesar': 'Tren monoton dan signifikan: makin terkonsentrasi pembelinya, makin tinggi porsi High.',
    'presisi kuadran': 'Aturan kuadran menemukan pindah bank dengan presisi jauh di atas porsi dasar; sinyal wallet erosion nyata.',
    'event study: pergeseran tanggal gaji': 'Gaji bergeser ±1–2 hari menjelang distress (berpasangan, signifikan), sehingga early warning bisa memberi lead time ±3 bulan.',
    'indeks inflow Lebaran 2025-03': 'Lonjakan Lebaran signifikan, jadi perlu koreksi musiman di fitur tren.',
    'indeks inflow Lebaran 2026-03': 'Lonjakan Lebaran 2026 juga signifikan dan konsisten antartahun.',
    'nominal transaksi berdistribusi lognormal': 'Uji kecocokan: tidak ada bukti menyimpang dari lognormal (p > 0,05). Log-transform nominal membuatnya mendekati normal.',
}


def insight(lapis, text):
    """Kunci 'F2b:...' khusus lapis tsb (teks ujinya ada yang sama dengan F2); kunci lain berlaku umum."""
    code = lapis.split()[0]
    hit = [v for k, v in INSIGHT.items() if k.startswith(code + ':') and str(text).startswith(k[len(code) + 1:])]
    hit = hit or [v for k, v in INSIGHT.items() if not re.match(r'F\d+b?:', k) and str(text).startswith(k)]
    if len(hit) != 1:
        raise KeyError(f'insight tidak ditemukan / ganda untuk uji: {lapis} · {text!r}')
    return hit[0]


def fmt_num(x, nd=4):
    if pd.isna(x): return ''
    return f'{x:.2e}' if (abs(x) < 1e-3 and x != 0) or abs(x) >= 1e4 else f'{x:.{nd}g}'


refs = pd.read_csv(REPORT / 'references.csv')
refs['_surname'] = refs.kutipan.str.extract(r'^([^\s,(&]+)')[0]


ALIAS = {'Tabel Input–Output (BPS)': 'R40', 'BI: pola konsumsi Ramadan–Idulfitri': 'R41'}   # rujukan lembaga tanpa format "Nama Tahun"


def ref_links(text):
    """Cocokkan teks rujukan (mis. 'Newman 2002; Blondel 2008') dengan references.csv → (id, tautan)."""
    ids, links = [], []
    for part in re.split(r';', str(text)):
        m = refs[[(s in part and str(y) in part) or ALIAS.get(part.strip()) == i for s, y, i in zip(refs._surname, refs.tahun, refs.id)]]
        for r in m.itertuples():
            if r.id not in ids: ids.append(r.id); links.append(r.tautan)
    return ' ; '.join(ids), ' ; '.join(links)


val = pd.read_csv(REPORT / 'validation_report.csv')
net = pd.read_csv(REPORT / 'network_tests.csv')
sig = pd.read_csv(REPORT / 'significance_tests.csv')

rows = []
for r in val.itertuples():
    rows.append(dict(lapis=r.lapis, tabel=r.tabel, uji=r.uji, hasil=r.nilai, statistik='', target=r.target, status=r.status, rujukan=r.rujukan))
for r in net.itertuples():
    stat = f'observasi {fmt_num(r.observasi)}'
    if pd.notna(r.null_rata2): stat += f' vs acak {fmt_num(r.null_rata2)} (sd {fmt_num(r.null_sd)}); z = {r.z:.1f}'
    else: stat = f'rasio log-likelihood R = {r.observasi:.2f} (uji Vuong)'
    stat += f'; p = {fmt_num(r.p_value)}'
    rows.append(dict(lapis='F2b Uji jaringan', tabel='relationships', uji=r.uji, hasil=fmt_num(r.observasi), statistik=stat, target=r.target,
                     status=r.status, rujukan=r.rujukan))
for r in sig.itertuples():
    pct = r.satuan == '%'
    f_ = (lambda v: f'{v:+.1%}') if pct else (lambda v: fmt_num(v))
    hasil = f_(r.estimasi) + ('' if pct or r.satuan in ('ρ',) else f' {r.satuan}')
    ci = '' if pd.isna(r.ci95_bawah) else f'; CI95% [{f_(r.ci95_bawah)}; {f_(r.ci95_atas)}]'
    stat = f'{r.uji}: statistik = {fmt_num(r.statistik)}; p = {fmt_num(r.p_value)}; n = {r.n}{ci}'
    if r.jenis == 'beda':
        status = 'LOLOS' if r.lolos_bonferroni is True or str(r.lolos_bonferroni) == 'True' else 'GAGAL'
        target = 'p < α Bonferroni (0,05/9)'
    else:
        status = 'LOLOS' if r.kesimpulan == 'distribusi sesuai' else 'GAGAL'
        target = 'p ≥ 0,05 (distribusi sesuai)'
    rows.append(dict(lapis='F8 Signifikansi', tabel=r.pola, uji=r.yang_diuji, hasil=hasil, statistik=stat, target=target, status=status, rujukan=r.rujukan))

df = pd.DataFrame(rows)
order = ['F1', 'F2', 'F2b', 'F3', 'F4', 'F4b', 'F5', 'F6', 'F7', 'F8']
df['_k'] = df.lapis.str.split().str[0].map({k: i for i, k in enumerate(order)})
df = df.sort_values('_k', kind='stable').drop(columns='_k').reset_index(drop=True)
df.insert(0, 'kode', df.groupby(df.lapis.str.split().str[0], sort=False).cumcount().add(1).astype(str).radd(df.lapis.str.split().str[0] + '-').str.replace(r'-(\d)$', r'-0\1', regex=True))
df['insight'] = [insight(l, u) for l, u in zip(df.lapis, df.uji)]
df[['id_rujukan', 'tautan']] = [ref_links(t) for t in df.rujukan]
df.to_csv(REPORT / 'catatan_uji_validasi.csv', index=False, encoding='utf-8-sig')   # utf-8-sig agar rapi dibuka di Excel

# ---------------- Markdown
esc = lambda s: str(s).replace('|', '\\|').replace('\n', ' ')
cnt = df.status.value_counts()
LAPIS_DESC = {
    'F1': 'Apakah aturan & integritas data terpenuhi? (Sargent 2013 — verifikasi)',
    'F2': 'Apakah pola statistiknya mirip dunia nyata (stylized facts)?',
    'F2b': 'Apakah struktur jaringan berbeda nyata dari graf acak dengan jumlah mitra yang sama?',
    'F3': 'Apakah generator bereaksi logis bila parameter diubah, dan stabil antar-seed?',
    'F4': 'Apakah polanya bisa dipelajari tetapi tidak terlalu mudah (tidak trivial)?',
    'F4b': 'Apakah pola yang ditanam bisa ditemukan kembali dari data teramati?',
    'F5': 'Apakah ada informasi masa depan / label yang menyusup ke fitur?',
    'F6': 'Apakah ada data pribadi riil?',
    'F7': 'Apakah dataset terdokumentasi?',
    'F8': 'Apakah pola tertanam signifikan secara statistik (bukan kebetulan sampel)?',
}
L = ['# Catatan uji validasi — Notebook 01 Dataset Generation & Validation', '',
     f'Dibuat otomatis oleh `scripts/build_catatan_uji.py` dari hasil notebook 01. Versi tabel: `catatan_uji_validasi.csv`.', '',
     f'**{len(df)} uji — {cnt.get("LOLOS", 0)} lolos, {cnt.get("GAGAL", 0)} gagal, {cnt.get("info", 0)} informasi** '
     '(informasi = angka konteks tanpa target lolos/gagal).', '',
     '## Ringkasan per lapis', '', '| Lapis | Pertanyaan | Lolos | Gagal | Info |', '|---|---|---|---|---|']
for k in order:
    d = df[df.lapis.str.split().str[0] == k]
    L.append(f"| {d.lapis.iloc[0]} | {LAPIS_DESC[k]} | {(d.status == 'LOLOS').sum()} | {(d.status == 'GAGAL').sum()} | {(d.status == 'info').sum()} |")
L += ['', '## Cara membaca', '',
      '- **Hasil**: nilai yang diamati pada data. **Statistik**: uji statistik, p-value, z, atau CI95% (hanya F2b & F8).',
      '- **z** = seberapa jauh nilai nyata dari rata-rata graf/label acak, dalam satuan simpangan baku. **p** = peluang hasil sebesar itu muncul kebetulan.',
      '- F8 memakai koreksi Bonferroni (α = 0,05/9 ≈ 0,0056) karena ada 9 uji beda sekaligus. Dengan ribuan perusahaan, efek kecil pun mudah signifikan, jadi lihat juga besar efek dan CI-nya.',
      '- p-value permutasi F2b terbatas oleh jumlah graf acak (p terkecil = 1/(50+1) ≈ 0,02); z-nya yang menunjukkan seberapa ekstrem.', '']
for k in order:
    d = df[df.lapis.str.split().str[0] == k]
    L += [f'## {d.lapis.iloc[0]}', '', f'*{LAPIS_DESC[k]}*', '']
    with_stat = k in ('F2b', 'F8')
    head = ['Kode', 'Uji', 'Hasil'] + (['Statistik'] if with_stat else []) + ['Target', 'Status', 'Insight', 'Rujukan']
    L += ['| ' + ' | '.join(head) + ' |', '|' + '---|' * len(head)]
    for r in d.itertuples():
        st = {'LOLOS': '✅ LOLOS', 'GAGAL': '❌ GAGAL', 'info': 'ℹ️ info'}[r.status]
        rj = esc(r.rujukan)
        if r.id_rujukan:                                                # satu tautan per rujukan
            kut = refs.set_index('id').kutipan
            rj = '; '.join(f'[{kut[i]}]({u})' for i, u in zip(r.id_rujukan.split(' ; '), r.tautan.split(' ; ')))
        cells = [r.kode, esc(r.uji), esc(r.hasil)] + ([esc(r.statistik)] if with_stat else []) + [esc(r.target), st, esc(r.insight), rj]
        L.append('| ' + ' | '.join(cells) + ' |')
    L.append('')
L += ['## Implikasi untuk notebook 02–07', '',
      '- **Pembersihan (02):** deduplikasi transaksi, buang nominal nol, tangani `channel`/`counterparty_id` kosong (F1-06).',
      '- **Musiman (02–03):** koreksi Lebaran & Desember per industri sebelum menghitung tren/anomali (F2-03, F2-04, F8-08/09).',
      '- **Fitur risiko (03):** rasio relatif-peer, % pajak telat, % gaji ≥ tgl 28, pergeseran tanggal gaji, porsi pembeli terbesar, indikator laporan hilang (F4-05, F4b, F8).',
      '- **Fitur jaringan (03):** derajat/anchor, eksposur ke anchor bermasalah, komunitas, agregat grup usaha (F2, F2b, F4b-07, F8-01/02).',
      '- **Modelling (04–05):** kelas tidak seimbang → stratified CV & macro-F1/recall High; target realistis di bawah plafon oracle (F2-10, F4-01).',
      '- **Larangan:** jangan pakai kolom proxy-label (`collectibility`, `max_dpd_12m`, `watchlist_flag`, `restructuring_flag`) dan `gt_*` sebagai fitur (F5-06, F5-04).',
      '- **Evaluasi (06–07):** adopsi Jul–Sep 2026 sebagai out-of-time; `label_flipped` untuk analisis kesalahan; skenario krisis/boom untuk stress test (F4-04, F5-03, F3).', '',
      '## Rujukan yang dipakai', '']
used = sorted({i for s in df.id_rujukan for i in s.split(' ; ') if i}, key=lambda x: int(x[1:]))
for r in refs[refs.id.isin(used)].itertuples():
    kode = ', '.join(df[df.id_rujukan.str.split(' ; ').map(lambda x: r.id in x)].kode)
    L.append(f'- **{r.id}** {r.penulis} ({r.tahun}). *{r.judul}*. {r.terbitan}. [{("doi:" + r.doi) if isinstance(r.doi, str) and r.doi else "tautan"}]({r.tautan}) — dipakai di {kode}')
L += ['', 'Rujukan non-paper (logika bisnis, konsistensi kausal, pola gajian, dll.) adalah aturan desain dataset; penjelasannya ada di notebook 01 bagian B–D.',
      'Status pengecekan tiap tautan ada di `references.csv` (kolom `status_tautan`) — cek dahulu sebelum dikutip di laporan.']
(REPORT / 'catatan_uji_validasi.md').write_text('\n'.join(L) + '\n', encoding='utf-8')
print(f"Tersimpan: catatan_uji_validasi.csv & .md — {len(df)} uji: {cnt.to_dict()}")
