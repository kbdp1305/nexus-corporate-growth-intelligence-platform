"""Saran rencana lanjutan setelah kunjungan, dipersonalisasi per nasabah.

Dua lapis:
  1. Analisis data (selalu jalan, tanpa LLM):
     - model risiko (NB04)          → kelas risiko, keputusan, alasan; produk kredit ditahan bila High / ada isu legal
     - model peluang produk (NB05)  → peluang konversi & adopsi peer per produk yang dibahas; produk alternatif terbaik
     - alarm anomali & arus kas     → erosi wallet, distress, ekspansi, porsi transaksi di BNI, keterlambatan bayar
     - kasus serupa (log aksi RM)   → kontak dengan hasil & catatan mirip (TF-IDF); kanal & jeda yang paling sering berujung
                                      konversi di kontak berikutnya (dihaluskan ke rata-rata agar sampel kecil tidak mendominasi)
     - riwayat kunjungan nasabah ini (log aksi + feedback dashboard)
     Dasar utama tetap CATATAN hasil kunjungan (read_note): PIC yang ditemui, permintaan nasabah, produk yang disebut,
     kebutuhan & keberatan (issue_product_map), angka, dan waktu yang disebut nasabah. Model melengkapi dan mengoreksi.
  2. LLM (bila dikonfigurasi): menulis langkah, alasan, dan permintaan ke divisi dari paket analisis di atas.
     Angka divalidasi terhadap paket (reports.check_numbers); bagian dengan angka asing diganti hasil analisis data.
"""
from __future__ import annotations

import json
import re

import numpy as np
import pandas as pd
import streamlit as st
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

import reports as R

from . import llm, tindak as T

KANAL_KONTAK = ['Kunjungan', 'Telepon', 'Email']
GAP = [(1, 7, 5), (8, 14, 10), (15, 30, 21), (31, 60, 45)]          # (hari min, hari maks, usulan jeda)
KREDIT = ('P06', 'P07')
SMOOTH = 8                                                         # bobot rata-rata umum pada penghalusan tingkat konversi
f0, f1 = (lambda x: R.fmt(x, 0)), (lambda x: R.fmt(x, 1))


# ------------------------------------------------------------------ kasus serupa dari log aksi RM
@st.cache_resource(show_spinner=False)
def _cases(_store, n_log):
    """Pasangan (kontak → kontak berikutnya ke pihak yang sama) + indeks TF-IDF teks hasil & catatan."""
    lg = _store.log.sort_values(['party_id', 'contact_date']).copy()
    lg['d'] = pd.to_datetime(lg.contact_date)
    g = lg.groupby('party_id')
    lg['next_ch'], lg['next_conv'] = g.channel.shift(-1), g.converted.shift(-1)
    lg['gap'] = (g.d.shift(-1) - lg.d).dt.days
    pairs = lg.dropna(subset=['next_ch']).reset_index(drop=True)
    vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True)
    X = vec.fit_transform((pairs.response.str.lower() + ' ' + pairs.feedback_note.fillna('').str.lower()))
    return pairs, vec, X


def _rate(s, p0):
    return (s.sum() + SMOOTH * p0) / (len(s) + SMOOTH)


def similar_cases(store, hasil, catatan, keberatan, k=60):
    pairs, vec, X = _cases(store, len(store.log))
    p0 = float(pairs.next_conv.mean())
    sim = linear_kernel(vec.transform([f'{hasil} {catatan} {keberatan}'.lower()]), X).ravel()
    w = sim * np.where(pairs.response == hasil, 1.5, 1.0)
    idx = np.argsort(-w)[:k]
    nb = pairs.iloc[idx[w[idx] > 0.05]]
    if len(nb) < 15:                                               # catatan tidak mirip apa pun → pakai hasil yang sama
        nb = pairs[pairs.response == hasil]
    by_ch = {c: (_rate(nb.next_conv[nb.next_ch == c], p0) * 100, int((nb.next_ch == c).sum())) for c in KANAL_KONTAK}
    by_gap = {h: (_rate(nb.next_conv[nb.gap.between(lo, hi)], p0) * 100, int(nb.gap.between(lo, hi).sum())) for lo, hi, h in GAP}
    return {'n': len(nb), 'konversi_berikutnya': float(nb.next_conv.mean() * 100), 'rata_umum': p0 * 100,
            'per_kanal': by_ch, 'per_jeda': by_gap, 'kanal_terbaik': max(by_ch, key=lambda c: by_ch[c][0]),
            'jeda_terbaik': max(by_gap, key=lambda h: by_gap[h][0]),
            'catatan_mirip': nb.feedback_note.value_counts().head(3).index.tolist()}


