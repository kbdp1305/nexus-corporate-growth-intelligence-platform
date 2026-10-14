import json
import uuid
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

from egi import agent, auth, copilot_flow as flow, data, guard, llm, planner, profile_workspace as PW, sim, state, ui, viz
from egi import kalender as K, tindak as T
import reports as R  # noqa: E402  (src/ ditambahkan ke sys.path oleh egi.data)

store = data.get_store(); ss = st.session_state
user = auth.current()
if not user or user['role'] not in ('rm', 'supervisor'):
    st.stop()
if user['role'] == 'rm':
    ss.rm = user['rm_id']
allowed = PW.accessible_ids(store, user)
context_rm = (user['username'], ss.rm)
if ss.get('_copilot_context_rm') != context_rm:
    if ss.get('_copilot_context_rm') is not None:
        ss.agent_result = None; ss.chat = []; ss.week_plan_ctx = None
        ss.plan_to_cal = None; ss.triage_msg = None
    ss._copilot_context_rm = context_rm
if ss.focus_company and ss.focus_company not in allowed:
    ss.focus_company = None
    st.info('Fokus perusahaan dilepas karena berada di luar cakupan akun saat ini.')
TASKS = {'chat': 'Tanya Copilot', 'triase': 'Tinjau Temuan', 'plan': 'Susun Rencana', 'alarm': 'Tinjau Temuan', 'brief': 'Siapkan Bahan Kunjungan'}
cfg = llm.config()

ui.page_header(f"{ss.rm} · Data analisis per {data.SNAPSHOT:%d/%m/%Y} · tindakan dijalankan setelah persetujuan Anda", 'RM Copilot')
with st.container(border=True):
    focus_text, focus_control = st.columns([2, 1])
    if ss.focus_company:
        focus_text.markdown(f"**Perusahaan aktif:** {ui.esc(store.co.name.get(ss.focus_company, ss.focus_company))}", unsafe_allow_html=True)
        focus_text.caption(f'{ss.focus_company} · {ss.rm}')
    else:
        focus_text.markdown(f'**Konteks aktif: Portofolio {ss.rm}**')
        focus_text.caption('Pilih perusahaan untuk membahas kebutuhan atau menyiapkan bahan kunjungan.')
    with focus_control.popover('Ganti / Lepas Fokus', use_container_width=True):
        options = [None] + sorted(allowed, key=lambda cid: str(store.co.name.get(cid, cid)))
        chosen = st.selectbox('Perusahaan dalam cakupan akun', options,
                              index=options.index(ss.focus_company) if ss.focus_company in options else 0,
                              format_func=lambda cid: 'Portofolio (tanpa fokus perusahaan)' if cid is None else f'{store.co.name.get(cid, cid)} · {cid}',
                              key=f'copilot_focus_pick_{ss.rm}')
        if st.button('Terapkan Fokus', key='copilot_apply_focus'):
            ss.focus_company = chosen
            st.rerun()
with st.expander('Informasi layanan & rincian teknis'):
    st.caption(f"{'AI aktif: ' + cfg['provider'] + ' · ' + cfg['model'] if cfg['enabled'] else 'Mode ringkasan otomatis; pertanyaan bebas belum tersedia.'}")
    st.caption(f'{len(agent.TOOLS)} alat tersedia · hasil analisis mengikuti data yang tersedia · jejak proses ada pada rincian hasil.')
inv = {'Tanya Copilot': 'chat', 'Siapkan Bahan Kunjungan': 'brief', 'Susun Rencana': 'plan'}
want = ss.get('copilot_task') or 'chat'
if want not in TASKS:
    want = 'chat'
if ss.get('_task_seen') != want or 'task_sel' not in ss or ss.task_sel not in TASKS.values():
    ss['task_sel'] = TASKS[want]
    if want in ('triase', 'alarm'):
        ss.copilot_review_mode = 'Analisis Perusahaan' if want == 'alarm' else 'Ringkas Temuan Portofolio'
pick = st.segmented_control('Tugas', ['Tanya Copilot', 'Siapkan Bahan Kunjungan', 'Tinjau Temuan', 'Susun Rencana'], key='task_sel')
if pick == 'Tinjau Temuan':
    review = st.radio('Cakupan tinjauan', ['Ringkas Temuan Portofolio', 'Analisis Perusahaan'], horizontal=True, key='copilot_review_mode')
    task = 'alarm' if review == 'Analisis Perusahaan' else 'triase'
else:
    task = inv.get(pick or TASKS['chat'], 'chat')
ss.copilot_task = ss._task_seen = task


def show_trace(trace):
    with st.expander(f'Jejak agen · {len(trace)} langkah'):
        for t in trace:
            if len(t) == 2:
                st.markdown(f"`{t[0]}` → {ui.esc(t[1])}", unsafe_allow_html=True)
            else:
                st.markdown(f"`{t[0]}({json.dumps(t[1], ensure_ascii=False)})`")
                st.json(t[2], expanded=False)


