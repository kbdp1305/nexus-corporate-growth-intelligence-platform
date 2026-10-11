"""Contoh keluaran PDF RM Copilot (C1195 + rencana minggu RM-017).

Narasi di bawah ditulis manual sebagai contoh keluaran LLM. Di dashboard, dict yang sama
diisi LLM dari paket fakta (reports.fact_pack) lalu dicek reports.check_numbers sebelum dirender.
Jalankan dari folder proyek:  python notebooks/demo_reports.py
"""
import sys
from pathlib import Path

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / 'pyproject.toml').exists())
sys.path.insert(0, str(ROOT / 'src'))
import reports as R

OUT = ROOT / 'outputs' / 'reports'; OUT.mkdir(parents=True, exist_ok=True)
D = R.Data(ROOT)
fp = R.fact_pack(D, 'C1195')

narr = {
    'ringkasan': ('CV Cahaya Makmur Industri Utama adalah nasabah kredit S3 Besar yang sehat dan sedang tumbuh: omzet naik 27% menjadi Rp 486,9 M, '
                  'risiko kredit Low (P(High) 0,2%, diputus otomatis). Yang perlu diperhatikan adalah porsi transaksinya di BNI: turun dari 0,74 di Maret '
                  'ke 0,58 di April dan bertahan di 0,61, atau −17 poin dalam 6 bulan, padahal inflow tetap tumbuh. Polanya mirip nasabah yang mulai '
                  'memindahkan sebagian pembayaran ke bank lain. Perusahaan ini juga pusat ekosistem kecil dengan 52 mitra aktif, 17 di antaranya belum '
                  'menjadi nasabah BNI. Peringkat 2 dari 312 di segmennya; tujuan kunjungan berikutnya adalah retensi sambil menawarkan P03.'),
    'keuangan': ('Masih rugi tipis (−1,9 M) dan ICR 0,94 di bawah 1, tetapi untuk perdagangan besar skala besar pola ini umum: median peer ICR 0,87 '
                 'dan margin −0,90%. Semua rasio setara atau lebih baik dari peer, dan arahnya membaik: utang dipangkas 42%, rugi menyusut dari '
                 'Rp 13,4 M. Current ratio 1,96 lebih kuat dari median peer 1,59. Aset turun 40% sementara omzet naik; kebutuhan modal kerja bisa '
                 'muncul setelah deleveraging ini.'),
    'risiko': ('Model menilai risiko rendah dengan keyakinan tinggi (Low 94,2%). Limit kredit besar dan arus kas keluar yang lebih kecil dari kas masuk '
               'menurunkan risiko. Satu faktor yang menaikkan risiko justru inflow BNI yang relatif rendah terhadap omzet, sejalan dengan temuan porsi wallet.'),
    'anomali': ('Tidak ada alarm resmi dalam 3 bulan terakhir: tidak ada keterlambatan gaji atau pajak (0%), outflow masih 0,89 dari inflow, dan pembeli '
                'yang menghilang hanya 0,9% dari inflow. Satu-satunya sinyal adalah porsi wallet −17 poin; aturan erosi tidak menyala karena inflow belum turun. '
                'Ini sinyal retensi, bukan tanda kesulitan keuangan.'),
    'jaringan': ('Jaringannya jauh lebih luas dari peer (52 mitra, median 11) dengan nilai relasi Rp 816 M per tahun. Ada 17 prospect di dalamnya, '
                 'terbesar PT Mitra Gemilang Persada Lestari (Rp 8,6 M). Di sisi lain, 7 mitranya sedang alarm distress dengan nilai relasi Rp 131 M; '
                 'pantau apakah pembayaran dari mereka mulai terlambat.'),
    'rekomendasi': [
        'Kunjungan retensi: tanyakan pembayaran mana yang pindah ke bank lain sejak April dan alasannya (biaya, layanan, atau limit).',
        'Bawa simulasi P03 (peluang 50%, dipakai 59% peer) sebagai solusi untuk pembayaran yang pindah; P05 sebagai opsi kedua.',
        'Tawarkan pembiayaan rantai pasok untuk mitra yang belum menjadi nasabah, mulai dari PT Mitra Gemilang Persada Lestari.',
        'Payroll masih di bank lain: siapkan penawaran payroll untuk 1.335 karyawan sebagai pintu masuk berikutnya.',
    ],
    'pertanyaan': ['Sejak April, pembayaran pemasok mana yang dipindah ke bank lain, dan apa alasannya?',
                   'Setelah utang turun, apa rencana ekspansi tahun depan?'],
}
n, bad = R.check_numbers(narr, fp)
print(f'validasi narasi: {n} angka, tidak cocok: {bad}')
buf, _ = R.company_summary_pdf(fp, narr, out=str(OUT / 'ringkasan_C1195.pdf'), today='12 Okt 2026')