# ------------------------------------------------------------------ membaca catatan hasil kunjungan
_PIHAK = [('direktur keuangan', 'direktur keuangan'), ('direktur utama', 'direktur utama'), ('dirut', 'direktur utama'), ('cfo', 'CFO'), ('ceo', 'CEO'),
          ('direksi', 'direksi'), ('direktur', 'direktur'), ('komisaris', 'komisaris'), ('owner', 'pemilik'), ('pemilik', 'pemilik'),
          ('manajer keuangan', 'manajer keuangan'), ('finance manager', 'manajer keuangan'), ('kepala keuangan', 'kepala keuangan'),
          ('bendahara', 'bendahara'), ('treasurer', 'treasurer'), ('hrd', 'HRD'), ('staf keuangan', 'staf keuangan'), ('accounting', 'bagian akuntansi')]
_MINTA = [('penawaran harga', 'penawaran harga'), ('proposal', 'proposal'), ('simulasi', 'simulasi'), ('presentasi', 'presentasi'), ('demo', 'demo sistem'),
          ('perbandingan', 'perbandingan'), ('term sheet', 'term sheet'), ('brosur', 'brosur'), ('daftar dokumen', 'daftar dokumen'), ('dokumen', 'daftar dokumen')]
_SEBUT = {'P01': ['giro'], 'P02': ['deposito'], 'P03': ['virtual account', ' va '], 'P04': ['cash management', 'cms'], 'P05': ['payroll', 'penggajian', 'gaji'],
          'P06': ['kredit modal kerja', 'kmk'], 'P07': ['kredit investasi'], 'P08': ['trade finance', 'l/c', 'skbdn', 'lindung nilai']}
_WAKTU = [('minggu depan', 7), ('pekan depan', 7), ('dua minggu', 14), ('2 minggu', 14), ('akhir bulan', 21), ('bulan depan', 30), ('kuartal depan', 90),
          ('triwulan depan', 90), ('semester depan', 180), ('tahun depan', 365), ('akhir tahun', 120)]
_ANGKA = re.compile(r'(?:rp\.?\s*)?\d[\d.,]*\s*(?:karyawan|pegawai|orang|unit|cabang|gerai|toko|truk|armada|miliar|milyar|juta|m\b|jt\b|%|hari|bulan)', re.I)
_KEBERATAN_ISU = {'biaya_tidak_kompetitif', 'sudah_pakai_bank_lain'}


def read_note(catatan, keberatan, isu):
    """Catatan & keberatan RM → hal-hal yang menjadi dasar rencana lanjutan."""
    t = f' {catatan} {keberatan} '.lower()
    iss = T.issues()
    sol = lambda i: [p for p in str(iss.solution_products.get(i, '')).split(';') if p and p != 'nan']
    return {'pihak': next((lab for k, lab in _PIHAK if k in t), ''),
            'permintaan': list(dict.fromkeys(lab for k, lab in _MINTA if k in t)),
            'produk_disebut': [p for p, ws in _SEBUT.items() if any(w in t for w in ws)],
            'kebutuhan': [{'isu': i, 'nama': iss.issue_name.get(i, i), 'produk': sol(i)} for i in isu if i not in _KEBERATAN_ISU and sol(i)],
            'keberatan': [keberatan.strip()] if keberatan.strip() else
                         [iss.issue_name.get(i, i).lower().removeprefix('keberatan ') for i in isu if i in _KEBERATAN_ISU],
            'biaya': 'biaya administrasi' if 'administrasi' in t else ('biaya' if any(w in t for w in ('biaya', 'mahal', 'fee', 'bunga', 'harga')) else ''),
            'bank_lain': any(w in t for w in ('bank lain', 'sudah memakai', 'sudah pakai', 'sudah aktif di')),
            'waktu': [(k, d) for k, d in _WAKTU if k in t],
            'angka': [m.group().strip() for m in _ANGKA.finditer(catatan)]}


