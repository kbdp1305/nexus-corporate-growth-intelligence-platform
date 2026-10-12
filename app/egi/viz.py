"""Grafik (Plotly) dan peta (pydeck) dengan gaya yang sama di semua halaman."""
from __future__ import annotations

import json

import networkx as nx
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pydeck as pdk

from .ui import INK, INK2, LINE, NAVY2, ORANGE

FONT = dict(family='IBM Plex Sans, system-ui, sans-serif', size=12, color=INK)
CLIENT_RGB, PROSPECT_RGB, MINE_RGB = [42, 120, 214, 215], [235, 104, 52, 230], [30, 58, 110, 240]   # biru · oranye · navy


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


# Peta: tiga peran warna yang tidak saling menyaru (divalidasi dengan validate_palette.js, skill dataviz)
#   kategori titik : nasabah = biru #2a78d6, nasabah saya = navy, prospect = oranye #eb6834
#   besaran wilayah: ramp aqua satu hue terang→gelap (monoton, ujung terang ≥ 2:1 vs latar)
#   penanda        : tinta gelap netral, dibedakan BENTUK (cincin besar = white-space, cincin tebal = fokus, cakram putih = cabang)
SEQ_RAMP = ['#6ac399', '#20b07b', '#009765', '#007f4f', '#00673a', '#005026']
_SEQ = [tuple(int(h[i:i + 2], 16) for i in (1, 3, 5)) for h in SEQ_RAMP]
INK_RGB = [17, 24, 39, 255]
BRANCH_FILL, BRANCH_LINE = [255, 255, 255, 255], INK_RGB
SEQ_ALPHA = 165


def seq_rgb(v, alpha=SEQ_ALPHA):
    """0–1 → warna ramp aqua (interpolasi antar langkah)."""
    v = 0.0 if v != v else min(max(float(v), 0.0), 1.0) * (len(_SEQ) - 1)
    i = min(int(v), len(_SEQ) - 2); t = v - i
    return [int(a + (b - a) * t) for a, b in zip(_SEQ[i], _SEQ[i + 1])] + [alpha]


def _sym(kind, color):
    """Simbol legenda SVG 14px, sama bentuknya dengan penanda di peta."""
    c = f'rgb({color[0]},{color[1]},{color[2]})'
    body = {'dot': f"<circle cx='7' cy='7' r='4' fill='{c}'/>",
            'disk': f"<circle cx='7' cy='7' r='4.5' fill='white' stroke='{c}' stroke-width='2'/>",
            'ring': f"<circle cx='7' cy='7' r='5.5' fill='none' stroke='{c}' stroke-width='1.6'/>",
            'ring_bold': f"<circle cx='7' cy='7' r='5' fill='none' stroke='{c}' stroke-width='3'/>"}[kind]
    return f"<svg width='14' height='14' style='vertical-align:-2px'>{body}</svg>"


def scale_legend(title, lo, hi, mine=False, focus=False):
    """Legenda peta: skala choropleth + simbol titik & penanda (identitas tidak bergantung warna saja)."""
    grad = 'linear-gradient(90deg, ' + ', '.join(SEQ_RAMP) + ')'
    item = lambda sym, txt: f"<span style='white-space:nowrap'>{sym} {txt}</span>"
    pts = ([item(_sym('dot', MINE_RGB), 'nasabah saya'), item(_sym('dot', CLIENT_RGB), 'nasabah RM lain')] if mine else
           [item(_sym('dot', CLIENT_RGB), 'nasabah')]) + [item(_sym('dot', PROSPECT_RGB), 'prospect')]
    marks = [item(_sym('disk', INK_RGB), 'cabang BNI'), item(_sym('ring', INK_RGB), 'white-space')] + ([item(_sym('ring_bold', INK_RGB), 'fokus')] if focus else [])
    return (f"<div style='display:flex;flex-wrap:wrap;align-items:center;gap:6px 14px;font-size:12px;color:{INK2};margin-top:4px'>"
            f"<span style='white-space:nowrap'><b style='color:{INK}'>{title}</b> {lo} "
            f"<span style='display:inline-block;width:120px;height:10px;border-radius:5px;vertical-align:-1px;background:{grad}'></span> {hi}</span>"
            + ''.join(pts + marks) + '</div>')


