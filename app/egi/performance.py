"""Perhitungan kinerja dari catatan kontak, bukan transaksi terverifikasi."""
import pandas as pd


def contacts(log, rm):
    frame = log[log.rm_id == rm].copy()
    frame['tanggal'] = pd.to_datetime(frame.contact_date, errors='coerce').dt.normalize()
    frame = frame.dropna(subset=['tanggal'])
    frame['deal_value_idr_mn'] = pd.to_numeric(frame.deal_value_idr_mn, errors='coerce').fillna(0)
    frame['converted'] = pd.to_numeric(frame.converted, errors='coerce').fillna(0)
    frame['is_conversion'] = frame.response.eq('Converted') | frame.converted.eq(1)
    return frame.sort_values('tanggal', kind='stable')


def between(frame, start, end):
    return frame[frame.tanggal.between(pd.Timestamp(start), pd.Timestamp(end))].copy()


def product_contacts(frame):
    frame = frame.copy()
    frame['product_id'] = frame.product_id.fillna('').astype(str).str.split(';')
    return frame.explode('product_id')


def first_conversions(frame):
    return product_contacts(frame[frame.is_conversion]).drop_duplicates(['party_id', 'product_id'], keep='first')


def metrics(frame, start, end):
    selected = between(frame, start, end)
    wins = between(first_conversions(frame), start, end)
    return {'companies': selected.party_id.nunique(), 'contacts': len(selected),
            'conversions': len(wins), 'deal_bn': selected.deal_value_idr_mn.sum() / 1000}


def pipeline(frame, end):
    history = product_contacts(frame[frame.tanggal <= pd.Timestamp(end)])
    latest = history.groupby(['party_id', 'product_id'], dropna=False).tail(1)
    closed = pd.MultiIndex.from_frame(first_conversions(history)[['party_id', 'product_id']])
    keys = pd.MultiIndex.from_frame(latest[['party_id', 'product_id']])
    result = latest[latest.response.eq('Interested') & ~keys.isin(closed)].copy()
    result['hari_menunggu'] = (pd.Timestamp(end) - result.tanggal).dt.days
    return result.sort_values('tanggal', kind='stable')