# ------------------------------------------------------------------ paket analisis
def _fact_pack(store, cid):
    try:
        fp = R.fact_pack(store, cid)
    except Exception:                                              # perusahaan tanpa skor model
        return None
    fp['arus_kas'] = {k: v for k, v in fp['arus_kas'].items() if k != 'capture_seri'}
    fp['kunjungan'] = fp['kunjungan'][-5:]
    return fp


def analyze(store, *, cid, hasil, catatan, keberatan, produk, isu, hold, ulang, riwayat: pd.DataFrame) -> dict:
    """Semua bahan saran untuk satu feedback kunjungan. Angka di sini satu-satunya sumber angka saran."""
    pn = T.products().product_name
    fp = _fact_pack(store, cid) if cid else None
    note = read_note(catatan, keberatan, isu)
    prod = {p['produk']: p for p in (fp or {}).get('produk') or []}
    held = set((fp or {}).get('produk_dimiliki') or [])
    risk = (fp or {}).get('risiko') or {}
    credit_hold = hold or risk.get('kelas') == 'High'

    def info(p):
        d = {'id': p, 'nama': pn.get(p, p), 'dimiliki': p in held, 'ditunda': credit_hold and p in KREDIT}
        if p in prod:
            d.update(peluang=prod[p]['peluang'], peer_pct=prod[p]['peer_pct'], ditunda=bool(prod[p]['ditunda']) or d['ditunda'])
        return d

    fokus = list(dict.fromkeys(list(produk) + note['produk_disebut']))          # dipilih RM + disebut di catatan
    for k in note['kebutuhan']:
        k['produk'] = [info(p) for p in k['produk'] if p not in fokus and p not in held]
    alt = sorted([v for p, v in prod.items() if p not in fokus and p not in held and not v['ditunda'] and not (credit_hold and p in KREDIT)],
                 key=lambda v: -v['peluang'])
    prev = [{'tanggal': r.tanggal, 'kanal': r.kanal, 'hasil': r.hasil, 'catatan': r.catatan, 'keberatan': r.keberatan} for r in riwayat.head(5).itertuples()]
    return {'nama': (fp or {}).get('nama') or store.co.name.get(cid, cid), 'segmen': (fp or {}).get('segmen'), 'tipe': (fp or {}).get('tipe'),
            'karyawan': (fp or {}).get('karyawan'), 'payroll': (fp or {}).get('payroll'), 'hasil': hasil, 'catatan': catatan, 'keberatan': keberatan,
            'dari_catatan': note, 'perlu_pertimbangan_ulang': ulang, 'kredit_ditahan': credit_hold,
            'risiko': {k: risk.get(k) for k in ('kelas', 'p_high', 'keputusan', 'alasan')} if risk else None,
            'produk_fokus': [info(p) for p in fokus], 'produk_alternatif': [info(v['produk']) for v in alt[:2]], 'produk_dimiliki': sorted(held),
            'arus_kas': (fp or {}).get('arus_kas'), 'alarm_3bln': ((fp or {}).get('anomali') or {}).get('jenis_3bln', []),
            'erosi_tanpa_alarm': ((fp or {}).get('anomali') or {}).get('sinyal_bawah_ambang', False),
            'kasus_serupa': similar_cases(store, hasil, catatan, keberatan),
            'riwayat_dashboard': prev, 'riwayat_log': (fp or {}).get('kunjungan', [])}


