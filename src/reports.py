"""BNI EGI — paket fakta, validasi angka, dan PDF untuk RM (dashboard + RM Copilot).

Alur:
1. fact_pack(cid)            → semua angka tentang satu perusahaan, dihitung kode (bukan LLM).
2. LLM menulis narasi        → dict per bagian (lihat NARRATIVE_KEYS), hanya boleh memakai angka dari paket fakta.
3. check_numbers(narr, fp)   → setiap angka di narasi harus ada di paket fakta; yang asing dilaporkan.
4. company_summary_pdf(...)  / weekly_plan_pdf(...) → PDF A4 siap unduh (Streamlit: st.download_button).
"""
from __future__ import annotations

import io
import re
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, Line, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

NARRATIVE_KEYS = ['ringkasan', 'keuangan', 'risiko', 'anomali', 'jaringan', 'rekomendasi', 'pertanyaan']
REF_MONTH = '2026-06'

# ------------------------------------------------------------------ font (Unicode bila ada)
_FONT_CANDIDATES = [
    ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'),
    ('C:/Windows/Fonts/segoeui.ttf', 'C:/Windows/Fonts/segoeuib.ttf', 'C:/Windows/Fonts/consola.ttf'),
    ('C:/Windows/Fonts/arial.ttf', 'C:/Windows/Fonts/arialbd.ttf', 'C:/Windows/Fonts/cour.ttf'),
    ('/Library/Fonts/Arial Unicode.ttf', '/Library/Fonts/Arial Unicode.ttf', '/Library/Fonts/Arial Unicode.ttf'),
]
FONT, FONT_B, FONT_M, UNICODE = 'Helvetica', 'Helvetica-Bold', 'Courier', False
for reg, bold, mono in _FONT_CANDIDATES:
    if all(Path(p).exists() for p in (reg, bold, mono)):
        pdfmetrics.registerFont(TTFont('EGI', reg)); pdfmetrics.registerFont(TTFont('EGI-B', bold)); pdfmetrics.registerFont(TTFont('EGI-M', mono))
        FONT, FONT_B, FONT_M, UNICODE = 'EGI', 'EGI-B', 'EGI-M', True
        break


def _t(s):
    """Ganti karakter non-ASCII bila tidak ada font Unicode."""
    s = str(s)
    if UNICODE:
        return s
    for a, b in {'−': '-', '→': '->', '≥': '>=', '≤': '<=', '·': '-', '×': 'x', '…': '...', '±': '+/-', '°': ''}.items():
        s = s.replace(a, b)
    return s


NAVY, NAVY2, ORANGE, INK, INK2, LINE, SOFT = (colors.HexColor(c) for c in ('#0F1E3A', '#1E3A6E', '#C2500A', '#111827', '#4B5563', '#E3E6EB', '#F4F5F7'))
GREEN, AMBER, RED = colors.HexColor('#17613F'), colors.HexColor('#7A4E00'), colors.HexColor('#9A2416')

ST = {
    'h1': ParagraphStyle('h1', fontName=FONT_B, fontSize=17, leading=21, textColor=colors.white),
    'sub': ParagraphStyle('sub', fontName=FONT, fontSize=8.5, leading=11, textColor=colors.HexColor('#C8D0DE')),
    'h2': ParagraphStyle('h2', fontName=FONT_B, fontSize=11, leading=14, textColor=NAVY2, spaceBefore=8, spaceAfter=4),
    'body': ParagraphStyle('body', fontName=FONT, fontSize=9, leading=13, textColor=INK, alignment=TA_LEFT),
    'small': ParagraphStyle('small', fontName=FONT, fontSize=7.5, leading=10, textColor=INK2),
    'cell': ParagraphStyle('cell', fontName=FONT, fontSize=8, leading=10.5, textColor=INK),
    'cellb': ParagraphStyle('cellb', fontName=FONT_B, fontSize=8, leading=10.5, textColor=INK),
    'kpi_l': ParagraphStyle('kpi_l', fontName=FONT, fontSize=7.5, leading=9.5, textColor=INK2),
    'kpi_v': ParagraphStyle('kpi_v', fontName=FONT_B, fontSize=14, leading=17, textColor=INK),
    'ai': ParagraphStyle('ai', fontName=FONT, fontSize=9, leading=13.2, textColor=INK, backColor=colors.HexColor('#EEF2F9'), borderPadding=(6, 7, 6, 7)),
}