def district_polygons(districts: pd.DataFrame, shapes: dict, value: str, focus=None, invert=False):
    """Satu baris per cincin poligon kecamatan; warna dari kolom `value` (dinormalisasi 0–1, invert = rendah → gelap).
    districts wajib punya kolom label. Warna per kecamatan juga disimpan di .attrs['fill'] untuk kecamatan tanpa poligon."""
    v = districts[value].astype(float)
    vn = (v - v.min()) / ((v.max() - v.min()) or 1)
    vn = 1 - vn if invert else vn
    fill = {k: seq_rgb(vn[k], 200 if k == focus else SEQ_ALPHA) for k in districts.index}
    rows = [{'district': k, 'polygon': ring, 'fill': fill[k], 'label': r.label} for k, r in districts.iterrows() for ring in shapes.get(k, [])]
    out = pd.DataFrame(rows)
    out.attrs['fill'] = fill
    return out


def branch_points(branches: pd.DataFrame):
    b = branches.rename(columns={'longitude': 'lon', 'latitude': 'lat'})[['lon', 'lat']].copy()
    b['label'] = '<b>' + branches.name + '</b><br>' + branches.branch_type
    return b


class _CompactDeck(pdk.Deck):
    """pydeck menyerialisasi dengan indent=2 (±55% payload hanya spasi); kirim JSON ringkas ke browser."""

    def to_json(self):
        return json.dumps(json.loads(super().to_json()), separators=(',', ':'))


def deck(points: pd.DataFrame, districts: pd.DataFrame, focus=None, height=520, zoom=10.2, polygons=None, branches=None):
    """points: lon, lat, rgb, label · districts: lon, lat, radius, label, white_space (+ fill/line bila tanpa polygons)
    polygons: hasil district_polygons() · branches: hasil branch_points()."""
    has_poly = polygons is not None and len(polygons)
    circles = districts[~districts.index.isin(polygons.district)].copy() if has_poly else districts.copy()
    # kecamatan tanpa poligon OSM (Kota Bekasi): lingkaran berwarna ramp yang sama, tanpa garis
    fill = polygons.attrs.get('fill', {}) if polygons is not None else {}
    circles['fill'] = [fill.get(k, seq_rgb(0.5)) for k in circles.index]
    circles['line'] = [[0, 0, 0, 0]] * len(circles)
    circles = circles[['lon', 'lat', 'radius', 'fill', 'line', 'label']]       # hanya kolom yang dipakai layer (semua kolom ikut terkirim)
    points = points[['lon', 'lat', 'rgb', 'label']]
    # penanda di titik tengah kecamatan (pengganti garis tepi poligon): cincin tipis besar = white-space, cincin tebal = fokus
    ws = districts[districts.white_space & (districts.index != focus)][['lon', 'lat', 'label']]
    fc = districts[districts.index == focus][['lon', 'lat', 'label']]
    layers = []
    if has_poly:
        # Tanpa garis tepi & tanpa auto_highlight: komponen deck.gl Streamlit memproses ulang data tiap frame, dan garis tepi poligon
        # membuat geser peta turun ke ±2 fps tanpa GPU / ±40 fps dengan GPU (diukur di Edge). Tanpa itu: ±39 / ±157 fps.
        layers.append(pdk.Layer('PolygonLayer', polygons[['polygon', 'fill', 'label']], get_polygon='polygon', get_fill_color='fill',
                                stroked=False, filled=True, pickable=True, id='kecamatan_poligon'))
    layers.append(pdk.Layer('ScatterplotLayer', circles, get_position='[lon, lat]', get_radius='radius', get_fill_color='fill', get_line_color='line',
                            stroked=True, filled=True, line_width_min_pixels=2, pickable=True, id='kecamatan'))
    # titik perusahaan: kecil dengan cincin putih tipis supaya terpisah dari warna kecamatan di bawahnya
    layers.append(pdk.Layer('ScatterplotLayer', points, get_position='[lon, lat]', get_fill_color='rgb', get_radius=75, radius_min_pixels=2.2, radius_max_pixels=5,
                            stroked=True, get_line_color=[255, 255, 255, 200], line_width_min_pixels=0.6, pickable=True, id='perusahaan'))
    # ketebalan garis lewat line_width_min_pixels (lebar dasar 1 m): pydeck mengubah line_width_units='pixels' menjadi ekspresi "@@=pixels" yang rusak
    for data, r, px, lid in [(ws, 650, 2, 'penanda_white_space'), (fc, 900, 4, 'penanda_fokus')]:
        if len(data):
            layers.append(pdk.Layer('ScatterplotLayer', data, get_position='[lon, lat]', get_radius=r, get_line_color=INK_RGB, filled=False, stroked=True,
                                    line_width_min_pixels=px, radius_min_pixels=12, pickable=True, id=lid))
    if branches is not None and len(branches):
        layers.append(pdk.Layer('ScatterplotLayer', branches, get_position='[lon, lat]', get_fill_color=BRANCH_FILL, get_line_color=BRANCH_LINE, get_radius=200,
                                stroked=True, line_width_min_pixels=2, radius_min_pixels=5, radius_max_pixels=8, pickable=True, id='cabang'))
    lat, lon = (districts.loc[focus, 'lat'], districts.loc[focus, 'lon']) if focus is not None and focus in districts.index else (-6.2, 106.85)
    return _CompactDeck(layers=layers, initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=zoom if focus is None else 12),
                        map_provider='carto', map_style='light', tooltip={'html': '{label}', 'style': {'backgroundColor': '#0F1E3A', 'color': 'white', 'fontSize': '12px'}})


