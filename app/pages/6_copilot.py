import json
from datetime import date, datetime

import pandas as pd
import streamlit as st

from egi import agent, data, llm, state, ui
import reports as R  # noqa: E402  (src/ ditambahkan ke sys.path oleh egi.data)

store = data.get_store(); ss = st.session_state
TASKS = {'plan': 'Rencana minggu', 'alarm': 'Investigasi alarm', 'brief': 'Siapkan kunjungan', 'chat': 'Tanya Copilot'}
cfg = llm.config()

ui.page_header(f"{ss.rm} · {'LLM ' + cfg['provider'] + ' · ' + cfg['model'] if cfg['enabled'] else 'mode template (tanpa LLM)'} · setiap tindakan menunggu persetujuan Anda", 'RM Copilot')
inv = {v: k for k, v in TASKS.items()}
want = ss.get('copilot_task') or 'plan'
if ss.get('_task_seen') != want or 'task_sel' not in ss:     # lompatan dari halaman lain memilih tugasnya
    ss['task_sel'] = TASKS[want]
pick = st.segmented_control('Tugas', list(TASKS.values()), key='task_sel')
task = inv.get(pick or TASKS['plan'])
ss.copilot_task = ss._task_seen = task


def show_trace(trace):
    with st.expander(f'Jejak agen · {len(trace)} langkah'):
        for t in trace:
            if len(t) == 2:
                st.markdown(f"`{t[0]}` → {ui.esc(t[1])}", unsafe_allow_html=True)
            else:
                st.markdown(f"`{t[0]}({json.dumps(t[1], ensure_ascii=False)})`")
                st.json(t[2], expanded=False)