# ------------------------------------------------------------------ saran dari analisis data (tanpa LLM)
def _pnames(lst):
    return ', '.join(x['nama'] for x in lst) or 'produk yang dibahas'


def _model(p):
    return f" (peluang {f0(p['peluang'])}%, dipakai {f0(p['peer_pct'])}% peer)" if 'peluang' in p else ''


def from_data(a: dict) -> dict:
    """Paket analisis → {langkah, alasan[], hari, kanal, jam, pesan_divisi}. Dasar utama: catatan kunjungan; model & kasus serupa melengkapi."""
    hasil, ks, ak, n = a['hasil'], a['kasus_serupa'], a['arus_kas'] or {}, a['dari_catatan']
    fokus = [p for p in a['produk_fokus'] if not p['ditunda']]
    ditunda = [p for p in a['produk_fokus'] if p['ditunda']]
    alt = a['produk_alternatif'][0] if a['produk_alternatif'] else None
    ke = f" ke {n['pihak']}" if n['pihak'] else ''
    angka = [x for x in n['angka'] if not x.lower().endswith(('hari', 'bulan'))]
    untuk = f" untuk {' dan '.join(angka[:2])}" if angka else ''
    minta = ' dan '.join(n['permintaan'][:2])
    n_prev = len(a['riwayat_log']) + len(a['riwayat_dashboard'])
    tolak = sum(r['hasil'] == 'Not interested' for r in a['riwayat_dashboard']) + sum(r['respons'] == 'Not interested' for r in a['riwayat_log'])
    diam = sum(r['hasil'] == 'No response' for r in a['riwayat_dashboard']) + sum(r['respons'] == 'No response' for r in a['riwayat_log'])
    kanal, hari = ks['kanal_terbaik'], ks['jeda_terbaik']
    langkah, sebab = [], ''

    # 1. tanggapi hasil & permintaan nasabah di catatan
    if hasil == 'Converted':
        langkah.append(f"Proses onboarding {_pnames(fokus)}{untuk}: kirim {minta or 'daftar dokumen'}{ke} dan koordinasikan aktivasi dengan divisi pemilik produk")
        hari, sebab = min(hari, 5), 'onboarding dipercepat sebelum minat turun'
    elif hasil == 'Interested' or a['perlu_pertimbangan_ulang']:
        langkah.append(f"Kirim {minta or 'proposal dan simulasi'} {_pnames(fokus)}{untuk}{ke}")
    elif hasil == 'Not interested':
        alasan_tolak = n['keberatan'][0].lower() if n['keberatan'] else ''
        butuh = next(((k, p) for k in n['kebutuhan'] for p in k['produk'] if not p['ditunda']), None)
        if butuh:                                                  # catatan memuat kebutuhan lain → alihkan ke produk solusinya
            k, p = butuh
            langkah.append(f"Catat penolakan {_pnames(fokus)}" + (f" (alasan: {alasan_tolak})" if alasan_tolak else '')
                           + f"; alihkan ke {p['nama']}{_model(p)} untuk {k['nama'].lower()} yang muncul di catatan")
            hari, sebab = max(min(hari, 21), 14), 'kebutuhan baru muncul di catatan; tawarkan solusi selagi relevan'
        elif tolak >= 1 and not alt:
            langkah.append('Turunkan prioritas; pantau sinyal arus kas dan hubungi lagi bila ada kebutuhan baru')
            hari, kanal, sebab = 90, 'Telepon', 'sudah berulang kali menolak'
        else:
            langkah.append(f"Catat penolakan {_pnames(fokus)}" + (f" (alasan: {alasan_tolak})" if alasan_tolak else '')
                           + (f"; tawarkan sudut lain lewat {alt['nama']}{_model(alt)}" if alt else ''))
            hari, sebab = max(hari, 30 if tolak else 21), 'jeda setelah penolakan sebelum menawarkan produk lain'
    else:
        hari, sebab = min(hari, 14), 'jangan biarkan kontak dingin terlalu lama'
        langkah.append(f'Hubungi ulang lewat {kanal.lower()}' + ('; cari PIC lain (mis. bagian keuangan) karena sudah berulang kali tidak ada respons' if diam else ''))

    # 2. jawab keberatan di catatan
    if hasil != 'Not interested':
        if n['biaya']:
            langkah.append(f"ajukan keringanan {n['biaya']} ke Pricing dan sertakan perbandingan biaya-manfaat")
        if n['bank_lain']:
            if 'perbandingan' in n['permintaan']:
                langkah[0] = langkah[0].replace('Kirim perbandingan', 'Kirim perbandingan layanan (vs bank yang dipakai saat ini) untuk', 1)
            else:
                langkah.append('siapkan perbandingan layanan dengan bank yang dipakai nasabah saat ini')

    # 3. kebutuhan lain yang muncul di catatan → produk solusi (dengan peluang dari model)
    for k in n['kebutuhan'][:2]:
        ps = [p for p in k['produk'] if not p['ditunda']]
        if ps and hasil != 'Not interested':
            w = next((kw for kw, d in n['waktu'] if d > 60), '')
            langkah.append(f"siapkan pembahasan {ps[0]['nama']}{_model(ps[0])} untuk {k['nama'].lower()}" + (f" ({w})" if w else ''))

    # 4. jadwal ulang bila nasabah menimbang; waktu yang disebut nasabah diutamakan
    dekat = [(kw, d) for kw, d in n['waktu'] if d <= 60]
    if a['perlu_pertimbangan_ulang'] and hasil != 'Not interested':
        t = f"{a['catatan']} {a['keberatan']}".lower()
        langkah.append('jadwalkan ulang untuk konfirmasi keputusan'
                       + (' setelah dibahas di rapat direksi' if 'direksi' in t and n['pihak'] != 'direksi' else f" setelah {n['pihak']} menimbang" if n['pihak'] else ''))
        hari, sebab = max(hari, 10), 'beri waktu nasabah menimbang'
    if dekat:
        hari, sebab = dekat[0][1], f'sesuai waktu yang disebut di catatan ({dekat[0][0]})'

    # 5. sinyal model yang perlu diwaspadai
    if ditunda or (a['kredit_ditahan'] and hasil != 'Not interested'):
        langkah.append('jangan lanjutkan produk kredit dulu; libatkan Risiko Kredit' + (f" ({_pnames(ditunda)} ditahan)" if ditunda else ''))
    if 'erosi wallet' in a['alarm_3bln'] or a['erosi_tanpa_alarm']:
        langkah.append('tanyakan pembayaran mana yang pindah ke bank lain dan alasannya')
    if 'ekspansi' in a['alarm_3bln'] and not a['kredit_ditahan'] and hasil in ('Interested', 'Converted') and not n['kebutuhan']:
        langkah.append('gali kebutuhan pembiayaan ekspansi')
    if hasil == 'Converted' and alt:
        langkah.append(f"siapkan {alt['nama']}{_model(alt)} sebagai penawaran berikutnya")

    # alasan (bukti): isi catatan dulu, lalu model
    dari = [f"bertemu {n['pihak']}" if n['pihak'] else '', f'minta {minta}' if minta else '',
            f"produk disebut: {_pnames([p for p in a['produk_fokus'] if p['id'] in n['produk_disebut']])}" if n['produk_disebut'] else '',
            f"kebutuhan: {', '.join(k['nama'].lower() for k in n['kebutuhan'])}" if n['kebutuhan'] else '',
            f"keberatan: {', '.join(x.lower() for x in n['keberatan'])}" if n['keberatan'] else '',
            f"angka: {', '.join(n['angka'])}" if n['angka'] else '', f"waktu: {', '.join(k for k, _ in n['waktu'])}" if n['waktu'] else '']
    alasan = ['Dari catatan kunjungan: ' + ('; '.join(x for x in dari if x) or 'tidak ada detail spesifik, saran bertumpu pada data model') + '.']
    for p in a['produk_fokus'] + [p for k in n['kebutuhan'] for p in k['produk']]:
        if 'peluang' in p:
            alasan.append(f"Model peluang · {p['nama']}: peluang konversi {f0(p['peluang'])}%, dipakai {f0(p['peer_pct'])}% peer"
                          + (' · ditahan karena risiko.' if p['ditunda'] else ' · sudah dimiliki.' if p['dimiliki'] else '.'))
    if a['risiko']:
        r = a['risiko']
        alasan.append(f"Model risiko: kelas {r['kelas']} (peluang High {f1(r['p_high'])}%), keputusan {str(r['keputusan']).lower()}.")
    if ak.get('ada_data') and ak.get('capture_chg_6m') is not None and np.isfinite(ak['capture_chg_6m']):
        alasan.append(f"Arus kas: porsi transaksi di BNI {f1(ak['capture_now'] * 100)}%, berubah {f1(ak['capture_chg_6m'])} poin dalam 6 bulan; "
                      f"keterlambatan bayar {f0(ak['telat_3m'])}%.")
    if a['alarm_3bln']:
        alasan.append(f"Alarm 3 bulan terakhir: {', '.join(a['alarm_3bln'])}.")
    ch_rate, ch_n = ks['per_kanal'][ks['kanal_terbaik']]
    g_rate, g_n = ks['per_jeda'][ks['jeda_terbaik']]
    alasan.append(f"Kasus serupa di log RM ({ks['n']} kontak dengan hasil/catatan mirip): konversi di kontak berikutnya {f0(ks['konversi_berikutnya'])}% "
                  f"(rata-rata umum {f0(ks['rata_umum'])}%); tertinggi lewat {ks['kanal_terbaik'].lower()} ({f0(ch_rate)}%, {ch_n} kasus) "
                  f"dan jeda sekitar {ks['jeda_terbaik']} hari ({f0(g_rate)}%, {g_n} kasus)."
                  + (f" Jadwal disesuaikan ke {hari} hari: {sebab}." if hari != ks['jeda_terbaik'] and sebab else ''))
    alasan.append(f"Riwayat: kunjungan ke-{n_prev + 1}" + (f"; sebelumnya {tolak}× tidak tertarik" if tolak else '') + (f", {diam}× tidak ada respons" if diam else '') + '.')

    if minta:
        minta_div = f" Nasabah minta {minta}; mohon disiapkan" + (f" beserta opsi keringanan {n['biaya']}." if n['biaya'] else '.')
    elif n['biaya']:
        minta_div = f" Mohon opsi keringanan {n['biaya']} dan simulasi biaya-manfaat."
    else:
        minta_div = ' Mohon dukungan materi dan simulasi untuk tindak lanjut.'
    pesan = (f"Hasil kunjungan ke {a['nama']}" + (f" ({a['segmen']}, risiko {a['risiko']['kelas']})" if a['risiko'] else '')
             + f": {T.HASIL_ID.get(hasil, hasil).lower()}" + (f", bertemu {n['pihak']}" if n['pihak'] else '') + '.'
             + (f" Produk: {_pnames(a['produk_fokus'])}{untuk}." if a['produk_fokus'] else '')
             + (f" Kebutuhan: {', '.join(k['nama'].lower() for k in n['kebutuhan'])}." if n['kebutuhan'] else '')
             + (f" Keberatan: {', '.join(x.lower() for x in n['keberatan'])}." if n['keberatan'] else '')
             + minta_div + (' Produk kredit ditahan sampai ada kajian risiko.' if a['kredit_ditahan'] else ''))
    txt = '; '.join(langkah)
    return {'langkah': txt[:1].upper() + txt[1:] + '.', 'alasan': alasan, 'hari': int(min(hari, 120)),
            'kanal': kanal if kanal in KANAL_KONTAK else 'Kunjungan', 'jam': '10:00', 'pesan_divisi': pesan}


