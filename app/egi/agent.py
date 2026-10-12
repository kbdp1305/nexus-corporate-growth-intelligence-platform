"""RM Copilot: alat (tools) di atas data skor, alur agen deterministik, dan agen LLM dengan tool use.

Alur deterministik (selalu jalan, juga tanpa LLM) menjamin hasil yang bisa diaudit;
LLM (bila aktif) dipakai untuk menjawab pertanyaan bebas dengan memanggil alat yang sama.
"""
from __future__ import annotations

import json
import re

import numpy as np
import pandas as pd

import reports as R

from . import llm
from .data import ROOT

UP, CAUTION = {'expansion', 'wallet_erosion'}, {'distress', 'buyer_exit', 'contagion'}
JAM = ['09.00', '11.00', '14.00', '16.00']


# ---------------------------------------------------------------- penilaian kandidat
def candidates(store, rm, basket_ids=()):
    pf = store.portfolio(rm).copy()
    if pf.empty:
        return pf
    wn = store.why_now(pf.index)
    pf['why_up'] = pf.index.isin(wn[wn.event_type.isin(UP)].company_id)
    pf['caution'] = pf.index.isin(wn[wn.event_type.isin(CAUTION)].company_id)
    pf['alarm'] = pf.index.map(wn.groupby('company_id').event_type.agg(lambda s: ', '.join(sorted(set(s))))).fillna('')
    pf['contacted'] = pf.index.isin(store.contacted(rm))
    pf['in_basket'] = pf.index.isin(basket_ids)
    pf['prio'] = pf.opportunity_score + 0.3 * pf.in_basket + 0.08 * pf.why_up + 0.05 * (~pf.contacted)
    return pf.sort_values('prio', ascending=False)


def _purpose(store, cid, row):
    fp_cap = store.panel[(store.panel.company_id == cid) & (store.panel.ym == R.REF_MONTH)].capture_chg_6m
    cap = float(fp_cap.iloc[0]) * 100 if len(fp_cap) and np.isfinite(fp_cap.iloc[0]) else 0.0
    pr = store.prod[(store.prod.company_id == cid) & (~store.prod.ditunda_risiko)].sort_values('rank_produk')
    p = pr.iloc[0] if len(pr) else None
    parts = []
    if cap <= -10 or 'wallet_erosion' in row.get('alarm', ''):
        parts.append(f'Retensi: porsi wallet berubah {R.fmt(cap, 0)} poin dalam 6 bulan.')
    if 'expansion' in row.get('alarm', ''):
        parts.append('Alarm ekspansi: cek kebutuhan modal kerja.')
    if p is not None:
        parts.append(f"Tawarkan {p.product_id} (peluang {R.fmt(p.p_konversi * 100, 0)}%).")
    if row.get('risk_class') == 'Medium':
        parts.append('Risiko Medium: kredit × 0,5.')
    if row.get('risk_class') == 'High':
        parts.append('Risiko High: hanya produk non-kredit.')
    if not row.get('contacted', True):
        parts.append('Belum pernah dihubungi.')
    return ' '.join(parts), (f"{R.fmt(p.p_konversi * 100, 0)}%" if p is not None else '—')


def _item(store, cid, row, jam, siapkan):
    tujuan, peluang = _purpose(store, cid, row)
    c = store.cox.loc[cid]
    return {'jam': jam, 'id': cid, 'nama': c['name'], 'kecamatan': c.district, 'info': f"{c.segment} · {c.district} · risiko {c.pred_class}", 'tujuan': tujuan, 'peluang': peluang, 'siapkan': siapkan}