def P(text, style='body'):
    return Paragraph(_t(text), ST[style])


def fmt(x, d=1):
    """Angka gaya Indonesia: 1.234,5 dan minus '−'."""
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return '—'
    s = f'{abs(x):,.{d}f}'.replace(',', '_').replace('.', ',').replace('_', '.')
    return ('−' if x < 0 else '') + s


# ------------------------------------------------------------------ paket fakta
class Data:
    """Memuat semua tabel sekali (di Streamlit: bungkus dengan st.cache_resource)."""

    def __init__(self, root):
        root = Path(root)
        R, Sc, Pr = root / 'data/raw', root / 'outputs/scores', root / 'data/processed'
        self.co = pd.read_csv(R / 'companies.csv').set_index('company_id')
        self.co['name'] = self.co.company_name.str.replace(' (dummy)', '', regex=False)
        self.fin = pd.read_csv(R / 'financials.csv')
        self.rel = pd.read_csv(R / 'relationships.csv')
        self.act = self.rel[self.rel.relationship_end.isna() | (self.rel.relationship_end > '2026-06-30')]
        self.hold = pd.read_csv(R / 'product_holdings.csv')
        self.log = pd.read_csv(R / 'rm_action_log.csv')
        self.risk = pd.read_csv(Sc / 'risk_scores.csv').set_index('company_id')
        self.opp = pd.read_csv(Sc / 'opportunity_scores.csv').set_index('company_id')
        self.prod = pd.read_csv(Sc / 'opportunity_products.csv')
        self.seg = pd.read_csv(Sc / 'segments.csv').set_index('company_id')
        alerts = Sc / 'anomaly_alerts_v2_shadow.csv'
        self.alerts = pd.read_csv(alerts if alerts.exists() else Sc / 'anomaly_alerts.csv')
        self.panel = pd.read_csv(Pr / 'features_anomaly_panel.csv.gz')
        f = self.fin.copy()
        f['DER'] = f.total_debt_idr_bn / f.total_equity_idr_bn
        f['CR'] = f.current_assets_idr_bn / f.current_liabilities_idr_bn
        f['NPM'] = f.net_profit_idr_bn / f.revenue_idr_bn * 100
        f['ICR'] = f.ebit_idr_bn / f.interest_expense_idr_bn
        f['ROA'] = f.net_profit_idr_bn / f.total_assets_idr_bn * 100
        self.ratios = f.join(self.co[['industry', 'size_class_reference']], on='company_id')


EVENT_ID = {'distress': 'distress', 'buyer_exit': 'pembeli keluar', 'wallet_erosion': 'erosi wallet', 'expansion': 'ekspansi', 'contagion': 'efek berantai', 'spike': 'lonjakan'}


