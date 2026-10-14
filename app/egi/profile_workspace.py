"""Relationship context and action-oriented views for Profil 360°."""
import pandas as pd
import streamlit as st

from . import data, kalender as K, state, tindak, ui


def accessible_ids(store, user):
    if user['role'] == 'supervisor':
        return set(store.co.index)
    if user['role'] != 'rm':
        return set()
    mine = set(store.co.index[store.co.rm_id == user['rm_id']])
    links = store.act
    neighbors = set(links.loc[links.source_id.isin(mine), 'target_id']) | set(links.loc[links.target_id.isin(mine), 'source_id'])
    prospects = set(store.co.index[store.co.customer_type == 'Prospect'])
    claimed = K.for_rm(user['rm_id'])
    return mine | (neighbors & prospects) | (set(claimed.company_id) & prospects)


def context(store, cid, user):
    now = pd.Timestamp.now(tz='Asia/Bangkok').tz_localize(None)
    logs = store.log_all[store.log_all.party_id == cid].copy()
    logs['_time'] = pd.to_datetime(logs.contact_date, errors='coerce')
    logs['_order'] = range(len(logs))
    logs = logs.sort_values(['_time', '_order'], ascending=[False, False])
    calendar = K.load()
    calendar = calendar[calendar.company_id == cid].copy()
    calendar['_time'] = pd.to_datetime(calendar.mulai, errors='coerce')
    upcoming = calendar[(calendar.status == 'Terjadwal') & (calendar._time >= now)].sort_values('_time')
    rm = user['rm_id'] if user['role'] == 'rm' else 'Semua RM'
    activities = tindak.kegiatan_for(rm)
    activities = activities[activities.company_id == cid].copy()
    return logs, calendar, upcoming, activities


def product_cards(fp, catalog, key):
    products = fp.get('produk') or []
    if not products:
        st.info('Belum ada rekomendasi produk untuk perusahaan ini.')
        return
    for start in range(0, len(products), 2):
        cols = st.columns(2)
        for col, product in zip(cols, products[start:start + 2]):
            pid = product['produk']
            name = catalog.product_name.get(pid, pid)
            with col, st.container(border=True, height='stretch'):
                st.markdown(f"<div style='min-height:44px;font-weight:600'>{ui.esc(name)}</div>", unsafe_allow_html=True)
                st.caption(pid)
                held = product['ditunda']
                st.markdown(ui.badge('Ditunda karena risiko' if held else 'Boleh ditawarkan',
                                    '#FADFDB' if held else '#E4F1EA', '#9A2416' if held else '#17613F'), unsafe_allow_html=True)
                a, b = st.columns(2)
                a.metric('Peluang konversi', ui.fmt(product['peluang'], 0, pct=True))
                b.metric('Estimasi nilai bersih', f"Rp {ui.fmt(product['ev'], 1)} jt")
                detail = (f"Rentang estimasi Rp {ui.fmt(product['ev_lo'], 1)}–{ui.fmt(product['ev_hi'], 1)} jt · "
                          f"{ui.fmt(product['peer_pct'], 0)}% peer memiliki produk")
                st.markdown(f"<div class='egi-muted' style='min-height:44px;font-size:12px'>{ui.esc(detail)}</div>", unsafe_allow_html=True)
                if st.button('Siapkan penawaran', key=f'{key}_{pid}', disabled=held, use_container_width=True):
                    st.session_state.copilot_task = 'chat'
                    st.session_state.pending_q = f"Siapkan penawaran {name} ({pid}) untuk {fp['nama']} ({fp['id']}) sesuai kebutuhan dan kelayakan risikonya."
                    state.go('copilot')


def timeline(logs, calendar, activities, feedback):
    rows = []
    for r in logs.itertuples():
        rows.append({'waktu': pd.to_datetime(r.contact_date, errors='coerce'),
                     'jenis': 'Kontak', 'judul': f'{r.channel} · {r.response}',
                     'detail': f'{r.product_id} · {r.feedback_note}', 'status': r.response})
    for r in calendar.itertuples():
        rows.append({'waktu': pd.to_datetime(r.mulai, errors='coerce'), 'jenis': 'Agenda',
                     'judul': r.judul, 'detail': f'{r.kanal} · {r.catatan}', 'status': r.status})
    for r in feedback.itertuples():
        rows.append({'waktu': pd.to_datetime(r.tanggal, errors='coerce'), 'jenis': 'Feedback',
                     'judul': tindak.HASIL_ID.get(r.hasil, r.hasil), 'detail': r.catatan, 'status': r.hasil})
    for r in activities.itertuples():
        timestamp = r.selesai_pada if r.status == 'Selesai' and r.selesai_pada else r.tenggat
        rows.append({'waktu': pd.to_datetime(timestamp, errors='coerce'), 'jenis': 'Kegiatan',
                     'judul': r.judul, 'detail': f'{r.aksi} · PIC {r.pemilik}', 'status': r.status_tampil})
    return pd.DataFrame(rows, columns=['waktu', 'jenis', 'judul', 'detail', 'status']).dropna(subset=['waktu']).sort_values('waktu', ascending=False)


def render_timeline(rows):
    kind = st.segmented_control('Jenis interaksi', ['Semua', 'Kontak', 'Agenda', 'Feedback', 'Kegiatan'], default='Semua', key='profile_timeline_kind') or 'Semua'
    rows = rows if kind == 'Semua' else rows[rows.jenis == kind]
    if rows.empty:
        st.info('Belum ada riwayat untuk jenis interaksi ini.')
        return
    colors = {'Kontak': ('#E7EDF8', ui.NAVY2), 'Agenda': ('#FBEFD6', '#7A4E00'),
              'Feedback': ('#E4F1EA', '#17613F'), 'Kegiatan': ('#EDE9F6', '#4C3A86')}
    st.caption('Urutan terbaru terlebih dahulu; agenda dan tenggat mendatang ikut ditampilkan.')
    for r in rows.head(20).itertuples():
        with st.container(border=True):
            bg, fg = colors[r.jenis]
            st.markdown(ui.badge(r.jenis, bg, fg) + f" **{ui.esc(r.judul)}**", unsafe_allow_html=True)
            st.caption(f'{r.waktu:%d/%m/%Y %H:%M} · {r.status}')
            st.write(r.detail)
    if len(rows) > 20:
        with st.expander(f'Lihat seluruh {len(rows)} interaksi'):
            st.dataframe(rows, hide_index=True, use_container_width=True)