# ---------------------------------------------------------------- alur 1: rencana minggu
def plan_week(store, rm, basket=(), days=None, week_label='minggu ini'):
    """days = [(hari, 'Kunjungan'|'Telepon', jumlah_slot), ...]"""
    days = days or [('Selasa', 'Kunjungan', 3), ('Rabu', 'Telepon', 2), ('Kamis', 'Kunjungan', 2)]
    basket_ids = [b['id'] for b in basket]
    trace = []
    pf = candidates(store, rm, basket_ids)
    trace.append((f'get_portfolio("{rm}")', f"{len(pf)} nasabah: " + ' · '.join(f"{s.split()[0]} {int((pf.segment == s).sum())}" for s in ['S1 Kecil', 'S2 Menengah', 'S3 Besar'])))
    trace.append(('get_alerts(rm, 3 bulan)', f"{int(pf.why_up.sum())} Why Now · {int(pf.caution.sum())} nasabah dengan alarm risiko"))
    hi = pf[pf.opportunity_score >= 0.75]
    trace.append(('get_priority(rm, skor ≥ 0,75)', f"{len(hi)} nasabah, {int((~hi.contacted).sum())} belum pernah dihubungi"))
    trace.append(('filter_risk()', 'nasabah High hanya ditawari produk non-kredit'))
    used, out_days = set(), []
    caution = [c for c in pf[pf.caution].index if c not in basket_ids][:1]
    visit_days = [d for d in days if d[1] == 'Kunjungan']
    call_days = [d for d in days if d[1] == 'Telepon']
    # hari kunjungan pertama: area dengan kandidat terbanyak
    pool = pf[~pf.index.isin(caution)].head(25)
    area = pool[pool.segment != 'S1 Kecil'].district.value_counts()
    area = area.index[0] if len(area) and area.iloc[0] >= 2 else None
    ws = set(store.districts().query('white_space').index)
    if area:
        trace.append(('group_by_area()', f"{area}: {int(area_n := (pool.district == area).sum())} nasabah kandidat" + (' · kecamatan white-space' if area in ws else '')))
    for k, (hari, kanal, n) in enumerate(visit_days):
        if k == 0 and area:
            ids = [c for c in pool[pool.district == area].index if c not in used][:n]
            tema = f'hari {area}'
        elif caution and k == len(visit_days) - 1:
            ids = caution + [c for c in pf[(pf.segment != 'S1 Kecil') & ~pf.caution].index if c not in used][:max(n - 1, 0)]
            tema = 'cek alarm dulu'
        else:
            ids = [c for c in pf[pf.segment != 'S1 Kecil'].index if c not in used][:n]
            tema = 'nasabah prioritas'
        items = []
        for j, cid in enumerate(ids):
            used.add(cid); row = pf.loc[cid].to_dict()
            sk = 'Hasil investigasi Copilot' if cid in caution else ('Simulasi produk; ringkasan eksekutif' if j == 0 else 'Profil 360°')
            it = _item(store, cid, row, JAM[j % 4], sk)
            if cid in caution:
                it['tujuan'] = f"Alarm {row['alarm']}. Jalankan investigasi dulu; bila tanda distress, teruskan ke analis. " + it['tujuan']
            items.append(it)
        if k == 0 and area:   # prospect lewat jaringan di area yang sama
            pr = store.prospects_for(rm)
            if len(pr):
                pr = pr[(pr.district == area) & (pr.risk_class != 'High')]
            if len(pr):
                pid = pr.index[0]; via = [v for v in pr.loc[pid, 'lewat'] if v in used] or pr.loc[pid, 'lewat']
                trace.append((f'find_intro_path("{area}")', f"{pid} lewat {via[0]} (nasabah sendiri)"))
                for it in items:
                    if it['id'] == via[0]:
                        it['tujuan'] += f" Minta perkenalan ke {store.co.name[pid]}."
                        it['siapkan'] = 'Draf permintaan perkenalan'
                out_days.append({'hari': hari, 'kanal': kanal, 'tema': tema, 'item': items, 'intro': (pid, via[0])})
                continue
        out_days.append({'hari': hari, 'kanal': kanal, 'tema': tema, 'item': items})
    for hari, kanal, n in call_days:
        ids = [c for c in pf[pf.segment == 'S1 Kecil'].index if c not in used][:n]
        items = []
        for j, cid in enumerate(ids):
            used.add(cid); items.append(_item(store, cid, pf.loc[cid].to_dict(), JAM[j % 4], 'Skrip telepon'))
        out_days.append({'hari': hari, 'kanal': kanal, 'tema': 'telepon S1 (kanal murah)', 'item': items})
    order = {d[0]: i for i, d in enumerate(days)}
    out_days.sort(key=lambda d: order[d['hari']])
    last = store.log_all[(store.log_all.rm_id == rm) & store.log_all.party_id.isin(used)].sort_values('contact_date').groupby('party_id').tail(1)
    for x in last.itertuples():
        trace.append((f'get_visit_history("{x.party_id}")', f"{x.contact_date}: {x.response}, {x.feedback_note}"))
        break
    n_items = sum(len(d['item']) for d in out_days)
    n_prio = int(pf.loc[list(used)].opportunity_score.ge(0.75).sum()) if used else 0
    intro = next((d['intro'] for d in out_days if 'intro' in d), None)
    msgs = []
    for d in out_days:
        if d['tema'].startswith('hari'):
            for it in d['item'][:2]:
                txt, _ = llm.draft_message('janji', {'nama': it['nama'], 'rm': rm, 'waktu': f"{d['hari']} pukul {it['jam']}", 'topik': it['tujuan'][:120]})
                msgs.append({'ke': it['nama'], 'kanal': 'WhatsApp', 'isi': txt})
    if intro:
        txt, _ = llm.draft_message('intro', {'perantara': store.co.name[intro[1]], 'prospect': store.co.name[intro[0]]})
        msgs.append({'ke': store.co.name[intro[1]] + ' (perkenalan)', 'kanal': 'WhatsApp', 'isi': txt})
    trace.append((f'draft_message(× {len(msgs)})', 'menunggu persetujuan'))
    ringkasan = ' '.join(filter(None, [
        f"{out_days[0]['hari']} dipusatkan di {area}: {len(out_days[0]['item'])} nasabah Anda ada di sana" + (', kecamatan white-space tanpa cabang' if area in ws else '') + '.' if area else '',
        f"Satu prospect, {store.co.name[intro[0]]}, bisa dikenalkan lewat nasabah sendiri." if intro else '',
        'Hari telepon untuk nasabah S1 sesuai playbook segmen.' if call_days else '',
        'Nasabah dengan alarm risiko diinvestigasi dulu sebelum ditawari produk.' if caution else '']))
    plan = {'rm': rm, 'minggu': week_label, 'portofolio': f'{len(pf)} nasabah', 'status': 'draf, menunggu persetujuan RM',
            'kpi': [('Aksi', str(n_items), f"{len(days)} hari"), ('Nasabah prioritas', str(n_prio), 'skor peluang ≥ 0,75'),
                    ('Prospect lewat jaringan', '1' if intro else '0', 'perkenalan via nasabah sendiri'), ('Alarm dicek dulu', str(len(caution)), 'distress / pembeli keluar')],
            'ringkasan': ringkasan, 'hari': out_days, 'pesan': msgs, 'jejak': trace}
    return plan


