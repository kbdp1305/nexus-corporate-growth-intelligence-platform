"""Saran rencana lanjutan setelah kunjungan, dipersonalisasi per nasabah.

Dua lapis:
  1. Analisis data (selalu jalan, tanpa LLM):
     - model risiko (NB04)          → kelas risiko, keputusan, alasan; produk kredit ditahan bila High / ada isu legal
     - model peluang produk (NB05)  → peluang konversi & adopsi peer per produk yang dibahas; produk alternatif terbaik
     - alarm anomali & arus kas     → erosi wallet, distress, ekspansi, porsi transaksi di BNI, keterlambatan bayar
     - kasus serupa (log aksi RM)   → kontak dengan hasil & catatan mirip (TF-IDF); kanal & jeda yang paling sering berujung
                                      konversi di kontak berikutnya (dihaluskan ke rata-rata agar sampel kecil tidak mendominasi)
     - riwayat kunjungan nasabah ini (log aksi + feedback dashboard)
  2. LLM (bila dikonfigurasi): menulis langkah, alasan, dan permintaan ke divisi dari paket analisis di atas.
     Angka divalidasi terhadap paket (reports.check_numbers); bagian dengan angka asing diganti hasil analisis data.
"""
from __future__ import annotations

import json

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
    prod = {p['produk']: p for p in (fp or {}).get('produk') or []}
    held = set((fp or {}).get('produk_dimiliki') or [])
    risk = (fp or {}).get('risiko') or {}
    credit_hold = hold or risk.get('kelas') == 'High'
    dibahas = [{'id': p, 'nama': pn.get(p, p), 'peluang': prod[p]['peluang'], 'peer_pct': prod[p]['peer_pct'],
                'ditunda': prod[p]['ditunda'] or (credit_hold and p in KREDIT)} if p in prod else {'id': p, 'nama': pn.get(p, p)} for p in produk]
    alt = sorted([v for p, v in prod.items() if p not in produk and p not in held and not v['ditunda'] and not (credit_hold and p in KREDIT)],
                 key=lambda v: -v['peluang'])
    alt = [{'id': v['produk'], 'nama': pn.get(v['produk'], v['produk']), 'peluang': v['peluang'], 'peer_pct': v['peer_pct']} for v in alt[:2]]
    prev = [{'tanggal': r.tanggal, 'kanal': r.kanal, 'hasil': r.hasil, 'catatan': r.catatan, 'keberatan': r.keberatan} for r in riwayat.head(5).itertuples()]
    return {'nama': (fp or {}).get('nama') or store.co.name.get(cid, cid), 'segmen': (fp or {}).get('segmen'), 'tipe': (fp or {}).get('tipe'),
            'karyawan': (fp or {}).get('karyawan'), 'payroll': (fp or {}).get('payroll'), 'hasil': hasil, 'catatan': catatan, 'keberatan': keberatan,
            'perlu_pertimbangan_ulang': ulang, 'isu': [T.issues().issue_name.get(i, i) for i in isu], 'kredit_ditahan': credit_hold,
            'risiko': {k: risk.get(k) for k in ('kelas', 'p_high', 'keputusan', 'alasan')} if risk else None,
            'produk_dibahas': dibahas, 'produk_alternatif': alt, 'produk_dimiliki': sorted(held),
            'arus_kas': (fp or {}).get('arus_kas'), 'alarm_3bln': ((fp or {}).get('anomali') or {}).get('jenis_3bln', []),
            'erosi_tanpa_alarm': ((fp or {}).get('anomali') or {}).get('sinyal_bawah_ambang', False),
            'jaringan_prospect_teratas': [x[1] for x in ((fp or {}).get('jaringan') or {}).get('prospect_teratas', [])[:2]],
            'kasus_serupa': similar_cases(store, hasil, catatan, keberatan),
            'riwayat_dashboard': prev, 'riwayat_log': (fp or {}).get('kunjungan', [])}


# ------------------------------------------------------------------ saran dari analisis data (tanpa LLM)
def _pnames(lst):
    return ', '.join(x['nama'] for x in lst) or 'produk yang dibahas'


