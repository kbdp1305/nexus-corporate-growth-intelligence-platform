"""Company directory layout for the Profil 360 page."""
import pandas as pd
import streamlit as st

from . import auth, data, ui


CSS = """
<style>
.profile-hero {display:flex;align-items:center;justify-content:space-between;gap:24px;
  padding:26px 28px;background:linear-gradient(120deg,#0F1E3A,#244574);border-radius:18px;margin-bottom:24px;}
.profile-hero .eyebrow {color:#F6B48A;font-size:11px;font-weight:600;letter-spacing:1.6px;text-transform:uppercase;}
.profile-hero h1 {color:#fff !important;font-size:30px !important;line-height:1.25;margin:8px 0;padding:0;}
.profile-hero p {color:#CBD8EA;font-size:14px;margin:0;line-height:1.6;max-width:560px;}
.profile-total {padding-left:28px;border-left:1px solid #ffffff25;min-width:140px;}
.profile-total strong {display:block;color:#fff;font-size:34px;font-weight:600;line-height:1.2;}
.profile-total span {color:#CBD8EA;font-size:12px;}
.profile-results {display:flex;justify-content:space-between;align-items:center;gap:12px;padding:16px 0 8px;}
.profile-results strong {color:#0F1E3A;font-size:16px;}
.profile-results span {color:#66758B;font-size:12px;}
.profile-meta {font-size:12px;color:#6B7789;line-height:1.6;}
.profile-id {font-family:'IBM Plex Mono',monospace;font-size:11px;color:#7A879A;}
.profile-location {font-size:13px;font-weight:500;color:#30435E;line-height:1.5;}
.profile-city {font-size:12px;color:#7A879A;line-height:1.5;}
[class*="st-key-profile_row_"] {background:#fff;border:1px solid #E3E9F1 !important;
  border-radius:14px !important;padding:16px 18px !important;transition:border-color .18s,box-shadow .18s;}
[class*="st-key-profile_row_"]:hover {border-color:#B6C6DB !important;box-shadow:0 4px 16px #0F1E3A08;}
[class*="st-key-profile_row_"] [data-testid="stVerticalBlock"] {gap:5px;}
[class*="st-key-profile_row_"] [data-testid="stColumn"]:first-child button {padding:0 !important;min-height:24px !important;justify-content:flex-start !important;text-align:left !important;
  background:transparent !important;border:0 !important;box-shadow:none !important;color:#102C4D !important;}
[class*="st-key-profile_row_"] [data-testid="stColumn"]:first-child button [data-testid="stMarkdownContainer"] {width:100%;text-align:left !important;}
[class*="st-key-profile_row_"] [data-testid="stColumn"]:first-child button p {font-size:15px;font-weight:600;text-align:left !important;line-height:1.45;}
[class*="st-key-profile_row_"] [data-testid="stColumn"]:first-child button:hover {color:#C2500A !important;}
[class*="st-key-profile_row_"] [data-testid="stColumn"]:first-child button:focus-visible {outline:2px solid #C2500A;outline-offset:4px;}
[class*="st-key-profile_arrow_"] button {background:#F4F7FB !important;border-color:#E3E9F1 !important;
  border-radius:10px;min-width:36px;padding:6px !important;color:#284B73 !important;}
.profile-empty {text-align:center;padding:48px 20px;border:1px dashed #CED8E6;border-radius:14px;background:#fff;}
.profile-empty strong {display:block;color:#30435E;font-size:16px;margin-bottom:8px;}
.profile-empty span {color:#7A879A;font-size:13px;}
@media(max-width:700px) {
  .profile-hero {padding:22px;align-items:flex-start;flex-direction:column;gap:16px;}
  .profile-hero h1 {font-size:25px !important;}
  .profile-total {border-left:0;padding-left:0;}
  .profile-total strong {display:inline;font-size:24px;margin-right:8px;}
  .profile-results {align-items:flex-start;flex-direction:column;gap:4px;}
}
</style>
"""


def _open(company_id):
    st.session_state.focus_company = company_id
    st.query_params['company'] = company_id


def _change_page(delta):
    st.session_state.profile_list_page += delta


