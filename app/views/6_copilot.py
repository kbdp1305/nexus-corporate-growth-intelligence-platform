import json
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

from egi import agent, auth, data, llm, planner, state, ui, viz
from egi import kalender as K
import reports as R  # noqa: E402  (src/ ditambahkan ke sys.path oleh egi.data)

store = data.get_store(); ss = st.session_state
TASKS = {'chat': 'Tanya Copilot', 'plan': 'Rencana minggu', 'alarm': 'Investigasi alarm', 'brief': 'Siapkan kunjungan'}
cfg = llm.config()

ui.page_header(f"{ss.rm} · {'LLM ' + cfg['provider'] + ' · ' + cfg['model'] if cfg['enabled'] else 'mode template (tanpa LLM)'} · setiap tindakan menunggu persetujuan Anda", 'RM Copilot')
inv = {v: k for k, v in TASKS.items()}
want = ss.get('copilot_task') or 'chat'
if ss.get('_task_seen') != want or 'task_sel' not in ss:     # lompatan dari halaman lain memilih tugasnya
    ss['task_sel'] = TASKS[want]
pick = st.segmented_control('Tugas', list(TASKS.values()), key='task_sel')
task = inv.get(pick or TASKS['chat'])
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
        nxt = date.today() + timedelta(days=7 - date.today().weekday())
        week_start = st.date_input('Senin minggu rencana', nxt, format='DD/MM/YYYY')
        week_start = week_start - timedelta(days=week_start.weekday())
    with b:
        st.markdown(f"**Keranjang rencana** · {len(ss.plan)} perusahaan (didahulukan, prospect ikut dijadwalkan)")
        for p in ss.plan:
            st.markdown(f"- {ui.esc(p['nama'])} <span class='egi-muted'>{p['id']} · {p['jenis']}</span>", unsafe_allow_html=True)
        if not ss.plan:
            st.caption('Kosong. Tambahkan dari Daftar prioritas, Profil, Wilayah, atau Prospect; Copilot tetap memilih dari portofolio.')
    if st.button('Susun rencana', type='primary'):
        dd = [(r.hari, r.kanal, int(r.slot)) for r in days.dropna().itertuples()]
        with st.spinner('Copilot memeriksa portofolio, alarm, wilayah, dan jaringan…'):
            plan = agent.plan_week(store, ss.rm, ss.plan, dd or None, week)
            planner.add_basket_prospects(store, ss.rm, plan, ss.plan)
            planner.refresh_kpi(plan, store)
            ss.agent_result = ('plan', plan)
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

        # -------------------------------------------------------------- rute perjalanan per hari
        visit = [d for d in plan['hari'] if d.get('kanal', 'Kunjungan') == 'Kunjungan' and d['item']]
        if visit:
            st.markdown('#### Rute kunjungan')
            r1, r2 = st.columns([1.6, 1])
            pick = r2.segmented_control('Hari', [d['hari'] for d in visit], default=visit[0]['hari'], key='route_day') or visit[0]['hari']
            d = next(x for x in visit if x['hari'] == pick)
            stops = pd.DataFrame([{'lat': planner.coords(store, it['id'])[0], 'lon': planner.coords(store, it['id'])[1], 'no': str(i + 1),
                                   'rgb': viz.MINE_RGB if store.cox.is_client.get(it['id'], False) else viz.PROSPECT_RGB,
                                   'label': f"<b>{i + 1}. {ui.esc(it['nama'])}</b><br>{it['jam']} · {ui.esc(it['info'])}"} for i, it in enumerate(d['item'])])
            with r1:
                st.pydeck_chart(viz.route_deck(stops, viz.branch_points(store.branches)), height=380)
            with r2:
                legs = [planner.km(planner.coords(store, x['id']), planner.coords(store, y['id'])) for x, y in zip(d['item'], d['item'][1:])]
                st.markdown(f"**{d['hari']}** · {len(d['item'])} kunjungan · ±{sum(legs):.1f} km · ±{sum(legs) / planner.SPEED_KMH * 60:.0f} menit di jalan")
                for i, it in enumerate(d['item']):
                    st.markdown(f"**{i + 1}.** {it['jam']} · {ui.esc(it['nama'])}" + (f"<br><span class='egi-muted'>↓ {legs[i]:.1f} km</span>" if i < len(legs) else ''),
                                unsafe_allow_html=True)
                if len(d['item']) >= 3 and st.button(f"Optimalkan rute {d['hari']}", key=f"opt_{d['hari']}", use_container_width=True,
                                                     help='Urutan tetangga terdekat; slot jam hari itu tetap, hanya urutan kunjungan yang berubah.'):
                    before = planner.route_km(store, d['item']); planner.optimize(store, d)
                    st.toast(f"{d['hari']}: rute {before:.1f} → {planner.route_km(store, d['item']):.1f} km"); st.rerun()
                st.caption('Navy = nasabah · oranye = prospect · ◯ = cabang BNI. Jarak garis lurus; waktu tempuh perkiraan (±20 km/jam).')

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
            data.audit('setujui_rencana', rm=ss.rm, berkas=f.name, minggu_mulai=str(week_start), pesan_disetujui=sum(bool(m.get('ok')) for m in plan['pesan']))
            if ss.rm != 'Semua RM':
                n_new, n_upd = K.upsert(K.from_plan(plan, week_start), auth.current()['username'])
                ss.plan_to_cal = f'{n_new} jadwal baru, {n_upd} diperbarui di Kalender kunjungan'
            st.success(f'Rencana disimpan: outputs/app/plans/{f.name}. Pesan tidak dikirim otomatis.')
        buf = R.weekly_plan_pdf({**plan, 'pesan': [m for m in plan['pesan'] if m.get('ok')] or plan['pesan']})
        c2.download_button('Unduh PDF rencana', buf.getvalue(), file_name=f"rencana_minggu_{ss.rm}.pdf", mime='application/pdf', use_container_width=True)
        if ss.get('plan_to_cal'):
            st.info(ss.plan_to_cal)
            if st.button('Buka Kalender kunjungan'):
                ss.plan_to_cal = None; state.go('kalender')
        st.caption(f"Setelah disetujui, jadwal masuk ke Kalender kunjungan untuk minggu {week_start:%d %b} – {week_start + timedelta(days=4):%d %b %Y} (WIB).")

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