# ------------------------------------------------------------------ saran dari LLM
LLM_KEYS = ['langkah', 'alasan', 'hari', 'kanal', 'jam', 'pesan_divisi']
PROMPT = ('Anda menyusun rencana tindak lanjut setelah kunjungan RM ke nasabah korporasi. DASAR UTAMA adalah CATATAN hasil kunjungan (lihat "catatan", '
          '"keberatan", dan "dari_catatan": PIC yang ditemui, permintaan nasabah, produk yang disebut, kebutuhan, keberatan, angka, waktu). '
          'Setiap langkah harus menjawab hal yang tertulis di catatan. Output model (risiko, peluang produk, arus kas, kasus serupa, riwayat) dipakai '
          'untuk memperkuat atau mengoreksi, misalnya menahan produk kredit atau memilih kanal dan jeda. Bila nasabah perlu pertimbangan ulang, '
          'tentukan kapan dijadwalkan ulang; bila catatan menyebut waktu, ikuti waktu itu. '
          'Kunci JSON: langkah (1–2 kalimat perintah yang langsung bisa dikerjakan RM), alasan (daftar 3–5 butir; butir pertama merangkum isi catatan, '
          'sisanya bukti dari analisis beserta angkanya), hari (bilangan bulat 1–120: jeda ke jadwal berikutnya), kanal (Kunjungan / Telepon / Email), '
          'jam (HH:MM, 08:00–15:00), pesan_divisi (2–3 kalimat permintaan ke divisi terkait, sebut permintaan nasabah). '
          'Format angka gaya Indonesia (koma desimal). Hanya pakai angka yang ada di ANALISIS.\n\nANALISIS:\n')


