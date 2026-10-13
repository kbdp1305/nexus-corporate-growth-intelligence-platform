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

from . import guard, llm
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
FOKUS = ['seimbang', 'retensi', 'pertumbuhan', 'alarm']


def plan_week(store, rm, basket=(), days=None, week_label='minggu ini', exclude=(), must=(), focus='seimbang'):
    """days = [(hari, 'Kunjungan'|'Telepon', jumlah_slot), ...] · exclude = perusahaan yang sudah terjadwal di kalender.
    must = perusahaan yang wajib masuk (permintaan RM) · focus = bobot tambahan: retensi (porsi wallet turun), pertumbuhan (Why Now naik), alarm."""
    days = days or [('Selasa', 'Kunjungan', 3), ('Rabu', 'Telepon', 2), ('Kamis', 'Kunjungan', 2)]
    must = [c for c in dict.fromkeys(must) if c in store.co.index]
    basket_ids = [b['id'] for b in basket] + must
    trace = []
    pf = candidates(store, rm, basket_ids)
    if focus != 'seimbang' and len(pf):
        chg = store.panel[store.panel.ym == R.REF_MONTH].set_index('company_id').capture_chg_6m.reindex(pf.index).fillna(0)
        boost = {'retensi': (chg <= -0.10) | pf.alarm.str.contains('wallet_erosion'), 'pertumbuhan': pf.why_up, 'alarm': pf.alarm != ''}.get(focus)
        if boost is not None:
            pf['prio'] += 0.3 * boost.astype(float)
            pf = pf.sort_values('prio', ascending=False)
            trace.append((f'fokus("{focus}")', f"{int(boost.sum())} nasabah dinaikkan prioritasnya"))
    if len(exclude):
        pf = pf[~pf.index.isin(set(exclude) - set(must))]
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
    cap = {h: n for h, _, n in days}
    for cid in must:                                     # nasabah wajib yang belum terpilih → hari dengan kanal cocok (kecamatan sama didahulukan)
        if cid in used or not out_days:
            continue
        kan = 'Telepon' if store.cox.segment.get(cid) == 'S1 Kecil' else 'Kunjungan'
        pool_d = [d for d in out_days if d['kanal'] == kan] or out_days
        dist = store.co.district.get(cid)
        d = min(pool_d, key=lambda d: (not any(it['kecamatan'] == dist for it in d['item']), len(d['item'])))
        if len(d['item']) >= cap.get(d['hari'], 4):
            drop = next((it for it in reversed(d['item']) if it['id'] not in must), None)
            if drop:
                d['item'].remove(drop); used.discard(drop['id'])
        jam = next((j for j in JAM if j not in {it['jam'] for it in d['item']}), JAM[-1])
        it = _item(store, cid, pf.loc[cid].to_dict() if cid in pf.index else {}, jam, 'Profil 360°')
        it['tujuan'] = 'Diminta RM. ' + it['tujuan']
        d['item'].append(it); d['item'].sort(key=lambda x: x['jam']); used.add(cid)
        trace.append((f'wajib("{cid}")', f"{store.co.name[cid]} → {d['hari']} {jam}"))
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
_CP = _CF = None


def counterparties():
    """Transaksi mitra 12 bulan (data/raw/counterparty_transactions.csv), dimuat sekali."""
    global _CP
    if _CP is None:
        _CP = pd.read_csv(ROOT / 'data/raw/counterparty_transactions.csv')
    return _CP


def facilities():
    """Fasilitas kredit BNI per nasabah (data/raw/credit_facilities.csv), dimuat sekali."""
    global _CF
    if _CF is None:
        _CF = pd.read_csv(ROOT / 'data/raw/credit_facilities.csv').set_index('company_id')
    return _CF


def bank_shift(store, cid):
    """Bukti perpindahan transaksi dari data mitra 12 bulan: mitra yang dulu lewat BNI lalu berhenti (≥ 3 bulan tanpa transaksi),
    mitra baru yang memakai bank lain, dan porsi nilai mitra lewat bank lain. IN = mitra membayar nasabah (pembeli), OUT = nasabah membayar mitra (pemasok)."""
    cp = counterparties()
    cp = cp[cp.bni_party_id == cid]
    p = store.panel[(store.panel.company_id == cid) & (store.panel.ym == R.REF_MONTH)]
    wallet = {'porsi_wallet_pct': round(float(p.capture_t.iloc[0]) * 100, 1) if len(p) else None,
              'porsi_wallet_chg_6m_poin': round(float(p.capture_chg_6m.iloc[0]) * 100, 1) if len(p) and np.isfinite(p.capture_chg_6m.iloc[0]) else None}
    if cp.empty:
        return {**wallet, 'info': 'tidak ada data transaksi mitra'}
    ref = pd.Period(R.REF_MONTH, 'M')
    stop_by, new_after = str(ref - 3), str(ref - 6)
    other = cp.counterparty_bank != 'BNI'
    tot = cp.txn_value_12m_idr_mn.sum()
    stop = cp[~other & (cp.last_txn_month <= stop_by)].sort_values('txn_value_12m_idr_mn', ascending=False)
    new = cp[other & (cp.first_txn_month > new_after)].sort_values('txn_value_12m_idr_mn', ascending=False)
    rows = lambda d: [{'mitra': r.counterparty_name_raw, 'peran': 'pembeli' if r.direction == 'IN' else 'pemasok', 'bank': r.counterparty_bank,
                       'nilai_12m_Rp_juta': round(r.txn_value_12m_idr_mn, 1), 'bulan_pertama': r.first_txn_month, 'bulan_terakhir': r.last_txn_month}
                      for r in d.head(5).itertuples()]
    stop_pct = stop.txn_value_12m_idr_mn.sum() / tot * 100 if tot else 0
    tanda = []
    if len(stop):
        tanda.append(f"{len(stop)} mitra yang bertransaksi lewat BNI berhenti sejak {stop.last_txn_month.max()} atau lebih awal "
                     f"(Rp {R.fmt(stop.txn_value_12m_idr_mn.sum(), 1)} juta, {R.fmt(stop_pct, 1)}% nilai mitra)")
    if len(new):
        tanda.append(f"{len(new)} mitra baru sejak {new.first_txn_month.min()} memakai bank lain (Rp {R.fmt(new.txn_value_12m_idr_mn.sum(), 1)} juta)")
    return {**wallet, 'mitra': len(cp), 'porsi_nilai_bank_lain_pct': round(float(cp.txn_value_12m_idr_mn[other].sum() / tot * 100), 1) if tot else None,
            'per_bank_Rp_juta': cp.groupby('counterparty_bank').txn_value_12m_idr_mn.sum().round(1).to_dict(),
            'mitra_bni_berhenti': len(stop), 'nilai_mitra_berhenti_pct': round(stop_pct, 1), 'mitra_berhenti': rows(stop),
            'mitra_baru_bank_lain': len(new), 'mitra_baru': rows(new), 'tanda': tanda,
            'catatan': 'Data mitra hanya mencakup 12 bulan; mitra berhenti = tidak bertransaksi ≥ 3 bulan terakhir.'}