# ---------------------------------------------------------------- alur 2: investigasi alarm
def investigate(store, cid):
    fp = R.fact_pack(store, cid)
    ak, an, j = fp['arus_kas'], fp['anomali'], fp['jaringan']
    ev, distress_pts, retention_pts = [], 0, 0
    if ak['telat_3m'] >= 30: distress_pts += 2; ev.append(f"Gaji/pajak telat {R.fmt(ak['telat_3m'], 0)}% dalam 3 bulan")
    if ak['out_in_3m'] > 1.05: distress_pts += 1; ev.append(f"Outflow {R.fmt(ak['out_in_3m'], 2)}× inflow")
    if ak['buyer_exit'] >= 20: distress_pts += 1; ev.append(f"{R.fmt(ak['buyer_exit'], 0)}% inflow dari pembeli yang menghilang")
    if 'distress' in an['jenis_3bln']: distress_pts += 2; ev.append('Alarm distress aktif')
    if ak['chg_3v6'] is not None and ak['chg_3v6'] > 0: retention_pts += 1; ev.append(f"Inflow masih tumbuh (3v6 {R.fmt(ak['chg_3v6'], 2)})")
    if ak['capture_chg_6m'] <= -10: retention_pts += 2; ev.append(f"Porsi wallet {R.fmt(ak['capture_chg_6m'], 0)} poin dalam 6 bulan")
    if ak['telat_3m'] < 10: retention_pts += 1; ev.append(f"Ketepatan bayar baik (telat {R.fmt(ak['telat_3m'], 0)}%)")
    if j['mitra_distress']: ev.append(f"{j['mitra_distress']} mitra sedang alarm distress (Rp {R.fmt(j['nilai_distress_M'], 0)} M)")
    if distress_pts >= 2:
        verdict, route = 'Tanda kesulitan keuangan', 'Teruskan ke analis risiko dengan paket bukti; tunda tawaran kredit.'
    elif retention_pts >= 2:
        verdict, route = 'Kemungkinan perpindahan transaksi ke bank lain', 'Kunjungan retensi oleh RM; tanyakan alasan dan tawarkan solusi.'
    else:
        verdict, route = 'Sinyal lemah', 'Pantau bulan depan; tidak perlu tindakan khusus.'
    trace = [('get_cashflow', f"telat {R.fmt(ak['telat_3m'], 0)}% · out/in {R.fmt(ak['out_in_3m'], 2)} · 3v6 {R.fmt(ak['chg_3v6'], 2)}"),
             ('get_alerts', ', '.join(an['jenis_3bln']) or 'tidak ada alarm 3 bulan'), ('get_network', f"{j['mitra']} mitra · {j['mitra_distress']} distress"),
             ('get_visit_history', fp['kunjungan'][-1]['catatan'] if fp['kunjungan'] else 'belum ada')]
    return {'fp': fp, 'verdict': verdict, 'route': route, 'evidence': ev, 'trace': trace}


# ---------------------------------------------------------------- agen LLM: alat baca + usulan aksi
EVENTS = ['distress', 'buyer_exit', 'wallet_erosion', 'expansion', 'contagion', 'spike']
RESPONSES = ['Converted', 'Interested', 'Not interested', 'No response']


def _obj(props=None, req=None):
    return {'type': 'object', 'properties': props or {}, **({'required': req} if req else {})}


_CID = {'type': 'string', 'description': 'ID perusahaan, mis. C0844. Bila hanya tahu nama, cari dulu dengan search_company.'}
_N = {'type': 'integer', 'description': 'jumlah baris (maks 30)'}

