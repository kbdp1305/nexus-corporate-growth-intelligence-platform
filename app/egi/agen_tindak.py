"""Agen tindak lanjut kunjungan: catatan hasil kunjungan + keberatan + produk dibahas → rencana langkah berikutnya.

Cara kerja (agentic, tool use):
  1. Agen membaca catatan RM dan memahami konteks: siapa pengambil keputusan, tahap minat nasabah, permintaan eksplisit,
     kebutuhan tersirat, keberatan, dan waktu yang disebut.
  2. Agen memanggil alat sesuai kebutuhan: profil & sinyal model nasabah, detail produk + peluang konversi, playbook
     penanganan keberatan, kebutuhan dari catatan, kasus serupa di log RM, riwayat kunjungan, produk alternatif, slot kalender.
  3. Agen menutup dengan alat `ajukan_rencana` (keluaran terstruktur). Angka di rencana divalidasi terhadap hasil alat.

Tanpa LLM: alat yang sama dijalankan dengan urutan tetap (agen deterministik) dan rencana disusun dari saran.from_data,
sehingga tampilan & format keluaran sama dan tetap bisa diaudit.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta

import streamlit as st

import reports as R

from . import kalender as K, llm, saran as S, tindak as T

# ------------------------------------------------------------------ playbook keberatan
PLAYBOOK = [
    {'id': 'biaya', 'nama': 'Biaya / harga', 'kata': ('biaya', 'mahal', 'fee', 'admin', 'harga', 'bunga', 'tarif'), 'divisi': ['pricing'],
     'respon': 'Tunjukkan biaya-manfaat (hemat waktu rekonsiliasi, biaya transfer, kontrol kas) dan ajukan pricing khusus berbasis volume ke divisi Pricing.'},
    {'id': 'bank_lain', 'nama': 'Sudah memakai bank lain', 'kata': ('bank lain', 'sudah memakai', 'sudah pakai', 'sudah punya', 'pesaing'), 'divisi': [],
     'respon': 'Jangan minta pindah total; posisikan BNI sebagai bank kedua untuk sebagian transaksi, siapkan perbandingan layanan dan kemudahan migrasi.'},
    {'id': 'belum_butuh', 'nama': 'Belum ada kebutuhan', 'kata': ('belum butuh', 'belum perlu', 'tidak butuh', 'belum ada kebutuhan', 'tidak perlu'), 'divisi': [],
     'respon': 'Gali kebutuhan tersembunyi lewat pertanyaan arus kas dan rencana bisnis; tawarkan produk yang didukung sinyal data nasabah.'},
    {'id': 'keputusan', 'nama': 'Menunggu keputusan internal', 'kata': ('direksi', 'diskusi', 'pertimbang', 'persetujuan', 'pusat', 'komisaris', 'menimbang', 'rapat'),
     'divisi': [], 'respon': 'Siapkan ringkasan proposal satu halaman untuk pengambil keputusan, tawarkan presentasi langsung, dan sepakati tanggal keputusan.'},
    {'id': 'proses', 'nama': 'Proses dianggap rumit', 'kata': ('ribet', 'rumit', 'lama', 'birokrasi', 'repot'), 'divisi': ['transaksi'],
     'respon': 'Kirim checklist dokumen ringkas, tawarkan pendampingan onboarding dan penjemputan dokumen.'},
    {'id': 'agunan', 'nama': 'Agunan / jaminan', 'kata': ('agunan', 'jaminan', 'collateral'), 'divisi': ['kredit'],
     'respon': 'Libatkan analis kredit untuk opsi struktur fasilitas; jangan menjanjikan persetujuan kredit.'},
    {'id': 'waktu', 'nama': 'Belum ada waktu', 'kata': ('sibuk', 'belum sempat', 'tidak ada waktu', 'nanti saja'), 'divisi': [],
     'respon': 'Minta slot singkat 30 menit atau telepon; kirim materi ringkas lebih dulu.'},
]

SYSTEM = (llm.SYSTEM + ' Anda adalah Agen Tindak Lanjut Kunjungan. Tugas: dari CATATAN hasil kunjungan, KEBERATAN nasabah, dan PRODUK yang dibahas, '
          'susun langkah berikutnya yang konkret untuk RM.\n'
          'Cara kerja:\n'
          '1. Pahami konteks catatan lebih dulu: siapa yang ditemui dan apakah ia pengambil keputusan; tahap minat nasabah; permintaan eksplisit '
          '(proposal, simulasi, perbandingan, dokumen); kebutuhan tersirat (mis. ekspansi, piutang, kas mengendap); keberatan eksplisit maupun tersirat; '
          'waktu yang disebut nasabah; janji RM pada kunjungan sebelumnya.\n'
          '2. Verifikasi dan lengkapi dengan alat. Minimal panggil profil_nasabah dan info_produk. Panggil penanganan_keberatan bila ada keberatan, '
          'kebutuhan_dari_catatan bila catatan menyebut rencana/masalah bisnis, riwayat_kunjungan untuk melihat janji sebelumnya, kasus_serupa untuk memilih '
          'kanal & jeda, produk_alternatif bila nasabah menolak, dan cari_slot untuk tanggal jadwal.\n'
          '3. Aturan: jangan menawarkan produk kredit bila alat menyatakan ditahan; jangan menjanjikan harga atau persetujuan kredit; setiap langkah harus '
          'menjawab sesuatu yang tertulis di catatan atau sinyal dari alat; sebut nama produk (bukan kodenya) dan nama PIC; pemilik langkah ditulis \"RM\" '
          'atau nama divisi; hanya pakai angka dari catatan atau hasil alat.\n'
          '4. Waktu: bila catatan menyebut waktu (mis. \"minggu depan\" = 7 hari, \"bulan depan\" = 30 hari), tenggat langkah yang diminta nasabah '
          'dan jadwal kontak berikutnya wajib mengikutinya. Tenggat langkah persiapan tidak boleh melewati jadwal kontak berikutnya.\n'
          '5. Akhiri dengan memanggil ajukan_rencana tepat satu kali. Langkah 2–5 butir, urut prioritas.')

TOOLS = [
    {'name': 'profil_nasabah', 'description': 'Profil & sinyal model nasabah: segmen, kelas risiko (model NB04), produk dimiliki, payroll, karyawan, arus kas, alarm 3 bulan.',
     'parameters': {'type': 'object', 'properties': {}}},
    {'name': 'info_produk', 'description': 'Detail produk (manfaat, syarat, catatan harga, divisi pemilik) + peluang konversi & adopsi peer untuk nasabah ini (model NB05), '
                                           'dan apakah ditahan karena risiko.',
     'parameters': {'type': 'object', 'properties': {'produk': {'type': 'array', 'items': {'type': 'string'}, 'description': 'ID produk P01–P08'}},
                    'required': ['produk']}},
    {'name': 'penanganan_keberatan', 'description': 'Playbook penanganan keberatan + hasil kontak berikutnya pada kasus dengan keberatan serupa di log RM.',
     'parameters': {'type': 'object', 'properties': {'keberatan': {'type': 'string'}}, 'required': ['keberatan']}},
    {'name': 'kebutuhan_dari_catatan', 'description': 'Deteksi isu bisnis dari teks (peta isu → produk solusi → divisi), termasuk isu yang menahan kredit.',
     'parameters': {'type': 'object', 'properties': {'teks': {'type': 'string'}}, 'required': ['teks']}},
    {'name': 'kasus_serupa', 'description': 'Kontak di log RM dengan hasil & catatan mirip: tingkat konversi di kontak berikutnya per kanal dan per jeda hari.',
     'parameters': {'type': 'object', 'properties': {'teks': {'type': 'string'}, 'hasil': {'type': 'string', 'enum': T.HASIL}}, 'required': ['teks', 'hasil']}},
    {'name': 'riwayat_kunjungan', 'description': 'Riwayat kontak sebelumnya ke nasabah ini (log RM + feedback dashboard), termasuk langkah lanjut yang pernah dijanjikan.',
     'parameters': {'type': 'object', 'properties': {}}},
    {'name': 'produk_alternatif', 'description': 'Produk dengan peluang konversi tertinggi yang belum dimiliki & tidak ditahan risiko, di luar produk yang dikecualikan.',
     'parameters': {'type': 'object', 'properties': {'kecuali': {'type': 'array', 'items': {'type': 'string'}}}}},
    {'name': 'cari_slot', 'description': 'Slot kosong pertama di kalender RM (hari kerja 08.00–16.00) mulai N hari dari sekarang.',
     'parameters': {'type': 'object', 'properties': {'hari': {'type': 'integer'}, 'kanal': {'type': 'string', 'enum': S.KANAL_KONTAK}}, 'required': ['hari', 'kanal']}},
    {'name': 'ajukan_rencana', 'description': 'Serahkan rencana tindak lanjut final. Panggil tepat satu kali di akhir.',
     'parameters': {'type': 'object', 'properties': {
         'pemahaman': {'type': 'string', 'description': '2–3 kalimat: situasi nasabah menurut catatan (PIC, tahap minat, permintaan, kebutuhan, keberatan).'},
         'langkah': {'type': 'array', 'description': '2–5 langkah urut prioritas', 'items': {'type': 'object', 'properties': {
             'judul': {'type': 'string', 'description': 'judul singkat 2–5 kata, mis. \"Kirim simulasi Payroll\"'},
             'aksi': {'type': 'string', 'description': '1 kalimat perintah lengkap'}, 'alasan': {'type': 'string'}, 'pemilik': {'type': 'string', 'description': 'RM atau nama divisi'},
             'tenggat_hari': {'type': 'integer'}}, 'required': ['aksi', 'alasan', 'pemilik', 'tenggat_hari']}},
         'keberatan': {'type': 'array', 'items': {'type': 'object', 'properties': {'keberatan': {'type': 'string'}, 'respon': {'type': 'string'}},
                                                   'required': ['keberatan', 'respon']}},
         'jadwal': {'type': 'object', 'properties': {'hari': {'type': 'integer'}, 'jam': {'type': 'string', 'description': 'HH:MM'},
                                                     'kanal': {'type': 'string', 'enum': S.KANAL_KONTAK}, 'tujuan': {'type': 'string'}},
                    'required': ['hari', 'jam', 'kanal', 'tujuan']},
         'perlu_jadwal_ulang': {'type': 'boolean', 'description': 'true bila nasabah perlu menimbang ulang / menunggu keputusan'},
         'divisi': {'type': 'array', 'items': {'type': 'string', 'enum': list(T.DIVISI)}},
         'pesan_divisi': {'type': 'string', 'description': '2–3 kalimat permintaan ke divisi; sebut permintaan nasabah.'},
         'pertanyaan_kunci': {'type': 'array', 'items': {'type': 'string'}, 'description': '2–3 pertanyaan untuk kontak berikutnya'}},
         'required': ['pemahaman', 'langkah', 'jadwal', 'divisi', 'pesan_divisi', 'pertanyaan_kunci']}},
]


# ------------------------------------------------------------------ eksekutor alat
def make_executor(store, ctx):
    """ctx: company_id, rm_id, hasil, catatan, keberatan, produk, isu, hold, ulang, riwayat. Hasil akhir disimpan di ex.rencana."""
    pm, cid = T.products(), ctx['company_id']
    fp = S._fact_pack(store, cid) if cid else None
    prod = {p['produk']: p for p in (fp or {}).get('produk') or []}
    held = set((fp or {}).get('produk_dimiliki') or [])
    risk = (fp or {}).get('risiko') or {}
    credit_hold = ctx['hold'] or risk.get('kelas') == 'High'

    def model(p):
        d = {'id': p, 'nama': pm.product_name.get(p, p), 'sudah_dimiliki': p in held, 'ditahan_risiko': credit_hold and p in S.KREDIT}
        if p in prod:
            d.update(peluang_konversi_pct=round(prod[p]['peluang'], 1), dipakai_peer_pct=round(prod[p]['peer_pct'], 1),
                     ditahan_risiko=bool(prod[p]['ditunda']) or d['ditahan_risiko'])
        return d

    def ex(name, args):
        args = args or {}
        if name == 'profil_nasabah':
            if not fp:
                return {'nama': store.co.name.get(cid, cid), 'catatan': 'tidak ada skor model untuk perusahaan ini'}
            ak = fp['arus_kas']
            return {'nama': fp['nama'], 'industri': fp['industri'], 'segmen': fp['segmen'], 'tipe': fp['tipe'], 'karyawan': fp['karyawan'],
                    'payroll_di': fp['payroll'], 'produk_dimiliki': [model(p)['nama'] for p in sorted(held)],
                    'risiko': {'kelas': risk.get('kelas'), 'peluang_high_pct': round(risk.get('p_high', 0), 1), 'keputusan': risk.get('keputusan'),
                               'alasan': risk.get('alasan'), 'produk_kredit_ditahan': credit_hold},
                    'arus_kas': {'porsi_transaksi_di_bni_pct': round(ak['capture_now'] * 100, 1) if ak.get('ada_data') else None,
                                 'perubahan_porsi_6bln_poin': round(ak['capture_chg_6m'], 1) if ak.get('ada_data') else None,
                                 'telat_bayar_3bln_pct': round(ak['telat_3m'], 1) if ak.get('ada_data') else None},
                    'alarm_3bln': fp['anomali']['jenis_3bln'], 'erosi_wallet_tanpa_alarm': fp['anomali']['sinyal_bawah_ambang']}
        if name == 'info_produk':
            out = []
            for p in args.get('produk') or []:
                p = str(p).upper()
                if p not in pm.index:
                    out.append({'id': p, 'error': 'produk tidak dikenal'}); continue
                r = pm.loc[p]
                out.append({**model(p), 'kategori': r.product_category, 'manfaat': r.key_benefit, 'syarat': r.eligibility,
                            'catatan_harga': r.pricing_note, 'divisi_pemilik': r.owner_department, 'kunci_divisi': T.dept_keys(r.owner_department)})
            return out
        if name == 'penanganan_keberatan':
            t = str(args.get('keberatan', '')).lower()
            hit = [{'jenis': b['nama'], 'respon': b['respon'], 'divisi': b['divisi']} for b in PLAYBOOK if any(w in t for w in b['kata'])]
            ks = S.similar_cases(store, ctx['hasil'], t, '')
            return {'playbook': hit or [{'jenis': 'lainnya', 'respon': 'Klarifikasi akar keberatan pada kontak berikutnya sebelum menawarkan ulang.', 'divisi': []}],
                    'kasus_serupa': {'n': ks['n'], 'konversi_kontak_berikutnya_pct': round(ks['konversi_berikutnya'], 1),
                                     'catatan_mirip': ks['catatan_mirip']}}
        if name == 'kebutuhan_dari_catatan':
            hit, div, hold = T.suggest(args.get('teks', ''), ())
            iss = T.issues()
            return {'isu': [{'isu': iss.issue_name.get(i, i), 'produk_solusi': [model(p) for p in str(iss.solution_products.get(i, '')).split(';') if p and p != 'nan'],
                             'divisi': T.dept_keys(iss.department.get(i, ''))} for i in hit], 'menahan_kredit': hold}
        if name == 'kasus_serupa':
            ks = S.similar_cases(store, args.get('hasil') or ctx['hasil'], args.get('teks', ''), '')
            return {'n': ks['n'], 'konversi_kontak_berikutnya_pct': round(ks['konversi_berikutnya'], 1), 'rata_umum_pct': round(ks['rata_umum'], 1),
                    'per_kanal': {c: {'konversi_pct': round(r, 1), 'kasus': n} for c, (r, n) in ks['per_kanal'].items()},
                    'per_jeda_hari': {str(h): {'konversi_pct': round(r, 1), 'kasus': n} for h, (r, n) in ks['per_jeda'].items()},
                    'kanal_terbaik': ks['kanal_terbaik'], 'jeda_terbaik_hari': ks['jeda_terbaik']}
        if name == 'riwayat_kunjungan':
            rw = ctx['riwayat']
            return {'feedback_dashboard': [{'tanggal': r.tanggal, 'kanal': r.kanal, 'hasil': r.hasil, 'catatan': r.catatan, 'keberatan': r.keberatan,
                                            'langkah_lanjut_dijanjikan': r.langkah_lanjut} for r in rw.head(5).itertuples()],
                    'log_rm': (fp or {}).get('kunjungan', [])}
        if name == 'produk_alternatif':
            kec = {str(p).upper() for p in args.get('kecuali') or []} | set(ctx['produk'])
            alt = sorted([p for p in prod if p not in kec and p not in held and not model(p)['ditahan_risiko']], key=lambda p: -prod[p]['peluang'])
            return [model(p) for p in alt[:3]]
        if name == 'cari_slot':
            kanal = args.get('kanal') if args.get('kanal') in S.KANAL_KONTAK else 'Kunjungan'
            h = min(max(int(args.get('hari') or 7), 1), 120)
            t = T.free_slot(ctx['rm_id'], datetime.combine(date.today() + timedelta(days=h), time(10, 0)), K.R.DURASI_MENIT.get(kanal, 60))
            return {'mulai': t.isoformat(timespec='minutes'), 'hari_dari_sekarang': (t.date() - date.today()).days, 'kanal': kanal}
        if name == 'ajukan_rencana':
            ex.rencana = args
            return {'status': 'diterima'}
        return {'error': f'alat {name} tidak dikenal'}

    ex.rencana = None
    return ex


# ------------------------------------------------------------------ validasi & normalisasi rencana
def _clean(plan: dict, facts) -> tuple[dict, list]:
    """Buang langkah/teks yang memuat angka di luar catatan & hasil alat; rapikan jadwal & divisi."""
    dropped = []
    ok = lambda s: not R.check_numbers({'x': str(s)}, facts, extra_allowed=[str(h) for _, _, h in S.GAP])[1]
    langkah = []
    for l in plan.get('langkah') or []:
        if isinstance(l, dict) and l.get('aksi'):
            if ok(f"{l.get('aksi')} {l.get('alasan', '')}"):
                langkah.append({'judul': judul_singkat(l.get('judul') or l['aksi']), 'aksi': str(l['aksi']).strip(), 'alasan': str(l.get('alasan', '')).strip(),
                                'pemilik': T.DIVISI.get(str(l.get('pemilik') or 'RM'), str(l.get('pemilik') or 'RM')),
                                'tenggat_hari': min(max(int(l.get('tenggat_hari') or 3), 0), 120)})
            else:
                dropped.append(l.get('aksi'))
    j = plan.get('jadwal') or {}
    jam = str(j.get('jam', '10:00'))
    jam = jam if len(jam) == 5 and jam[2] == ':' and jam[:2].isdigit() and 8 <= int(jam[:2]) <= 15 else '10:00'
    out = {'pemahaman': str(plan.get('pemahaman', '')).strip() if ok(plan.get('pemahaman', '')) else '',
           'langkah': langkah,
           'keberatan': [k for k in plan.get('keberatan') or [] if isinstance(k, dict) and k.get('respon') and ok(k['respon'])],
           'jadwal': {'hari': min(max(int(j.get('hari') or 7), 1), 120), 'jam': jam, 'kanal': j.get('kanal') if j.get('kanal') in S.KANAL_KONTAK else 'Kunjungan',
                      'tujuan': str(j.get('tujuan', '')).strip()},
           'perlu_jadwal_ulang': bool(plan.get('perlu_jadwal_ulang')),
           'divisi': [d for d in plan.get('divisi') or [] if d in T.DIVISI],
           'pesan_divisi': str(plan.get('pesan_divisi', '')).strip() if ok(plan.get('pesan_divisi', '')) else '',
           'pertanyaan_kunci': [str(q) for q in plan.get('pertanyaan_kunci') or [] if ok(q)][:3]}
    return out, dropped


def judul_singkat(teks, n=5) -> str:
    """Judul kartu langkah: potong di tanda baca pertama, maksimal n kata."""
    t = str(teks).strip()
    for sep in (' — ', ' (', ';', ':', ',', ' dan ', ' lalu ', ' untuk ', ' ke '):
        if sep in t[3:]:
            t = t[:t.index(sep, 3)]
    w = t.split()
    return (' '.join(w[:n]) + ('…' if len(w) > n else '')).rstrip('.') or 'Langkah'


def langkah_teks(plan) -> str:
    """Rencana → isi kolom 'Langkah berikutnya' (bernomor, dengan pemilik & tenggat)."""
    return '\n'.join(f"{i}. {l['aksi']} — {l['pemilik']}, {'hari ini' if l['tenggat_hari'] == 0 else f'dalam {l["tenggat_hari"]} hari'}"
                     for i, l in enumerate(plan['langkah'], 1))


# ------------------------------------------------------------------ agen deterministik (tanpa LLM)
def _deterministic(store, ctx, ex):
    trace = []

    def call(name, args):
        out = ex(name, args); trace.append((name, args, out)); return out

    teks = f"{ctx['catatan']} {ctx['keberatan']}"
    prof = call('profil_nasabah', {})
    note = S.read_note(ctx['catatan'], ctx['keberatan'], ctx['isu'])
    fokus = list(dict.fromkeys(list(ctx['produk']) + note['produk_disebut']))
    if fokus:
        call('info_produk', {'produk': fokus})
    keb = call('penanganan_keberatan', {'keberatan': teks}) if (ctx['keberatan'] or note['keberatan'] or note['biaya'] or note['bank_lain']) else None
    call('kebutuhan_dari_catatan', {'teks': teks})
    call('riwayat_kunjungan', {})
    ks = call('kasus_serupa', {'teks': teks, 'hasil': ctx['hasil']})
    if ctx['hasil'] in ('Not interested', 'Converted'):
        call('produk_alternatif', {'kecuali': fokus})
    base = S.from_data(S.analyze(store, cid=ctx['company_id'], hasil=ctx['hasil'], catatan=ctx['catatan'], keberatan=ctx['keberatan'], produk=ctx['produk'],
                                 isu=ctx['isu'], hold=ctx['hold'], ulang=ctx['ulang'], riwayat=ctx['riwayat']))
    slot = call('cari_slot', {'hari': base['hari'], 'kanal': base['kanal']})
    parts = [p.strip() for p in base['langkah'].rstrip('.').split(';') if p.strip()]
    owner = lambda s: 'Pricing' if 'Pricing' in s else ('Risiko Kredit' if 'Risiko Kredit' in s else 'RM')
    langkah = [{'aksi': p[:1].upper() + p[1:], 'alasan': base['alasan'][0] if i == 0 else 'Dari sinyal model & kasus serupa.', 'pemilik': owner(p),
                'tenggat_hari': 2 if i == 0 else min(base['hari'], 7)} for i, p in enumerate(parts)]
    pihak = f"bertemu {note['pihak']}, " if note['pihak'] else ''
    pemahaman = (f"{prof.get('nama')}: {T.HASIL_ID.get(ctx['hasil'], ctx['hasil']).lower()}; {pihak}"
                 + (f"minta {' dan '.join(note['permintaan'])}; " if note['permintaan'] else '')
                 + (f"kebutuhan {', '.join(k['nama'].lower() for k in note['kebutuhan'])}; " if note['kebutuhan'] else '')
                 + (f"keberatan {', '.join(note['keberatan'])}." if note['keberatan'] else 'tanpa keberatan tercatat.'))
    plan = {'pemahaman': pemahaman, 'langkah': langkah,
            'keberatan': [{'keberatan': b['jenis'], 'respon': b['respon']} for b in (keb or {}).get('playbook', []) if b['jenis'] != 'lainnya'],
            'jadwal': {'hari': slot['hari_dari_sekarang'], 'jam': slot['mulai'][11:16], 'kanal': slot['kanal'],
                       'tujuan': 'Konfirmasi keputusan' if ctx['ulang'] else 'Tindak lanjut ' + (', '.join(note['permintaan']) or 'hasil kunjungan')},
            'perlu_jadwal_ulang': ctx['ulang'], 'divisi': list(dict.fromkeys(T.suggest(teks, fokus)[1] + [d for b in (keb or {}).get('playbook', []) for d in b['divisi']])),
            'pesan_divisi': base['pesan_divisi'],
            'pertanyaan_kunci': [q for q in [
                f"Kapan {note['pihak'] or 'pengambil keputusan'} bisa memberi keputusan, dan siapa lagi yang terlibat?" if ctx['ulang'] else '',
                f"Berapa {note['biaya']} yang dianggap wajar dibanding bank yang dipakai saat ini?" if note['biaya'] else '',
                'Layanan apa di bank lain yang paling sulit ditinggalkan?' if note['bank_lain'] else '',
                'Apa rencana bisnis 6–12 bulan ke depan dan kebutuhan pembiayaannya?'] if q][:3]}
    trace.append(('ajukan_rencana', {}, {'status': 'diterima'}))
    return plan, trace, ks


# ------------------------------------------------------------------ jalankan
@st.cache_data(show_spinner=False, max_entries=200)
def _run_llm(_store, _ex, key, user_msg):
    ans, trace = llm.run_tools(SYSTEM, user_msg, TOOLS, _ex, max_steps=12)
    if ans is None and _ex.rencana is None:
        raise RuntimeError(llm.complete.last_error or 'LLM tidak tersedia')                       # gagal tidak di-cache
    return _ex.rencana, [(n, a, o) for n, a, o in trace]


def run(store, *, company_id, rm_id, hasil, catatan, keberatan, produk, isu, hold, ulang, riwayat, nonce=0):
    """→ dict(rencana, jejak, mode, info). Rencana None bila catatan kosong."""
    if not str(catatan).strip():
        return None
    ctx = dict(company_id=company_id, rm_id=rm_id, hasil=hasil, catatan=catatan, keberatan=keberatan, produk=list(produk), isu=list(isu), hold=hold,
               ulang=ulang, riwayat=riwayat)
    ex = make_executor(store, ctx)
    nama = store.co.name.get(company_id, company_id)
    user_msg = (f"Nasabah: {nama} ({company_id}). RM: {rm_id}. Hari ini: {date.today():%Y-%m-%d}.\n"
                f"HASIL KUNJUNGAN: {T.HASIL_ID.get(hasil, hasil)} ({hasil})\n"
                f"PRODUK DIBAHAS: {', '.join(f'{p} {T.products().product_name.get(p, p)}' for p in produk) or '(tidak dipilih; cek catatan)'}\n"
                f"KEBERATAN NASABAH: {keberatan or '(tidak diisi; cek catatan)'}\n"
                f"CATATAN HASIL KUNJUNGAN:\n{catatan}")
    info, mode = None, 'deterministik'
    if llm.config()['enabled']:
        try:
            key = json.dumps([company_id, hasil, catatan, keberatan, sorted(produk), len(riwayat), nonce], ensure_ascii=False)
            plan, trace = _run_llm(store, ex, key, user_msg)
            if plan:
                facts = [catatan, keberatan, [o for _, _, o in trace]]
                plan, dropped = _clean(plan, json.loads(json.dumps(facts, default=lambda o: o.item() if hasattr(o, 'item') else str(o))))
                if plan['langkah']:
                    if dropped:
                        info = f"{len(dropped)} langkah dibuang karena memuat angka di luar catatan/data."
                    return {'rencana': plan, 'jejak': trace, 'mode': 'LLM', 'info': info}
                info = 'Rencana LLM tidak lolos validasi angka; dipakai agen deterministik.'
            else:
                info = 'LLM tidak memanggil ajukan_rencana; dipakai agen deterministik.'
        except Exception as e:
            info = f'LLM gagal ({str(e)[:140]}); dipakai agen deterministik.'
    plan, trace, _ = _deterministic(store, ctx, ex)
    plan, _ = _clean(plan, json.loads(json.dumps([catatan, keberatan, [o for _, _, o in trace]], default=lambda o: o.item() if hasattr(o, 'item') else str(o))))
    return {'rencana': plan, 'jejak': trace, 'mode': mode, 'info': info}



# ------------------------------------------------------------------ permintaan ke divisi (dipanggil tombol "Susun permintaan dengan AI")
def susun_permintaan(store, *, company_id, hasil, catatan, keberatan, produk, divisi, kegiatan, cadangan=''):
    """Draf permintaan RM ke divisi dari hasil kunjungan + kegiatan yang perlu koordinasi. → (teks, mode).
    Angka harus berasal dari catatan / kegiatan / profil; bila tidak, atau LLM tidak aktif, dipakai cadangan."""
    nama = store.co.name.get(company_id, company_id)
    seg = store.cox.segment.get(company_id, '') if company_id in store.cox.index else ''
    risk = store.cox.pred_class.get(company_id, '') if company_id in store.cox.index else ''
    pn = [T.products().product_name.get(p, p) for p in produk]
    divs = [T.DIVISI.get(d, d) for d in divisi]
    if not cadangan:
        cadangan = (f"Hasil kunjungan ke {nama}" + (f" ({seg}, risiko {risk})" if seg else '') + f": {T.HASIL_ID.get(hasil, hasil).lower()}."
                    + (f" Produk: {', '.join(pn)}." if pn else '') + (f" Keberatan: {keberatan}." if keberatan else '')
                    + (f" Mohon dukungan untuk: {'; '.join(kegiatan)}." if kegiatan else ' Mohon dukungan materi dan simulasi untuk tindak lanjut.'))
    if not llm.config()['enabled']:
        return cadangan, 'tanpa LLM'
    ctx = {'nasabah': nama, 'segmen': seg, 'risiko': risk, 'hasil_kunjungan': T.HASIL_ID.get(hasil, hasil), 'produk_dibahas': pn,
           'catatan': catatan, 'keberatan': keberatan, 'divisi_tujuan': divs, 'kegiatan_yang_perlu_dukungan': kegiatan}
    txt = llm.complete('Tulis permintaan singkat dari RM kepada divisi tujuan (3–4 kalimat, bahasa Indonesia profesional). Sebut nasabah, apa yang '
                       'diminta dari divisi dengan jelas, konteks dari catatan kunjungan, dan keberatan nasabah bila ada. Jangan menjanjikan harga atau '
                       'persetujuan kredit; hanya pakai angka yang ada di KONTEKS. Balas hanya dengan teks permintaannya.\n\nKONTEKS: '
                       + json.dumps(ctx, ensure_ascii=False), max_tokens=500)
    if not txt or not txt.strip():
        return cadangan, 'tanpa LLM'
    txt = txt.strip().strip('"')
    if R.check_numbers({'x': txt}, ctx)[1]:
        return cadangan, 'tanpa LLM'
    return txt, 'LLM'