def fact_pack(D: Data, cid: str) -> dict:
    co, r = D.co.loc[cid], D.risk.loc[cid]
    o = D.opp.loc[cid] if cid in D.opp.index else None
    seg = D.seg.segment.get(cid)
    fp = {'id': cid, 'nama': co['name'], 'industri': co.industry, 'kota': co.city, 'kecamatan': co.district, 'karyawan': int(co.employees),
          'rm': co.rm_id if isinstance(co.rm_id, str) else '—', 'tipe': co.customer_type, 'segmen': seg, 'sejak': str(co.onboarding_date)[:7], 'payroll': co.payroll_bank,
          'listed': bool(co.is_listed)}
    # risiko
    fp['risiko'] = {'kelas': r.pred_class, 'p_low': r.p_low * 100, 'p_med': r.p_medium * 100, 'p_high': r.p_high * 100,
                    'keputusan': r.decision, 'himpunan': r.conformal_set, 'alasan': [r.reason_1, r.reason_2, r.reason_3]}
    # peluang
    if o is not None:
        n_seg = int((D.opp.segment == seg).sum())
        comps = {k.replace('pct_', ''): o[k] * 100 for k in o.index if k.startswith('pct_')}
        fp['peluang'] = {'skor': o.opportunity_score * 100, 'peringkat': int(o.rank_in_segment), 'n_segmen': n_seg, 'komponen': comps,
                         'produk_disarankan': o.recommended_products, 'alasan': o.reason}
        pr = D.prod[D.prod.company_id == cid].sort_values('rank_produk')
        fp['produk'] = [{'produk': x.product_id, 'peer_pct': x.need_score * 100, 'peluang': x.p_konversi * 100, 'deal': x.ukuran_deal_Rp_juta,
                         'ev': x.ev_Rp_juta, 'ev_lo': x.ev_p10, 'ev_hi': x.ev_p90, 'ditunda': bool(x.ditunda_risiko)} for x in pr.itertuples()]
    fp['produk_dimiliki'] = sorted(D.hold[D.hold.company_id == cid].product_id)
    # keuangan
    rf = D.ratios[D.ratios.company_id == cid].set_index('fiscal_year')
    if len(rf):
        ind, size = co.industry, co.size_class_reference
        peer = D.ratios[(D.ratios.fiscal_year == 2025) & (D.ratios.industry == ind) & (D.ratios.size_class_reference == size)]
        rows = {}
        for k, lab in [('revenue_idr_bn', 'Omzet'), ('net_profit_idr_bn', 'Laba bersih'), ('ebit_idr_bn', 'EBIT'), ('total_assets_idr_bn', 'Total aset'),
                       ('total_debt_idr_bn', 'Total utang'), ('total_equity_idr_bn', 'Ekuitas')]:
            rows[lab] = (rf[k].get(2024, np.nan), rf[k].get(2025, np.nan))
        rat = {}
        for k in ['DER', 'CR', 'NPM', 'ICR', 'ROA']:
            v = rf[k].get(2025, np.nan); pct = (peer[k] < v).mean() * 100
            rat[k] = {'2024': rf[k].get(2024, np.nan), '2025': v, 'median_peer': peer[k].median(), 'persentil': 100 - pct if k == 'DER' else pct}
        chg = {lab: ((b / a - 1) * 100 if a and a > 0 and np.isfinite(b) else np.nan) for lab, (a, b) in rows.items()}
        fp['keuangan'] = {'pos': rows, 'perubahan_pct': chg, 'rasio': rat, 'n_peer': len(peer), 'peer': f'{ind.lower()} · {size.lower()}', 'diaudit': bool(rf.is_audited.get(2025, False))}
    else:
        fp['keuangan'] = None
    # arus kas & anomali
    p = D.panel[D.panel.company_id == cid].set_index('ym')
    if len(p):
        last = p.loc[REF_MONTH] if REF_MONTH in p.index else p.iloc[-1]
        cap = p.capture_t.dropna()
        fp['arus_kas'] = {'ada_data': True, 'capture_seri': cap.tail(12).round(3).to_dict(), 'capture_now': last.capture_t, 'capture_chg_6m': last.capture_chg_6m * 100,
                          'chg_3v6': last.chg_3v6, 'telat_3m': last.late_share_3m * 100, 'out_in_3m': last.out_in_3m, 'buyer_exit': last.buyer_exit_share * 100}
    else:   # prospect: belum ada rekening di BNI, jadi tidak ada panel arus kas
        last = pd.Series({'capture_chg_6m': np.nan})
        fp['arus_kas'] = {'ada_data': False, 'capture_seri': {}, 'capture_now': np.nan, 'capture_chg_6m': np.nan, 'chg_3v6': np.nan,
                          'telat_3m': np.nan, 'out_in_3m': np.nan, 'buyer_exit': np.nan}
    al = D.alerts[D.alerts.company_id == cid]
    recent = al[al.ym > '2026-03']
    fp['anomali'] = {'resmi_3bln': int(recent.ym.nunique()), 'jenis_3bln': sorted({EVENT_ID.get(e, e) for e in recent.event_type}),
                     'riwayat': [(x.ym, EVENT_ID.get(x.event_type, x.event_type)) for x in al.sort_values('ym').itertuples()],
                     'sinyal_bawah_ambang': bool(last.capture_chg_6m < -0.10 and len(recent) == 0)}
    # jaringan
    a = D.act
    lk = a[(a.source_id == cid) | (a.target_id == cid)]
    other = np.where(lk.source_id == cid, lk.target_id, lk.source_id)
    typ = pd.Series(other).map(D.co.customer_type).fillna('Eksternal')
    val = lk.annual_transaction_value_idr_mn.values
    deg = pd.concat([a.source_id, a.target_id]).value_counts()
    peers = D.co.index[(D.co.industry == co.industry)]
    fp['jaringan'] = {'mitra': len(lk), 'median_peer': float(deg.reindex(peers).fillna(0).median()), 'nilai_M': val.sum() / 1000,
                      'bni': int(typ.isin(['Existing credit client', 'Existing non-credit client']).sum()), 'prospect': int((typ == 'Prospect').sum()),
                      'eksternal': int((typ == 'Eksternal').sum())}
    pros = pd.DataFrame({'id': other, 'v': val, 't': typ.values})
    top = pros[pros.t == 'Prospect'].groupby('id').v.sum().sort_values(ascending=False).head(3)
    fp['jaringan']['prospect_teratas'] = [(i, D.co.loc[i, 'name'], D.co.loc[i, 'district'], v / 1000) for i, v in top.items()]
    dis = D.alerts[(D.alerts.company_id.isin(other)) & (D.alerts.ym > '2026-03') & (D.alerts.event_type == 'distress')].company_id.unique()
    fp['jaringan']['mitra_distress'] = len(dis)
    fp['jaringan']['nilai_distress_M'] = pros[pros.id.isin(dis)].v.sum() / 1000
    # riwayat kunjungan
    lg = D.log[D.log.party_id == cid].sort_values('contact_date')
    fp['kunjungan'] = [{'tgl': x.contact_date, 'rm': x.rm_id, 'produk': x.product_id, 'kanal': x.channel, 'respons': x.response, 'catatan': x.feedback_note} for x in lg.itertuples()]
    return fp