def credit_facility(store, cid):
    """Fasilitas kredit nasabah di BNI + tanda bahaya + peluang tambah limit (bahan diskusi dengan analis; bukan keputusan kredit)."""
    cf = facilities()
    if cid not in cf.index:
        return {'info': 'tidak punya fasilitas kredit di BNI'}
    f, risk = cf.loc[cid], store.cox.pred_class.get(cid)
    bahaya = []
    if f.collectibility >= 2: bahaya.append(f'Kolektibilitas {int(f.collectibility)}')
    if f.max_dpd_12m > 30: bahaya.append(f'Tunggakan terlama {int(f.max_dpd_12m)} hari dalam 12 bulan')
    if f.watchlist_flag: bahaya.append('Masuk watchlist')
    if f.restructuring_flag: bahaya.append('Pernah direstrukturisasi')
    if isinstance(f.policy_restriction, str): bahaya.append(f'Pembatasan kebijakan: {f.policy_restriction}')
    tambah = bool(f.utilization >= 0.85 and not bahaya and risk != 'High')
    return {'jenis_fasilitas': f.facility_type, 'limit_Rp_M': round(float(f.limit_idr_bn), 2), 'outstanding_Rp_M': round(float(f.outstanding_idr_bn), 2),
            'utilisasi_pct': round(float(f.utilization) * 100, 1), 'kolektibilitas': int(f.collectibility), 'dpd_maks_12m_hari': int(f.max_dpd_12m),
            'watchlist': bool(f.watchlist_flag), 'restrukturisasi': bool(f.restructuring_flag), 'kelas_risiko_model': risk,
            'tanda_bahaya': bahaya, 'peluang_tambah_limit': tambah,
            'catatan': 'Copilot tidak memutuskan kredit; peluang tambah limit hanya bahan diskusi dengan analis kredit.'}


