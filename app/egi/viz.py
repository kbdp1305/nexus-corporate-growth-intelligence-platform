"""Grafik (Plotly) dan peta (pydeck) dengan gaya yang sama di semua halaman."""
from __future__ import annotations

import networkx as nx
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pydeck as pdk

from .ui import INK, INK2, LINE, NAVY2, ORANGE

FONT = dict(family='IBM Plex Sans, system-ui, sans-serif', size=12, color=INK)
CLIENT_RGB, PROSPECT_RGB, MINE_RGB = [111, 143, 196, 170], [210, 87, 15, 200], [30, 58, 110, 230]


def _layout(fig, h=320, **kw):
    fig.update_layout(height=h, margin=dict(l=10, r=10, t=30, b=10), paper_bgcolor='white', plot_bgcolor='white', font=FONT,
                      xaxis=dict(gridcolor=LINE, zeroline=False), yaxis=dict(gridcolor=LINE, zeroline=False), showlegend=kw.pop('legend', False), **kw)
    return fig


def hbar(labels, values, text=None, color=NAVY2, h=300, xmax=None, title=None):
    fig = go.Figure(go.Bar(y=labels, x=values, orientation='h', marker_color=color, text=text, textposition='outside', cliponaxis=False))
    fig.update_yaxes(autorange='reversed')
    if xmax: fig.update_xaxes(range=[0, xmax])
    return _layout(fig, h, title=title)


def line(x, y, title=None, h=260, fmt_y=None, highlight_last=True, ref=None):
    fig = go.Figure(go.Scatter(x=x, y=y, mode='lines+markers', line=dict(color=NAVY2, width=2.5), marker=dict(size=5)))
    if highlight_last and len(x):
        fig.add_trace(go.Scatter(x=[x[-1]], y=[y[-1]], mode='markers+text', marker=dict(size=10, color=ORANGE), text=[fmt_y(y[-1]) if fmt_y else y[-1]], textposition='top center'))
    if ref is not None:
        fig.add_hline(y=ref, line_dash='dot', line_color=INK2)
    return _layout(fig, h, title=title)


def ratio_vs_peer(df):
    """df: rasio, persentil (0–100, kanan = lebih sehat)."""
    fig = go.Figure()
    fig.add_trace(go.Bar(y=df.rasio, x=[100] * len(df), orientation='h', marker_color='#EEF0F3', hoverinfo='skip'))
    fig.add_trace(go.Bar(y=df.rasio, x=[50] * len(df), base=25, orientation='h', marker_color='#DCE3EE', hoverinfo='skip'))
    fig.add_trace(go.Scatter(y=df.rasio, x=df.persentil, mode='markers', marker=dict(size=14, color=[('#17613F' if p >= 60 else '#9A2416' if p <= 40 else NAVY2) for p in df.persentil],
                             line=dict(color='white', width=2)), text=df.label, hovertemplate='%{y}: %{text}<extra></extra>'))
    fig.add_vline(x=50, line_color=INK2, line_width=1)
    fig.update_layout(barmode='overlay'); fig.update_yaxes(autorange='reversed')
    fig.update_xaxes(range=[0, 100], title='persentil di antara peer (kanan = lebih sehat)')
    return _layout(fig, 60 + 42 * len(df))


def ego_graph(center_name, ego):
    """ego: DataFrame id, nama, tipe, nilai, distress, peran."""
    G = nx.Graph(); G.add_node('C')
    for r in ego.itertuples():
        G.add_edge('C', r.id, w=r.nilai)
    pos = nx.spring_layout(G, seed=7, k=0.9)
    xs, ys = [], []
    for r in ego.itertuples():
        xs += [pos['C'][0], pos[r.id][0], None]; ys += [pos['C'][1], pos[r.id][1], None]
    fig = go.Figure(go.Scatter(x=xs, y=ys, mode='lines', line=dict(color='#C9D2E0', width=1), hoverinfo='skip'))
    col = {'Existing credit client': NAVY2, 'Existing non-credit client': '#6F8FC4', 'Prospect': '#D2570F', 'Eksternal': '#9AA0A9'}
    lab = {'Existing credit client': 'nasabah kredit', 'Existing non-credit client': 'nasabah non-kredit', 'Prospect': 'prospect', 'Eksternal': 'eksternal'}
    for t, g in ego.groupby('tipe'):
        fig.add_trace(go.Scatter(x=[pos[i][0] for i in g.id], y=[pos[i][1] for i in g.id], mode='markers', name=lab.get(t, t),
                                 marker=dict(size=8 + 14 * np.sqrt(g.nilai / ego.nilai.max()), color=col.get(t, '#999'),
                                             line=dict(color=['#9A2416' if d else 'white' for d in g.distress], width=[3 if d else 1 for d in g.distress])),
                                 text=[f"{n}<br>Rp {v / 1000:,.1f} M/thn{'<br><b>alarm distress</b>' if d else ''}" for n, v, d in zip(g.nama, g.nilai, g.distress)],
                                 hovertemplate='%{text}<extra></extra>'))
    fig.add_trace(go.Scatter(x=[pos['C'][0]], y=[pos['C'][1]], mode='markers+text', marker=dict(size=26, color='#0F1E3A'), text=[center_name[:28]],
                             textposition='bottom center', hoverinfo='skip', showlegend=False))
    fig.update_xaxes(visible=False); fig.update_yaxes(visible=False)
    return _layout(fig, 460, legend=True, legend_orientation='h')


def deck(points: pd.DataFrame, districts: pd.DataFrame, focus=None, height=520, zoom=10.2):
    """points: lon, lat, rgb, label · districts: lon, lat, radius, rgb, label."""
    layers = [
        pdk.Layer('ScatterplotLayer', points, get_position='[lon, lat]', get_fill_color='rgb', get_radius=110, pickable=True, radius_min_pixels=2),
        pdk.Layer('ScatterplotLayer', districts, get_position='[lon, lat]', get_radius='radius', get_fill_color='fill', get_line_color='line',
                  stroked=True, filled=True, line_width_min_pixels=2, pickable=True, id='kecamatan'),
    ]
    lat, lon = (districts.loc[focus, 'lat'], districts.loc[focus, 'lon']) if focus is not None and focus in districts.index else (-6.2, 106.85)
    return pdk.Deck(layers=layers, initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=zoom if focus is None else 12),
                    map_provider='carto', map_style='light', tooltip={'html': '{label}', 'style': {'backgroundColor': '#0F1E3A', 'color': 'white', 'fontSize': '12px'}})