# ------------------------------------------------------------------ validasi angka narasi
_NUM = re.compile(r'(?<![\w])[−-]?\d[\d.]*(?:,\d+)?')


def _variants(x):
    out = set()
    if isinstance(x, (int, np.integer)):
        out |= {str(int(x)), fmt(int(x), 0)}
    elif isinstance(x, (float, np.floating)) and np.isfinite(x):
        for d in (0, 1, 2, 3):
            s = fmt(float(x), d); out |= {s, s.lstrip('−'), s.replace('−', '-')}
        if abs(x) < 1:
            for d in (0, 1):
                s = fmt(float(x) * 100, d); out |= {s, s.lstrip('−')}
    return out


def _collect(o, acc):
    if isinstance(o, dict):
        for v in o.values(): _collect(v, acc)
    elif isinstance(o, (list, tuple)):
        for v in o: _collect(v, acc)
    elif isinstance(o, str):
        acc |= set(m.group().lstrip('−-') for m in _NUM.finditer(o)) | set(m.group() for m in _NUM.finditer(o))
    else:
        acc |= _variants(o)
    return acc


def check_numbers(narrative: dict, facts, extra_allowed=()):
    """Kembalikan (jumlah angka, daftar angka yang tidak ditemukan di paket fakta)."""
    allowed = _collect(facts, set()) | set(extra_allowed)
    text = ' '.join(v if isinstance(v, str) else ' '.join(v) for v in narrative.values())
    nums = [m.group() for m in _NUM.finditer(text)]
    def generic(n):   # bilangan kecil (jumlah bulan, urutan) & tahun tidak perlu dicek
        n = n.lstrip('−-').rstrip('.,')
        return n.isdigit() and (int(n) <= 12 or 2020 <= int(n) <= 2030)
    bad = [n for n in nums if not generic(n) and n.rstrip('.,') not in allowed and n.lstrip('−-').rstrip('.,') not in allowed]
    return len(nums), bad