def from_data(a: dict) -> dict:
    """Paket analisis → {langkah, alasan[], hari, kanal, jam, pesan_divisi}. Setiap kalimat merujuk angka di paket."""
    hasil, ks, ak, k = a['hasil'], a['kasus_serupa'], a['arus_kas'] or {}, str(a['keberatan']).lower()
    dib = [p for p in a['produk_dibahas'] if not p.get('ditunda')]
    ditunda = [p for p in a['produk_dibahas'] if p.get('ditunda')]
    alt = a['produk_alternatif'][0] if a['produk_alternatif'] else None
    alt_txt = f"{alt['nama']} (peluang {f0(alt['peluang'])}%, dipakai {f0(alt['peer_pct'])}% peer)" if alt else ''
    n_prev = len(a['riwayat_log']) + len(a['riwayat_dashboard'])
    tolak = sum(r['hasil'] == 'Not interested' for r in a['riwayat_dashboard']) + sum(r['respons'] == 'Not interested' for r in a['riwayat_log'])
    diam = sum(r['hasil'] == 'No response' for r in a['riwayat_dashboard']) + sum(r['respons'] == 'No response' for r in a['riwayat_log'])
    kanal, hari = ks['kanal_terbaik'], ks['jeda_terbaik']
    langkah, sebab = [], ''

    # inti langkah per hasil kunjungan
    if hasil == 'Converted':
        langkah.append(f'Proses onboarding {_pnames(dib)}: kirim checklist dokumen dan koordinasikan aktivasi dengan divisi pemilik produk')
        if alt:
            langkah.append(f'siapkan {alt_txt} sebagai penawaran berikutnya')
        hari, sebab = min(hari, 5), 'onboarding dipercepat sebelum minat turun'
    elif a['perlu_pertimbangan_ulang']:
        if any(w in k for w in ('biaya', 'mahal', 'bunga', 'fee', 'admin', 'harga')) or 'biaya' in a['catatan'].lower():
            langkah.append(f'Siapkan simulasi biaya-manfaat {_pnames(dib)} dan ajukan pricing khusus ke divisi Pricing')
        elif 'bank lain' in k or 'bank lain' in a['catatan'].lower():
            langkah.append(f'Siapkan perbandingan layanan {_pnames(dib)} dengan bank lain yang dipakai nasabah')
        elif any(w in a['catatan'].lower() for w in ('direksi', 'direktur', 'cfo', 'komisaris', 'pusat')):
            langkah.append(f'Kirim ringkasan proposal {_pnames(dib)} satu halaman untuk bahan rapat direksi nasabah')
        else:
            langkah.append(f'Kirim ringkasan proposal {_pnames(dib)} beserta jawaban atas pertanyaan nasabah')
        langkah.append('jadwalkan ulang pertemuan untuk konfirmasi keputusan')
        hari, sebab = max(hari, 10), 'beri waktu nasabah menimbang'
    elif hasil == 'Interested':
        top = max(dib, key=lambda p: p.get('peluang', 0)) if dib else None
        langkah.append(f"Kirim proposal dan simulasi {top['nama']}" + (f" (peluang konversi {f0(top['peluang'])}%, dipakai {f0(top['peer_pct'])}% peer)" if 'peluang' in top else '')
                       if top else 'Kirim proposal dan simulasi produk yang dibahas')
        langkah.append('minta jadwal presentasi ke pengambil keputusan')
    elif hasil == 'Not interested':
        if tolak >= 1 and not alt:
            langkah.append('Turunkan prioritas; pantau sinyal arus kas dan hubungi lagi bila ada kebutuhan baru')
            hari, kanal, sebab = 90, 'Telepon', 'sudah berulang kali menolak'
        else:
            langkah.append(f'Ganti sudut penawaran ke {alt_txt} yang belum dibahas' if alt else 'Catat alasan penolakan dan cari produk lain yang lebih sesuai')
            hari, sebab = max(hari, 30 if tolak else 21), 'jeda setelah penolakan sebelum menawarkan produk lain'
    else:
        hari, sebab = min(hari, 14), 'jangan biarkan kontak dingin terlalu lama'
        langkah.append(f'Hubungi ulang lewat {kanal.lower()}' + ('; cari PIC lain (mis. bagian keuangan) karena sudah berulang kali tidak ada respons' if diam else ''))
        if alt:
            langkah.append(f'buka percakapan dengan {alt_txt}')

    # pengubah dari sinyal model
    if ditunda or (a['kredit_ditahan'] and hasil != 'Not interested'):
        langkah.append('jangan lanjutkan produk kredit dulu; libatkan Risiko Kredit' + (f" ({_pnames(ditunda)} ditahan)" if ditunda else ''))
    if 'erosi wallet' in a['alarm_3bln'] or a['erosi_tanpa_alarm']:
        langkah.append('tanyakan pembayaran mana yang pindah ke bank lain dan alasannya')
    if 'ekspansi' in a['alarm_3bln'] and not a['kredit_ditahan'] and hasil in ('Interested', 'Converted'):
        langkah.append('gali kebutuhan pembiayaan ekspansi')

    # alasan (bukti)
    alasan = []
    if a['risiko']:
        r = a['risiko']
        alasan.append(f"Model risiko: kelas {r['kelas']} (peluang High {f1(r['p_high'])}%), keputusan {str(r['keputusan']).lower()}.")
    for p in a['produk_dibahas']:
        if 'peluang' in p:
            alasan.append(f"{p['nama']}: peluang konversi {f0(p['peluang'])}%, dipakai {f0(p['peer_pct'])}% peer" + (' · ditahan karena risiko.' if p['ditunda'] else '.'))
    if alt and hasil != 'Interested':
        alasan.append(f"Produk alternatif dengan peluang tertinggi yang belum dimiliki: {alt_txt}.")
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

    pesan = (f"Hasil kunjungan ke {a['nama']}" + (f" ({a['segmen']}, risiko {a['risiko']['kelas']})" if a['risiko'] else '')
             + f": {T.HASIL_ID.get(hasil, hasil).lower()}." + (f" Produk: {_pnames(a['produk_dibahas'])}." if a['produk_dibahas'] else '')
             + (f" Keberatan: {a['keberatan']}." if a['keberatan'] else '')
             + (' Mohon simulasi biaya dan opsi pricing khusus.' if 'biaya' in k or 'mahal' in k else ' Mohon dukungan materi dan simulasi untuk tindak lanjut.')
             + (' Produk kredit ditahan sampai ada kajian risiko.' if a['kredit_ditahan'] else ''))
    return {'langkah': '; '.join(langkah) + '.', 'alasan': alasan, 'hari': int(hari),
            'kanal': kanal if kanal in KANAL_KONTAK else 'Kunjungan', 'jam': '10:00', 'pesan_divisi': pesan}