TOOLS = [
    # --- baca
    {'name': 'search_company', 'description': 'Cari perusahaan (nasabah atau prospect) menurut nama, ID, industri, atau kecamatan. Pakai ini setiap kali pengguna menyebut nama perusahaan.',
     'parameters': _obj({'query': {'type': 'string'}, 'hanya_portofolio': {'type': 'boolean', 'description': 'true = hanya nasabah RM ini'}, 'n': _N}, ['query'])},
    {'name': 'portfolio_summary', 'description': 'Ringkasan portofolio RM: jumlah nasabah per segmen & kelas risiko, jumlah Why Now dan alarm, prioritas yang belum dihubungi. Untuk daftar/peringkat nasabah pakai list_priority.', 'parameters': _obj()},
    {'name': 'list_priority', 'description': 'Daftar nasabah RM urut prioritas (skor peluang + Why Now + belum dihubungi), dengan filter. Pakai ini untuk pertanyaan "siapa yang paling layak/prioritas".',
     'parameters': _obj({'segmen': {'type': 'string', 'enum': ['S1 Kecil', 'S2 Menengah', 'S3 Besar', 'Semua']}, 'kelas_risiko': {'type': 'string', 'enum': ['Low', 'Medium', 'High', 'Semua']},
                         'kecamatan': {'type': 'string'}, 'belum_dihubungi': {'type': 'boolean'}, 'ada_alarm': {'type': 'boolean'},
                         'produk': {'type': 'string', 'description': 'kode produk yang disarankan, mis. P03'}, 'n': _N})},
    {'name': 'company_facts', 'description': 'Paket fakta lengkap satu perusahaan: profil, risiko (+alasan model), peluang, keuangan vs median peer, arus kas, alarm, jaringan, produk, riwayat kunjungan.',
     'parameters': _obj({'company_id': _CID}, ['company_id'])},
    {'name': 'compare_companies', 'description': 'Bandingkan 2–5 perusahaan berdampingan (risiko, peluang, keuangan, arus kas, alarm, produk teratas).',
     'parameters': _obj({'company_ids': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 2, 'maxItems': 5}}, ['company_ids'])},
    {'name': 'product_opportunities', 'description': 'Peluang per produk untuk satu perusahaan: kebutuhan (peer), peluang konversi, ukuran deal, expected value & rentangnya, ditunda karena risiko atau tidak.',
     'parameters': _obj({'company_id': _CID}, ['company_id'])},
    {'name': 'product_catalog', 'description': 'Katalog produk P01–P08: nama, kategori, target, manfaat utama, syarat, catatan harga. Pakai untuk menjelaskan produk ke nasabah.', 'parameters': _obj()},
    {'name': 'cashflow_trend', 'description': 'Tren bulanan arus kas satu nasabah: porsi wallet di BNI, perubahan 6 bln, keterlambatan bayar, outflow/inflow, pembeli hilang, jumlah mitra aktif.',
     'parameters': _obj({'company_id': _CID, 'bulan': {'type': 'integer', 'description': 'jumlah bulan terakhir (default 12)'}}, ['company_id'])},
    {'name': 'visit_history', 'description': 'Riwayat kontak/kunjungan RM ke satu perusahaan (termasuk catatan dari dashboard).', 'parameters': _obj({'company_id': _CID}, ['company_id'])},
    {'name': 'investigate_alarm', 'description': 'Investigasi alarm satu nasabah dengan aturan baku: kesimpulan (distress vs perpindahan ke bank lain vs sinyal lemah), rute tindakan, dan bukti.',
     'parameters': _obj({'company_id': _CID}, ['company_id'])},
    {'name': 'alerts_feed', 'description': 'Daftar alarm terbaru di portofolio RM (Why Now), bisa difilter jenis.',
     'parameters': _obj({'jenis': {'type': 'string', 'enum': EVENTS + ['Semua']}, 'bulan': {'type': 'integer', 'description': 'jendela bulan (default 3)'}, 'n': _N})},
    {'name': 'district_ranking', 'description': 'Peringkat kecamatan menurut skor potensi wilayah (gap wallet, prospect, penetrasi rendah, POI industri, ekspansi).',
     'parameters': _obj({'n': _N, 'hanya_white_space': {'type': 'boolean', 'description': 'hanya kecamatan penetrasi rendah tanpa cabang'}})},
    {'name': 'district_detail', 'description': 'Detail satu kecamatan: statistik, nasabah prioritas RM di sana, prospect teratas.', 'parameters': _obj({'kecamatan': {'type': 'string'}}, ['kecamatan'])},
    {'name': 'network_prospects', 'description': 'Prospect yang bertransaksi dengan nasabah RM, urut nilai relasi (jalan masuk akuisisi).', 'parameters': _obj({'n': _N, 'kecamatan': {'type': 'string'}})},
    {'name': 'intro_path', 'description': 'Jalur kenalan ke satu prospect lewat nasabah BNI (utamakan nasabah RM sendiri).', 'parameters': _obj({'prospect_id': _CID}, ['prospect_id'])},
    # --- usulan aksi (baru berlaku setelah RM menyetujui di layar)
    {'name': 'propose_add_to_plan', 'description': 'USULKAN menambah perusahaan ke rencana minggu RM. Menunggu persetujuan RM.',
     'parameters': _obj({'company_id': _CID, 'catatan': {'type': 'string', 'description': 'tujuan kunjungan singkat'}}, ['company_id', 'catatan'])},
    {'name': 'propose_log_visit', 'description': 'USULKAN pencatatan hasil kontak/kunjungan (mis. dari cerita RM). Menunggu persetujuan RM.',
     'parameters': _obj({'company_id': _CID, 'respons': {'type': 'string', 'enum': RESPONSES}, 'produk': {'type': 'string'}, 'kanal': {'type': 'string', 'enum': ['Visit', 'Call', 'WhatsApp', 'Email']},
                         'catatan': {'type': 'string'}}, ['company_id', 'respons', 'catatan'])},
    {'name': 'propose_escalation', 'description': 'USULKAN meneruskan nasabah ke analis risiko beserta paket bukti. Menunggu persetujuan RM.',
     'parameters': _obj({'company_id': _CID, 'alasan': {'type': 'string'}}, ['company_id', 'alasan'])},
    {'name': 'propose_message', 'description': 'USULKAN draf pesan WhatsApp/email untuk nasabah atau perantara (Anda yang menulis isinya, maks 4 kalimat). Tidak dikirim otomatis.',
     'parameters': _obj({'company_id': _CID, 'jenis': {'type': 'string', 'enum': ['janji temu', 'perkenalan', 'tindak lanjut']}, 'isi': {'type': 'string'}}, ['company_id', 'jenis', 'isi'])},
]
TOOL_LABEL = {'search_company': 'Mencari perusahaan', 'portfolio_summary': 'Membaca portofolio', 'list_priority': 'Menyusun daftar prioritas', 'company_facts': 'Membaca profil 360°',
              'compare_companies': 'Membandingkan perusahaan', 'product_opportunities': 'Menghitung peluang produk', 'product_catalog': 'Membaca katalog produk',
              'cashflow_trend': 'Membaca tren arus kas', 'visit_history': 'Membaca riwayat kunjungan', 'investigate_alarm': 'Investigasi alarm', 'alerts_feed': 'Membaca alarm terbaru',
              'district_ranking': 'Memeringkat kecamatan', 'district_detail': 'Membaca detail kecamatan', 'network_prospects': 'Menelusuri jaringan prospect', 'intro_path': 'Mencari jalur kenalan',
              'propose_add_to_plan': 'Mengusulkan tambah ke rencana', 'propose_log_visit': 'Mengusulkan catatan kunjungan', 'propose_escalation': 'Mengusulkan eskalasi ke analis',
              'propose_message': 'Menyiapkan draf pesan'}