def render(store, mine_set, company_ids):
    ss = st.session_state
    user = auth.current()
    supervisor = user['role'] == 'supervisor'
    scopes = ['Portofolio RM', 'Seluruh bank'] if supervisor else ['Portofolio Saya', 'Prospect Jaringan']
    scope = st.segmented_control('Cakupan perusahaan', scopes, default=scopes[0], key='profile_scope') or scopes[0]
    if scope != 'Seluruh bank':
        company_ids = [cid for cid in company_ids if (cid not in mine_set if scope == 'Prospect Jaringan' else cid in mine_set)]
    scoped = store.cox.loc[company_ids]
    st.markdown(CSS, unsafe_allow_html=True)
    total = f'{len(company_ids):,}'.replace(',', '.')
    st.markdown(f'<div class="profile-hero"><div><div class="eyebrow">Direktori perusahaan</div>'
                '<h1>Profil 360° Perusahaan</h1><p>Kenali bisnis, telusuri peluang, dan siapkan langkah berikutnya. '
                'Pilih perusahaan untuk membuka profil lengkap.</p></div>'
                f'<div class="profile-total"><strong>{total}</strong><span>perusahaan terdaftar</span></div></div>',
                unsafe_allow_html=True)

    ss.setdefault('profile_search', ss.get('profile_list_search', ''))
    ss.setdefault('profile_industry', ss.get('profile_list_industry', 'Semua industri'))
    with st.container(border=True, key='profile_filters'):
        search_col, industry_col = st.columns([3, 1.4])
        search = search_col.text_input('Cari perusahaan', placeholder='Cari nama, ID, atau lokasi perusahaan…',
                                       key='profile_search', icon=':material/search:')
        industry = industry_col.selectbox('Industri', ['Semua industri'] + sorted(scoped.industry.dropna().unique()),
                                         key='profile_industry')
        if scoped.customer_type.eq('Prospect').all():
            f2, f3 = st.columns(2)
            segment = 'Semua'
        else:
            f1, f2, f3 = st.columns(3)
            segment = f1.selectbox('Segmen Nasabah', ['Semua'] + data.SEGS, key='profile_segment')
        risk = f2.selectbox('Risiko', ['Semua', 'Low', 'Medium', 'High'], key='profile_risk')
        alarm_only = f3.checkbox('Dengan temuan bulan data', key='profile_alarm_only')
    alarms = store.why_now(company_ids, months=1)
    alarm_ids = set(alarms.loc[alarms.ym == data.REF_MONTH, 'company_id'])
    ss.profile_list_search, ss.profile_list_industry = search, industry
    query = search.strip().casefold()
    filtered = [c for c in company_ids if (industry == 'Semua industri' or store.co.at[c, 'industry'] == industry)
                and (segment == 'Semua' or store.co.at[c, 'customer_type'] == 'Prospect' or store.cox.at[c, 'segment'] == segment)
                and (risk == 'Semua' or store.cox.at[c, 'pred_class'] == risk)
                and (not alarm_only or c in alarm_ids)
                and (not query or query in ' '.join(str(store.co.at[c, field])
                    for field in ['name', 'industry', 'district', 'city']).casefold() or query in str(c).casefold())]
    page_size = 20
    page_count = max(1, (len(filtered) + page_size - 1) // page_size)
    signature = (query, industry, ss.rm, scope, segment, risk, alarm_only)
    if ss.get('profile_list_signature') != signature:
        ss.profile_list_page = 1
        ss.profile_list_signature = signature
    ss.profile_list_page = min(max(ss.get('profile_list_page', ss.get('profile_page_number', 1)), 1), page_count)
    page = ss.profile_list_page
    start, end = (page - 1) * page_size, min(page * page_size, len(filtered))
    count = f'{len(filtered):,}'.replace(',', '.')
    st.markdown(f'<div class="profile-results"><strong>{count} perusahaan ditemukan</strong>'
                f'<span>{start + 1 if filtered else 0}–{end} dari {count} perusahaan</span></div>', unsafe_allow_html=True)

    if not filtered:
        st.markdown('<div class="profile-empty"><strong>Perusahaan belum ditemukan</strong>'
                    '<span>Coba nama atau lokasi lain, atau pilih semua industri.</span></div>', unsafe_allow_html=True)
    for company_id in filtered[start:end]:
        company = store.co.loc[company_id]
        with st.container(border=True, key=f'profile_row_{company_id}'):
            name_col, location_col, status_col, arrow_col = st.columns([4.35, 1.6, 1.9, .4],
                                                                     vertical_alignment='center')
            name_col.button(str(company['name']), key=f'profile_open_{company_id}', width='content',
                            on_click=_open, args=(company_id,))
            name_col.markdown(f'<div class="profile-meta"><span class="profile-id">{ui.esc(company_id)}</span>'
                              f' &nbsp;·&nbsp; {ui.esc(company["industry"])}</div>', unsafe_allow_html=True)
            location_col.markdown(f'<div class="profile-location">{ui.esc(company["district"])}</div>'
                                  f'<div class="profile-city">{ui.esc(company["city"])}</div>', unsafe_allow_html=True)
            if company_id in mine_set:
                label, bg, fg = 'Portofolio Saya', '#E4F1EA', '#17613F'
            elif pd.notna(company['rm_id']):
                label, bg, fg = 'Portofolio RM Lain', '#EEF2F9', ui.NAVY2
            else:
                label, bg, fg = 'Belum dalam Portofolio', '#EEF0F3', '#374151'
            status_col.markdown(ui.badge(label, bg, fg), unsafe_allow_html=True)
            status_col.markdown(ui.badge(store.cox.at[company_id, 'segment'], ui.SEG_COLOR.get(store.cox.at[company_id, 'segment'], '#999'), '#fff')
                                + ui.risk_badge(store.cox.at[company_id, 'pred_class'])
                                + (ui.badge('Temuan aktif', '#FBEFD6', '#7A4E00') if company_id in alarm_ids else ''), unsafe_allow_html=True)
            arrow_col.button('→', key=f'profile_arrow_{company_id}', help=f'Buka profil {company["name"]}',
                             on_click=_open, args=(company_id,))

    if filtered:
        st.write('')
        previous, indicator, page_input, following = st.columns([1.2, 2.6, 1, 1.2], vertical_alignment='bottom')
        previous.button('Sebelumnya', icon=':material/chevron_left:', key='profile_previous',
                        disabled=page <= 1, on_click=_change_page, args=(-1,), width='stretch')
        indicator.caption(f'Halaman {page} dari {page_count}')
        ss.profile_page_number = int(page_input.number_input('Halaman', min_value=1, max_value=page_count,
                                                            step=1, key='profile_list_page'))
        following.button('Berikutnya', icon=':material/chevron_right:', key='profile_next',
                         disabled=page >= page_count, on_click=_change_page, args=(1,), width='stretch')