# ------------------------------------------------------------------ saran dari LLM
LLM_KEYS = ['langkah', 'alasan', 'hari', 'kanal', 'jam', 'pesan_divisi']
PROMPT = ('Anda menyusun rencana tindak lanjut setelah kunjungan RM ke nasabah korporasi. Gunakan ANALISIS (output model risiko, model peluang produk, '
          'alarm arus kas, kasus serupa dari log RM, riwayat kunjungan) dan isian RM. Personalisasi ke kondisi nasabah ini: sebut produk, keberatan, '
          'dan sinyal yang relevan; jangan memberi saran umum. Bila nasabah perlu pertimbangan ulang, tentukan kapan dijadwalkan ulang. '
          'Kunci JSON: langkah (1–2 kalimat perintah yang langsung bisa dikerjakan RM), alasan (daftar 3–5 butir bukti dari ANALISIS, sebut angkanya), '
          'hari (bilangan bulat 1–120: jeda ke jadwal berikutnya; pertimbangkan jeda terbaik di kasus serupa), kanal (Kunjungan / Telepon / Email), '
          'jam (HH:MM, 08:00–15:00), pesan_divisi (2–3 kalimat permintaan ke divisi terkait). Format angka gaya Indonesia (koma desimal). '
          'Hanya pakai angka yang ada di ANALISIS.\n\nANALISIS:\n')


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
    """→ (saran, mode, info). mode: 'LLM' atau 'analisis data'; info: pesan galat / bagian yang diganti."""
    a = analyze(store, **kw)
    base = from_data(a)
    if not (pakai_llm and llm.config()['enabled']):
        return base, 'analisis data', None, a
    try:
        s, bad = from_llm(a, base)
        return s, 'LLM', ('Bagian dengan angka di luar data diganti hasil analisis: ' + ', '.join(k for k, _ in bad)) if bad else None, a
    except Exception as e:
        return base, 'analisis data', f'LLM gagal: {str(e)[:160]}', a
