"""RM Copilot: alat (tools) di atas data skor, alur agen deterministik, dan agen LLM dengan tool use.

Alur deterministik (selalu jalan, juga tanpa LLM) menjamin hasil yang bisa diaudit;
LLM (bila aktif) dipakai untuk menjawab pertanyaan bebas dengan memanggil alat yang sama.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import reports as R

from . import llm

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
    return {'jam': jam, 'id': cid, 'nama': c['name'], 'info': f"{c.segment} · {c.district} · risiko {c.pred_class}", 'tujuan': tujuan, 'peluang': peluang, 'siapkan': siapkan}


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
                out_days.append({'hari': hari, 'tema': tema, 'item': items, 'intro': (pid, via[0])})
                continue
        out_days.append({'hari': hari, 'tema': tema, 'item': items})
    for hari, kanal, n in call_days:
        ids = [c for c in pf[pf.segment == 'S1 Kecil'].index if c not in used][:n]
        items = []
        for j, cid in enumerate(ids):
            used.add(cid); items.append(_item(store, cid, pf.loc[cid].to_dict(), JAM[j % 4], 'Skrip telepon'))
        out_days.append({'hari': hari, 'tema': 'telepon S1 (kanal murah)', 'item': items})
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


# ---------------------------------------------------------------- alat untuk agen LLM
TOOLS = [
    {'name': 'portfolio_summary', 'description': 'Ringkasan portofolio RM: jumlah nasabah per segmen, Why Now, nasabah prioritas yang belum dihubungi.', 'parameters': {'type': 'object', 'properties': {}}},
    {'name': 'list_priority', 'description': 'Daftar nasabah RM urut skor peluang.', 'parameters': {'type': 'object', 'properties': {'segmen': {'type': 'string', 'enum': ['S1 Kecil', 'S2 Menengah', 'S3 Besar', 'Semua']}, 'n': {'type': 'integer'}}}},
    {'name': 'company_facts', 'description': 'Paket fakta satu perusahaan (risiko, keuangan, arus kas, alarm, jaringan, produk, riwayat).', 'parameters': {'type': 'object', 'properties': {'company_id': {'type': 'string'}}, 'required': ['company_id']}},
    {'name': 'investigate_alarm', 'description': 'Investigasi alarm satu nasabah: kesimpulan retensi vs distress dan bukti.', 'parameters': {'type': 'object', 'properties': {'company_id': {'type': 'string'}}, 'required': ['company_id']}},
    {'name': 'district_ranking', 'description': 'Peringkat kecamatan menurut skor potensi wilayah.', 'parameters': {'type': 'object', 'properties': {'n': {'type': 'integer'}}}},
    {'name': 'network_prospects', 'description': 'Prospect yang bertransaksi dengan nasabah RM, urut nilai relasi.', 'parameters': {'type': 'object', 'properties': {'n': {'type': 'integer'}}}},
    {'name': 'intro_path', 'description': 'Jalur kenalan ke satu prospect lewat nasabah BNI.', 'parameters': {'type': 'object', 'properties': {'prospect_id': {'type': 'string'}}, 'required': ['prospect_id']}},
]


def make_executor(store, rm):
    def slim(fp):
        fp = dict(fp); fp['arus_kas'] = {k: v for k, v in fp['arus_kas'].items() if k != 'capture_seri'}; return fp

    def ex(name, args):
        if name == 'portfolio_summary':
            pf = candidates(store, rm)
            return {'rm': rm, 'nasabah': len(pf), 'per_segmen': pf.segment.value_counts().to_dict(), 'why_now': int(pf.why_up.sum()), 'alarm_risiko': int(pf.caution.sum()),
                    'prioritas_belum_dihubungi': pf[(pf.opportunity_score >= 0.75) & ~pf.contacted].name.head(10).to_dict()}
        if name == 'list_priority':
            pf = candidates(store, rm); s = args.get('segmen', 'Semua')
            pf = pf if s in (None, 'Semua') else pf[pf.segment == s]
            return pf.head(int(args.get('n', 10)))[['name', 'segment', 'opportunity_score', 'risk_class', 'alarm', 'recommended_products', 'reason', 'contacted']].round(3).reset_index().to_dict('records')
        if name == 'company_facts':
            cid = args['company_id']
            if cid not in store.co.index: return {'error': 'tidak ditemukan'}
            if rm != 'Semua RM' and store.co.rm_id.get(cid) not in (rm, None) and store.cox.is_client.get(cid): return {'error': 'di luar portofolio RM ini'}
            return llm._facts_json(slim(R.fact_pack(store, cid)))
        if name == 'investigate_alarm':
            r = investigate(store, args['company_id']); return {k: r[k] for k in ('verdict', 'route', 'evidence')}
        if name == 'district_ranking':
            return store.districts().head(int(args.get('n', 8)))[['kota', 'skor', 'prospect', 'pen', 'gap_T', 'cabang']].round(3).reset_index().to_dict('records')
        if name == 'network_prospects':
            p = store.prospects_for(rm)
            return [] if p.empty else p.head(int(args.get('n', 10)))[['name', 'segment', 'district', 'lewat_nama', 'nilai_M', 'risk_class']].round(2).reset_index().to_dict('records')
        if name == 'intro_path':
            return store.intro_paths(args['prospect_id'], rm).head(5)[['name', 'rm_id', 'nilai_M', 'jenis', 'milik_saya']].round(2).reset_index().to_dict('records')
        return {'error': f'alat {name} tidak dikenal'}
    return ex


def chat(store, rm, question):
    sys = llm.SYSTEM + f" Anda bekerja untuk {rm}. Gunakan alat untuk mengambil data; jangan menebak. Jawab ringkas, sebutkan nama dan ID perusahaan."
    ans, trace = llm.run_tools(sys, question, TOOLS, make_executor(store, rm))
    if ans is None:
        ex = make_executor(store, rm); s = ex('portfolio_summary', {})
        top = ex('list_priority', {'n': 5})
        ans = (f"Mode template (LLM tidak aktif). Portofolio {rm}: {s['nasabah']} nasabah, {s['why_now']} Why Now, {s['alarm_risiko']} dengan alarm risiko. "
               'Lima teratas: ' + '; '.join(f"{t['name']} ({t['company_id']})" for t in top) + '. Aktifkan LLM di .env untuk menjawab pertanyaan bebas.')
        trace = [('portfolio_summary', {}, s), ('list_priority', {'n': 5}, top)]
    return ans, trace