_PRODUCTS = None


def products():
    """Katalog produk (data/raw/product_master.csv), dimuat sekali."""
    global _PRODUCTS
    if _PRODUCTS is None:
        _PRODUCTS = pd.read_csv(ROOT / 'data/raw/product_master.csv').set_index('product_id')
    return _PRODUCTS


def _records(df, cols, n=None, nd=3):
    df = df if n is None else df.head(n)
    cols = [c for c in cols if c in df.columns]
    return json.loads(df[cols].round(nd).reset_index().to_json(orient='records', force_ascii=False))


_BIZ_PCT = {'opportunity_score': 'skor_peluang_pct', 'p_convert': 'peluang_konversi_pct', 'need_score': 'kebutuhan_peer_pct', 'p_konversi': 'peluang_konversi_pct',
            'capture_t': 'porsi_wallet_pct', 'capture_chg_6m': 'porsi_wallet_chg_6m_poin', 'late_share_3m': 'telat_bayar_3m_pct',
            'buyer_exit_share': 'pembeli_hilang_pct', 'pen': 'penetrasi_pct'}
_BIZ_NAME = {'out_in_3m': 'outflow_per_inflow', 'chg_3v6': 'inflow_3v6', 'n_active_cp_3m': 'mitra_aktif_3m', 'ev_idr_mn': 'ev_Rp_juta', 'gap_T': 'gap_wallet_Rp_T'}


def _biz(df):
    """Kolom pecahan 0–1 → persen bernama bisnis, supaya agen tidak salah membaca atau memformat angka."""
    d = df.copy()
    for a, b in _BIZ_PCT.items():
        if a in d.columns:
            d[b] = d[a] * 100
    return d.rename(columns=_BIZ_NAME)


def _slim(fp):
    fp = json.loads(llm._facts_json(fp))
    fp['arus_kas'].pop('capture_seri', None)
    cap = fp['arus_kas'].pop('capture_now', None)
    fp['arus_kas']['porsi_wallet_pct'] = round(cap * 100, 1) if isinstance(cap, (int, float)) else None
    fp['anomali']['riwayat'] = fp['anomali']['riwayat'][-6:]
    fp['kunjungan'] = fp['kunjungan'][-5:]
    return fp