# ------------------------------------------------------------------ elemen PDF
def _header(title, sub, right):
    t = Table([[[P(title, 'h1'), P(sub, 'sub')], P(right, 'sub')]], colWidths=[125 * mm, 55 * mm])
    t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), NAVY), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('LEFTPADDING', (0, 0), (-1, -1), 9),
                           ('RIGHTPADDING', (0, 0), (-1, -1), 9), ('TOPPADDING', (0, 0), (-1, -1), 9), ('BOTTOMPADDING', (0, 0), (-1, -1), 9),
                           ('LINEBELOW', (0, 0), (-1, -1), 2.5, ORANGE)]))
    return t


def _kpis(items):
    cells = [[[P(l, 'kpi_l'), P(v, 'kpi_v'), P(s, 'small')] for l, v, s in items]]
    t = Table(cells, colWidths=[180 * mm / len(items)] * len(items))
    t.setStyle(TableStyle([('BOX', (0, 0), (-1, -1), 0.6, LINE), ('INNERGRID', (0, 0), (-1, -1), 0.6, LINE), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                           ('LEFTPADDING', (0, 0), (-1, -1), 7), ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))
    return t


def _table(rows, widths, head=True, align_right=()):
    data = [[P(c, 'cellb' if (head and i == 0) else 'cell') if not isinstance(c, Paragraph) else c for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1 if head else 0)
    st = [('LINEBELOW', (0, 0), (-1, -1), 0.4, LINE), ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 4),
          ('RIGHTPADDING', (0, 0), (-1, -1), 4), ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3)]
    if head:
        st += [('BACKGROUND', (0, 0), (-1, 0), SOFT), ('LINEBELOW', (0, 0), (-1, 0), 0.8, NAVY2)]
    t.setStyle(TableStyle(st))
    return t


def _ai_box(label, text):
    return KeepTogether([P(f'<font name="{FONT_B}" color="#1E3A6E">{label}</font>', 'small'), Spacer(1, 7), P(text, 'ai'), Spacer(1, 4)])


def _capture_chart(series: dict):
    keys = list(series.keys()); vals = [series[k] for k in keys]
    d = Drawing(85 * mm, 38 * mm)
    lp = LinePlot(); lp.x, lp.y, lp.width, lp.height = 18, 14, 85 * mm - 26, 38 * mm - 24
    lp.data = [[(i, v) for i, v in enumerate(vals)]]
    lp.lines[0].strokeColor = NAVY2; lp.lines[0].strokeWidth = 1.6
    lo, hi = min(vals) - 0.05, max(vals) + 0.05
    lp.yValueAxis.valueMin, lp.yValueAxis.valueMax, lp.yValueAxis.valueStep = round(lo, 1), round(hi, 1) + 0.05, 0.1
    lp.yValueAxis.labels.fontName = FONT; lp.yValueAxis.labels.fontSize = 6; lp.yValueAxis.labelTextFormat = lambda v: fmt(v, 1)
    lp.yValueAxis.strokeColor = LINE; lp.xValueAxis.strokeColor = LINE
    lp.xValueAxis.valueMin, lp.xValueAxis.valueMax = 0, len(vals) - 1
    lp.xValueAxis.labels.fontName = FONT; lp.xValueAxis.labels.fontSize = 6
    lp.xValueAxis.valueSteps = [0, len(vals) - 1]; lp.xValueAxis.labelTextFormat = lambda i: keys[int(i)]
    d.add(lp)
    d.add(String(18, 38 * mm - 8, _t('Porsi inflow BNI ÷ omzet'), fontName=FONT, fontSize=6.5, fillColor=INK2))
    return d