def route_deck(stops: pd.DataFrame, branches=None):
    """Rute satu hari. stops: lon, lat, no (urutan), rgb, label. Garis = urutan kunjungan; angka = nomor urut."""
    stops = stops[['lon', 'lat', 'no', 'rgb', 'label']]
    layers = []
    if len(stops) > 1:
        layers.append(pdk.Layer('PathLayer', pd.DataFrame([{'path': stops[['lon', 'lat']].values.tolist()}]), get_path='path',
                                get_color=[30, 58, 110, 170], width_min_pixels=3, id='rute'))
    if branches is not None and len(branches):
        layers.append(pdk.Layer('ScatterplotLayer', branches, get_position='[lon, lat]', get_fill_color=BRANCH_FILL, get_line_color=BRANCH_LINE, get_radius=200,
                                stroked=True, line_width_min_pixels=2, radius_min_pixels=5, radius_max_pixels=8, pickable=True, id='cabang'))
    layers.append(pdk.Layer('ScatterplotLayer', stops, get_position='[lon, lat]', get_fill_color='rgb', get_radius=150, radius_min_pixels=12,
                            stroked=True, get_line_color=[255, 255, 255, 255], line_width_min_pixels=2, pickable=True, id='kunjungan'))
    layers.append(pdk.Layer('TextLayer', stops, get_position='[lon, lat]', get_text='no', get_size=13, get_color=[255, 255, 255, 255],
                            get_text_anchor=pdk.types.String('middle'), get_alignment_baseline=pdk.types.String('center'), id='nomor'))
    span = max(stops.lat.max() - stops.lat.min(), stops.lon.max() - stops.lon.min()) if len(stops) else 0
    zoom = 13 if span < 0.03 else 12 if span < 0.08 else 11 if span < 0.2 else 10.2
    return _CompactDeck(layers=layers, initial_view_state=pdk.ViewState(latitude=float(stops.lat.mean()), longitude=float(stops.lon.mean()), zoom=zoom),
                        map_provider='carto', map_style='light', tooltip={'html': '{label}', 'style': {'backgroundColor': '#0F1E3A', 'color': 'white', 'fontSize': '12px'}})


def ev_waterfall(r: dict, h=280):
    """Rincian EV simulasi: pendapatan − kerugian kredit − biaya aksi = EV (Rp juta)."""
    fig = go.Figure(go.Waterfall(x=['Pendapatan harapan', 'Kerugian kredit', 'Biaya aksi', 'EV'], measure=['relative', 'relative', 'relative', 'total'],
                                 y=[r['pendapatan'], -r['kerugian'], -r['biaya'], 0], text=[f"{v:,.1f}" for v in [r['pendapatan'], -r['kerugian'], -r['biaya'], r['ev']]],
                                 textposition='outside', connector=dict(line=dict(color=LINE)), increasing=dict(marker_color='#17613F'),
                                 decreasing=dict(marker_color='#9A2416'), totals=dict(marker_color=NAVY2 if r['ev'] >= 0 else ORANGE)))
    return _layout(fig, h, title='Rincian EV (Rp juta)')


def ev_curve(ps, evs, p_now, ev_now, impas=None, h=280):
    """EV terhadap peluang konversi; titik = asumsi saat ini, garis putus = titik impas."""
    fig = go.Figure(go.Scatter(x=ps, y=evs, mode='lines', line=dict(color=NAVY2, width=2.5), hovertemplate='P %{x:.0f}% → EV %{y:,.1f}<extra></extra>'))
    fig.add_trace(go.Scatter(x=[p_now], y=[ev_now], mode='markers+text', marker=dict(size=11, color=ORANGE), text=['sekarang'], textposition='top center'))
    fig.add_hline(y=0, line_color=INK2, line_width=1)
    if impas is not None and impas == impas and impas <= 100:
        fig.add_vline(x=impas, line_dash='dot', line_color='#17613F', annotation_text=f'impas {impas:.0f}%', annotation_position='top')
    fig.update_xaxes(title='peluang konversi (%)', range=[0, 100]); fig.update_yaxes(title='EV (Rp juta)')
    return _layout(fig, h, title='EV menurut peluang konversi')
