import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from egi import agent, data, state, ui, viz

store = data.get_store(); ss = st.session_state
ui.page_header(f'{ss.rm} · aksi RM Jan–Jun 2026 (+ catatan dari dashboard)', 'Kinerja saya')
if ss.rm == 'Semua RM':
    st.info('Pilih satu RM di sidebar untuk melihat kinerja.'); st.stop()

L = store.log_all.copy()
L['bulan'] = L.contact_date.astype(str).str[:7]
L['converted'] = pd.to_numeric(L.converted, errors='coerce').fillna(0)
L['deal_value_idr_mn'] = pd.to_numeric(L.deal_value_idr_mn, errors='coerce').fillna(0)
me = L[L.rm_id == ss.rm]
per = L.groupby('rm_id').agg(aksi=('party_id', 'size'), konversi=('converted', 'mean'), deal=('deal_value_idr_mn', 'sum'))
med = per.median()

k = st.columns(4)
ui.kpi(k[0], 'Aksi', ui.fmt(len(me), 0), f"median RM {ui.fmt(med.aksi, 0)}")
ui.kpi(k[1], 'Tingkat konversi', ui.fmt(me.converted.mean() * 100, 0, pct=True) if len(me) else '—', f"median RM {ui.fmt(med.konversi * 100, 0)}%", color=ui.ORANGE)
ui.kpi(k[2], 'Nilai deal', f"Rp {ui.fmt(me.deal_value_idr_mn.sum() / 1000, 1)} M", f"median RM Rp {ui.fmt(med.deal / 1000, 1)} M")
rank = int((per.konversi > (me.converted.mean() if len(me) else 0)).sum()) + 1
ui.kpi(k[3], 'Peringkat konversi', f'{rank} / {len(per)}', 'di antara semua RM')
st.write('')

a, b = st.columns([1.4, 1])
with a:
    mm = me.groupby('bulan').agg(aksi=('party_id', 'size'), konv=('converted', 'sum')).reset_index()
    allm = L.groupby(['bulan', 'rm_id']).size().groupby('bulan').median()
    fig = go.Figure()
    fig.add_bar(x=mm.bulan, y=mm.aksi, name='aksi saya', marker_color=ui.NAVY2)
    fig.add_bar(x=mm.bulan, y=mm.konv, name='konversi saya', marker_color=ui.ORANGE)
    fig.add_scatter(x=allm.index, y=allm.values, name='median aksi RM', mode='lines+markers', line=dict(color='#9AA0A9', dash='dot'))
    st.plotly_chart(viz._layout(fig, 300, legend=True, legend_orientation='h', title='Aksi & konversi per bulan', barmode='group'), use_container_width=True)
with b:
    ch = me.groupby('channel').agg(aksi=('party_id', 'size'), konversi=('converted', 'mean'))
    chall = L.groupby('channel').converted.mean().rename('konversi_semua_RM')
    ch = ch.join(chall).reset_index()
    for c in ('konversi', 'konversi_semua_RM'): ch[c] *= 100
    st.markdown('**Per kanal**')
    st.dataframe(ch, hide_index=True, use_container_width=True,
                 column_config={'channel': 'Kanal', 'aksi': 'Aksi', 'konversi': st.column_config.NumberColumn('Konversi saya', format='%.0f%%'),
                                'konversi_semua_RM': st.column_config.NumberColumn('Semua RM', format='%.0f%%')})
    seg = me.join(store.cox.segment, on='party_id').groupby('segment').converted.agg(['size', 'mean']).reset_index()
    seg['mean'] *= 100
    st.markdown('**Per segmen**')
    st.dataframe(seg, hide_index=True, use_container_width=True, column_config={'segment': 'Segmen', 'size': 'Aksi', 'mean': st.column_config.NumberColumn('Konversi', format='%.0f%%')})

c1, c2 = st.columns(2)
with c1:
    st.subheader('Pipeline: tertarik, belum konversi')
    last = me.sort_values('contact_date').groupby(['party_id', 'product_id']).tail(1)
    pipe = last[last.response == 'Interested'].join(store.co[['name']], on='party_id').sort_values('contact_date', ascending=False)
    for r in pipe.head(8).itertuples():
        y1, y2 = st.columns([4, 1])
        y1.markdown(f"**{ui.esc(r.name if isinstance(r.name, str) else r.party_id)}** <span class='egi-muted'>{r.party_id} · {r.product_id} · {r.contact_date} · {ui.esc(r.feedback_note)}</span>", unsafe_allow_html=True)
        if r.party_id in store.co.index and y2.button('Profil', key=f'kp_{r.party_id}_{r.product_id}'):
            state.focus_company(r.party_id)
    if pipe.empty:
        st.caption('Tidak ada.')
with c2:
    st.subheader('Prioritas yang belum disentuh')
    pf = agent.candidates(store, ss.rm)
    un = pf[(pf.opportunity_score >= .75) & ~pf.contacted].head(8) if not pf.empty else pf
    for cid, r in un.iterrows():
        y1, y2 = st.columns([4, 1])
        y1.markdown(f"**{ui.esc(r['name'])}** <span class='egi-muted'>{cid} · {r.segment} · skor {r.opportunity_score:.2f}</span>", unsafe_allow_html=True)
        if y2.button('📅 Jadwalkan', key=f'ku_{cid}'):
            state.schedule_visit(store, cid, 'Prioritas yang belum disentuh', 'Kinerja saya')
    if len(un) == 0:
        st.caption('Semua nasabah prioritas sudah dihubungi.')
st.caption('Konversi = aksi dengan respons Converted / semua aksi. Catatan dari dashboard ikut dihitung sejak disimpan.')
