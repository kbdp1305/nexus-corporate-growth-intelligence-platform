"""Tampilan bersama: tema, kartu angka, badge, kartu perusahaan, format angka."""
from __future__ import annotations

import html

import numpy as np
import streamlit as st

NAVY, NAVY2, ORANGE, INK, INK2, LINE = '#0F1E3A', '#1E3A6E', '#C2500A', '#111827', '#4B5563', '#E3E6EB'
SEG_COLOR = {'S1 Kecil': '#8FA9D6', 'S2 Menengah': '#4D6FAE', 'S3 Besar': '#1E3A6E'}
RISK_STYLE = {'Low': ('#E4F1EA', '#17613F', 'Low'), 'Medium': ('#FBEFD6', '#7A4E00', 'Medium · kredit ×0,5'),
              'High': ('#FADFDB', '#9A2416', 'High · kredit ditunda')}
EVENT_STYLE = {'distress': ('#FADFDB', '#9A2416', 'Distress', 'analis risiko'), 'buyer_exit': ('#FDEBDD', '#9A3412', 'Pembeli keluar', 'RM + analis'),
               'expansion': ('#E4F1EA', '#17613F', 'Ekspansi', 'RM: tawarkan kredit'), 'wallet_erosion': ('#FBEFD6', '#7A4E00', 'Erosi wallet', 'RM: retensi'),
               'contagion': ('#EDE9F6', '#4C3A86', 'Efek berantai', 'pantau anchor'), 'spike': ('#EEF0F3', '#374151', 'Lonjakan', 'verifikasi')}

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');
html, body, [class*="css"], .stMarkdown, .stText, button, input, select, textarea {{ font-family: 'IBM Plex Sans', system-ui, sans-serif; }}
.block-container {{ padding-top: 1.6rem; max-width: 1400px; }}
section[data-testid="stSidebar"] {{ background: {NAVY}; }}
section[data-testid="stSidebar"] * {{ color: #C8D0DE; }}
section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] h2, section[data-testid="stSidebar"] h3, section[data-testid="stSidebar"] strong {{ color: #FFFFFF; }}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-current="page"], section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"][aria-current="page"] {{ background: {ORANGE}; border-radius: 8px; }}
section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"][aria-current="page"] span {{ color: #FFFFFF; font-weight: 600; }}
section[data-testid="stSidebar"] div[data-baseweb="select"] > div {{ background: #16284A; border-color: #2B3D60; }}
section[data-testid="stSidebar"] .stButton button {{ background: #16284A; border: 1px solid #2B3D60; }}
.egi-kpi {{ background: #FFFFFF; border: 1px solid {LINE}; border-radius: 12px; padding: 14px 16px; height: 100%; }}
.egi-kpi .l {{ font-size: 12px; color: {INK2}; font-weight: 500; }}
.egi-kpi .v {{ font-family: 'IBM Plex Mono', monospace; font-size: 26px; font-weight: 500; color: {INK}; margin: 4px 0 2px; }}
.egi-kpi .s {{ font-size: 12px; color: {INK2}; }}
.egi-badge {{ display: inline-block; font-size: 12px; font-weight: 600; padding: 2px 9px; border-radius: 999px; margin: 0 4px 4px 0; white-space: nowrap; }}
.egi-ai {{ background: #EEF2F9; border-left: 0; border-radius: 10px; padding: 12px 14px; font-size: 14px; line-height: 1.6; color: #1F2937; }}
.egi-ai .h {{ font-size: 12px; font-weight: 700; color: {NAVY2}; margin-bottom: 4px; }}
.egi-ai .src {{ font-size: 11px; color: {INK2}; margin-top: 6px; }}
.egi-muted {{ color: {INK2}; font-size: 13px; }}
.egi-card {{ background: #FFFFFF; border: 1px solid {LINE}; border-radius: 12px; padding: 14px 16px; }}
.egi-title {{ font-size: 13px; color: {INK2}; font-weight: 500; margin-bottom: -6px; }}
.egi-warn {{ background: #FBEFD6; color: #7A4E00; border-radius: 8px; padding: 8px 12px; font-size: 13px; }}
div[data-testid="stMetricValue"] {{ font-family: 'IBM Plex Mono', monospace; }}
.egi-plan {{ background: #FFFFFF; border: 1px solid {LINE}; border-radius: 12px; padding: 14px 16px; margin: 6px 0 10px; }}
.egi-plan .hd {{ display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 10px; }}
.egi-plan .tt {{ font-size: 14px; font-weight: 700; color: {NAVY}; }}
.egi-plan .sum {{ font-size: 13.5px; line-height: 1.55; color: #1F2937; background: #F5F7FB; border-radius: 8px; padding: 10px 12px; }}
.egi-plan .sec {{ font-size: 11.5px; font-weight: 700; color: {INK2}; text-transform: uppercase; letter-spacing: .5px; margin: 14px 0 4px; }}
.egi-step {{ display: flex; gap: 10px; padding: 9px 0; border-top: 1px solid #EEF0F3; }}
.egi-step.first {{ border-top: 0; }}
.egi-step .no {{ flex: 0 0 24px; height: 24px; border-radius: 50%; background: {NAVY2}; color: #FFFFFF; font-size: 12px; font-weight: 700;
                 display: flex; align-items: center; justify-content: center; margin-top: 1px; }}
.egi-step .ak {{ font-size: 14px; font-weight: 600; color: {INK}; line-height: 1.45; }}
.egi-step .mt {{ margin-top: 5px; }}
.egi-step .al {{ font-size: 12.5px; color: {INK2}; line-height: 1.45; margin-top: 2px; }}
.egi-obj {{ border-left: 3px solid #E8B04B; background: #FFFBF2; border-radius: 0 8px 8px 0; padding: 7px 10px; margin: 6px 0; font-size: 13.5px; line-height: 1.5; }}
.egi-obj .k {{ font-weight: 600; color: #7A4E00; }}
.egi-when {{ display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: baseline; background: #E4F1EA; color: #17613F; border-radius: 8px;
             padding: 9px 12px; margin-top: 14px; font-size: 13.5px; }}
.egi-when b {{ font-size: 14px; }}
.egi-when .tj {{ color: #2F5D46; font-size: 13px; }}
</style>
"""


def apply_theme():
    st.markdown(CSS, unsafe_allow_html=True)


def fmt(x, d=1, pct=False):
    if x is None or (isinstance(x, (float, np.floating)) and not np.isfinite(x)):
        return '—'
    s = f'{abs(float(x)):,.{d}f}'.replace(',', '_').replace('.', ',').replace('_', '.')
    return ('−' if x < 0 else '') + s + ('%' if pct else '')


def esc(s):
    return html.escape(str(s))


def badge(text, bg, fg):
    return f'<span class="egi-badge" style="background:{bg};color:{fg}">{esc(text)}</span>'


def risk_badge(cls):
    bg, fg, lab = RISK_STYLE.get(cls, ('#EEF0F3', '#374151', str(cls)))
    return badge(lab, bg, fg)


def event_badge(ev):
    bg, fg, lab, _ = EVENT_STYLE.get(ev, ('#EEF0F3', '#374151', ev, ''))
    return badge(lab, bg, fg)


def kpi(col, label, value, sub='', color=INK):
    col.markdown(f'<div class="egi-kpi"><div class="l">{esc(label)}</div><div class="v" style="color:{color}">{esc(value)}</div>'
                 f'<div class="s">{esc(sub)}</div></div>', unsafe_allow_html=True)


def ai_box(title, text, source='', mode=''):
    tag = f' · {esc(mode)}' if mode else ''
    st.markdown(f'<div class="egi-ai"><div class="h">{esc(title)}{tag}</div>{esc(text)}'
                + (f'<div class="src">Sumber: {esc(source)}</div>' if source else '') + '</div>', unsafe_allow_html=True)


def page_header(eyebrow, title):
    st.markdown(f'<div class="egi-title">{esc(eyebrow)}</div>', unsafe_allow_html=True)
    st.title(title)