def make_executor(store, rm, proposals=None):
    """proposals: list yang diisi alat propose_* (dieksekusi UI setelah RM menyetujui)."""
    proposals = proposals if proposals is not None else []
    mine = set(store.portfolio(rm).index)

    def guard(cid):
        if cid not in store.co.index:
            return {'error': f'{cid} tidak ditemukan; cari dengan search_company'}
        if rm != 'Semua RM' and store.cox.is_client.get(cid) and store.co.rm_id.get(cid) != rm:
            return {'error': f'{cid} nasabah RM lain ({store.co.rm_id.get(cid)}); di luar portofolio {rm}'}
        return None

    def name(cid):
        return store.co.name.get(cid, cid)

    def propose(tipe, cid, **kw):
        err = guard(cid)
        if err:
            return err
        a = {'id': f'A{len(proposals) + 1}', 'tipe': tipe, 'company_id': cid, 'nama': name(cid), 'status': 'menunggu', **kw}
        proposals.append(a)
        return {'status': 'diusulkan; menunggu persetujuan RM di layar', 'aksi_id': a['id']}

    def ex(tool, args):
        n = min(int(args.get('n') or 10), 30)
        cid = args.get('company_id') or args.get('prospect_id')
        if cid:
            cid = str(cid).strip().upper()
        if tool == 'search_company':
            q = str(args.get('query', '')).lower().strip()
            c = store.cox if not args.get('hanya_portofolio') else store.cox[store.cox.index.isin(mine)]
            hay = (c.index.str.lower() + ' ' + c.name.str.lower() + ' ' + c.industry.str.lower() + ' ' + c.district.str.lower())
            toks = q.split()
            hit = c[hay.apply(lambda h: all(t in h for t in toks))].copy()
            hit['_s'] = (hit.index.str.lower() == q) * 3 + hit.name.str.lower().str.startswith(q) * 2 + hit.name.str.lower().str.contains(q, regex=False)
            hit['milik_saya'] = hit.index.isin(mine)
            hit = hit.sort_values(['_s', 'milik_saya'], ascending=False)
            return {'jumlah': len(hit), 'hasil': _records(hit, ['name', 'customer_type', 'segment', 'industry', 'district', 'rm_id', 'pred_class', 'milik_saya'], n)}
        if tool == 'portfolio_summary':
            pf = candidates(store, rm)
            return {'rm': rm, 'nasabah': len(pf), 'per_segmen': pf.segment.value_counts().to_dict(), 'per_kelas_risiko': pf.risk_class.value_counts().to_dict(),
                    'why_now_naik': int(pf.why_up.sum()), 'alarm_risiko': int(pf.caution.sum()), 'belum_pernah_dihubungi': int((~pf.contacted).sum()),
                    'skor_peluang_median_pct': round(float(pf.opportunity_score.median()) * 100, 1),
                    'prioritas_belum_dihubungi': _records(_biz(pf[(pf.opportunity_score >= 0.75) & ~pf.contacted]), ['name', 'segment', 'skor_peluang_pct', 'risk_class'], 10, 1)}
        if tool == 'list_priority':
            pf = candidates(store, rm)
            if args.get('segmen') not in (None, 'Semua'): pf = pf[pf.segment == args['segmen']]
            if args.get('kelas_risiko') not in (None, 'Semua'): pf = pf[pf.risk_class == args['kelas_risiko']]
            if args.get('kecamatan'): pf = pf[pf.district.str.lower() == str(args['kecamatan']).lower()]
            if args.get('belum_dihubungi'): pf = pf[~pf.contacted]
            if args.get('ada_alarm'): pf = pf[pf.alarm != '']
            if args.get('produk'): pf = pf[pf.recommended_products.fillna('').str.contains(str(args['produk']).upper())]
            return {'jumlah_cocok': len(pf), 'daftar': _records(_biz(pf), ['name', 'segment', 'district', 'skor_peluang_pct', 'rank_in_segment', 'risk_class', 'alarm',
                                                                            'recommended_products', 'reason', 'peluang_konversi_pct', 'ev_Rp_juta', 'contacted'], n, 1)}
        if tool in ('company_facts', 'product_opportunities', 'cashflow_trend', 'visit_history', 'investigate_alarm', 'intro_path'):
            err = guard(cid)
            if err: return err
        if tool == 'company_facts':
            return _slim(R.fact_pack(store, cid))
        if tool == 'compare_companies':
            out = []
            for c in [str(x).strip().upper() for x in args.get('company_ids', [])][:5]:
                err = guard(c)
                if err: out.append({'id': c, **err}); continue
                fp = R.fact_pack(store, c); k, ak, pl = fp['keuangan'], fp['arus_kas'], fp.get('peluang')
                out.append({'id': c, 'nama': fp['nama'], 'segmen': fp['segmen'], 'tipe': fp['tipe'], 'kecamatan': fp['kecamatan'], 'risiko': fp['risiko']['kelas'],
                            'p_high_pct': fp['risiko']['p_high'], 'skor_peluang': pl['skor'] if pl else None, 'peringkat_segmen': pl['peringkat'] if pl else None,
                            'omzet_2025_M': k['pos']['Omzet'][1] if k else None, 'omzet_tumbuh_pct': k['perubahan_pct']['Omzet'] if k else None,
                            'DER': k['rasio']['DER']['2025'] if k else None, 'CR': k['rasio']['CR']['2025'] if k else None, 'NPM_pct': k['rasio']['NPM']['2025'] if k else None,
                            'porsi_wallet_pct': ak['capture_now'] * 100, 'wallet_chg_6m_poin': ak['capture_chg_6m'], 'telat_bayar_3m_pct': ak['telat_3m'],
                            'alarm_3bln': fp['anomali']['jenis_3bln'], 'mitra': fp['jaringan']['mitra'],
                            'produk_teratas': [p['produk'] for p in (fp.get('produk') or []) if not p['ditunda']][:2]})
            return json.loads(llm._facts_json(out))
        if tool == 'product_opportunities':
            pr = store.prod[store.prod.company_id == cid].sort_values('rank_produk').set_index('product_id')
            pr['nama_produk'] = pr.index.map(products().product_name)
            return {'dimiliki': sorted(store.hold[store.hold.company_id == cid].product_id), 'kelas_risiko': store.cox.pred_class.get(cid),
                    'produk': _records(_biz(pr), ['nama_produk', 'kebutuhan_peer_pct', 'peluang_konversi_pct', 'ukuran_deal_Rp_juta', 'ev_Rp_juta', 'ev_p10', 'ev_p90',
                                                  'ditunda_risiko', 'rank_produk'], nd=2)}
        if tool == 'product_catalog':
            return _records(products(), ['product_name', 'product_category', 'target_segment', 'key_benefit', 'eligibility', 'pricing_note'])
        if tool == 'cashflow_trend':
            p = store.panel[store.panel.company_id == cid].sort_values('ym').tail(int(args.get('bulan') or 12)).set_index('ym')
            if p.empty: return {'info': 'belum ada data arus kas (prospect / belum bertransaksi lewat BNI)'}
            return _records(_biz(p), ['porsi_wallet_pct', 'porsi_wallet_chg_6m_poin', 'telat_bayar_3m_pct', 'outflow_per_inflow', 'inflow_3v6', 'pembeli_hilang_pct',
                                      'mitra_aktif_3m'], nd=2)
        if tool == 'visit_history':
            lg = store.log_all[store.log_all.party_id == cid].sort_values('contact_date').tail(10).set_index('contact_date')
            return {'jumlah': int((store.log_all.party_id == cid).sum()), 'kontak': _records(lg, ['rm_id', 'channel', 'product_id', 'response', 'deal_value_idr_mn', 'feedback_note', 'sumber'])}
        if tool == 'investigate_alarm':
            r = investigate(store, cid); return {k: r[k] for k in ('verdict', 'route', 'evidence')}
        if tool == 'alerts_feed':
            pf = candidates(store, rm)
            a = store.why_now(pf.index, int(args.get('bulan') or 3))
            if args.get('jenis') not in (None, 'Semua'): a = a[a.event_type == args['jenis']]
            a = a.assign(name=a.company_id.map(store.co.name)).sort_values(['ym', 'score'], ascending=False).set_index('company_id')
            return {'jumlah': len(a), 'per_jenis': a.event_type.value_counts().to_dict(), 'alarm': _records(a, ['name', 'ym', 'event_type', 'score', 'reason'], n)}
        if tool == 'district_ranking':
            d = store.districts()
            if args.get('hanya_white_space'): d = d[d.white_space]
            return _records(_biz(d), ['kota', 'skor', 'n', 'nasabah', 'prospect', 'penetrasi_pct', 'gap_wallet_Rp_T', 'cabang', 'white_space'], n, 2)
        if tool == 'district_detail':
            d = store.districts(); k = next((i for i in d.index if i.lower() == str(args.get('kecamatan', '')).lower()), None)
            if k is None: return {'error': 'kecamatan tidak dikenal', 'pilihan': list(d.index)}
            pf = candidates(store, rm); pf = pf[pf.district == k]
            acq = store.acq.join(store.cox[['name', 'district']]); acq = acq[acq.district == k].sort_values('acquisition_score', ascending=False)
            return {'kecamatan': k, 'peringkat': int(list(d.index).index(k)) + 1, 'dari': len(d), **json.loads(_biz(d).loc[[k]].drop(columns=['pen']).round(2).to_json(orient='records'))[0],
                    'nasabah_saya': _records(_biz(pf), ['name', 'segment', 'skor_peluang_pct', 'risk_class', 'alarm', 'contacted'], 8, 1),
                    'prospect_teratas': _records(acq, ['name', 'segment', 'acquisition_score', 'risk_class'], 8)}
        if tool == 'network_prospects':
            p = store.prospects_for(rm)
            if p.empty: return []
            if args.get('kecamatan'): p = p[p.district.str.lower() == str(args['kecamatan']).lower()]
            p = p.rename_axis('company_id')
            return {'jumlah': len(p), 'prospect': _records(p, ['name', 'segment', 'district', 'lewat_nama', 'nilai_M', 'acquisition_score', 'risk_class', 'white_space'], n)}
        if tool == 'intro_path':
            return {'prospect': name(cid), 'jalur': _records(store.intro_paths(cid, rm).set_index('id'), ['name', 'rm_id', 'nilai_M', 'jenis', 'arah', 'milik_saya'], 5)}
        if tool == 'propose_add_to_plan':
            return propose('rencana', cid, catatan=args.get('catatan', ''))
        if tool == 'propose_log_visit':
            prod = str(args.get('produk') or '').strip()
            code = {v.lower(): k for k, v in products().product_name.items()}.get(prod.lower(), prod.upper())   # 'Virtual Account' → P03
            return propose('kunjungan', cid, respons=args.get('respons') if args.get('respons') in RESPONSES else 'Interested',
                           produk=code, kanal=args.get('kanal') or 'Visit', catatan=args.get('catatan', ''))
        if tool == 'propose_escalation':
            return propose('eskalasi', cid, alasan=args.get('alasan', ''))
        if tool == 'propose_message':
            return propose('pesan', cid, jenis=args.get('jenis', 'tindak lanjut'), isi=args.get('isi', ''))
        return {'error': f'alat {tool} tidak dikenal'}
    return ex