def approve_plan(plan, week_start):
    """Simpan rencana yang disetujui (JSON + audit) dan masukkan ke Kalender kunjungan. Mengembalikan pesan hasil."""
    error = flow.plan_scope_error(plan, ss.rm, allowed)
    if error or not flow.plan_matches(plan, ss.rm, week_start):
        return {'ok': False, 'status': 'gagal', 'message': error or 'Minggu rencana telah berubah. Susun ulang sebelum menyetujui.'}
    rows = K.from_plan(plan, week_start)
    n_new, n_upd, rej = K.upsert(K.fit_free(rows, ss.rm), user['username'])
    success = n_new + n_upd
    status = 'disetujui' if not rej and success else 'sebagian berhasil' if success else 'gagal'
    message = f'{n_new} jadwal baru, {n_upd} diperbarui di Kalender kunjungan'
    if rej:
        message += '. Dilewati: ' + '; '.join(f'{j} — {w}' for j, w in rej)
    elif not success:
        message = 'Tidak ada jadwal yang berhasil disimpan.'
    out = data.APP_OUT / 'plans'; out.mkdir(parents=True, exist_ok=True)
    f = out / f"rencana_{ss.rm}_{datetime.now():%Y%m%d_%H%M%S}.json"
    plan['status'] = status
    plan['hasil_kalender'] = {'baru': n_new, 'diperbarui': n_upd, 'ditolak': rej}
    f.write_text(json.dumps(plan, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
    data.audit('setujui_rencana', rm=ss.rm, berkas=f.name, minggu_mulai=str(week_start), pesan_disetujui=sum(bool(m.get('ok')) for m in plan['pesan']))
    return {'ok': bool(success), 'status': status, 'message': message}


def escalate(cid, alasan, bukti=None):
    """Eskalasi yang disetujui RM → tiket ke divisi Risiko Kredit / Remedial (halaman Koordinasi divisi) + log audit."""
    if cid not in allowed:
        raise ValueError('Perusahaan berada di luar cakupan akun.')
    bukti = bukti if bukti is not None else agent.investigate(store, cid)['evidence']
    rm = K.owner(store, ss.rm, cid) or ss.rm
    ids = T.escalate(rm_id=rm, company_id=cid, nama=store.co.name.get(cid, cid), alasan=alasan, bukti=bukti, user=auth.current()['username'])
    data.audit('teruskan_analis', rm=rm, company=cid, bukti=bukti, tiket=ids)
    return ids


# ================================================================== rencana minggu
if task == 'plan':
    if ss.rm == 'Semua RM':
        st.info('Pilih satu RM di sidebar untuk menyusun rencana kunjungan.'); st.stop()
    st.caption('Atur minggu dan kapasitas → susun usulan → pilih kegiatan → simpan ke kalender.')
    with st.container(border=True):
        st.markdown('### 1. Tentukan minggu rencana')
        context, period = st.columns([1, 2])
        context.markdown(f'**Portofolio {ui.esc(ss.rm)}**')
        context.caption('Rencana mencakup portofolio RM dan prospect dalam jaringan yang dapat diakses.')
        nxt = ss.get('plan_week_start') or date.today() + timedelta(days=7 - date.today().weekday())
        week_start = period.date_input('Minggu dimulai', nxt, format='DD/MM/YYYY', key='copilot_plan_week',
                                      help='Tanggal pilihan disesuaikan ke Senin pada minggu yang sama.')
        week_start = week_start - timedelta(days=week_start.weekday())
        period.caption(f'Senin {week_start:%d/%m/%Y} sampai Jumat {week_start + timedelta(days=4):%d/%m/%Y}')
        week = f'minggu {week_start:%d/%m/%Y}'
    a, b = st.columns([1.25, 1], gap='large')
    with a, st.container(border=True):
        st.markdown('### 2. Atur kapasitas kegiatan')
        st.caption('Pilih hari, kanal, dan jumlah kegiatan yang sanggup Anda lakukan. Tambahkan baris untuk hari lain.')
        days = st.data_editor(pd.DataFrame([('Selasa', 'Kunjungan', 3), ('Rabu', 'Telepon', 2), ('Kamis', 'Kunjungan', 2)], columns=['hari', 'kanal', 'slot']),
                              num_rows='dynamic', hide_index=True, use_container_width=True, key='days_ed',
                              column_config={'hari': st.column_config.SelectboxColumn('Hari', options=['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat']),
                                             'kanal': st.column_config.SelectboxColumn('Kanal', options=['Kunjungan', 'Telepon']),
                                             'slot': st.column_config.NumberColumn('Jumlah kegiatan', min_value=1, max_value=4, step=1)})
        capacity = int(pd.to_numeric(days.slot, errors='coerce').fillna(0).sum())
        st.caption(f'Kapasitas yang diminta: {capacity} kegiatan. Usulan dapat lebih sedikit sesuai slot dan perusahaan yang tersedia.')
        generate = st.button('Susun rencana', type='primary', use_container_width=True)
    with b, st.container(border=True):
        wk = K.active(ss.rm) if ss.rm != 'Semua RM' else K.active('Semua RM').iloc[0:0]
        wk = wk[(wk._m.dt.date >= week_start) & (wk._m.dt.date < week_start + timedelta(days=5))].sort_values('_m')
        st.markdown('### Agenda yang sudah ada')
        st.caption(f'{len(wk)} agenda pada minggu terpilih')
        if wk.empty:
            st.caption('Belum ada agenda. Copilot akan mengusulkan kegiatan sesuai kapasitas Anda.')
        for r in wk.head(8).itertuples():
            st.markdown(f"- {state.when(r.mulai)} · {ui.esc(r.judul)} <span class='egi-muted'>{r.kanal} · {r.sumber}</span>", unsafe_allow_html=True)
        if len(wk) > 8:
            st.caption(f'+{len(wk) - 8} agenda lainnya di Kalender kunjungan.')
        st.caption('Agenda yang sudah ada tetap dipertahankan. Copilot mencari slot kosong untuk kegiatan baru.')
    if generate:
        ss.plan_to_cal = None
        dd = [(r.hari, r.kanal, int(r.slot)) for r in days.dropna().itertuples()]
        with st.spinner('Copilot memeriksa portofolio, alarm, wilayah, dan jaringan…'):
            plan = agent.plan_week(store, ss.rm, (), dd or None, week, exclude=K.scheduled_ids(ss.rm))
            agent.finalize_plan(store, plan, week_start, ss.rm)
            ss.agent_result = ('plan', plan)
        data.audit('susun_rencana', rm=ss.rm, minggu_mulai=str(week_start))
    res = ss.agent_result
    if res and res[0] == 'plan' and not flow.plan_matches(res[1], ss.rm, week_start):
        st.info('RM atau minggu rencana telah berubah. Klik Susun rencana untuk membuat usulan yang sesuai.')
    if res and res[0] == 'plan' and flow.plan_matches(res[1], ss.rm, week_start):
        plan = res[1]
        plan.setdefault('_ui_id', uuid.uuid4().hex[:10])
        selections = set()
        st.markdown('### 3. Tinjau dan pilih kegiatan')
        st.caption('Centang kegiatan yang ingin dimasukkan ke kalender. Buka profil perusahaan bila perlu sebelum memilih.')
        k = st.columns(4)
        for col, (l, v, sub) in zip(k, plan['kpi']):
            ui.kpi(col, l, v, sub)
        st.write('')
        with st.expander('Ringkasan dan alasan penyusunan'):
            ui.ai_box('Ringkasan rencana', plan['ringkasan'], 'Portofolio, temuan, peluang, dan ketersediaan agenda')
            show_trace(plan['jejak'])
        for di, d in enumerate(plan['hari']):
            with st.container(border=True):
                channel = d.get('kanal', 'Kunjungan')
                day_date = week_start + timedelta(days=planner.HARI.index(d['hari']))
                st.markdown(f"#### {d['hari']} · {day_date.day} {state.BULAN[day_date.month - 1]}")
                st.markdown(ui.badge(channel, '#EEF2F9' if channel == 'Telepon' else '#FDEBDD',
                                     ui.NAVY2 if channel == 'Telepon' else '#9A3412')
                            + f" <span class='egi-muted'>{len(d['item'])} usulan · {ui.esc(d['tema'])}</span>", unsafe_allow_html=True)
                if not d['item']:
                    st.caption('Belum ada usulan untuk hari ini. Coba ubah kapasitas atau minggu rencana.')
                for it in d['item']:
                    checkbox, x1, x2, x3 = st.columns([0.3, 0.6, 4, 1.2], vertical_alignment='center')
                    if checkbox.checkbox('Pilih kegiatan', value=True, key=f'plan_item_{plan["_ui_id"]}_{di}_{it["id"]}', label_visibility='collapsed'):
                        selections.add((di, it['id']))
                    x1.markdown(f"**{it['jam']}**")
                    x2.markdown(f"**{ui.esc(it['nama'])}** <span class='egi-muted'>{it['id']} · {ui.esc(it['info'])} · peluang {it['peluang']}</span><br>{ui.esc(it['tujuan'])}"
                                f"<br><span class='egi-muted'>Siapkan: {ui.esc(it['siapkan'])}</span>", unsafe_allow_html=True)
                    if x3.button('Profil', key=f"pl_{di}_{it['id']}"):
                        state.focus_company(it['id'])

        # -------------------------------------------------------------- rute perjalanan per hari
        visit = [d for d in plan['hari'] if d.get('kanal', 'Kunjungan') == 'Kunjungan' and d['item']]
        if visit:
            with st.expander('Opsional: lihat dan optimalkan rute kunjungan'):
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
            with st.expander('Opsional: siapkan draf pesan'):
                st.caption('Draf dapat diedit dan disertakan dalam PDF. Pesan tidak dikirim saat menyimpan rencana.')
                st.markdown('#### Draf pesan (centang yang disetujui)')
                for i, m in enumerate(plan['pesan']):
                    c1, c2 = st.columns([0.3, 5])
                    m['ok'] = c1.checkbox('ok', key=f"msg_ok_{i}_{m['ke']}", label_visibility='collapsed')
                    m['isi'] = c2.text_area(f"Ke {m['ke']} · {m['kanal']}", m['isi'], key=f"msg_{i}_{m['ke']}", height=90)
        chosen_plan = flow.selected_plan(plan, selections)
        agent.finalize_plan(store, chosen_plan, week_start, ss.rm)
        st.markdown('### 4. Simpan kegiatan terpilih')
        st.caption(f'{len(selections)} kegiatan dipilih. Jadwal yang sudah ada tetap dipertahankan; hanya kegiatan terpilih yang ditambahkan atau diperbarui.')
        with st.expander('Tinjau jadwal yang akan disimpan', expanded=True):
            previous_times = {(day['hari'], item['id']): item['jam'] for day in plan['hari'] for item in day['item']}
            preview = [{'Hari': day['hari'], 'Jam': item['jam'], 'Perusahaan': item['nama'], 'Kanal': day.get('kanal', 'Kunjungan'), 'Tujuan': item['tujuan'],
                        'Perubahan jam': f"{previous_times[(day['hari'], item['id'])]} → {item['jam']}" if previous_times[(day['hari'], item['id'])] != item['jam'] else 'Tidak berubah'}
                       for day in chosen_plan['hari'] for item in day['item']]
            st.dataframe(pd.DataFrame(preview), hide_index=True, use_container_width=True)
        c1, c2 = st.columns(2)
        if c1.button('Setujui rencana', type='primary', use_container_width=True, disabled=not selections):
            result = approve_plan(chosen_plan, week_start)
            ss.plan_to_cal = result['message']
            (st.success if result['status'] == 'disetujui' else st.warning if result['ok'] else st.error)(result['message'])
        buf = R.weekly_plan_pdf({**chosen_plan, 'pesan': [m for m in plan['pesan'] if m.get('ok')]})
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
    if ss.focus_company and ss.focus_company not in opts and ss.focus_company in allowed:
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
            ids = escalate(cid, f"{r['verdict']}. {r['route']}", r['evidence'])
            st.success('Tiket dibuat untuk divisi Risiko Kredit / Remedial (Koordinasi divisi).' if ids else 'Nasabah ini sudah punya tiket eskalasi yang masih terbuka.')
        if c2.button('📅 Jadwalkan kunjungan retensi', use_container_width=True):
            state.schedule_visit(store, cid, f"Retensi: {r['verdict']}. {r['route']}", 'Copilot · investigasi alarm')
        if c3.button('Buka profil', use_container_width=True):
            state.focus_company(cid)
        st.caption('Aturan: ≥ 2 poin distress (telat bayar, outflow > inflow, pembeli hilang, alarm distress, kolektibilitas/tunggakan/watchlist) → analis; '
                   '≥ 2 poin retensi (porsi wallet turun, inflow tumbuh, bayar tepat waktu, mitra BNI berhenti) dengan minimal satu bukti perpindahan → kunjungan RM. '
                   'Copilot tidak memutuskan kredit.')

# ================================================================== triase semua alarm
elif task == 'triase':
    if ss.rm == 'Semua RM':
        st.info('Pilih satu RM di sidebar untuk menjalankan triase.'); st.stop()
    a, b = st.columns([1, 3])
    months = a.selectbox('Jendela alarm', [1, 3, 6], index=1, format_func=lambda m: f'{m} bulan terakhir')
    b.caption('Copilot menyelidiki setiap nasabah beralarm (arus kas, fasilitas kredit, transaksi mitra, jaringan, riwayat kunjungan), '
              'mengelompokkannya, lalu mengusulkan satu tindakan per nasabah. Nasabah yang sudah terjadwal atau sudah dieskalasi dilewati.')
    if b.button('Jalankan triase', type='primary'):
        with st.spinner('Copilot menyelidiki semua nasabah beralarm…'):
            ss.agent_result = ('triase', agent.triage(store, ss.rm, months))
        data.audit('triase', rm=ss.rm, bulan=months, hasil=ss.agent_result[1]['jumlah'])
    res = ss.agent_result
    if res and res[0] == 'triase' and res[1]['rm'] == ss.rm:
        tr = res[1]
        k = st.columns(4)
        for col, (g, (lbl, _)) in zip(k, agent.TRIASE.items()):
            ui.kpi(col, lbl, str(tr['jumlah'][g]), 'nasabah', color=ui.ORANGE if g == 'distress' else ui.INK)
        st.write('')
        ui.ai_box('Ringkasan triase', tr['ringkasan'], 'alur agen: alarm → investigasi × kredit × transaksi mitra → kalender & tiket')
        show_trace(tr['jejak'])
        badge = {'usul': ('menunggu persetujuan', '#FBEFD6', '#7A4A00'), 'disetujui': ('disetujui', '#DDF1E4', '#17613F'), 'gagal': ('gagal', '#FADFDB', '#9A2416'),
                 'sudah terjadwal': ('sudah terjadwal', '#EEF0F3', '#374151'), 'sudah dieskalasi': ('sudah dieskalasi', '#EEF0F3', '#374151'), 'pantau': ('pantau', '#EEF0F3', '#374151')}
        for g, (lbl, act) in agent.TRIASE.items():
            rows = [r for r in tr['baris'] if r['kelompok'] == g]
            if not rows:
                continue
            st.markdown(f"#### {lbl} · {len(rows)} nasabah <span class='egi-muted'>→ {act}</span>", unsafe_allow_html=True)
            for r in rows:
                with st.container(border=True):
                    c0, c1, c2 = st.columns([0.35, 5, 1.1])
                    if r['status'] == 'usul':
                        c0.checkbox('pilih', value=True, key=f"tr_ok_{r['id']}", label_visibility='collapsed')
                    t, bg, fg = badge.get(r['status'], (r['status'], '#EEF0F3', '#374151'))
                    c1.markdown(f"**{ui.esc(r['nama'])}** <span class='egi-muted'>{r['id']} · {r['segmen']} · risiko {r['risiko']} · alarm {ui.esc(r['alarm'])}</span> "
                                + ui.badge(t, bg, fg) + f"<br>{ui.esc(r['detail'])}"
                                + ''.join(f"<br><span class='egi-muted'>• {ui.esc(e)}</span>" for e in r['bukti']), unsafe_allow_html=True)
                    if c2.button('Profil', key=f"tr_pf_{r['id']}", use_container_width=True):
                        state.focus_company(r['id'])
        pick = [r for r in tr['baris'] if r['status'] == 'usul' and ss.get(f"tr_ok_{r['id']}", True)]
        if pick and st.button(f'Setujui {len(pick)} tindakan terpilih', type='primary'):
            done = {'eskalasi': 0, 'rencana': 0}
            for r in pick:
                if r['aksi'] == 'eskalasi':
                    ok = bool(escalate(r['id'], r['detail'], r['bukti']))
                else:
                    ok = state.schedule_now(store, r['id'], r['detail'], 'Copilot · triase', rerun=False) is not None
                r['status'] = 'disetujui' if ok else 'gagal'
                done[r['aksi']] += ok
            data.audit('triase_setujui', rm=ss.rm, eskalasi=done['eskalasi'], jadwal=done['rencana'], gagal=sum(r['status'] == 'gagal' for r in pick))
            ss.triage_msg = f"{done['eskalasi']} tiket eskalasi ke divisi Risiko · {done['rencana']} jadwal masuk Kalender kunjungan"
            st.rerun()
        if ss.get('triage_msg'):
            st.success(ss.triage_msg)
            x1, x2, _ = st.columns([1, 1, 2])
            if x1.button('Buka Kalender kunjungan', use_container_width=True):
                ss.triage_msg = None; state.go('kalender')
            if x2.button('Buka Koordinasi divisi', use_container_width=True):
                ss.triage_msg = None; state.go('koordinasi')
        st.caption('Eskalasi = tiket ke Risiko Kredit / Remedial dengan paket bukti. Kunjungan = slot kosong terdekat yang searah rute. Copilot tidak memutuskan kredit.')

# ================================================================== siapkan kunjungan
elif task == 'brief':
    mine = list(store.portfolio(ss.rm).sort_values('opportunity_score', ascending=False).index)
    if ss.focus_company and ss.focus_company not in mine and ss.focus_company in allowed:
        mine = [ss.focus_company] + mine
    mine = [cid for cid in mine if cid in allowed]
    if not mine:
        st.info('Belum ada perusahaan dalam cakupan akun untuk bahan kunjungan.'); st.stop()
    brief_company_key = f'copilot_brief_company_{ss.rm}'
    seen_key = f'copilot_brief_focus_seen_{ss.rm}'
    if ss.get(seen_key) != ss.focus_company:
        if ss.focus_company in mine:
            ss[brief_company_key] = ss.focus_company
        ss[seen_key] = ss.focus_company
    def update_brief_focus():
        ss.focus_company = ss[brief_company_key]
        ss[seen_key] = ss.focus_company
    cid = st.selectbox('Perusahaan', mine, index=mine.index(ss.focus_company) if ss.focus_company in mine else 0,
                       format_func=lambda c: f"{store.co.name[c]} · {c}", key=brief_company_key, on_change=update_brief_focus)
    fp = R.fact_pack(store, cid)
    narr, mode = (ss.narr[cid][0], ss.narr[cid][1]) if cid in ss.get('narr', {}) else (llm.template_company(fp), 'template')
    row = agent.candidates(store, ss.rm).reindex([cid]).iloc[0].to_dict() if cid in store.portfolio(ss.rm).index else {}
    tujuan, peluang = agent._purpose(store, cid, row) if row else ('Prospect: perkenalan dan pemetaan kebutuhan.', '—')
    a, b = st.columns([1.85, 1])
    with a:
        ui.ai_box('Kondisi Nasabah', narr['ringkasan'], f'Data per {data.SNAPSHOT:%d/%m/%Y}')
        with st.container(border=True):
            st.markdown('#### Kontak Terakhir')
            if fp['kunjungan']:
                last = fp['kunjungan'][-1]
                st.caption(f"{last['tgl']} · {last['kanal']} · {T.HASIL_ID.get(last['respons'], last['respons'])}")
                st.write(last['catatan'])
            else:
                st.caption('Belum ada kontak tercatat; mulai dengan perkenalan dan pemetaan kebutuhan.')
        st.markdown('#### Pertanyaan Pembuka')
        for q in narr['pertanyaan']:
            st.markdown(f'- {q}')
        st.markdown('#### Hal yang Perlu Dikonfirmasi')
        if fp['anomali']['jenis_3bln']:
            st.write(f"Konfirmasi penyebab temuan: {', '.join(fp['anomali']['jenis_3bln'])}.")
        else:
            st.caption('Konfirmasi kebutuhan bisnis, PIC pengambil keputusan, dan langkah berikutnya.')
        if fp['risiko']['kelas'] == 'High':
            st.warning('Risiko High: penawaran kredit ditunda. Koordinasikan kelayakan dengan analis.')
    with b:
        ui.ai_box('Arah Pembicaraan', tujuan)
        st.markdown('#### Produk yang Boleh Ditawarkan')
        products = fp.get('produk') or []
        names = sim.catalog().product_name
        eligible = [p for p in products if not p['ditunda']]
        for p in eligible[:3]:
            with st.container(border=True):
                st.markdown(f"**{names.get(p['produk'], p['produk'])}**")
                st.caption(p['produk'])
                st.metric('Estimasi konversi', ui.fmt(p['peluang'], 1, pct=True), help='Estimasi model untuk penawaran produk ini, bukan kepastian konversi.')
        if not eligible:
            st.caption('Belum ada rekomendasi produk yang boleh ditawarkan. Gali kebutuhan nasabah terlebih dahulu.')
        held = [p for p in products if p['ditunda']]
        if held:
            with st.expander('Produk ditunda — bukan bahan penawaran'):
                for p in held:
                    st.write(f"{names.get(p['produk'], p['produk'])}: ditunda karena risiko.")
        draft_key = f'copilot_brief_draft_{ss.rm}_{cid}'
        if st.button('Draf pesan janji temu'):
            ss[draft_key] = llm.draft_message('janji', {'nama': fp['nama'], 'rm': ss.rm, 'waktu': 'minggu ini', 'topik': tujuan[:120]})
        if ss.get(draft_key):
            wa, m = ss[draft_key]
            edited = st.text_area('Draf pesan — edit sebelum dikirim', wa, height=130, key=f'{draft_key}_text')
            with st.expander('Salin draf pesan'):
                st.code(edited, language=None)
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

    def execute_action(a, msg_i):
        cid = a['company_id']
        if a.get('_rm', ss.rm) != ss.rm:
            raise ValueError('Usulan berasal dari konteks RM yang berbeda.')
        if a['tipe'] == 'rencana_minggu':
            result = approve_plan(a['plan'], date.fromisoformat(a['plan']['minggu_mulai']))
            ss.plan_to_cal = result['message']
            a['status'] = result['status']; a['hasil'] = result['message']
            return
        if cid not in allowed:
            raise ValueError('Perusahaan berada di luar cakupan akun.')
        if a['tipe'] == 'eskalasi':
            ids = escalate(cid, a.get('alasan', ''), a.get('bukti'))
            a['status'] = 'disetujui'; a['hasil'] = 'tiket dibuat untuk divisi Risiko' if ids else 'sudah ada tiket eskalasi terbuka'
            return
        if a['tipe'] == 'rencana':
            status, row = K.schedule(store, ss.rm, cid, user['username'], a.get('catatan', ''), 'Copilot · chat',
                                     (a.get('hari'), a.get('jam')) if a.get('hari') else None)
            if status == 'gagal':
                raise ValueError(row)
            a['hasil'] = ('Sudah terjadwal' if status == 'sudah' else 'Jadwal tersimpan') + f": {state.when(row['mulai'])}"
        elif a['tipe'] == 'kunjungan':
            c = store.cox.loc[cid]
            owner, _ = K.holder(K.load(), cid)
            action_rm = owner or K.owner(store, ss.rm, cid)
            if not action_rm or not auth.can_edit(action_rm):
                raise ValueError('Pilih RM pemilik yang sesuai sebelum mencatat kontak perusahaan ini.')
            T.record_contact(store, {'action_id': f"APP-{pd.Timestamp.now():%Y%m%d%H%M%S}", 'track': 'Deepening' if c.is_client else 'Acquisition', 'party_id': cid,
                                'product_id': a.get('produk', ''), 'rm_id': action_rm, 'contact_date': pd.Timestamp.now(tz='Asia/Bangkok').date().isoformat(), 'channel': a.get('kanal', 'Kunjungan'),
                                'tier_at_contact': '', 'response': a['respons'], 'converted': int(a['respons'] == 'Converted'), 'deal_value_idr_mn': 0.0, 'rm_rating': '',
                                'feedback_note': f"{a.get('catatan', '')} | sumber: Copilot"}, user['username'])
        elif a['tipe'] == 'pesan':
            a['isi'] = ss.get(f"act_txt_{msg_i}_{a['id']}", a['isi'])
        data.audit(f"copilot_{a['tipe']}", rm=ss.rm, company=cid, **{k: v for k, v in a.items() if k not in ('id', 'tipe', 'company_id', 'status')})
        a['status'] = 'disetujui'

    def run_action(a, msg_i):
        if a['status'] != 'menunggu':
            return
        try:
            execute_action(a, msg_i)
        except Exception as error:
            a['status'] = 'gagal'
            a['hasil'] = str(error)
            data.audit('copilot_aksi_gagal', rm=ss.rm, company=a.get('company_id'), tipe=a['tipe'], alasan=str(error))

    def show_plan(a, msg_i):
        p = a['plan']
        with st.container(border=True):
            st.markdown(f"**{ui.esc(a['nama'])}** <span class='egi-muted'>mulai Senin {p['minggu_mulai']} · "
                        + ' · '.join(f'{l} {v}' for l, v, _ in p['kpi']) + '</span>', unsafe_allow_html=True)
            for d in p['hari']:
                km = p.get('jarak_km', {}).get(d['hari'])
                st.markdown(f"**{d['hari']}** · {d['kanal']} · {ui.esc(d['tema'])}" + (f" <span class='egi-muted'>±{km:.1f} km</span>" if km else ''), unsafe_allow_html=True)
                for it in d['item']:
                    st.markdown(f"<span class='egi-muted'>{it['jam']}</span> {ui.esc(it['nama'])} <span class='egi-muted'>{it['id']} · {ui.esc(it['tujuan'][:110])}</span>",
                                unsafe_allow_html=True)
            c1, c2, c3 = st.columns([1.2, 1.2, 1])
            if a['status'] == 'menunggu':
                if c1.button('Setujui rencana', key=f"okp_{msg_i}_{a['id']}", type='primary', use_container_width=True):
                    run_action(a, msg_i); st.rerun()
                if c3.button('Tolak', key=f"nop_{msg_i}_{a['id']}", use_container_width=True):
                    a['status'] = 'ditolak'; data.audit('copilot_tolak', rm=ss.rm, tipe='rencana_minggu'); st.rerun()
            else:
                c1.markdown({'disetujui': '✅ disetujui', 'ditolak': '✖ ditolak', 'diganti': '↻ diganti revisi berikutnya'}.get(a['status'], a['status']))
                if a.get('hasil'):
                    st.caption(a['hasil'])
            if c2.button('Buka rute & draf pesan', key=f"opp_{msg_i}_{a['id']}", use_container_width=True,
                         help='Buka rencana ini di tab Rencana minggu: peta rute, optimasi urutan, draf pesan, PDF.'):
                if not flow.plan_matches(p, ss.rm):
                    st.error('Rencana ini tidak sesuai konteks RM aktif.')
                else:
                    ss.agent_result = ('plan', p); ss.plan_week_start = date.fromisoformat(p['minggu_mulai'])
                    ss.copilot_plan_week = ss.plan_week_start; ss.copilot_task = 'plan'; st.rerun()

    def show_actions(m, msg_i):
        if not m.get('usulan'):
            return
        wait = [a for a in m['usulan'] if a['status'] == 'menunggu' and a['tipe'] != 'rencana_minggu']
        h1, h2 = st.columns([3, 1])
        h1.markdown(f"**Usulan tindakan** · {sum(a['status'] == 'menunggu' for a in m['usulan'])} menunggu persetujuan")
        if len(wait) >= 2 and h2.button(f'Setujui semua ({len(wait)})', key=f'okall_{msg_i}', type='primary', use_container_width=True):
            for a in wait:
                run_action(a, msg_i)
            data.audit('copilot_setujui_semua', rm=ss.rm, jumlah=len(wait)); st.rerun()
        judul = {'rencana': 'Jadwalkan di Kalender kunjungan', 'kunjungan': 'Catat hasil kontak', 'eskalasi': 'Teruskan ke divisi Risiko', 'pesan': 'Draf pesan'}
        for a in m['usulan']:
            if a['tipe'] == 'rencana_minggu':
                show_plan(a, msg_i); continue
            with st.container(border=True):
                c1, c2, c3 = st.columns([5, 1, 1])
                detail = {'rencana': ' · '.join(x for x in [(f"{a['hari']} {a.get('jam') or ''}".strip() if a.get('hari') else 'slot kosong terdekat'), a.get('catatan')] if x), 'kunjungan': f"{a.get('respons')} · {a.get('kanal')} · {a.get('produk') or '—'} · {a.get('catatan')}",
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
                    if a.get('hasil'):
                        c1.caption(a['hasil'])
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

    if cfg.get('killed'):
        st.markdown("<div class='egi-warn'>🛑 Agen LLM dimatikan (kill switch). Copilot menjawab dengan template ringkasan portofolio; fitur lain tetap berjalan.</div>", unsafe_allow_html=True)
    elif not cfg['enabled']:
        st.info('Pertanyaan bebas belum tersedia. Ringkasan portofolio dan tugas terstruktur tetap dapat digunakan; hubungi administrator untuk mengaktifkan layanan AI.')
    fokus = f" · fokus {store.co.name.get(ss.focus_company, '')} ({ss.focus_company})" if ss.focus_company else ''
    st.caption(f"Konteks percakapan: {ss.rm}{fokus} · usulan tindakan menunggu persetujuan Anda")
    with st.expander('🛡 Guardrail aktif'):
        st.markdown('**Input** · prompt injection & jailbreak diblokir · kata kasar disamarkan · pertanyaan di luar cakupan diarahkan · PII (NIK, NPWP, rekening, HP, email) '
                    'disamarkan sebelum dikirim ke AI\n\n**Proses** · agen hanya memakai alat yang terdaftar, hanya untuk nasabah RM sendiri, maks 14 langkah · '
                    'setiap tindakan menunggu persetujuan Anda\n\n**Output** · angka dicek terhadap data · tawaran kredit ke nasabah risiko High dihapus · PII & kata kasar disamarkan\n\n'
                    '**Audit** · pertanyaan (tersamar), jawaban, alat, versi model, dan kejadian guardrail dicatat di log audit')
        sts = guard.stats(ss.rm)
        if sts:
            gc = st.columns(min(len(sts), 6))
            for col, (k, v) in zip(gc, sorted(sts.items(), key=lambda x: -x[1])):
                ui.kpi(col, guard.LABELS.get(k, k), str(v), 'kejadian')
        else:
            st.caption('Belum ada kejadian guardrail tercatat.')
        if auth.current() and auth.current()['role'] == 'supervisor':
            off = st.toggle('Kill switch: matikan agen LLM untuk semua pengguna', value=bool(guard.settings().get('llm_off')))
            if off != bool(guard.settings().get('llm_off')):
                guard.set_llm_off(off, auth.current()['username']); st.rerun()
    q = ss.pop('pending_q', None)
    if not ss.chat:
        ex = ['Periksa semua alarm saya 3 bulan terakhir dan siapkan tindakannya', 'Susun rencana minggu depan saya, Rabu saya rapat seharian, fokus retensi',
              'Siapa 5 nasabah S2 saya yang paling layak dikunjungi minggu ini dan kenapa?', 'Prospect mana yang bisa saya dekati lewat nasabah sendiri, dan siapa perantaranya?']
        cols = st.columns(2)
        for i, e in enumerate(ex):
            if cols[i % 2].button(e, use_container_width=True, key=f'ex_{i}'):
                q = e
    for i, m in enumerate(ss.chat):
        with st.chat_message(m['role']):
            gd = m.get('guard') or {}
            if gd.get('status') == 'diblokir':
                bg, fg = ('#EEF0F3', '#374151') if gd['kategori'] == 'scope' else ('#FADFDB', '#9A2416')
                st.markdown(f"<div class='egi-card' style='background:{bg};color:{fg}'><b>🛡 {ui.esc(gd['judul'])}</b><br>{ui.esc(m['text'])}</div>", unsafe_allow_html=True)
            else:
                st.markdown(m['text'])
            for n in gd.get('catatan', []):
                st.caption(f"🛡 {n[0].upper() + n[1:]}.")
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
                res = agent.chat(store, ss.rm, q, history=history, focus=ss.focus_company, plan_ctx=ss.get('week_plan_ctx'),
                                 on_step=lambda n, a, o: st.markdown(step_line(n, a, o), unsafe_allow_html=True))
                box.update(label=f"Selesai · {len(res['jejak'])} langkah · {res['mode']}", state='complete', expanded=False)
        new_plans = [a for a in res['usulan'] if a['tipe'] == 'rencana_minggu']
        for proposal in res['usulan']:
            proposal['_rm'] = ss.rm
        if new_plans:                     # rencana terbaru jadi bahan revisi berikutnya; versi lama yang belum disetujui ditandai diganti
            for a in [a for m in ss.chat for a in m.get('usulan', [])] + new_plans[:-1]:
                if a['tipe'] == 'rencana_minggu' and a['status'] == 'menunggu':
                    a['status'] = 'diganti'
            ss.week_plan_ctx = {'plan': new_plans[-1]['plan']}
        ss.chat[-1]['text'] = res.get('pertanyaan_aman') or q          # yang tersimpan & dikirim ulang sebagai riwayat = versi tersamar
        ss.chat.append({'role': 'assistant', 'text': res['jawaban'] or 'Tidak ada jawaban.', 'trace': res['jejak'], 'usulan': res['usulan'],
                        'lanjut': res['lanjut'], 'cek': res['cek'], 'guard': res.get('guard')})
        data.audit('chat', rm=ss.rm, pertanyaan=res.get('pertanyaan_aman') or q, jawaban=res['jawaban'], alat=[t[0] for t in res['jejak']],
                   usulan=[{'tipe': a['tipe'], 'company': a['company_id']} for a in res['usulan']], mode=res['mode'],
                   model_llm=cfg['model'] if res['mode'] == 'LLM' else None, **guard.versions(),
                   cek_angka=({'jumlah': res['cek'][0], 'tak_berdasar': list(dict.fromkeys(res['cek'][1]))} if res['cek'] else None), guardrail=res.get('guard'))
        st.rerun()
    if ss.chat and st.button('Mulai percakapan baru'):
        ss.chat = []; ss.week_plan_ctx = None; st.rerun()