# ================================================================== rencana minggu
if task == 'plan':
    a, b = st.columns([1, 1.4])
    with a:
        st.markdown('**Hari & kanal**')
        days = st.data_editor(pd.DataFrame([('Selasa', 'Kunjungan', 3), ('Rabu', 'Telepon', 2), ('Kamis', 'Kunjungan', 2)], columns=['hari', 'kanal', 'slot']),
                              num_rows='dynamic', hide_index=True, use_container_width=True, key='days_ed',
                              column_config={'hari': st.column_config.SelectboxColumn('Hari', options=['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat']),
                                             'kanal': st.column_config.SelectboxColumn('Kanal', options=['Kunjungan', 'Telepon']),
                                             'slot': st.column_config.NumberColumn('Slot', min_value=1, max_value=4, step=1)})
        week = st.text_input('Label minggu', 'minggu depan')
    with b:
        st.markdown(f"**Keranjang rencana** · {len(ss.plan)} perusahaan (didahulukan)")
        for p in ss.plan:
            st.markdown(f"- {ui.esc(p['nama'])} <span class='egi-muted'>{p['id']} · {p['jenis']}</span>", unsafe_allow_html=True)
        if not ss.plan:
            st.caption('Kosong. Tambahkan dari Daftar prioritas, Profil, Wilayah, atau Prospect; Copilot tetap memilih dari portofolio.')
    if st.button('Susun rencana', type='primary'):
        dd = [(r.hari, r.kanal, int(r.slot)) for r in days.dropna().itertuples()]
        with st.spinner('Copilot memeriksa portofolio, alarm, wilayah, dan jaringan…'):
            ss.agent_result = ('plan', agent.plan_week(store, ss.rm, ss.plan, dd or None, week))
        data.audit('susun_rencana', rm=ss.rm, keranjang=[p['id'] for p in ss.plan])
    res = ss.agent_result
    if res and res[0] == 'plan':
        plan = res[1]
        k = st.columns(4)
        for col, (l, v, sub) in zip(k, plan['kpi']):
            ui.kpi(col, l, v, sub)
        st.write('')
        ui.ai_box('Ringkasan rencana', plan['ringkasan'], 'alur agen deterministik: portofolio → alarm → prioritas → risiko → area → jaringan')
        show_trace(plan['jejak'])
        for di, d in enumerate(plan['hari']):
            st.markdown(f"#### {d['hari']} · {d['tema']}")
            for it in d['item']:
                x1, x2, x3 = st.columns([0.6, 4, 1.2])
                x1.markdown(f"**{it['jam']}**")
                x2.markdown(f"**{ui.esc(it['nama'])}** <span class='egi-muted'>{it['id']} · {ui.esc(it['info'])} · peluang {it['peluang']}</span><br>{ui.esc(it['tujuan'])}"
                            f"<br><span class='egi-muted'>Siapkan: {ui.esc(it['siapkan'])}</span>", unsafe_allow_html=True)
                if x3.button('Profil', key=f"pl_{di}_{it['id']}"):
                    state.focus_company(it['id'])
        if plan['pesan']:
            st.markdown('#### Draf pesan (centang yang disetujui)')
            for i, m in enumerate(plan['pesan']):
                c1, c2 = st.columns([0.3, 5])
                m['ok'] = c1.checkbox('ok', key=f"msg_ok_{i}_{m['ke']}", label_visibility='collapsed')
                m['isi'] = c2.text_area(f"Ke {m['ke']} · {m['kanal']}", m['isi'], key=f"msg_{i}_{m['ke']}", height=90)
        c1, c2 = st.columns(2)
        if c1.button('Setujui rencana', type='primary', use_container_width=True):
            out = data.APP_OUT / 'plans'; out.mkdir(parents=True, exist_ok=True)
            f = out / f"rencana_{ss.rm}_{datetime.now():%Y%m%d_%H%M%S}.json"
            plan['status'] = f"disetujui {ss.rm} {date.today():%d %b %Y}"
            f.write_text(json.dumps(plan, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
            data.audit('setujui_rencana', rm=ss.rm, berkas=f.name, pesan_disetujui=sum(bool(m.get('ok')) for m in plan['pesan']))
            st.success(f'Rencana disimpan: outputs/app/plans/{f.name}. Pesan tidak dikirim otomatis.')
        buf = R.weekly_plan_pdf({**plan, 'pesan': [m for m in plan['pesan'] if m.get('ok')] or plan['pesan']})
        c2.download_button('Unduh PDF rencana', buf.getvalue(), file_name=f"rencana_minggu_{ss.rm}.pdf", mime='application/pdf', use_container_width=True)

# ================================================================== investigasi alarm
elif task == 'alarm':
    pf = agent.candidates(store, ss.rm)
    al = pf[pf.alarm != ''] if not pf.empty else pf
    opts = list(al.index)
    if ss.focus_company and ss.focus_company not in opts and ss.focus_company in store.co.index:
        opts = [ss.focus_company] + opts
    if not opts:
        st.info('Tidak ada nasabah beralarm dalam 3 bulan terakhir.'); st.stop()
    cid = st.selectbox('Nasabah beralarm', opts, index=0, format_func=lambda c: f"{store.co.name[c]} · {c} · {pf.alarm.get(c, '') if c in pf.index else ''}")
    if st.button('Jalankan investigasi', type='primary') or (ss.agent_result and ss.agent_result[0] == 'alarm' and ss.agent_result[1]['fp']['id'] == cid):
        if not (ss.agent_result and ss.agent_result[0] == 'alarm' and ss.agent_result[1]['fp']['id'] == cid):
            ss.agent_result = ('alarm', agent.investigate(store, cid))
            data.audit('investigasi', rm=ss.rm, company=cid, hasil=ss.agent_result[1]['verdict'])
        r = ss.agent_result[1]
        tone = '#FADFDB' if r['verdict'].startswith('Tanda') else '#FBEFD6' if r['verdict'].startswith('Kemungkinan') else '#EEF0F3'
        st.markdown(f"<div class='egi-card' style='background:{tone}'><b>{ui.esc(r['verdict'])}</b><br>{ui.esc(r['route'])}</div>", unsafe_allow_html=True)
        st.markdown('**Bukti**')
        for e in r['evidence']:
            st.markdown(f'- {e}')
        show_trace(r['trace'])
        c1, c2, c3 = st.columns(3)
        if c1.button('Teruskan ke analis risiko', use_container_width=True):
            data.audit('teruskan_analis', rm=ss.rm, company=cid, bukti=r['evidence']); st.success('Paket bukti dicatat di log audit untuk analis.')
        if c2.button('Jadwalkan kunjungan retensi', use_container_width=True):
            state.add_to_plan(store, cid, 'retensi')
        if c3.button('Buka profil', use_container_width=True):
            state.focus_company(cid)
        st.caption('Aturan: ≥ 2 poin distress (telat bayar, outflow > inflow, pembeli hilang, alarm distress) → analis; ≥ 2 poin retensi → kunjungan RM. Copilot tidak memutuskan kredit.')

# ================================================================== siapkan kunjungan
elif task == 'brief':
    mine = list(store.portfolio(ss.rm).sort_values('opportunity_score', ascending=False).index)
    if ss.focus_company and ss.focus_company not in mine and ss.focus_company in store.co.index:
        mine = [ss.focus_company] + mine
    cid = st.selectbox('Perusahaan', mine, index=mine.index(ss.focus_company) if ss.focus_company in mine else 0, format_func=lambda c: f"{store.co.name[c]} · {c}")
    fp = R.fact_pack(store, cid)
    narr, mode = (ss.narr[cid][0], ss.narr[cid][1]) if cid in ss.get('narr', {}) else (llm.template_company(fp), 'template')
    row = agent.candidates(store, ss.rm).reindex([cid]).iloc[0].to_dict() if cid in store.portfolio(ss.rm).index else {}
    tujuan, peluang = agent._purpose(store, cid, row) if row else ('Prospect: perkenalan dan pemetaan kebutuhan.', '—')
    a, b = st.columns([1.3, 1])
    with a:
        ui.ai_box('Tujuan kunjungan', tujuan, 'aturan Copilot di atas skor NB08')
        st.write('')
        ui.ai_box('Ringkasan untuk dibawa', narr['ringkasan'], 'paket fakta', mode)
        st.markdown('**Pertanyaan pembuka**')
        for q in narr['pertanyaan']:
            st.markdown(f'- {q}')
    with b:
        st.markdown('**Produk yang dibawa**')
        for p in (fp.get('produk') or [])[:3]:
            st.markdown(f"- **{p['produk']}** · peluang {ui.fmt(p['peluang'], 0)}% · EV Rp {ui.fmt(p['ev'], 1)} juta" + (' · *ditunda (risiko)*' if p['ditunda'] else ''))
        st.markdown('**Jangan lupa**')
        if fp['anomali']['jenis_3bln']:
            st.markdown(f"- Ada alarm {', '.join(fp['anomali']['jenis_3bln'])}: tanyakan penyebabnya.")
        if fp['kunjungan']:
            last = fp['kunjungan'][-1]; st.markdown(f"- Kontak terakhir {last['tgl']} ({last['respons']}): {last['catatan']}")
        if fp['risiko']['kelas'] == 'High':
            st.markdown('- Risiko High: jangan menawarkan kredit.')
        wa, m = llm.draft_message('janji', {'nama': fp['nama'], 'rm': ss.rm, 'waktu': 'minggu ini', 'topik': tujuan[:120]}) if st.button('Draf pesan janji temu') else (None, None)
        if wa:
            st.text_area(f'Draf ({m})', wa, height=110)
        buf, _ = R.company_summary_pdf(fp, narr, generated_by='Copilot (LLM)' if mode == 'LLM' else 'Copilot (template)')
        st.download_button('Unduh ringkasan eksekutif (PDF)', buf.getvalue(), file_name=f'ringkasan_{cid}.pdf', mime='application/pdf', use_container_width=True)

# ================================================================== chat
else:
    if not cfg['enabled']:
        st.markdown("<div class='egi-warn'>LLM belum aktif: Copilot menjawab dengan template ringkasan portofolio. Isi <code>.env</code> untuk pertanyaan bebas.</div>", unsafe_allow_html=True)
    ex = ['Siapa 5 nasabah S2 saya yang paling layak dikunjungi minggu ini dan kenapa?', 'Prospect mana yang bisa saya dekati lewat nasabah sendiri?',
          'Kecamatan mana yang paling potensial dan belum ada cabang?']
    cols = st.columns(3)
    q = None
    for col, e in zip(cols, ex):
        if col.button(e, use_container_width=True):
            q = e
    for m in ss.chat:
        with st.chat_message(m['role']):
            st.markdown(m['text'])
            if m.get('trace'):
                show_trace(m['trace'])
    q = st.chat_input('Tanya tentang portofolio, nasabah, wilayah, atau prospect…') or q
    if q:
        ss.chat.append({'role': 'user', 'text': q})
        with st.spinner('Copilot memanggil alat…'):
            ans, trace = agent.chat(store, ss.rm, q)
        ss.chat.append({'role': 'assistant', 'text': ans or 'Tidak ada jawaban.', 'trace': trace})
        data.audit('chat', rm=ss.rm, pertanyaan=q, alat=[t[0] for t in trace])
        st.rerun()
    if ss.chat and st.button('Bersihkan percakapan'):
        ss.chat = []; st.rerun()