def investigate(store, cid):
    fp = R.fact_pack(store, cid)
    ak, an, j = fp['arus_kas'], fp['anomali'], fp['jaringan']
    cf, bs = credit_facility(store, cid), bank_shift(store, cid)
    ev, distress_pts, retention_pts = [], 0, 0
    if ak['telat_3m'] >= 30: distress_pts += 2; ev.append(f"Gaji/pajak telat {R.fmt(ak['telat_3m'], 0)}% dalam 3 bulan")
    if ak['out_in_3m'] > 1.05: distress_pts += 1; ev.append(f"Outflow {R.fmt(ak['out_in_3m'], 2)}× inflow")
    if ak['buyer_exit'] >= 20: distress_pts += 1; ev.append(f"{R.fmt(ak['buyer_exit'], 0)}% inflow dari pembeli yang menghilang")
    if 'distress' in an['jenis_3bln']: distress_pts += 2; ev.append('Alarm distress aktif')
    if cf.get('kolektibilitas', 1) >= 3 or cf.get('dpd_maks_12m_hari', 0) > 90: distress_pts += 2
    elif cf.get('kolektibilitas', 1) == 2 or cf.get('dpd_maks_12m_hari', 0) > 30 or cf.get('watchlist'): distress_pts += 1
    ev += [f"Kredit: {b}" for b in cf.get('tanda_bahaya', [])]
    if ak['chg_3v6'] is not None and ak['chg_3v6'] > 0: retention_pts += 1; ev.append(f"Inflow masih tumbuh (3v6 {R.fmt(ak['chg_3v6'], 2)})")
    if ak['capture_chg_6m'] <= -10: retention_pts += 2; ev.append(f"Porsi wallet {R.fmt(ak['capture_chg_6m'], 0)} poin dalam 6 bulan")
    if ak['telat_3m'] < 10: retention_pts += 1; ev.append(f"Ketepatan bayar baik (telat {R.fmt(ak['telat_3m'], 0)}%)")
    partner_shift = bs.get('mitra_bni_berhenti', 0) >= 2 or bs.get('nilai_mitra_berhenti_pct', 0) >= 15
    if partner_shift: retention_pts += 1
    ev += bs.get('tanda', [])
    # tanpa bukti perpindahan (wallet turun / mitra BNI berhenti / alarm wallet_erosion), "inflow tumbuh + bayar tepat waktu" bukan alasan retensi
    shift = ak['capture_chg_6m'] <= -10 or partner_shift or 'wallet_erosion' in an['jenis_3bln']
    if j['mitra_distress']: ev.append(f"{j['mitra_distress']} mitra sedang alarm distress (Rp {R.fmt(j['nilai_distress_M'], 0)} M)")
    if distress_pts >= 2:
        verdict, route = 'Tanda kesulitan keuangan', 'Teruskan ke analis risiko dengan paket bukti; tunda tawaran kredit.'
    elif retention_pts >= 2 and shift:
        verdict, route = 'Kemungkinan perpindahan transaksi ke bank lain', 'Kunjungan retensi oleh RM; tanyakan alasan dan tawarkan solusi.'
    else:
        verdict, route = 'Sinyal lemah', 'Pantau bulan depan; tidak perlu tindakan khusus.'
    trace = [('get_cashflow', f"telat {R.fmt(ak['telat_3m'], 0)}% · out/in {R.fmt(ak['out_in_3m'], 2)} · 3v6 {R.fmt(ak['chg_3v6'], 2)}"),
             ('get_alerts', ', '.join(an['jenis_3bln']) or 'tidak ada alarm 3 bulan'), ('get_network', f"{j['mitra']} mitra · {j['mitra_distress']} distress"),
             ('credit_facility', ', '.join(cf.get('tanda_bahaya', [])) or cf.get('info') or f"kolektibilitas {cf['kolektibilitas']}, utilisasi {R.fmt(cf['utilisasi_pct'], 0)}%"),
             ('bank_shift', f"{bs.get('mitra_bni_berhenti', 0)} mitra BNI berhenti · {bs.get('mitra_baru_bank_lain', 0)} mitra baru di bank lain"),
             ('get_visit_history', fp['kunjungan'][-1]['catatan'] if fp['kunjungan'] else 'belum ada')]
    return {'fp': fp, 'verdict': verdict, 'route': route, 'evidence': ev, 'trace': trace, 'kredit': cf, 'bank': bs,
            'poin': {'distress': distress_pts, 'retensi': retention_pts}}


# ---------------------------------------------------------------- alur 3: triase semua alarm
TRIASE = {'distress': ('Distress', 'Teruskan ke analis risiko'), 'retensi': ('Retensi', 'Kunjungan retensi'),
          'ekspansi': ('Ekspansi', 'Kunjungan peluang'), 'pantau': ('Pantau', 'Pantau bulan depan')}
_SEG_W = {'S3 Besar': 3, 'S2 Menengah': 2, 'S1 Kecil': 1}


def triage(store, rm, months=3):
    """Investigasi semua nasabah beralarm milik RM, kelompokkan (distress / retensi / ekspansi / pantau), lalu usulkan satu aksi per nasabah.
    Nasabah yang sudah terjadwal atau sudah punya tiket eskalasi terbuka dilewati (tidak digandakan)."""
    from . import kalender as K, tindak as T
    pf = candidates(store, rm)
    wn = store.why_now(pf.index, months)
    ids = list(dict.fromkeys(wn.sort_values('score', ascending=False).company_id))
    sched, esc = K.scheduled_ids(rm), T.open_escalations()
    rows, trace = [], [(f'alerts_feed("{rm}", {months} bulan)', f"{len(wn)} alarm di {len(ids)} nasabah: " + ', '.join(f'{k} {v}' for k, v in wn.event_type.value_counts().items()))]
    for cid in ids:
        r, row = investigate(store, cid), pf.loc[cid]
        alarm = sorted(set(wn[wn.company_id == cid].event_type))
        cf = r['kredit']
        if r['verdict'].startswith('Tanda'):
            grp = 'distress'
        elif r['verdict'].startswith('Kemungkinan'):
            grp = 'retensi'
        elif 'expansion' in alarm and r['poin']['distress'] == 0:
            grp = 'ekspansi'
        else:
            grp = 'pantau'
        if grp == 'distress':
            aksi, detail = 'eskalasi', f"Alarm {', '.join(alarm)}: {r['verdict'].lower()}. Tunda tawaran kredit."
            status = 'sudah dieskalasi' if cid in esc else 'usul'
        elif grp in ('retensi', 'ekspansi'):
            if grp == 'retensi':
                detail = f"Retensi: {r['verdict'].lower()}. Tanyakan alasan dan tawarkan solusi."
            else:
                detail = 'Ekspansi: cek kebutuhan modal kerja.'
                if cf.get('peluang_tambah_limit'):
                    detail += f" Utilisasi kredit {R.fmt(cf['utilisasi_pct'], 0)}%: bahas tambah limit dengan analis kredit."
                if row.risk_class == 'High':
                    detail += ' Risiko High: hanya produk non-kredit.'
            aksi, status = 'rencana', 'sudah terjadwal' if cid in sched else 'usul'
        else:
            aksi, detail, status = None, 'Sinyal lemah; tidak perlu tindakan khusus bulan ini.', 'pantau'
        prio = _SEG_W.get(row.segment, 1) * 10 + r['poin']['distress'] * (grp == 'distress') * 3 + r['poin']['retensi'] + float(row.opportunity_score)
        rows.append({'id': cid, 'nama': store.co.name[cid], 'segmen': row.segment, 'risiko': row.risk_class, 'alarm': ', '.join(alarm), 'kelompok': grp,
                     'kesimpulan': r['verdict'], 'bukti': r['evidence'][:4], 'aksi': aksi, 'detail': detail, 'status': status, 'prio': round(prio, 2),
                     'kontak_terakhir': r['fp']['kunjungan'][-1]['tgl'] if r['fp']['kunjungan'] else None})
        trace.append((f'investigate_alarm("{cid}")', f"{r['verdict']} · {len(r['evidence'])} bukti"))
    order = list(TRIASE)
    rows.sort(key=lambda x: (order.index(x['kelompok']), -x['prio']))
    n = {g: sum(x['kelompok'] == g for x in rows) for g in order}
    skip = sum(x['status'].startswith('sudah') for x in rows)
    act = sum(x['status'] == 'usul' for x in rows)
    trace.append(('cek_kalender_dan_tiket()', f"{skip} nasabah sudah terjadwal / sudah dieskalasi, dilewati"))
    top = next((x for x in rows if x['status'] == 'usul'), None)
    ringkasan = ' '.join(filter(None, [
        f"{len(rows)} nasabah beralarm dalam {months} bulan terakhir: {n['distress']} distress, {n['retensi']} retensi, {n['ekspansi']} ekspansi, {n['pantau']} cukup dipantau.",
        f"{act} tindakan diusulkan" + (f", {skip} dilewati karena sudah ditangani." if skip else '.'),
        f"Paling mendesak: {top['nama']} ({top['id']}), {top['kesimpulan'].lower()}." if top else '']))
    return {'rm': rm, 'bulan': months, 'baris': rows, 'jumlah': n, 'ringkasan': ringkasan, 'jejak': trace}


