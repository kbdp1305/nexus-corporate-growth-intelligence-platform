"""Konteks bersama antar-halaman: RM aktif, fokus (perusahaan / kecamatan), rencana minggu."""
from __future__ import annotations

import streamlit as st

from . import auth, llm
from .ui import esc

PAGE = {'overview': 'views/1_overview.py', 'prioritas': 'views/2_prioritas.py', 'profil': 'views/3_profil.py', 'wilayah': 'views/4_wilayah.py',
        'prospect': 'views/5_prospect.py', 'copilot': 'views/6_copilot.py', 'kinerja': 'views/7_kinerja.py', 'metodologi': 'views/8_metodologi.py',
        'kalender': 'views/9_kalender.py'}


def init(store):
    ss = st.session_state
    rms = sorted(store.co.rm_id.dropna().unique())
    ss.setdefault('rm', 'RM-017' if 'RM-017' in rms else rms[0])
    ss.setdefault('focus_company', None)
    ss.setdefault('focus_district', None)
    ss.setdefault('plan', [])               # [{'id','nama','jenis','catatan'}]
    ss.setdefault('chat', [])
    ss.setdefault('agent_result', None)
    q = st.query_params
    if 'company' in q and q['company'] in store.co.index:
        ss.focus_company = q['company']
    return rms


def go(page_key):
    st.switch_page(PAGE[page_key])


def focus_company(cid, open_profile=True):
    st.session_state.focus_company = cid
    st.query_params['company'] = cid
    if open_profile:
        go('profil')


def focus_district(d, open_page=None):
    st.session_state.focus_district = d
    if open_page:
        go(open_page)


def add_to_plan(store, cid, catatan=''):
    plan = st.session_state.plan
    if any(p['id'] == cid for p in plan):
        st.toast('Sudah ada di rencana minggu')
        return
    jenis = 'nasabah' if store.cox.is_client.get(cid, False) else 'prospect'
    plan.append({'id': cid, 'nama': store.co.name.get(cid, cid), 'jenis': jenis, 'catatan': catatan})
    st.toast(f"Ditambahkan ke rencana: {store.co.name.get(cid, cid)}")


def company_actions(store, cid, key, show_profile=True):
    """Tombol seragam untuk setiap perusahaan: profil · + rencana · Copilot."""
    cols = st.columns(3 if show_profile else 2)
    i = 0
    if show_profile:
        if cols[i].button('Lihat profil', key=f'p_{key}_{cid}', use_container_width=True):
            focus_company(cid)
        i += 1
    if cols[i].button('+ Rencana', key=f'r_{key}_{cid}', use_container_width=True):
        add_to_plan(store, cid)
    if cols[i + 1].button('Copilot', key=f'c_{key}_{cid}', use_container_width=True):
        st.session_state.focus_company = cid
        st.session_state.copilot_task = 'brief'
        go('copilot')


def sidebar(store, rms):
    ss = st.session_state
    with st.sidebar:
        st.markdown('<div style="display:flex;gap:10px;align-items:center;margin-bottom:8px"><div style="width:34px;height:34px;border-radius:8px;'
                    'background:#C2500A;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700">EG</div>'
                    '<div><strong>Growth Intelligence</strong><br><span style="font-size:12px">Ruang kerja RM</span></div></div>', unsafe_allow_html=True)
        n = lambda r: int((store.co.rm_id == r).sum())
        user = auth.current()
        if user['role'] == 'supervisor':
            opts = rms + ['Semua RM']
            ss.rm = st.selectbox('Lihat sebagai', opts, index=opts.index(ss.rm) if ss.rm in opts else len(rms), format_func=lambda r: f'{r} · {n(r)} nasabah' if r != 'Semua RM' else r)
        else:
            ss.rm = user['rm_id']
            st.markdown(f"**{esc(ss.rm)}** · {n(ss.rm)} nasabah")
        c1, c2 = st.columns(2)
        with c1.popover('Akun', use_container_width=True):
            st.caption(f"Masuk sebagai **{user['username']}** ({user['role']})")
            auth.change_password_form()
        if c2.button('Keluar', use_container_width=True):
            auth.logout()
        st.divider()
        st.markdown('**Fokus**')
        if ss.focus_company:
            c1, c2 = st.columns([5, 1])
            c1.markdown(f"{esc(store.co.name.get(ss.focus_company, ss.focus_company))}<br><span style='font-size:11px'>{ss.focus_company}</span>", unsafe_allow_html=True)
            if c2.button('×', key='clr_c', help='Lepas fokus perusahaan'):
                ss.focus_company = None; st.query_params.clear(); st.rerun()
        if ss.focus_district:
            c1, c2 = st.columns([5, 1])
            c1.markdown(f'Kecamatan {esc(ss.focus_district)}')
            if c2.button('×', key='clr_d', help='Lepas fokus kecamatan'):
                ss.focus_district = None; st.rerun()
        if not ss.focus_company and not ss.focus_district:
            st.caption('tidak ada')
        st.markdown(f"**Rencana minggu** · {len(ss.plan)}")
        for i, p in enumerate(ss.plan):
            c1, c2 = st.columns([5, 1])
            c1.markdown(f"<span style='font-size:13px'>{esc(p['nama'])}</span>" + (" <span style='color:#F6B48A;font-size:11px'>prospect</span>" if p['jenis'] == 'prospect' else ''), unsafe_allow_html=True)
            if c2.button('×', key=f'rm_plan_{i}'):
                ss.plan.pop(i); st.rerun()
        if ss.plan and st.button('Susun di Copilot', use_container_width=True):
            ss.copilot_task = 'plan'; go('copilot')
        st.divider()
        cfg = llm.config()
        st.caption(f"Copilot: {'LLM · ' + cfg['provider'] + ' · ' + cfg['model'] if cfg['enabled'] else 'mode template (tanpa LLM)'}")
        st.caption('Data per 30 Jun 2026 · data sintetis v8')
