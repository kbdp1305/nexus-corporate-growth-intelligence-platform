"""Tindak lanjut kunjungan: feedback RM, rencana lanjutan, pengajuan kunjungan, dan tiket koordinasi ke divisi lain.

Tabel (outputs/app/):
  feedback.csv    satu baris per kunjungan yang sudah diberi feedback
  requests.csv    pengajuan kunjungan (ke supervisor) dan tiket koordinasi (ke divisi); riwayat percakapan di kolom JSON
Divisi tujuan disarankan dari catatan RM lewat data/raw/issue_product_map.csv (kata kunci → isu → divisi).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from functools import lru_cache

import pandas as pd

from . import data, kalender as K
from .tables import CsvTable, now

DIVISI = {
    'kredit': 'Kredit Komersial (Analis Kredit)',
    'corporate': 'Corporate Banking',
    'risiko': 'Risiko Kredit / Remedial',
    'transaksi': 'Transaction Banking (Cash Mgmt, VA, Payroll)',
    'trade': 'Trade Finance & Treasury',
    'funding': 'Treasury / Funding',
    'legal': 'Legal & Compliance',
    'wealth': 'Wealth Management',
    'pricing': 'Pricing',
}
# teks departemen di issue_product_map / product_master → kunci divisi
_DEPT_KEYS = [('Remedial', 'risiko'), ('Risiko Kredit', 'risiko'), ('Corporate Banking', 'corporate'), ('Kredit Komersial', 'kredit'),
              ('Trade Finance', 'trade'), ('Transaction Banking', 'transaksi'), ('Treasury', 'funding'), ('Funding', 'funding'),
              ('Legal', 'legal'), ('Wealth', 'wealth'), ('Pricing', 'pricing')]
HASIL = ['Converted', 'Interested', 'Not interested', 'No response']
HASIL_ID = {'Converted': 'Setuju / onboarding', 'Interested': 'Tertarik, perlu tindak lanjut', 'Not interested': 'Tidak tertarik', 'No response': 'Tidak ada respons'}
PRIORITAS = ['Normal', 'Tinggi', 'Mendesak']
ST_PENGAJUAN = ['Diajukan', 'Disetujui', 'Ditolak', 'Dibatalkan']
ST_TIKET = ['Baru', 'Diproses', 'Selesai', 'Ditolak']

FEEDBACK = CsvTable('feedback.csv', ['id', 'event_id', 'rm_id', 'company_id', 'tanggal', 'kanal', 'hasil', 'produk', 'catatan', 'keberatan', 'isu',
                                     'langkah_lanjut', 'jadwal_lanjut_id', 'pertimbangan_ulang', 'tiket', 'dibuat_oleh', 'dibuat_pada'])
REQ = CsvTable('requests.csv', ['id', 'jenis', 'rm_id', 'company_id', 'divisi', 'judul', 'isi', 'prioritas', 'tenggat', 'status', 'ref',
                                'usulan_mulai', 'usulan_selesai', 'kanal', 'divisi_terlibat', 'event_id', 'riwayat', 'dibuat_oleh', 'dibuat_pada', 'diubah_pada'])


def dept_keys(text) -> list[str]:
    out = []
    for frag, k in _DEPT_KEYS:
        if frag.lower() in str(text).lower() and k not in out:
            out.append(k)
    return out


@lru_cache(maxsize=1)
def issues():
    f = data.ROOT / 'data/raw/issue_product_map.csv'
    return pd.read_csv(f).set_index('issue_id') if f.exists() else pd.DataFrame(columns=['issue_name', 'keywords', 'solution_products', 'department', 'hold_credit'])


@lru_cache(maxsize=1)
def products():
    f = data.ROOT / 'data/raw/product_master.csv'
    return pd.read_csv(f).set_index('product_id') if f.exists() else pd.DataFrame(columns=['product_name', 'owner_department'])


def suggest(note: str, prods=()):
    """Catatan + produk dibahas → (isu terdeteksi, divisi disarankan, ada isu yang menahan kredit)."""
    iss, t = issues(), str(note).lower()
    hit = [i for i, r in iss.iterrows() if any(k.strip() and k.strip() in t for k in str(r.keywords).split('|'))]
    div = []
    for i in hit:
        div += [k for k in dept_keys(iss.loc[i, 'department']) if k not in div]
    pm = products()
    for p in prods:
        if p in pm.index:
            div += [k for k in dept_keys(pm.loc[p, 'owner_department']) if k not in div]
    hold = any(str(iss.loc[i, 'hold_credit']).lower() == 'true' for i in hit)
    return hit, div, hold


# ------------------------------------------------------------------ saran rencana lanjutan & jadwal ulang
_TIMBANG = ('pertimbang', 'menimbang', 'diskusi internal', 'diskusikan', 'rapat direksi', 'persetujuan direksi', 'persetujuan pusat', 'belum memutuskan',
            'belum bisa memutuskan', 'dikabari', 'kabari', 'membandingkan', 'bandingkan', 'pikir-pikir', 'pikir dulu', 'nanti dulu', 'menunggu', 'tunggu')
JAM_KERJA = (8, 16)                              # slot jadwal ulang: hari kerja, jam 08.00–16.00


def needs_reconsider(hasil, catatan, keberatan) -> bool:
    """Nasabah belum memutuskan: menimbang ulang, diskusi internal, menunggu persetujuan, atau tertarik tapi ada keberatan."""
    if hasil == 'Converted':
        return False
    t = f'{catatan} {keberatan}'.lower()
    return any(k in t for k in _TIMBANG) or (hasil == 'Interested' and bool(str(keberatan).strip()))


def history(cid, exclude_event='') -> pd.DataFrame:
    """Feedback kunjungan sebelumnya ke perusahaan yang sama, terbaru dulu."""
    fb = FEEDBACK.load()
    return fb[(fb.company_id == cid) & (fb.event_id != exclude_event)].sort_values('tanggal', ascending=False) if cid else fb.iloc[0:0]


def free_slot(rm, start: datetime, menit=60) -> datetime:
    """Slot hari kerja pertama mulai `start` yang tidak bentrok dengan jadwal Terjadwal milik RM (langkah 30 menit, maks. 30 hari)."""
    cal = K.for_rm(rm)
    cal = cal[cal.status == 'Terjadwal']
    busy = [(datetime.fromisoformat(m), datetime.fromisoformat(s) if s else datetime.fromisoformat(m) + timedelta(minutes=60))
            for m, s in zip(cal.mulai, cal.selesai) if m]
    t, end = start, start + timedelta(days=30)
    h0, m0 = (start.hour, start.minute) if JAM_KERJA[0] <= start.hour < JAM_KERJA[1] else (JAM_KERJA[0], 0)
    while t < end:
        if t.weekday() >= 5 or t.hour < JAM_KERJA[0]:          # akhir pekan / terlalu pagi → jam usulan di hari (kerja) berikutnya
            t = t.replace(hour=h0, minute=m0) + timedelta(days=1 if t.weekday() >= 5 else 0)
            continue
        e = t + timedelta(minutes=menit)
        if e > t.replace(hour=JAM_KERJA[1], minute=0):
            t = t.replace(hour=h0, minute=m0) + timedelta(days=1)
            continue
        if not any(t < b1 and e > b0 for b0, b1 in busy):
            return t
        t += timedelta(minutes=30)
    return start


# ------------------------------------------------------------------ riwayat percakapan tiket
def thread(row) -> list:
    try:
        return json.loads(row['riwayat']) if row['riwayat'] else []
    except (ValueError, TypeError):
        return []


def _entry(user, pesan, status=None):
    return {'waktu': now(), 'oleh': user, 'pesan': pesan, **({'status': status} if status else {})}


def reply(req_id, user, pesan, status=None):
    df = REQ.load(); row = df[df.id == req_id].iloc[0]
    th = thread(row) + [_entry(user, pesan, status)]
    REQ.update(req_id, riwayat=json.dumps(th, ensure_ascii=False), diubah_pada=now(), **({'status': status} if status else {}))


# ------------------------------------------------------------------ tiket koordinasi
def create_tickets(divs, *, jenis, rm_id, company_id, judul, isi, prioritas='Normal', tenggat='', ref='', event_id='', user=''):
    rows = [{'jenis': jenis, 'rm_id': rm_id, 'company_id': company_id, 'divisi': d, 'judul': judul, 'isi': isi, 'prioritas': prioritas,
             'tenggat': str(tenggat or ''), 'status': 'Baru', 'ref': ref, 'event_id': event_id,
             'riwayat': json.dumps([_entry(user, 'Tiket dibuat', 'Baru')], ensure_ascii=False), 'dibuat_oleh': user, 'dibuat_pada': now()} for d in divs]
    _, _, ids = REQ.upsert(rows, {'diubah_pada': now()}) if rows else (0, 0, [])
    return ids


# ------------------------------------------------------------------ feedback kunjungan
def pending_feedback(rm) -> pd.DataFrame:
    """Kunjungan/telepon yang sudah lewat (atau ditandai selesai) dan belum diberi feedback."""
    cal = K.for_rm(rm)
    if cal.empty:
        return cal
    done = set(FEEDBACK.load().event_id)
    m = pd.to_datetime(cal.mulai, errors='coerce')
    due = cal[(cal.kanal.isin(['Kunjungan', 'Telepon'])) & (cal.status != 'Dibatalkan') & ((m <= pd.Timestamp(datetime.now())) | (cal.status == 'Selesai'))
              & ~cal.id.isin(done)]
    return due.assign(_m=m[due.index]).sort_values('_m', ascending=False)   # m[due.index]: frame kosong tetap kosong


def save_feedback(store, ev: dict, *, hasil, produk, catatan, keberatan, isu, langkah, lanjut, divs, prioritas, tenggat, pesan_divisi, user, ulang=False):
    """Simpan feedback + (opsional) jadwal lanjutan + tiket koordinasi; tandai jadwal selesai; catat ke log aksi RM."""
    cid, rm = ev['company_id'], ev['rm_id']
    nama = store.co.name.get(cid, cid)
    follow_id = ''
    if lanjut:                                   # (mulai, selesai, kanal)
        m, s, kanal = lanjut
        follow_id = uuid.uuid4().hex[:12]
        _, _, rej = K.upsert([{'id': follow_id, 'rm_id': rm, 'company_id': cid, 'judul': f'{nama} ({cid}) · ' + ('jadwal ulang (pertimbangan ulang)' if ulang else 'tindak lanjut'), 'kanal': kanal,
                               'mulai': m.isoformat(timespec='minutes'), 'selesai': s.isoformat(timespec='minutes'),
                               'lokasi': ev.get('lokasi', ''), 'catatan': f'Tindak lanjut kunjungan {ev["mulai"][:10]}: {langkah}',
                               'status': 'Terjadwal', 'sumber': 'Tindak lanjut'}], user)
        if rej:                                  # bentrok / dipegang RM lain → batalkan seluruh simpan
            raise ValueError(f'Jadwal lanjutan tidak bisa dibuat: {rej[0][1]} Pilih waktu lain atau matikan jadwal lanjutan.')
    fb_id = f"FB-{ev['id']}"
    pnames = ', '.join(f"{p} {products().product_name.get(p, '')}".strip() for p in produk) or '—'
    isi = (f"Hasil kunjungan {ev['mulai'][:10]} ({ev['kanal']}) oleh {rm}: {HASIL_ID.get(hasil, hasil)}.\n"
           f"Produk dibahas: {pnames}.\nCatatan RM: {catatan}\n" + (f"Keberatan: {keberatan}\n" if keberatan else '')
           + (f"Isu: {', '.join(issues().issue_name.get(i, i) for i in isu)}\n" if isu else '') + (f"Langkah lanjut: {langkah}\n" if langkah else '')
           + (f"Permintaan ke divisi: {pesan_divisi}" if pesan_divisi else ''))
    tickets = create_tickets(divs, jenis='Koordinasi hasil kunjungan', rm_id=rm, company_id=cid, judul=f'Hasil kunjungan {nama}', isi=isi,
                             prioritas=prioritas, tenggat=tenggat, ref=fb_id, event_id=ev['id'], user=user)
    FEEDBACK.upsert([{'id': fb_id, 'event_id': ev['id'], 'rm_id': rm, 'company_id': cid, 'tanggal': ev['mulai'][:10], 'kanal': ev['kanal'],
                      'hasil': hasil, 'produk': ';'.join(produk), 'catatan': catatan, 'keberatan': keberatan, 'isu': ';'.join(isu), 'langkah_lanjut': langkah,
                      'jadwal_lanjut_id': follow_id, 'pertimbangan_ulang': 'ya' if ulang else '', 'tiket': ';'.join(tickets), 'dibuat_oleh': user, 'dibuat_pada': now()}])
    K.set_status(ev['id'], 'Selesai', user)
    if cid in store.co.index:                    # format sama dengan log aksi RM → muncul di Profil › Riwayat
        store.append_visit({'action_id': f"APP-{fb_id}", 'track': 'Deepening' if store.cox.is_client.get(cid, False) else 'Acquisition', 'party_id': cid,
                            'product_id': produk[0] if produk else '', 'rm_id': rm, 'contact_date': ev['mulai'][:10], 'channel': ev['kanal'],
                            'tier_at_contact': '', 'response': hasil, 'converted': int(hasil == 'Converted'), 'deal_value_idr_mn': 0.0, 'rm_rating': '',
                            'feedback_note': f"{catatan} | keberatan: {keberatan or '-'} | lanjut: {langkah or '-'}"})
    data.audit('feedback_kunjungan', user=user, rm=rm, company=cid, hasil=hasil, tiket=len(tickets), jadwal_lanjut=bool(follow_id), pertimbangan_ulang=ulang)
    return fb_id, follow_id, tickets


# ------------------------------------------------------------------ pengajuan kunjungan
def submit_visit(*, rm_id, company_id, nama, mulai, selesai, kanal, tujuan, produk, divs, catatan, user):
    why = K.check(K.load(), {'id': '', 'rm_id': rm_id, 'company_id': company_id, 'status': 'Terjadwal',
                             'mulai': mulai.isoformat(timespec='minutes'), 'selesai': selesai.isoformat(timespec='minutes')})
    if why:
        raise ValueError(why)
    isi = f"Tujuan: {tujuan}\nProduk dibawa: {', '.join(produk) or '—'}\n" + (f"Catatan: {catatan}" if catatan else '')
    _, _, ids = REQ.upsert([{'jenis': 'Pengajuan kunjungan', 'rm_id': rm_id, 'company_id': company_id, 'divisi': '', 'judul': f'Kunjungan ke {nama}',
                             'isi': isi, 'prioritas': 'Normal', 'status': 'Diajukan', 'usulan_mulai': mulai.isoformat(timespec='minutes'),
                             'usulan_selesai': selesai.isoformat(timespec='minutes'), 'kanal': kanal, 'divisi_terlibat': ';'.join(divs),
                             'riwayat': json.dumps([_entry(user, 'Pengajuan dibuat', 'Diajukan')], ensure_ascii=False),
                             'dibuat_oleh': user, 'dibuat_pada': now()}], {'diubah_pada': now()})
    data.audit('ajukan_kunjungan', user=user, rm=rm_id, company=company_id, mulai=str(mulai), divisi=divs)
    return ids[0]


def decide_visit(store, req: dict, approve: bool, komentar, user):
    if not approve:
        reply(req['id'], user, komentar or 'Ditolak', 'Ditolak')
        data.audit('tolak_pengajuan', user=user, id=req['id'])
        return None, []
    cid = req['company_id']; nama = store.co.name.get(cid, cid)
    divs = [d for d in req['divisi_terlibat'].split(';') if d]
    ev_id = f"PJ-{req['id']}"
    _, _, rej = K.upsert([{'id': ev_id, 'rm_id': req['rm_id'], 'company_id': cid, 'judul': f'{nama} ({cid})', 'kanal': req['kanal'], 'mulai': req['usulan_mulai'],
                           'selesai': req['usulan_selesai'], 'lokasi': f"Kec. {store.cox.district.get(cid, '')}" if cid in store.cox.index else '',
                           'catatan': req['isi'] + (f"\nDidampingi: {', '.join(DIVISI.get(d, d) for d in divs)}" if divs else ''),
                           'status': 'Terjadwal', 'sumber': 'Pengajuan'}], user)
    if rej:                                      # pengajuan tetap Diajukan; supervisor bisa menolak atau RM mengajukan ulang
        raise ValueError(f'Belum bisa disetujui: {rej[0][1]}')
    m = datetime.fromisoformat(req['usulan_mulai'])
    tickets = create_tickets(divs, jenis='Pendampingan kunjungan', rm_id=req['rm_id'], company_id=cid, judul=f'Pendampingan kunjungan ke {nama}',
                             isi=f"{req['rm_id']} mengajak divisi Anda mendampingi {req['kanal'].lower()} ke {nama} pada {m:%A %d %b %Y, %H.%M} WIB.\n{req['isi']}",
                             prioritas='Normal', tenggat=m.date(), ref=req['id'], event_id=ev_id, user=user)
    REQ.update(req['id'], event_id=ev_id)
    reply(req['id'], user, (komentar or 'Disetujui') + (f" · {len(tickets)} divisi diberi tahu" if tickets else ''), 'Disetujui')
    data.audit('setujui_pengajuan', user=user, id=req['id'], jadwal=ev_id, tiket=len(tickets))
    return ev_id, tickets


# ------------------------------------------------------------------ tampilan per pengguna
def visible_requests(user) -> pd.DataFrame:
    df = REQ.load()
    if user['role'] == 'supervisor':
        return df
    if user['role'] == 'divisi':
        return df[(df.jenis != 'Pengajuan kunjungan') & (df.divisi == user['rm_id'])]
    return df[df.rm_id == user['rm_id']]


def badge_counts(user) -> dict:
    df = visible_requests(user)
    if user['role'] == 'divisi':
        return {'tiket baru': int((df.status == 'Baru').sum())}
    out = {'feedback tertunda': len(pending_feedback(user['rm_id'] if user['role'] == 'rm' else 'Semua RM'))}
    if user['role'] == 'supervisor':
        out['pengajuan menunggu'] = int(((df.jenis == 'Pengajuan kunjungan') & (df.status == 'Diajukan')).sum())
    return out