@st.cache_data(show_spinner=False, max_entries=300)
def _llm(pack_json):
    out = llm.complete_json(PROMPT + pack_json, LLM_KEYS, max_tokens=900)
    if not out:
        raise RuntimeError(llm.complete.last_error or 'LLM tidak membalas dengan JSON yang benar.')   # gagal tidak di-cache
    return out


def from_llm(a: dict, base: dict):
    """→ (saran, info). Bagian yang angkanya tidak ada di paket analisis diganti saran dari analisis data."""
    pack = json.dumps(a, ensure_ascii=False, default=lambda o: o.item() if hasattr(o, 'item') else str(o))
    out = _llm(pack)
    s, bad = dict(base), []
    for key in ('langkah', 'pesan_divisi', 'alasan'):
        v = out.get(key)
        if isinstance(v, str) and key == 'alasan':
            v = [x.strip('-• ') for x in v.split('\n') if x.strip()]
        if not v:
            continue
        _, wrong = R.check_numbers({key: v}, a, extra_allowed=[str(h) for _, _, h in GAP])
        if wrong:
            bad.append((key, wrong))
        else:
            s[key] = v.strip() if isinstance(v, str) else [str(x).strip() for x in v]
    try:
        s['hari'] = min(max(int(out.get('hari')), 1), 120)
    except (TypeError, ValueError):
        pass
    if out.get('kanal') in KANAL_KONTAK:
        s['kanal'] = out['kanal']
    jam = str(out.get('jam', '')).strip()
    if len(jam) == 5 and jam[2] == ':' and jam[:2].isdigit() and 8 <= int(jam[:2]) <= 15 and jam[3:].isdigit():
        s['jam'] = jam
    return s, bad


def suggest(store, pakai_llm=True, **kw):
    """→ (saran, mode, info, analisis). mode: 'LLM' atau 'analisis data'; info: pesan galat / bagian yang diganti.
    Tanpa catatan kunjungan tidak ada saran (None): rencana lanjutan harus berangkat dari hasil kunjungan."""
    if not str(kw.get('catatan', '')).strip():
        return None, None, None, None
    a = analyze(store, **kw)
    base = from_data(a)
    if not (pakai_llm and llm.config()['enabled']):
        return base, 'analisis data', None, a
    try:
        s, bad = from_llm(a, base)
        return s, 'LLM', ('Bagian dengan angka di luar data diganti hasil analisis: ' + ', '.join(k for k, _ in bad)) if bad else None, a
    except Exception as e:
        return base, 'analisis data', f'LLM gagal: {str(e)[:160]}', a