# ---------------------------------------------------------------- rencana minggu: kalender, rute, revisi
def week_start_for(minggu='minggu depan', today=None):
    from datetime import date, timedelta
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    return monday if minggu == 'minggu ini' else monday + timedelta(days=7)


def finalize_plan(store, plan, week_start, rm):
    """Urutkan rute hari kunjungan, geser jam yang bentrok dengan Kalender kunjungan, hitung ulang KPI & jarak.
    Hari dengan jam yang diminta RM (item 'tetap') tidak diurutkan ulang."""
    from datetime import timedelta
    from . import kalender as K, planner
    for d in plan['hari']:
        if d.get('kanal', 'Kunjungan') == 'Kunjungan' and not any(it.get('tetap') for it in d['item']):
            planner.optimize(store, d)
    if rm != 'Semua RM':
        when = {r['id']: r['mulai'] for r in K.fit_free(K.from_plan(plan, week_start), rm)}
        for d in plan['hari']:
            tgl = week_start + timedelta(days=planner.HARI.index(d['hari']))
            for it in d['item']:
                m = when.get(f"{rm}-{it['id']}-{tgl:%Y%m%d}")
                if m:
                    it['jam'] = m[11:16].replace(':', '.')
            d['item'].sort(key=lambda it: it['jam'])
    planner.refresh_kpi(plan, store)
    plan['jarak_km'] = {d['hari']: round(planner.route_km(store, d['item']), 1) for d in plan['hari'] if d.get('kanal') == 'Kunjungan' and len(d['item']) > 1}
    plan['minggu_mulai'] = week_start.isoformat()
    return plan


def plan_brief(plan):
    """Ringkasan rencana untuk LLM (tanpa draf pesan & jejak)."""
    return {'minggu': plan['minggu'], 'minggu_mulai': plan.get('minggu_mulai'), 'ringkasan': plan['ringkasan'],
            'kpi': {k: v for k, v, _ in plan['kpi']}, 'jarak_km_per_hari': plan.get('jarak_km', {}),
            'hari': [{'hari': d['hari'], 'kanal': d['kanal'], 'tema': d['tema'],
                      'jadwal': [{'jam': it['jam'], 'id': it['id'], 'nama': it['nama'], 'kecamatan': it['kecamatan'], 'tujuan': it['tujuan']} for it in d['item']]}
                     for d in plan['hari']]}