AGENT_RULES = """
Anda agen RM Copilot untuk {rm} ({n} nasabah). Data per 30 Juni 2026.{fokus}
Cara kerja:
- Pahami maksud pertanyaan, rencanakan langkah, lalu panggil alat (boleh beberapa sekaligus). Semua fakta harus berasal dari alat; jangan menebak.
- Bila pengguna menyebut nama perusahaan, cari ID-nya dengan search_company. Pahami rujukan seperti "yang kedua", "dia", "perusahaan tadi" dari percakapan sebelumnya.
- Analisis satu perusahaan: minimal company_facts; tambah cashflow_trend, product_opportunities, visit_history sesuai pertanyaan. Daftar/rekomendasi: periksa alarm & risiko kandidat teratas sebelum merekomendasikan.
- Untuk "kenapa"/"bagaimana", gali sampai akar lalu hubungkan temuan menjadi cerita yang bisa ditindaklanjuti (apa yang terjadi → artinya → yang perlu dilakukan RM).
- Tindakan (tambah rencana, catat kunjungan, eskalasi analis, draf pesan) hanya lewat alat propose_*. Usulkan tindakan bila jelas membantu atau diminta, lalu sampaikan bahwa usulan menunggu persetujuan RM di layar.
- Draf pesan: sapa perusahaan dengan namanya, perkenalkan diri sebagai {rm} dari BNI, sebut tujuan spesifik (produk/topik dari data) dan waktu yang diminta; sopan, maks 4 kalimat.
- Jangan memutuskan kelayakan kredit. Nasabah risiko High hanya ditawari produk non-kredit. Bila data tidak ada, katakan terus terang.
Kamus data (baca dengan benar):
- Kolom berakhiran _pct sudah dalam persen (0–100); _poin = poin persentase. skor_peluang_pct makin tinggi makin layak digarap; rank_in_segment 1 = terbaik.
  Komponen peluang (pct_* di company_facts.peluang.komponen) = persentil dalam segmen: dompet belum digarap, ekosistem, kebutuhan modal, celah produk, erosi wallet.
- Risiko: kelas Low/Medium/High; p_high = peluang masuk kelas High. Alasan risiko (reason/alasan) = pendorong utama MENUJU kelas yang diprediksi (TreeSHAP). Untuk kelas Low, alasan itu adalah faktor yang MENURUNKAN risiko (kekuatan), bukan masalah.
- porsi wallet = porsi transaksi perusahaan yang lewat BNI; perubahan 6 bln negatif = transaksi pindah ke bank lain.
- late_share/telat bayar = porsi gaji/pajak dibayar terlambat (makin tinggi makin buruk; ≥ 30% sinyal distress). out_in > 1,05 = kas keluar melebihi masuk.
  buyer_exit = porsi inflow dari pembeli yang menghilang. chg_3v6 > 0 = inflow tumbuh.
- p_konversi = peluang produk diterima; ev_Rp_juta = expected value (negatif = tidak menguntungkan ditawarkan); ditunda_risiko = produk kredit ditahan karena risiko.
- Jenis alarm: distress (kesulitan keuangan), buyer_exit (pembeli utama hilang), wallet_erosion (pindah bank), expansion (ekspansi → butuh modal), contagion (mitra bermasalah), spike (lonjakan sesaat).
Format jawaban:
- Bahasa Indonesia, ringkas, langsung ke inti; selalu sebut nama + ID perusahaan.
- Angka hanya dari hasil alat, gaya Indonesia: koma desimal (1,13 bukan 1.13). Bulatkan: persen 1 desimal, rasio 2 desimal, rupiah 1 desimal.
- Jangan menulis nama kolom mentah (late_share, capture_now, out_in_3m, dll.); pakai istilah bisnis (telat bayar, porsi wallet, outflow/inflow).
- Pakai tabel markdown untuk perbandingan atau daftar ≥ 3 baris; tebalkan kesimpulan utama.
- Baris terakhir WAJIB persis berformat: <<lanjut>> saran 1 | saran 2 | saran 3
  Tiap saran = permintaan singkat yang akan diketik RM berikutnya (kalimat perintah/pertanyaan dari RM, maks 9 kata), mis. "Buatkan draf pesan untuk ketiganya", bukan "Mau saya...?"."""