def _footer_fn(text):
    def draw(canvas, doc):
        canvas.saveState(); canvas.setFont(FONT, 6.8); canvas.setFillColor(INK2)
        canvas.drawString(15 * mm, 9 * mm, _t(text)); canvas.drawRightString(195 * mm, 9 * mm, f'{doc.page}')
        canvas.setStrokeColor(LINE); canvas.line(15 * mm, 12 * mm, 195 * mm, 12 * mm); canvas.restoreState()
    return draw


# ------------------------------------------------------------------ PDF 1: ringkasan eksekutif nasabah
def company_summary_pdf(fp: dict, narr: dict, out=None, generated_by='Copilot (LLM)', today=None):
    today = today or date.today().strftime('%d %b %Y')
    n_num, bad = check_numbers(narr, fp)
    buf = out or io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=12 * mm, bottomMargin=16 * mm,
                            title=f"Ringkasan eksekutif {fp['nama']}", author=fp['rm'])
    r, o, k, ak, an, j = fp['risiko'], fp.get('peluang'), fp['keuangan'], fp['arus_kas'], fp['anomali'], fp['jaringan']
    s = []
    s.append(_header('Ringkasan Eksekutif Nasabah', f"{fp['nama']} · {fp['id']} · {fp['industri']} · {fp['kecamatan']}, {fp['kota']}",
                     f"{fp['segmen']} · {fp['rm']}<br/>Data per 30 Jun 2026<br/>Dibuat {today}"))
    s.append(Spacer(1, 6))
    s.append(_kpis([
        ('Opportunity Score', fmt(o['skor'], 1) if o else '—', f"peringkat {o['peringkat']} dari {o['n_segmen']} di {fp['segmen']}" if o else ''),
        ('Risiko kredit', r['kelas'], f"P(High) {fmt(r['p_high'], 1)}% · {r['keputusan'].lower()}"),
        ('Porsi wallet BNI', fmt(ak['capture_now'], 2), f"{fmt(ak['capture_chg_6m'], 1)} poin dalam 6 bulan"),
        ('Mitra aktif', str(j['mitra']), f"median industri {fmt(j['median_peer'], 0)} · {j['prospect']} prospect"),
    ]))
    s.append(Paragraph(_t('Ringkasan'), ST['h2']))
    s.append(_ai_box(f'Disusun {generated_by}', narr['ringkasan']))
    s.append(Paragraph(_t('Rekomendasi'), ST['h2']))
    rec = [[P(f'<font name="{FONT_B}" color="#C2500A">{i + 1}</font>', 'cell'), P(t, 'cell')] for i, t in enumerate(narr['rekomendasi'])]
    s.append(_table(rec, [6, 174], head=False))
    s.append(Spacer(1, 4))
    s.append(P(f'<font name="{FONT_B}">Pertanyaan pembuka:</font> ' + ' '.join(f'“{q}”' for q in narr['pertanyaan']), 'body'))

    if k:
        s.append(Paragraph(_t(f"Keuangan (Rp miliar) · peer: {k['peer']}, {k['n_peer']} perusahaan" + (' · diaudit' if k['diaudit'] else '')), ST['h2']))
        rows = [['Pos', 'FY2024', 'FY2025', 'Δ']]
        for lab, (a, b) in k['pos'].items():
            ch = '' if not (np.isfinite(a) and np.isfinite(b)) or a == 0 else (f"{fmt((b / a - 1) * 100, 0)}%" if a > 0 else '')
            rows.append([lab, fmt(a, 1), fmt(b, 1), ch])
        rrows = [['Rasio FY2025', 'Nilai', 'Median peer', 'Posisi']]
        lab = {'DER': 'Utang/ekuitas', 'CR': 'Current ratio', 'NPM': 'Margin bersih (%)', 'ICR': 'ICR (EBIT÷bunga)', 'ROA': 'ROA (%)'}
        for kk, v in k['rasio'].items():
            pos = 'lebih baik' if v['persentil'] >= 60 else ('lebih buruk' if v['persentil'] <= 40 else 'setara')
            rrows.append([lab[kk], fmt(v['2025'], 2), fmt(v['median_peer'], 2), pos])
        t = Table([[_table(rows, [30, 18, 18, 14]), _table(rrows, [32, 16, 20, 20])]], colWidths=[84 * mm, 96 * mm])
        t.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0)]))
        s.append(t); s.append(Spacer(1, 4))
        s.append(_ai_box('Interpretasi keuangan', narr['keuangan']))

    s.append(Paragraph(_t('Risiko kredit'), ST['h2']))
    s.append(P(f"Kelas <b>{r['kelas']}</b> (Low {fmt(r['p_low'], 1)}% · Medium {fmt(r['p_med'], 1)}% · High {fmt(r['p_high'], 1)}%), "
               f"himpunan conformal {r['himpunan']} → {r['keputusan']}. Pendorong utama: " + '; '.join(r['alasan']) + '.', 'body'))
    s.append(Spacer(1, 3)); s.append(_ai_box('Interpretasi risiko', narr['risiko']))

    s.append(Paragraph(_t('Arus kas & anomali'), ST['h2']))
    ind = [['Indikator (Jun 2026)', 'Nilai'], ['Alarm resmi 3 bulan terakhir', str(an['resmi_3bln'])], ['Perubahan porsi wallet 6 bulan', f"{fmt(ak['capture_chg_6m'], 1)} poin"],
           ['Pertumbuhan inflow 3 vs 6 bulan', fmt(ak['chg_3v6'], 2)], ['Gaji/pajak telat 3 bulan', f"{fmt(ak['telat_3m'], 0)}%"],
           ['Outflow ÷ inflow 3 bulan', fmt(ak['out_in_3m'], 2)], ['Inflow dari pembeli yang menghilang', f"{fmt(ak['buyer_exit'], 1)}%"]]
    t = Table([[_table(ind, [54, 32]), _capture_chart(ak['capture_seri']) if ak['capture_seri'] else P('Belum ada data arus kas di BNI (prospect).', 'small')]], colWidths=[90 * mm, 90 * mm])
    t.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0)]))
    s.append(t)
    hist = ', '.join(f'{e} ({m})' for m, e in an['riwayat']) or 'tidak ada'
    s.append(P(f'Riwayat alarm 18 bulan: {hist}.', 'small')); s.append(Spacer(1, 3))
    s.append(_ai_box('Interpretasi anomali', narr['anomali']))

    s.append(Paragraph(_t('Jaringan rantai pasok'), ST['h2']))
    s.append(P(f"{j['mitra']} relasi aktif senilai Rp {fmt(j['nilai_M'], 0)} M/thn: {j['bni']} nasabah BNI, {j['prospect']} prospect, {j['eksternal']} eksternal. "
               f"{j['mitra_distress']} mitra sedang alarm distress (Rp {fmt(j['nilai_distress_M'], 0)} M/thn). Prospect terbesar: "
               + '; '.join(f'{n} ({d}, Rp {fmt(v, 1)} M)' for _, n, d, v in j['prospect_teratas']) + '.', 'body'))
    s.append(Spacer(1, 3)); s.append(_ai_box('Interpretasi jaringan', narr['jaringan']))

    if fp.get('produk'):
        s.append(Paragraph(_t('Produk yang belum dimiliki'), ST['h2']))
        rows = [['Produk', 'Peer memakai', 'Peluang', 'Ukuran deal (Rp jt)', 'EV (Rp jt, p10–p90)']]
        for x in fp['produk'][:4]:
            rows.append([x['produk'] + (' · ditunda (risiko)' if x['ditunda'] else ''), f"{fmt(x['peer_pct'], 0)}%", f"{fmt(x['peluang'], 0)}%",
                         fmt(x['deal'], 0), f"{fmt(x['ev'], 2)} ({fmt(x['ev_lo'], 2)} … {fmt(x['ev_hi'], 2)})"])
        s.append(_table(rows, [34, 26, 20, 36, 64]))
        s.append(P('EV ilustratif: margin, biaya aksi, PD/LGD adalah asumsi yang belum disepakati. Tidak dipakai untuk meranking.', 'small'))

    if fp['kunjungan']:
        s.append(Paragraph(_t('Riwayat kunjungan'), ST['h2']))
        rows = [['Tanggal', 'RM', 'Produk', 'Kanal', 'Respons', 'Catatan']] + [[v['tgl'], v['rm'], v['produk'], v['kanal'], v['respons'], v['catatan']] for v in fp['kunjungan']]
        s.append(_table(rows, [20, 18, 17, 20, 25, 80]))

    s.append(Spacer(1, 8))
    status = f'{n_num} angka di narasi, semuanya cocok dengan paket fakta' if not bad else f'{n_num} angka di narasi; tidak cocok: {", ".join(bad)} → periksa sebelum dipakai'
    s.append(P(f'<b>Validasi angka:</b> {status}. Sumber: risk_scores (XGBoost NB06), opportunity_scores &amp; opportunity_products (NB08), financials, '
               'features_anomaly_panel, anomaly_alerts v2, relationships, rm_action_log.', 'small'))
    doc.build(s, onFirstPage=_footer_fn(f"Disusun dengan bantuan AI dari data per 30 Jun 2026 · bukan keputusan kredit · diperiksa oleh {fp['rm']} · data sintetis"),
              onLaterPages=_footer_fn(f"{fp['nama']} · ringkasan eksekutif · bukan keputusan kredit"))
    return buf, (n_num, bad)