def revise_plan(store, plan, ops, rm):
    """Terapkan revisi RM ke rencana (salinan). ops: [{aksi: hapus|tambah|pindah|ubah_kanal|hapus_hari, company_id, hari, jam, kanal}].
    Mengembalikan (rencana_baru, catatan[])."""
    import copy
    from . import planner
    plan, notes = copy.deepcopy(plan), []
    pf = candidates(store, rm)

    def day(h, create_kanal=None):
        d = next((x for x in plan['hari'] if x['hari'] == h), None)
        if d is None and create_kanal:
            d = {'hari': h, 'kanal': create_kanal, 'tema': 'tambahan dari RM', 'item': []}
            plan['hari'].append(d); plan['hari'].sort(key=lambda x: planner.HARI.index(x['hari']))
        return d

    def remove(cid):
        for d in plan['hari']:
            hit = [it for it in d['item'] if it['id'] == cid]
            d['item'] = [it for it in d['item'] if it['id'] != cid]
            if hit:
                return hit[0]
        return None

    for op in ops:
        a, cid, h = op.get('aksi'), str(op.get('company_id') or '').strip().upper(), op.get('hari')
        jam = str(op.get('jam') or '').replace(':', '.') or None
        if a == 'hapus_hari':
            plan['hari'] = [d for d in plan['hari'] if d['hari'] != h]; notes.append(f'{h} dihapus dari rencana'); continue
        if a == 'ubah_kanal':
            d = day(h)
            if d is None: notes.append(f'{h} tidak ada di rencana'); continue
            d['kanal'] = op.get('kanal') or 'Telepon'; d['tema'] = f"{d['kanal'].lower()} (diubah RM)"; notes.append(f"{h} diubah menjadi {d['kanal']}"); continue
        if cid not in store.co.index:
            notes.append(f'{cid or "?"} tidak ditemukan'); continue
        if rm != 'Semua RM' and store.cox.is_client.get(cid) and store.co.rm_id.get(cid) != rm:
            notes.append(f'{cid} nasabah RM lain; dilewati'); continue
        if a == 'hapus':
            notes.append(f"{store.co.name[cid]} dihapus" if remove(cid) else f'{cid} tidak ada di rencana'); continue
        if a in ('tambah', 'pindah'):
            old = remove(cid)
            if a == 'pindah' and old is None:
                notes.append(f'{cid} tidak ada di rencana; ditambahkan'); a = 'tambah'
            kan = 'Telepon' if store.cox.segment.get(cid) == 'S1 Kecil' else 'Kunjungan'
            d = day(h, kan) if h in planner.HARI else min(plan['hari'] or [day('Selasa', kan)], key=lambda x: (x['kanal'] != kan, len(x['item'])))
            used = {it['jam'] for it in d['item']}
            jam = jam or next((j for j in JAM if j not in used), JAM[-1])
            it = old or _item(store, cid, pf.loc[cid].to_dict() if cid in pf.index else {}, jam, 'Profil 360°')
            it['jam'] = jam
            if op.get('jam'):
                it['tetap'] = True
            if a == 'tambah' and old is None:
                it['tujuan'] = 'Diminta RM. ' + it['tujuan']
            d['item'].append(it); d['item'].sort(key=lambda x: x['jam'])
            notes.append(f"{store.co.name[cid]} → {d['hari']} {jam}")
            continue
        notes.append(f'aksi {a} tidak dikenal')
    plan['hari'] = [d for d in plan['hari'] if d['item']]
    plan['status'] = 'draf (direvisi), menunggu persetujuan RM'
    return plan, notes


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
    {'name': 'bank_shift', 'description': 'Bukti perpindahan transaksi satu nasabah dari data mitra 12 bulan: mitra yang dulu lewat BNI lalu berhenti, mitra baru di bank lain, '
     'porsi nilai mitra lewat bank lain, porsi wallet. Pakai untuk "kenapa porsi wallet turun" / alarm wallet_erosion.', 'parameters': _obj({'company_id': _CID}, ['company_id'])},
    {'name': 'credit_facility', 'description': 'Fasilitas kredit nasabah di BNI: limit, outstanding, utilisasi, kolektibilitas, tunggakan (DPD), watchlist, restrukturisasi, '
     'tanda bahaya, dan peluang tambah limit (bahan diskusi dengan analis, bukan keputusan kredit).', 'parameters': _obj({'company_id': _CID}, ['company_id'])},
    {'name': 'triage_alerts', 'description': 'TRIASE SEMUA ALARM portofolio RM sekaligus: investigasi tiap nasabah beralarm (arus kas, kredit, transaksi mitra), kelompokkan '
     'distress / retensi / ekspansi / pantau, dan OTOMATIS membuat usulan aksi per nasabah (eskalasi ke divisi Risiko atau jadwal kunjungan). '
     'Nasabah yang sudah terjadwal / sudah dieskalasi dilewati. Jangan panggil propose_* lagi untuk nasabah yang sudah diusulkan alat ini.',
     'parameters': _obj({'bulan': {'type': 'integer', 'description': 'jendela alarm dalam bulan (default 3)'}})},
    {'name': 'propose_week_plan', 'description': 'USULKAN rencana minggu lengkap untuk disetujui sekali: memilih nasabah (skor peluang, alarm, wilayah, jaringan), '
     'menghormati hari yang tidak bisa & nasabah wajib, menghindari jadwal yang sudah ada di Kalender, mengurutkan rute, dan menyiapkan draf pesan. '
     'Ubah permintaan RM menjadi parameter. Untuk mengubah rencana yang sudah ada pakai revise_week_plan.',
     'parameters': _obj({'minggu': {'type': 'string', 'enum': ['minggu ini', 'minggu depan']},
                         'hari': {'type': 'array', 'description': 'opsional; hari kerja & kanal. Default: Selasa kunjungan 3, Rabu telepon 2, Kamis kunjungan 2.',
                                  'items': _obj({'hari': {'type': 'string', 'enum': ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat']},
                                                 'kanal': {'type': 'string', 'enum': ['Kunjungan', 'Telepon']}, 'slot': {'type': 'integer', 'description': '1–4'}}, ['hari', 'kanal'])},
                         'hari_tidak_bisa': {'type': 'array', 'items': {'type': 'string', 'enum': ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat']}},
                         'wajib': {'type': 'array', 'items': {'type': 'string'}, 'description': 'ID perusahaan yang wajib masuk'},
                         'kecualikan': {'type': 'array', 'items': {'type': 'string'}, 'description': 'ID perusahaan yang jangan dimasukkan'},
                         'fokus': {'type': 'string', 'enum': FOKUS, 'description': 'retensi = porsi wallet turun; pertumbuhan = alarm ekspansi; alarm = nasabah beralarm'}})},
    {'name': 'revise_week_plan', 'description': 'USULKAN revisi rencana minggu terakhir (yang sedang dibahas) tanpa menyusun ulang dari nol. '
     'Contoh: hapus nasabah, tambah/pindah nasabah ke hari & jam tertentu, ubah kanal satu hari, hapus satu hari.',
     'parameters': _obj({'operasi': {'type': 'array', 'items': _obj({'aksi': {'type': 'string', 'enum': ['hapus', 'tambah', 'pindah', 'ubah_kanal', 'hapus_hari']},
                                                                    'company_id': {'type': 'string'}, 'hari': {'type': 'string', 'enum': ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat']},
                                                                    'jam': {'type': 'string', 'description': 'HH.MM'}, 'kanal': {'type': 'string', 'enum': ['Kunjungan', 'Telepon']}}, ['aksi'])}},
                        ['operasi'])},
    # --- usulan aksi (baru berlaku setelah RM menyetujui di layar)
    {'name': 'propose_add_to_plan', 'description': 'USULKAN menjadwalkan perusahaan di Kalender kunjungan RM. Tanpa hari/jam → slot kosong terdekat '
     '(hari dengan kunjungan di kecamatan sama didahulukan); S1 dijadwalkan telepon. Menunggu persetujuan RM.',
     'parameters': _obj({'company_id': _CID, 'catatan': {'type': 'string', 'description': 'tujuan kunjungan singkat'},
                         'hari': {'type': 'string', 'enum': ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat'], 'description': 'opsional, bila RM meminta hari tertentu'},
                         'jam': {'type': 'string', 'description': 'opsional, format HH.MM, mis. 10.00'}}, ['company_id', 'catatan'])},
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
              'propose_add_to_plan': 'Mengusulkan jadwal di kalender', 'propose_log_visit': 'Mengusulkan catatan kunjungan', 'propose_escalation': 'Mengusulkan eskalasi ke analis',
              'propose_message': 'Menyiapkan draf pesan', 'bank_shift': 'Menelusuri perpindahan transaksi', 'credit_facility': 'Membaca fasilitas kredit',
              'triage_alerts': 'Triase semua alarm', 'propose_week_plan': 'Menyusun rencana minggu', 'revise_week_plan': 'Merevisi rencana minggu'}


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


def make_executor(store, rm, proposals=None, plan_ctx=None):
    """proposals: list yang diisi alat propose_* (dieksekusi UI setelah RM menyetujui).
    plan_ctx: rencana minggu terakhir dari percakapan sebelumnya (untuk revise_week_plan)."""
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
        text = ' '.join(str(kw.get(k) or '') for k in ('isi', 'catatan'))
        if store.cox.pred_class.get(cid) == 'High' and guard.credit_violation(text, [cid], [name(cid)]):
            guard.log('kredit_high', 'aksi', rm=rm, company=cid, tipe=tipe)
            return {'error': f'{name(cid)} berisiko High: usulan yang menawarkan produk kredit ditolak guardrail. Tawarkan produk non-kredit saja.'}
        if tipe == 'pesan':
            kw['isi'] = guard.mask_profanity(guard.mask_pii(kw.get('isi', ''))[0])[0]
        dup = next((a for a in proposals if a['tipe'] == tipe and a['company_id'] == cid and tipe != 'pesan'), None)
        if dup:
            return {'status': 'sudah diusulkan sebelumnya; menunggu persetujuan RM di layar', 'aksi_id': dup['id']}
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
        if tool in ('company_facts', 'product_opportunities', 'cashflow_trend', 'visit_history', 'investigate_alarm', 'intro_path', 'bank_shift', 'credit_facility'):
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
        if tool == 'bank_shift':
            return bank_shift(store, cid)
        if tool == 'credit_facility':
            return credit_facility(store, cid)
        if tool == 'triage_alerts':
            if rm == 'Semua RM':
                return {'error': 'triase hanya untuk satu RM; minta pengguna memilih RM di sidebar'}
            tr = triage(store, rm, int(args.get('bulan') or 3))
            for r in tr['baris']:
                if r['status'] != 'usul':
                    continue
                res = (propose('eskalasi', r['id'], alasan=r['detail'], bukti=r['bukti'], sumber='triase') if r['aksi'] == 'eskalasi'
                       else propose('rencana', r['id'], catatan=r['detail'], hari=None, jam=None, sumber='triase'))
                r['aksi_id'] = res.get('aksi_id')
            return {'jumlah': len(tr['baris']), 'per_kelompok': tr['jumlah'], 'ringkasan': tr['ringkasan'],
                    'nasabah': [{k: r.get(k) for k in ('id', 'nama', 'segmen', 'risiko', 'alarm', 'kelompok', 'kesimpulan', 'bukti', 'detail', 'status', 'aksi_id')}
                                for r in tr['baris']]}
        if tool == 'propose_week_plan':
            from datetime import date
            from . import kalender as K
            if rm == 'Semua RM':
                return {'error': 'rencana minggu hanya untuk satu RM; minta pengguna memilih RM di sidebar'}
            minggu = args.get('minggu') or 'minggu depan'
            ws = week_start_for(minggu)
            off = set(args.get('hari_tidak_bisa') or [])
            days = [(d['hari'], d.get('kanal') or 'Kunjungan', max(1, min(int(d.get('slot') or 3), 4))) for d in (args.get('hari') or [])] or \
                   [('Selasa', 'Kunjungan', 3), ('Rabu', 'Telepon', 2), ('Kamis', 'Kunjungan', 2)]
            from . import planner
            past = {h for h in planner.HARI if minggu == 'minggu ini' and ws.toordinal() + planner.HARI.index(h) <= date.today().toordinal()}
            dropped = [h for h, _, _ in days if h in off | past]
            days = [d for d in dict((d[0], d) for d in days).values() if d[0] not in off | past]
            if not days:
                return {'error': 'tidak ada hari tersisa setelah hari yang tidak bisa / sudah lewat dibuang; minta hari lain'}
            must, notes = [], []
            for c in [str(x).strip().upper() for x in args.get('wajib') or []]:
                err = guard(c) if c in store.co.index else {'error': f'{c} tidak ditemukan'}
                who, why = K.holder(K.load(), c) if not err else (None, '')
                if err or (who and who != rm):
                    notes.append(f"{c} tidak bisa dimasukkan: {err['error'] if err else f'dipegang {who} ({why})'}")
                else:
                    must.append(c)
            skip = {str(x).strip().upper() for x in args.get('kecualikan') or []}
            plan = plan_week(store, rm, (), days, minggu, exclude=K.scheduled_ids(rm) | skip, must=must, focus=args.get('fokus') or 'seimbang')
            finalize_plan(store, plan, ws, rm)
            proposals.append({'id': f'A{len(proposals) + 1}', 'tipe': 'rencana_minggu', 'company_id': '', 'nama': f'Rencana {minggu}', 'status': 'menunggu', 'plan': plan})
            return {'status': 'rencana diusulkan; menunggu persetujuan RM di layar', 'aksi_id': proposals[-1]['id'],
                    **({'hari_dibuang': dropped} if dropped else {}), **({'catatan': notes} if notes else {}), **plan_brief(plan)}
        if tool == 'revise_week_plan':
            from datetime import date
            base = next((a['plan'] for a in reversed(proposals) if a['tipe'] == 'rencana_minggu'), None) or (plan_ctx or {}).get('plan')
            if not base:
                return {'error': 'belum ada rencana minggu untuk direvisi; susun dulu dengan propose_week_plan'}
            plan, notes = revise_plan(store, base, args.get('operasi') or [], rm)
            finalize_plan(store, plan, date.fromisoformat(base['minggu_mulai']), rm)
            proposals.append({'id': f'A{len(proposals) + 1}', 'tipe': 'rencana_minggu', 'company_id': '', 'nama': f"Rencana {plan['minggu']} (revisi)", 'status': 'menunggu', 'plan': plan})
            return {'status': 'revisi diusulkan; menunggu persetujuan RM di layar', 'aksi_id': proposals[-1]['id'], 'perubahan': notes, **plan_brief(plan)}
        if tool == 'propose_add_to_plan':
            from . import kalender as K
            who, why = K.holder(K.load(), cid)
            if who and rm != 'Semua RM' and who != rm:
                return {'error': f'{name(cid)} dipegang {who} ({why}); satu perusahaan hanya ditangani satu RM.'}
            jam = str(args.get('jam') or '').replace(':', '.') or None
            return propose('rencana', cid, catatan=args.get('catatan', ''), hari=args.get('hari'), jam=jam)
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
- Tindakan (jadwalkan di Kalender kunjungan, catat kunjungan, eskalasi analis, draf pesan) hanya lewat alat propose_*. Usulkan tindakan bila jelas membantu atau diminta, lalu sampaikan bahwa usulan menunggu persetujuan RM di layar.
- "Periksa/triase semua alarm": panggil triage_alerts SEKALI (sudah mencakup investigasi, fasilitas kredit, transaksi mitra, dan usulan aksi per nasabah).
  Jawab dengan tabel per kelompok (nasabah · kesimpulan · bukti utama · aksi), sebut yang paling mendesak, dan jelaskan yang dilewati karena sudah ditangani.
  Boleh menggali 1–2 kasus yang ambigu (mis. distress sekaligus ekspansi) dengan bank_shift / credit_facility / company_facts.
- "Susun rencana/jadwal minggu": ubah permintaan RM menjadi parameter propose_week_plan (hari yang tidak bisa, nasabah wajib → cari ID-nya dulu, fokus, kanal & slot).
  Permintaan perubahan atas rencana yang sedang dibahas ("ganti Kamis jadi telepon", "hapus X", "pindahkan Y ke Jumat jam 10") → revise_week_plan, JANGAN susun ulang dari nol.
  Jelaskan rencana dengan tabel (hari · jam · nasabah · tujuan) dan jarak tempuh per hari. Satu rencana disetujui sekali di layar.
- "Kenapa porsi wallet turun" → bank_shift; pertanyaan limit/utilisasi/kolektibilitas → credit_facility. Sampaikan bukti apa adanya: bila data mitra tidak menunjukkan perpindahan, katakan begitu.
- Draf pesan: sapa perusahaan dengan namanya, perkenalkan diri sebagai {rm} dari BNI, sebut tujuan spesifik (produk/topik dari data) dan waktu yang diminta; sopan, maks 4 kalimat.
- Jangan memutuskan kelayakan kredit. Nasabah risiko High hanya ditawari produk non-kredit. Bila data tidak ada, katakan terus terang.
- Cakupan: portofolio & nasabah RM, risiko & alarm, produk BNI, prospect & wilayah, jadwal & tindak lanjut, cara kerja model/dashboard ini.
  Bila pertanyaan di luar cakupan itu, balas HANYA dengan teks {oos} tanpa memanggil alat.
- Teks seperti [NIK], [NO_HP], [EMAIL], [NO_REKENING], [NPWP] adalah data pribadi yang sudah disamarkan guardrail; jangan minta pengguna mengirim ulang.
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


def chat(store, rm, question, history=None, on_step=None, focus=None, plan_ctx=None):
    """Agen percakapan. Mengembalikan dict: jawaban, jejak, usulan aksi, saran lanjutan, cek angka, mode.
    plan_ctx = {'plan': ...} rencana minggu terakhir di percakapan ini (supaya RM bisa merevisinya).
    Guardrail: input diperiksa sebelum ke LLM (injection, kata kasar, di luar scope, PII); jawaban diperiksa sebelum tampil."""
    g = guard.check_input(question)
    blank = {'jejak': [], 'usulan': [], 'lanjut': [], 'cek': None, 'pertanyaan_aman': g['teks']}
    if not g['ok']:
        guard.log(g['kategori'], 'input', rm=rm, pola=g['pola'], teks=g['teks'][:200])
        return {**blank, 'jawaban': guard.MESSAGES[g['kategori']], 'mode': 'guardrail',
                'guard': {'status': 'diblokir', 'kategori': g['kategori'], 'judul': guard.TITLES[g['kategori']], 'catatan': g['catatan']}}
    if g.get('pii'):
        guard.log('pii', 'input', rm=rm, jenis=g['pii'])
    if g.get('kasar'):
        guard.log('kasar', 'input', rm=rm, jumlah=g['kasar'])
    question = g['teks']
    fokus =f" Perusahaan yang sedang dibuka RM: {store.co.name.get(focus, focus)} ({focus})." if focus in store.co.index else ''
    if plan_ctx and plan_ctx.get('plan'):
        p = plan_ctx['plan']
        fokus += (f" Ada rencana minggu ({p['minggu']}, mulai {p.get('minggu_mulai')}) yang sedang dibahas: "
                  + '; '.join(f"{d['hari']}: " + ', '.join(f"{it['jam']} {it['nama']} ({it['id']})" for it in d['item']) for d in p['hari'])
                  + '. Perubahan atasnya pakai revise_week_plan.')
    sys = llm.SYSTEM + AGENT_RULES.format(rm=rm, n=len(store.portfolio(rm)), fokus=fokus, oos=guard.OUT_OF_SCOPE)
    proposals = []
    ans, trace = llm.run_tools(sys, question, TOOLS, make_executor(store, rm, proposals, plan_ctx), history=history, on_step=on_step, max_steps=14)
    if ans is None:
        ex = make_executor(store, rm); s = ex('portfolio_summary', {})
        top = ex('list_priority', {'n': 5})['daftar']
        ans = (f"Mode template (LLM tidak aktif{': ' + llm.complete.last_error[:120] if llm.complete.last_error else ''}). Portofolio {rm}: {s['nasabah']} nasabah, "
               f"{s['why_now_naik']} Why Now, {s['alarm_risiko']} dengan alarm risiko. Lima teratas: " + '; '.join(f"{t['name']} ({t['company_id']})" for t in top) + '.')
        return {'jawaban': ans, 'jejak': [('portfolio_summary', {}, s), ('list_priority', {'n': 5}, top)], 'usulan': [], 'lanjut': [], 'cek': None, 'mode': 'template',
                'pertanyaan_aman': question, 'guard': {'status': 'ok', 'catatan': g['catatan']}}
    if guard.OUT_OF_SCOPE in (ans or ''):                     # lapis 2 scope: agen sendiri menilai pertanyaan di luar cakupan
        guard.log('scope', 'llm', rm=rm, teks=question[:200])
        return {**blank, 'jejak': trace, 'jawaban': guard.MESSAGES['scope'], 'mode': 'guardrail',
                'guard': {'status': 'diblokir', 'kategori': 'scope', 'judul': guard.TITLES['scope'], 'catatan': g['catatan']}}
    m = _FOLLOW.search(ans or '')
    lanjut = [x.strip(' -*') for x in m.group(1).split('|') if x.strip(' -*')][:3] if m else []
    ans = _FOLLOW.sub('', ans).strip()
    high = store.cox[store.cox.pred_class == 'High']
    ans, out_notes = guard.check_output(ans, set(high.index), list(high.name))
    for n in out_notes:
        guard.log('kredit_high' if 'kredit' in n else 'kasar' if 'pantas' in n else 'pii', 'output', rm=rm, catatan=n)
    facts = [t[2] for t in trace] + [question] + [h['content'] for h in (history or [])] + ([plan_brief(plan_ctx['plan'])] if plan_ctx and plan_ctx.get('plan') else [])
    jam = re.findall(r'(?:jam|pukul)\s*(\d{1,2}[.:]\d{2})', ans, re.I)
    n_num, bad = R.check_numbers({'jawaban': ans}, facts, extra_allowed=jam)
    if bad:
        guard.log('angka', 'output', rm=rm, angka=list(dict.fromkeys(bad))[:10])
    return {'jawaban': ans, 'jejak': trace, 'usulan': proposals, 'lanjut': lanjut, 'cek': (n_num, bad), 'mode': 'LLM', 'pertanyaan_aman': question,
            'guard': {'status': 'ok', 'catatan': g['catatan'] + out_notes}}