# ================================================================== chat (agen LLM)
else:
    def step_line(name, args, out):
        a = ', '.join(f"{k}={v}" for k, v in args.items() if k not in ('isi', 'catatan', 'alasan'))
        if isinstance(out, dict) and 'error' in out:
            res = f"⚠ {out['error']}"
        elif isinstance(out, dict) and 'jumlah' in out:
            res = f"{out['jumlah']} hasil"
        elif isinstance(out, dict) and 'status' in out:
            res = 'usulan dibuat'
        elif isinstance(out, list):
            res = f'{len(out)} baris'
        else:
            res = 'selesai'
        return f"**{agent.TOOL_LABEL.get(name, name)}** <span class='egi-muted'>{ui.esc(a)} → {ui.esc(res)}</span>"

    def run_action(a, msg_i):
        cid = a['company_id']
        if a['tipe'] == 'rencana':
            state.add_to_plan(store, cid, a.get('catatan', ''))
        elif a['tipe'] == 'kunjungan':
            c = store.cox.loc[cid]
            store.append_visit({'action_id': f"APP-{pd.Timestamp.now():%Y%m%d%H%M%S}", 'track': 'Deepening' if c.is_client else 'Acquisition', 'party_id': cid,
                                'product_id': a.get('produk', ''), 'rm_id': ss.rm, 'contact_date': date.today().isoformat(), 'channel': a.get('kanal', 'Visit'),
                                'tier_at_contact': '', 'response': a['respons'], 'converted': int(a['respons'] == 'Converted'), 'deal_value_idr_mn': 0.0, 'rm_rating': '',
                                'feedback_note': f"{a.get('catatan', '')} | sumber: Copilot"})
        elif a['tipe'] == 'pesan':
            a['isi'] = ss.get(f"act_txt_{msg_i}_{a['id']}", a['isi'])
        data.audit(f"copilot_{a['tipe']}", rm=ss.rm, company=cid, **{k: v for k, v in a.items() if k not in ('id', 'tipe', 'company_id', 'status')})
        a['status'] = 'disetujui'

    def show_actions(m, msg_i):
        if not m.get('usulan'):
            return
        st.markdown(f"**Usulan tindakan** · {sum(a['status'] == 'menunggu' for a in m['usulan'])} menunggu persetujuan")
        judul = {'rencana': 'Tambah ke rencana minggu', 'kunjungan': 'Catat hasil kontak', 'eskalasi': 'Teruskan ke analis risiko', 'pesan': 'Draf pesan'}
        for a in m['usulan']:
            with st.container(border=True):
                c1, c2, c3 = st.columns([5, 1, 1])
                detail = {'rencana': a.get('catatan'), 'kunjungan': f"{a.get('respons')} · {a.get('kanal')} · {a.get('produk') or '—'} · {a.get('catatan')}",
                          'eskalasi': a.get('alasan'), 'pesan': a.get('jenis')}[a['tipe']]
                c1.markdown(f"**{judul[a['tipe']]}** · {ui.esc(a['nama'])} <span class='egi-muted'>{a['company_id']}</span><br>"
                            f"<span class='egi-muted'>{ui.esc(detail or '')}</span>", unsafe_allow_html=True)
                if a['tipe'] == 'pesan':
                    c1.text_area('Isi pesan', a['isi'], key=f"act_txt_{msg_i}_{a['id']}", height=100, label_visibility='collapsed', disabled=a['status'] != 'menunggu')
                if a['status'] == 'menunggu':
                    if c2.button('Setujui', key=f"ok_{msg_i}_{a['id']}", type='primary', use_container_width=True):
                        run_action(a, msg_i); st.rerun()
                    if c3.button('Tolak', key=f"no_{msg_i}_{a['id']}", use_container_width=True):
                        a['status'] = 'ditolak'; data.audit('copilot_tolak', rm=ss.rm, company=a['company_id'], tipe=a['tipe']); st.rerun()
                else:
                    c2.markdown(f"{'✅' if a['status'] == 'disetujui' else '✖'} {a['status']}")
                    if a['tipe'] == 'pesan' and a['status'] == 'disetujui':
                        c1.caption('Pesan tidak dikirim otomatis; salin dan kirim lewat kanal resmi.')

    def show_check(m):
        if not m.get('cek'):
            return
        n, bad = m['cek']
        if bad:
            st.markdown(f"<div class='egi-warn'>{len(bad)} dari {n} angka tidak ditemukan di data yang dibaca agen: {ui.esc(', '.join(dict.fromkeys(bad)))}. "
                        'Cek ulang sebelum dipakai.</div>', unsafe_allow_html=True)
        elif n:
            st.caption(f"✓ {n} angka di jawaban cocok dengan data yang dibaca agen")

    if not cfg['enabled']:
        st.markdown("<div class='egi-warn'>LLM belum aktif: Copilot menjawab dengan template ringkasan portofolio. Isi <code>.env</code> untuk pertanyaan bebas.</div>", unsafe_allow_html=True)
    fokus = f" · fokus {store.co.name.get(ss.focus_company, '')} ({ss.focus_company})" if ss.focus_company else ''
    st.caption(f"Konteks agen: {ss.rm}{fokus} · {len(agent.TOOLS)} alat · mengingat {min(len(ss.chat), 12)} pesan terakhir · tindakan selalu menunggu persetujuan Anda")
    q = ss.pop('pending_q', None)
    if not ss.chat:
        ex = ['Siapa 5 nasabah S2 saya yang paling layak dikunjungi minggu ini dan kenapa?', 'Ada nasabah saya yang menunjukkan tanda distress? Apa yang harus saya lakukan?',
              'Prospect mana yang bisa saya dekati lewat nasabah sendiri, dan siapa perantaranya?', 'Bandingkan 3 nasabah S3 saya dengan skor peluang tertinggi']
        cols = st.columns(2)
        for i, e in enumerate(ex):
            if cols[i % 2].button(e, use_container_width=True, key=f'ex_{i}'):
                q = e
    for i, m in enumerate(ss.chat):
        with st.chat_message(m['role']):
            st.markdown(m['text'])
            if m['role'] == 'assistant':
                show_check(m)
                show_actions(m, i)
                if m.get('trace'):
                    show_trace(m['trace'])
                if m.get('lanjut') and i == len(ss.chat) - 1:
                    fc = st.columns(len(m['lanjut']))
                    for j, f in enumerate(m['lanjut']):
                        if fc[j].button(f, key=f'fu_{i}_{j}', use_container_width=True):
                            ss.pending_q = f; st.rerun()
    q = st.chat_input('Tanya, minta analisis, atau minta Copilot menyiapkan tindakan…') or q
    if q:
        history = [{'role': m['role'], 'content': m['text']} for m in ss.chat[-12:]]
        ss.chat.append({'role': 'user', 'text': q})
        with st.chat_message('user'):
            st.markdown(q)
        with st.chat_message('assistant'):
            with st.status('Copilot menganalisis…', expanded=True) as box:
                res = agent.chat(store, ss.rm, q, history=history, focus=ss.focus_company,
                                 on_step=lambda n, a, o: st.markdown(step_line(n, a, o), unsafe_allow_html=True))
                box.update(label=f"Selesai · {len(res['jejak'])} langkah · {res['mode']}", state='complete', expanded=False)
        ss.chat.append({'role': 'assistant', 'text': res['jawaban'] or 'Tidak ada jawaban.', 'trace': res['jejak'], 'usulan': res['usulan'],
                        'lanjut': res['lanjut'], 'cek': res['cek']})
        data.audit('chat', rm=ss.rm, pertanyaan=q, alat=[t[0] for t in res['jejak']], usulan=len(res['usulan']), mode=res['mode'])
        st.rerun()
    if ss.chat and st.button('Mulai percakapan baru'):
        ss.chat = []; st.rerun()