# ------------------------------------------------------------------ PDF 2: rencana minggu
def weekly_plan_pdf(plan: dict, out=None, today=None):
    today = today or date.today().strftime('%d %b %Y')
    buf = out or io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=12 * mm, bottomMargin=16 * mm,
                            title=f"Rencana kunjungan {plan['rm']} {plan['minggu']}", author=plan['rm'])
    s = [_header('Rencana Kunjungan Mingguan', f"{plan['rm']} · {plan['minggu']} · {plan['portofolio']}", f"Status: {plan['status']}<br/>Dibuat {today}")]
    s.append(Spacer(1, 6))
    s.append(_kpis([(l, v, sub) for l, v, sub in plan['kpi']]))
    s.append(Paragraph(_t('Ringkasan'), ST['h2']))
    s.append(_ai_box('Disusun RM Copilot', plan['ringkasan']))
    for d in plan['hari']:
        s.append(Paragraph(_t(f"{d['hari']} · {d['tema']}"), ST['h2']))
        rows = [['Jam', 'Nasabah', 'Tujuan & produk', 'Peluang', 'Siapkan']]
        for it in d['item']:
            rows.append([it['jam'], P(f"<b>{it['nama']}</b><br/><font size='7' color='#4B5563'>{it['id']} · {it['info']}</font>", 'cell'),
                         it['tujuan'], it['peluang'], it['siapkan']])
        s.append(_table(rows, [12, 50, 62, 16, 40]))
    s.append(Paragraph(_t('Draf pesan (menunggu persetujuan)'), ST['h2']))
    for m in plan['pesan']:
        s.append(KeepTogether([P(f"<b>{m['ke']}</b> · {m['kanal']}", 'cell'), Spacer(1, 7), P(m['isi'], 'ai'), Spacer(1, 10)]))
    s.append(Paragraph(_t('Langkah agen'), ST['h2']))
    s.append(_table([['#', 'Alat', 'Hasil']] + [[str(i + 1), a, b] for i, (a, b) in enumerate(plan['jejak'])], [8, 70, 102]))
    s.append(Spacer(1, 6))
    s.append(P('Pesan dan jadwal baru terkirim setelah disetujui RM. Hasil kunjungan dicatat kembali ke log aksi RM dan dipakai mengkalibrasi ulang peluang konversi tiap kuartal.', 'small'))
    doc.build(s, onFirstPage=_footer_fn(f"Disusun RM Copilot · data per 30 Jun 2026 · bukan keputusan kredit · disetujui oleh {plan['rm']}"),
              onLaterPages=_footer_fn(f"Rencana kunjungan {plan['rm']} · {plan['minggu']}"))
    return buf