_FOLLOW = re.compile(r'<<\s*lanjut\s*>>(.*)$', re.S | re.I)


def chat(store, rm, question, history=None, on_step=None, focus=None):
    """Agen percakapan. Mengembalikan dict: jawaban, jejak, usulan aksi, saran lanjutan, cek angka, mode."""
    fokus = f" Perusahaan yang sedang dibuka RM: {store.co.name.get(focus, focus)} ({focus})." if focus in store.co.index else ''
    sys = llm.SYSTEM + AGENT_RULES.format(rm=rm, n=len(store.portfolio(rm)), fokus=fokus)
    proposals = []
    ans, trace = llm.run_tools(sys, question, TOOLS, make_executor(store, rm, proposals), history=history, on_step=on_step)
    if ans is None:
        ex = make_executor(store, rm); s = ex('portfolio_summary', {})
        top = ex('list_priority', {'n': 5})['daftar']
        ans = (f"Mode template (LLM tidak aktif{': ' + llm.complete.last_error[:120] if llm.complete.last_error else ''}). Portofolio {rm}: {s['nasabah']} nasabah, "
               f"{s['why_now_naik']} Why Now, {s['alarm_risiko']} dengan alarm risiko. Lima teratas: " + '; '.join(f"{t['name']} ({t['company_id']})" for t in top) + '.')
        return {'jawaban': ans, 'jejak': [('portfolio_summary', {}, s), ('list_priority', {'n': 5}, top)], 'usulan': [], 'lanjut': [], 'cek': None, 'mode': 'template'}
    m = _FOLLOW.search(ans or '')
    lanjut = [x.strip(' -*') for x in m.group(1).split('|') if x.strip(' -*')][:3] if m else []
    ans = _FOLLOW.sub('', ans).strip()
    facts = [t[2] for t in trace] + [question] + [h['content'] for h in (history or [])]
    jam = re.findall(r'(?:jam|pukul)\s*(\d{1,2}[.:]\d{2})', ans, re.I)
    n_num, bad = R.check_numbers({'jawaban': ans}, facts, extra_allowed=jam)
    return {'jawaban': ans, 'jejak': trace, 'usulan': proposals, 'lanjut': lanjut, 'cek': (n_num, bad), 'mode': 'LLM'}