def item(cid, jam, tujuan, siapkan):
    f = R.fact_pack(D, cid); pr = f['produk'][0] if f.get('produk') else None
    info = f"{f['segmen']} · {f['kecamatan']} · risiko {f['risiko']['kelas']}"
    return {'jam': jam, 'nama': f['nama'], 'id': cid, 'info': info, 'tujuan': tujuan,
            'peluang': f"{R.fmt(pr['peluang'], 0)}%" if pr else '—', 'siapkan': siapkan}

plan = {
    'rm': 'RM-017', 'minggu': '13–15 Okt 2026', 'portofolio': '38 nasabah', 'status': 'disetujui RM',
    'kpi': [('Kunjungan & telepon', '7', '3 hari · 1 area utama'), ('Nasabah prioritas', '6', 'skor peluang ≥ 0,75'),
            ('Prospect lewat jaringan', '1', 'perkenalan via nasabah sendiri'), ('Alarm dicek dulu', '1', 'pembeli keluar + erosi')],
    'ringkasan': ('Selasa dipusatkan di Batuceper: tiga nasabah Anda berada di kecamatan white-space tanpa cabang ini, dan pemasok salah satunya '
                  '(PT Graha Nusantara Indah) bisa dikenalkan lewat nasabah sendiri. Rabu untuk telepon nasabah S1 sesuai playbook segmen, termasuk '
                  'nasabah dengan skor peluang tertinggi di segmen kecil yang belum pernah dihubungi. Kamis dimulai dengan investigasi alarm '
                  'sebelum menawarkan produk.'),
    'hari': [
        {'hari': 'Selasa 13 Okt', 'tema': 'hari Batuceper', 'item': [
            item('C1195', '09.00', 'Retensi: porsi wallet turun sejak April. Lanjutan kunjungan 18 Jun. Tawarkan P03.', 'Simulasi biaya P03; ringkasan eksekutif'),
            item('C1545', '11.00', 'P03; minta perkenalan ke pemasoknya PT Graha Nusantara Indah. Risiko Medium: kredit × 0,5.', 'Draf permintaan perkenalan'),
            item('C1448', '14.00', 'P03 / P02; dompet belum digarap besar, searah rute.', 'Profil 360°')]},
        {'hari': 'Rabu 14 Okt', 'tema': 'telepon S1', 'item': [
            item('C1892', '10.00', 'Peringkat 1 di S1, belum pernah dihubungi. Arus kas tumbuh; tawarkan P03.', 'Skrip telepon'),
            item('C1376', '11.00', 'Alarm ekspansi; tawarkan P03. Risiko Medium.', 'Skrip telepon')]},
        {'hari': 'Kamis 15 Okt', 'tema': 'cek alarm dulu', 'item': [
            item('C0478', '10.00', 'Alarm pembeli keluar + erosi wallet. Jalankan investigasi; bila distress, teruskan ke analis.', 'Hasil investigasi Copilot'),
            item('C1807', '13.00', 'Peringkat 25 di S3, porsi wallet turun; tawarkan P03.', 'Simulasi P03')]},
    ],
    'pesan': [
        {'ke': 'CV Cahaya Makmur Industri Utama', 'kanal': 'WhatsApp', 'isi': 'Selamat pagi Bapak/Ibu, menindaklanjuti pertemuan kita 18 Juni, saya ingin berkunjung Selasa, 13 Oktober pukul 09.00 untuk membahas simulasi biaya layanan yang kami siapkan. Apakah waktu tersebut sesuai?'},
        {'ke': 'CV Cahaya Abadi Indah Gemilang', 'kanal': 'WhatsApp', 'isi': 'Selamat pagi, saya berencana mampir Selasa, 13 Oktober pukul 11.00. Selain membahas layanan untuk perusahaan Bapak/Ibu, kami juga ingin berkenalan dengan PT Graha Nusantara Indah sebagai mitra pemasok. Apakah berkenan membantu memperkenalkan?'},
    ],
    'jejak': [('get_portfolio("RM-017")', '38 nasabah: S1 12 · S2 18 · S3 8'), ('get_alerts(rm, Apr–Jun 2026)', '5 Why Now; C0478 dengan 2 alarm'),
              ('get_priority(rm, skor ≥ 0,75)', '14 nasabah, 7 belum pernah dihubungi'), ('filter_risk()', 'nasabah High hanya ditawari produk non-kredit'),
              ('group_by_area()', 'Batuceper: 3 nasabah, kecamatan white-space'), ('find_intro_path("Batuceper")', 'C1155 lewat C1545 (nasabah sendiri)'),
              ('get_visit_history("C1195")', '18 Jun: Interested, perlu diskusi dengan direktur keuangan'), ('draft_message(× 2)', 'menunggu persetujuan')],
}
R.weekly_plan_pdf(plan, out=str(OUT / 'rencana_minggu_RM-017.pdf'), today='12 Okt 2026')
print('PDF:', *sorted(p.name for p in OUT.glob('*.pdf')))
