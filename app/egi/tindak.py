"""Tindak lanjut kunjungan: feedback RM, rencana lanjutan, pengajuan kunjungan, dan tiket koordinasi ke divisi lain.

Tabel (outputs/app/):
  feedback.csv    satu baris per kunjungan yang sudah diberi feedback
  kegiatan.csv    satu baris per kegiatan lanjutan yang disetujui RM; status & tenggat untuk pelacakan progres
  requests.csv    pengajuan kunjungan (ke supervisor) dan tiket koordinasi (ke divisi); riwayat percakapan di kolom JSON
Divisi tujuan disarankan dari catatan RM lewat data/raw/issue_product_map.csv (kata kunci → isu → divisi).
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from functools import lru_cache

import pandas as pd

from . import data, kalender as K
from .tables import CsvTable, now, transactional

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
ST_TIKET = ['Baru', 'Diproses', 'Dikonfirmasi', 'Selesai', 'Ditolak', 'Dibatalkan']

FEEDBACK = CsvTable('feedback.csv', ['id', 'event_id', 'rm_id', 'company_id', 'tanggal', 'kanal', 'hasil', 'produk', 'catatan', 'keberatan', 'isu',
                                     'langkah_lanjut', 'jadwal_lanjut_id', 'pertimbangan_ulang', 'tiket', 'dibuat_oleh', 'dibuat_pada'])
KEGIATAN = CsvTable('kegiatan.csv', ['id', 'feedback_id', 'event_id', 'rm_id', 'company_id', 'tanggal_kunjungan', 'urutan', 'judul', 'aksi', 'pemilik',
                                     'divisi', 'sumber', 'jenis', 'jadwal', 'kal_id', 'tenggat', 'status', 'selesai_pada', 'n_jadwal_ulang', 'alasan',
                                     'riwayat', 'dibuat_oleh', 'dibuat_pada', 'diubah_pada'])
ALASAN_ULANG = ['Nasabah minta diundur', 'PIC nasabah berhalangan', 'Menunggu dokumen / data nasabah', 'Bentrok jadwal RM',
                'Menunggu respons divisi', 'Lainnya']
ALASAN_BATAL = ['Nasabah membatalkan', 'Tidak relevan lagi', 'Digantikan kegiatan lain', 'Produk ditahan (risiko / legal)', 'Lainnya']
SUMBER_PROGRES = ('Progress kegiatan', 'Rapat dadakan')   # sumber jadwal kalender yang berasal dari tahap kegiatan
JENIS_DADAKAN = {'Rapat internal': 'Rapat internal', 'Rapat dengan nasabah': 'Kunjungan', 'Kunjungan nasabah': 'Kunjungan',
                 'Telepon nasabah': 'Telepon'}          # jenis kegiatan dadakan → kanal kalender
REQ = CsvTable('requests.csv', ['id', 'jenis', 'rm_id', 'company_id', 'divisi', 'judul', 'isi', 'prioritas', 'tenggat', 'status', 'ref',
                                'usulan_mulai', 'usulan_selesai', 'kanal', 'divisi_terlibat', 'event_id', 'kegiatan_id', 'riwayat', 'dibuat_oleh', 'dibuat_pada', 'diubah_pada'])


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
    cal = cal[cal.status != 'Dibatalkan']
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


def ticket_status_options(row, actor):
    if actor['role'] == 'rm':
        return ['Dibatalkan'] if row['rm_id'] == actor['rm_id'] and row['status'] in ('Baru', 'Diproses', 'Dikonfirmasi', 'Ditolak') else []
    if actor['role'] == 'divisi' and row['divisi'] != actor['rm_id']:
        return []
    transitions = {'Baru': ['Diproses', 'Ditolak'], 'Diproses': ['Selesai', 'Ditolak'],
                   'Selesai': [], 'Ditolak': [], 'Dibatalkan': []}
    if row['jenis'] in ('Pendampingan kunjungan', 'Undangan rapat dadakan'):
        transitions = {'Baru': ['Dikonfirmasi', 'Ditolak'], 'Dikonfirmasi': ['Selesai', 'Ditolak']}
    return transitions.get(row['status'], []) if actor['role'] in ('divisi', 'supervisor') else []


@transactional
def reply(req_id, user, pesan, status=None):
    df = REQ.load(); row = df[df.id == req_id].iloc[0]
    from . import auth
    actor = auth.current()
    if not actor or req_id not in set(visible_requests(actor).id):
        raise ValueError('Tiket berada di luar akses akun Anda.')
    if row.jenis == 'Pengajuan kunjungan':
        allowed = ['Disetujui', 'Ditolak', 'Dibatalkan'] if actor['role'] == 'supervisor' else ['Dibatalkan']
        if row.status != 'Diajukan':
            allowed = []
    else:
        allowed = ticket_status_options(row, actor)
    if status and status not in allowed:
        raise ValueError('Perubahan status ini tidak diizinkan untuk akun atau status tiket saat ini.')
    if status == 'Dikonfirmasi':
        ev = K.load().set_index('id')
        if row.event_id not in ev.index or ev.loc[row.event_id, 'status'] == 'Dibatalkan':
            raise ValueError('Agenda undangan sudah tidak tersedia.')
        invitation = ev.loc[row.event_id]
        for other in df[(df.divisi == row.divisi) & df.status.eq('Dikonfirmasi') & df.id.ne(req_id)].itertuples():
            if other.event_id in ev.index:
                booked = ev.loc[other.event_id]
                if booked.status != 'Dibatalkan' and pd.Timestamp(booked.mulai) < pd.Timestamp(invitation.selesai) and pd.Timestamp(booked.selesai) > pd.Timestamp(invitation.mulai):
                    raise ValueError('Divisi sudah mengonfirmasi agenda lain pada waktu tersebut.')
    th = thread(row) + [_entry(user, pesan, status)]
    REQ.update(req_id, riwayat=json.dumps(th, ensure_ascii=False), diubah_pada=now(), **({'status': status} if status else {}))
    if status == 'Selesai' and row.kegiatan_id:
        related = REQ.load()
        related = related[(related.kegiatan_id == row.kegiatan_id) & related.status.ne('Dibatalkan')]
        if len(related) and related.status.eq('Selesai').all():
            set_kegiatan(row.kegiatan_id, True, user)


# ------------------------------------------------------------------ tiket koordinasi
def create_tickets(divs, *, jenis, rm_id, company_id, judul, isi, prioritas='Normal', tenggat='', ref='', event_id='', kegiatan_id='', user=''):
    rows = [{'jenis': jenis, 'rm_id': rm_id, 'company_id': company_id, 'divisi': d, 'judul': judul, 'isi': isi, 'prioritas': prioritas,
             'tenggat': str(tenggat or ''), 'status': 'Baru', 'ref': ref, 'event_id': event_id, 'kegiatan_id': kegiatan_id,
             'riwayat': json.dumps([_entry(user, 'Tiket dibuat', 'Baru')], ensure_ascii=False), 'dibuat_oleh': user, 'dibuat_pada': now()} for d in divs]
    _, _, ids = REQ.upsert(rows, {'diubah_pada': now()}) if rows else (0, 0, [])
    return ids


# ------------------------------------------------------------------ eskalasi alarm (Copilot → divisi Risiko)
ESKALASI = 'Eskalasi alarm'


def open_escalations() -> set:
    """Perusahaan yang sudah punya tiket eskalasi alarm yang masih terbuka (supaya triase tidak menggandakan)."""
    df = REQ.load()
    return set(df[(df.jenis == ESKALASI) & df.status.isin(['Baru', 'Diproses'])].company_id)


def escalate(*, rm_id, company_id, nama, alasan, bukti=(), user=''):
    """Tiket ke divisi Risiko Kredit / Remedial berisi alasan + paket bukti; tenggat 3 hari kerja."""
    if company_id in open_escalations():
        return []
    isi = alasan + ('\n\nBukti:\n' + '\n'.join(f'- {b}' for b in bukti) if bukti else '')
    return create_tickets(['risiko'], jenis=ESKALASI, rm_id=rm_id, company_id=company_id, judul=f'Eskalasi alarm: {nama} ({company_id})',
                          isi=isi, prioritas='Tinggi', tenggat=(datetime.now() + timedelta(days=3)).date(), user=user)


# ------------------------------------------------------------------ feedback kunjungan
def pending_feedback(rm) -> pd.DataFrame:
    """Kunjungan/telepon yang sudah lewat (atau ditandai selesai) dan belum diberi feedback."""
    cal = K.for_rm(rm)
    if cal.empty:
        return cal
    done = set(FEEDBACK.load().event_id)
    m = pd.to_datetime(cal.mulai, errors='coerce')
    due = cal[(cal.kanal.isin(['Kunjungan', 'Telepon', 'Email'])) & (cal.company_id != '') & (cal.status != 'Dibatalkan') & ((m <= pd.Timestamp(datetime.now())) | (cal.status == 'Selesai'))
              & ~cal.id.isin(done) & ~cal.sumber.isin(SUMBER_PROGRES)]          # tahap progres / rapat dadakan dilacak di Progress kegiatan
    return due.assign(_m=m[due.index]).sort_values('_m', ascending=False)   # m[due.index]: frame kosong tetap kosong


def assignment_ids(store, rm, actor):
    from .profile_workspace import accessible_ids
    ids = accessible_ids(store, actor)
    return sorted(cid for cid in ids if not store.cox.is_client.get(cid, False) or store.co.rm_id.get(cid) == rm)


@transactional
def contact_event(store, rm, cid, mulai, kanal, user, reuse_existing=True):
    from . import auth
    if not auth.can_edit(rm) or cid not in assignment_ids(store, rm, auth.current()):
        raise ValueError('Perusahaan berada di luar cakupan akun Anda.')
    if mulai > datetime.now():
        raise ValueError('Hasil kontak tidak dapat dicatat untuk waktu mendatang.')
    calendar = K.for_rm(rm)
    matches = calendar[(calendar.company_id == cid) & (calendar.kanal == kanal)
                       & calendar.mulai.str.startswith(mulai.date().isoformat())
                       & calendar.status.ne('Dibatalkan') & ~calendar.sumber.isin(SUMBER_PROGRES)]
    matches = matches[pd.to_datetime(matches.mulai, errors='coerce', format='mixed') <= pd.Timestamp.now()]
    if reuse_existing and len(matches) > 1:
        raise ValueError('Ada beberapa agenda pada hari ini. Pilih agenda yang tepat di Feedback kunjungan.')
    if reuse_existing and len(matches):
        return matches.iloc[0].to_dict()
    event_id = f'CONTACT-{rm}-{cid}-{mulai:%Y%m%d%H%M}-{kanal}'
    row = dict(id=event_id, rm_id=rm, company_id=cid, judul=store.co.name.get(cid, cid), kanal=kanal,
               mulai=mulai.isoformat(timespec='minutes'), selesai=(mulai + timedelta(minutes=15)).isoformat(timespec='minutes'),
               status='Selesai', sumber='Kontak tanpa jadwal')
    _, _, rejected = K.upsert([row], user)
    if rejected:
        raise ValueError(rejected[0][1])
    return row


@transactional
def record_contact(store, row, user, event_id=None):
    """All contact entry points share the same event and feedback identity."""
    if event_id:
        ev = K.load().set_index('id').loc[event_id].to_dict() | {'id': event_id}
        if ev['company_id'] != row['party_id'] or ev['rm_id'] != row['rm_id']:
            raise ValueError('Agenda tidak sesuai dengan perusahaan atau RM aktif.')
    else:
        day = date.fromisoformat(row['contact_date'])
        ev = contact_event(store, row['rm_id'], row['party_id'], datetime.combine(day, datetime.now().time()),
                           row['channel'], user)
    previous = FEEDBACK.load().loc[lambda f: f.event_id == ev['id']]
    if len(previous) and previous.iloc[0].catatan != row['feedback_note']:
        raise ValueError('Agenda ini sudah memiliki feedback. Untuk kontak lain, buat kontak tanpa jadwal atau pilih agenda lain di Tindak lanjut kunjungan.')
    return save_feedback(store, ev, hasil=row['response'], produk=[p.strip() for p in str(row.get('product_id') or '').split(';') if p.strip()],
                         catatan=row['feedback_note'], keberatan='', isu=[], langkah='', lanjut=None, divs=[],
                         prioritas='Normal', tenggat='', pesan_divisi='', user=user)


@transactional
def save_feedback(store, ev: dict, *, hasil, produk, catatan, keberatan, isu, langkah, lanjut, divs, prioritas, tenggat, pesan_divisi, user, ulang=False,
                  kegiatan=()):
    """Simpan feedback + (opsional) jadwal lanjutan + tiket koordinasi; tandai jadwal selesai; catat ke log aksi RM."""
    from . import auth
    current_event = K.load().loc[lambda f: f.id == ev['id']]
    if current_event.empty or current_event.iloc[0].status == 'Dibatalkan':
        raise ValueError('Agenda sudah tidak tersedia atau dibatalkan. Muat ulang halaman.')
    ev = current_event.iloc[0].to_dict()
    cid, rm = ev['company_id'], ev['rm_id']
    if not auth.can_edit(rm) or cid not in assignment_ids(store, rm, auth.current()):
        raise ValueError('Hanya RM pemilik atau supervisor yang dapat menyimpan feedback.')
    if pd.Timestamp(ev['mulai']) > pd.Timestamp.now():
        raise ValueError('Waktu kunjungan masih mendatang. Sesuaikan tanggal/jam aktual di kalender sebelum mencatat hasil.')
    if ev.get('sumber') in SUMBER_PROGRES:
        raise ValueError('Agenda ini merupakan tahap kegiatan; perbarui melalui Progress kegiatan.')
    existing = FEEDBACK.load()
    previous = existing[existing.event_id == ev['id']]
    if len(previous):
        old = previous.iloc[0]
        return old.id, old.jadwal_lanjut_id, [x for x in old.tiket.split(';') if x]
    if not catatan.strip() or hasil not in HASIL:
        raise ValueError('Isi hasil dan catatan kontak yang valid.')
    if hasil == 'Converted' and not produk:
        raise ValueError('Pilih produk yang disetujui/onboarding agar hasil konversi dapat dicatat dengan benar.')
    if any(product not in products().index for product in produk):
        raise ValueError('Produk tidak dikenal. Gunakan kode produk dari daftar produk yang tersedia.')
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
    linked_divs = {d for k in kegiatan for d in division_keys(k.get('divisi')) + division_keys(k.get('pemilik'))}
    tickets = create_tickets([d for d in divs if d not in linked_divs], jenis='Koordinasi hasil kunjungan', rm_id=rm, company_id=cid, judul=f'Hasil kunjungan {nama}', isi=isi,
                             prioritas=prioritas, tenggat=tenggat, ref=fb_id, event_id=ev['id'], user=user)
    FEEDBACK.upsert([{'id': fb_id, 'event_id': ev['id'], 'rm_id': rm, 'company_id': cid, 'tanggal': ev['mulai'][:10], 'kanal': ev['kanal'],
                      'hasil': hasil, 'produk': ';'.join(produk), 'catatan': catatan, 'keberatan': keberatan, 'isu': ';'.join(isu), 'langkah_lanjut': langkah,
                      'jadwal_lanjut_id': follow_id, 'pertimbangan_ulang': 'ya' if ulang else '', 'tiket': ';'.join(tickets), 'dibuat_oleh': user, 'dibuat_pada': now()}])
    prepared = [{**k, 'pesan': k.get('pesan') or pesan_divisi or k['aksi']} for k in kegiatan]
    save_kegiatan(fb_id, ev, prepared, user, nama=nama)
    task_ids = set(KEGIATAN.load().loc[lambda f: f.feedback_id == fb_id, 'id'])
    tickets += list(REQ.load().loc[lambda f: f.kegiatan_id.isin(task_ids), 'id'])
    FEEDBACK.update(fb_id, tiket=';'.join(tickets))
    K.set_status(ev['id'], 'Selesai', user)
    if cid in store.co.index:                    # format sama dengan log aksi RM → muncul di Profil › Riwayat
        store.append_visit({'action_id': f"APP-{fb_id}", 'track': 'Deepening' if store.cox.is_client.get(cid, False) else 'Acquisition', 'party_id': cid,
                            'product_id': ';'.join(dict.fromkeys(produk)), 'event_id': ev['id'], 'rm_id': rm, 'contact_date': ev['mulai'][:10], 'channel': ev['kanal'],
                            'tier_at_contact': '', 'response': hasil, 'converted': int(hasil == 'Converted'), 'deal_value_idr_mn': 0.0, 'rm_rating': '',
                            'feedback_note': f"{catatan} | keberatan: {keberatan or '-'} | lanjut: {langkah or '-'}"})
    data.audit('feedback_kunjungan', user=user, rm=rm, company=cid, hasil=hasil, tiket=len(tickets), jadwal_lanjut=bool(follow_id), pertimbangan_ulang=ulang)
    return fb_id, follow_id, tickets


# ------------------------------------------------------------------ progres kegiatan lanjutan
def division_keys(value):
    values = value if isinstance(value, list) else [value] if value else []
    reverse = {v: k for k, v in DIVISI.items()}
    return list(dict.fromkeys(v if v in DIVISI else reverse[v] for v in values if v in DIVISI or v in reverse))


@transactional
def save_kegiatan(fb_id, ev: dict, kegiatan, user, nama=''):
    """Kegiatan selanjutnya (saran AI dicentang + manual) → satu baris per kegiatan, tenggat jadi tanggal, status 'Belum';
    setiap tahap langsung dipasang di Kalender kunjungan RM pada tanggal tenggatnya."""
    rows = []
    for i, k in enumerate(kegiatan, 1):
        dv = k.get('divisi')
        dv = [DIVISI.get(x, x) for x in dv] if isinstance(dv, list) else ([dv] if dv else [])
        rows.append({'id': f'{fb_id}-{i}', 'feedback_id': fb_id, 'event_id': ev['id'], 'rm_id': ev['rm_id'], 'company_id': ev['company_id'],
                     'tanggal_kunjungan': ev['mulai'][:10], 'urutan': i, 'judul': k.get('judul') or k['aksi'][:60], 'aksi': k['aksi'],
                     'pemilik': k.get('pemilik') or 'RM', 'divisi': ';'.join(dv), 'sumber': k.get('sumber', ''),
                     'jenis': 'Kegiatan', 'tenggat': (date.today() + timedelta(days=int(k.get('tenggat_hari') or 0))).isoformat(), 'status': 'Belum',
                     'selesai_pada': '', 'n_jadwal_ulang': 0, 'riwayat': json.dumps([_entry(user, 'Dibuat dari feedback kunjungan')], ensure_ascii=False),
                     'dibuat_oleh': user, 'dibuat_pada': now()})
    for r in rows:
        r['kal_id'], r['jadwal'] = pasang_kalender(r, nama, user)
    if rows:
        KEGIATAN.upsert(rows, {'diubah_pada': now()})
        for row, activity in zip(rows, kegiatan):
            divs = list(dict.fromkeys(division_keys(activity.get('divisi')) + division_keys(activity.get('pemilik'))))
            create_tickets(divs, jenis='Koordinasi kegiatan', rm_id=row['rm_id'], company_id=row['company_id'],
                           judul=f"{row['judul']} · {nama}", isi=activity.get('pesan') or row['aksi'],
                           prioritas=activity.get('prioritas', 'Normal'), tenggat=row['tenggat'],
                           ref=fb_id, event_id=ev['id'], kegiatan_id=row['id'], user=user)
    return len(rows)


def _buat_jadwal(row: dict, mulai: datetime, kanal, nama, user, status='Terjadwal', catatan=''):
    """Satu jadwal kalender untuk satu tahap kegiatan. → id jadwal."""
    dur = timedelta(minutes=K.R.DURASI_MENIT.get(kanal, 60))
    event_id = uuid.uuid4().hex[:12]
    _, _, rejected = K.upsert([{'id': event_id, 'rm_id': row['rm_id'], 'company_id': row['company_id'],
                             'judul': f"{nama or row['company_id']} ({row['company_id']}) · {row['judul']}", 'kanal': kanal,
                             'mulai': mulai.isoformat(timespec='minutes'), 'selesai': (mulai + dur).isoformat(timespec='minutes'), 'lokasi': '',
                             'catatan': f"Tahap {row['urutan']} tindak lanjut kunjungan {row['tanggal_kunjungan']}: {row['aksi']}" + (f"\n{catatan}" if catatan else ''),
                             'status': status, 'sumber': 'Progress kegiatan'}], user)
    if rejected:
        raise ValueError(rejected[0][1])
    return event_id


def pasang_kalender(row: dict, nama, user):
    """Tahap bertenggat → jadwal di kalender pada tanggal tenggat (slot kosong mulai 10.00, tidak melewati tenggat).
    Status kalender mengikuti status tahap. → (id jadwal, waktu mulai iso)."""
    kanal = kanal_kegiatan(row)
    tg = date.fromisoformat(str(row['tenggat'])[:10])
    workday = tg
    while workday.weekday() >= 5:
        workday -= timedelta(days=1)
    if workday < date.today() and row.get('status') not in ('Selesai', 'Dibatalkan'):
        raise ValueError('Tenggat tidak memiliki hari kerja yang tersedia. Ubah tenggat kegiatan.')
    awal = datetime.combine(workday, datetime.strptime('10:00', '%H:%M').time())
    if workday == date.today() and row.get('status') not in ('Selesai', 'Dibatalkan'):
        awal = max(awal, datetime.now().replace(second=0, microsecond=0) + timedelta(minutes=30))
    m = free_slot(row['rm_id'], awal, K.R.DURASI_MENIT.get(kanal, 60))
    if m.date() > tg:
        raise ValueError(f'Tidak ada slot kerja kosong pada tenggat {tg}. Ubah tenggat kegiatan sebelum menyimpan.')
    status = {'Selesai': 'Selesai', 'Dibatalkan': 'Dibatalkan'}.get(row.get('status'), 'Terjadwal')
    return _buat_jadwal(row, m, kanal, nama, user, status), m.isoformat(timespec='minutes')


@transactional
def sinkron_kalender(rm, nama_of, user) -> int:
    """Tahap yang belum punya jadwal kalender (mis. dibuat sebelum fitur ini) → dipasang di kalender. → jumlah yang dipasang."""
    df = KEGIATAN.load()
    df = df if rm == 'Semua RM' else df[df.rm_id == rm]
    if df.empty:
        return 0
    ada = set(K.load().id)
    n = 0
    perlu = ~df.kal_id.isin(ada) & (df.status != 'Dibatalkan') & ~((df.sumber == 'Dadakan') & (df.kal_id == ''))   # dadakan tanpa kalender = pilihan RM
    for r in df[perlu].to_dict('records'):
        kal_id, jadwal = pasang_kalender(r, nama_of(r['company_id']), user)
        KEGIATAN.update(r['id'], kal_id=kal_id, jadwal=r['jadwal'] or jadwal, diubah_pada=now())
        n += 1
    return n


def kegiatan_for(rm) -> pd.DataFrame:
    """Kegiatan lanjutan milik RM (atau semua) + status tampilan: selesai (hijau), terlambat (merah, lewat tenggat), berjalan."""
    df = KEGIATAN.load()
    df = df if rm == 'Semua RM' else df[df.rm_id == rm]
    if df.empty:
        return df.assign(status_tampil=pd.Series(dtype=str), sisa_hari=pd.Series(dtype=float))
    sisa = (pd.to_datetime(df.tenggat, errors='coerce') - pd.Timestamp(date.today())).dt.days
    status = (pd.Series('berjalan', index=df.index).mask(sisa < 0, 'terlambat').mask(df.status == 'Selesai', 'selesai')
              .mask(df.status == 'Dibatalkan', 'batal'))
    waktu = pd.to_datetime(df.jadwal.where((df.jadwal != '') & (df.kal_id != ''), df.tenggat), errors='coerce')   # jadwal kalender, atau tenggat
    return df.assign(status_tampil=status, sisa_hari=sisa, urutan=pd.to_numeric(df.urutan, errors='coerce'), waktu=waktu,
                     n_jadwal_ulang=pd.to_numeric(df.n_jadwal_ulang, errors='coerce').fillna(0).astype(int))


def _catat(kid, user, pesan, **fields):
    """Perbarui satu kegiatan + tambahkan entri ke riwayat perubahannya."""
    row = KEGIATAN.load().set_index('id').loc[kid]
    th = thread(row) + [_entry(user, pesan)]
    KEGIATAN.update(kid, riwayat=json.dumps(th, ensure_ascii=False), diubah_pada=now(), **fields)


def completion_block(kid):
    tickets = REQ.load()
    pending = tickets[(tickets.kegiatan_id == kid) & ~tickets.status.isin(['Selesai', 'Dibatalkan'])]
    return 'Tunggu hasil divisi; tiket terkait belum selesai.' if len(pending) else None


def sync_calendar_event(event_id, user):
    """Calendar changes update linked task, without recursively saving calendar."""
    ev = K.load().set_index('id').loc[event_id]
    for ticket in REQ.load().loc[lambda f: (f.event_id == event_id) & f.jenis.isin(['Pendampingan kunjungan', 'Undangan rapat dadakan']) & ~f.status.isin(['Selesai', 'Ditolak', 'Dibatalkan'])].to_dict('records'):
        changed = ticket['usulan_mulai'] and ticket['usulan_mulai'] != ev.mulai
        status = 'Dibatalkan' if ev.status == 'Dibatalkan' else 'Baru' if changed else ticket['status']
        message = f"Agenda terkini: {ev.mulai} – {ev.selesai}" + ('; mohon konfirmasi ulang' if changed else '')
        REQ.update(ticket['id'], status=status, tenggat=ev.mulai[:10], usulan_mulai=ev.mulai, usulan_selesai=ev.selesai,
                   riwayat=json.dumps(thread(ticket) + ([_entry(user, message, status)] if changed or status != ticket['status'] else []), ensure_ascii=False), diubah_pada=now())
    for row in KEGIATAN.load().loc[lambda f: f.kal_id == event_id].to_dict('records'):
        status = {'Selesai': 'Selesai', 'Dibatalkan': 'Dibatalkan'}.get(ev.status, 'Belum')
        fields = dict(status=status, jadwal=ev.mulai, tenggat=ev.mulai[:10] if row['jadwal'] != ev.mulai else row['tenggat'],
                      selesai_pada=now() if status == 'Selesai' else '')
        if row['status'] != status or row['jadwal'] != ev.mulai:
            _catat(row['id'], user, f'Kalender diperbarui: {status}', **fields)
        if row['status'] == 'Dibatalkan' and status == 'Belum':
            reopen_task_tickets(row['id'], user)
        if row['jadwal'] != ev.mulai:
            for ticket in REQ.load().loc[lambda f: (f.kegiatan_id == row['id']) & f.status.isin(['Baru', 'Diproses'])].to_dict('records'):
                history = thread(ticket) + [_entry(user, f'Tenggat kegiatan diperbarui ke {ev.mulai[:10]}')]
                REQ.update(ticket['id'], tenggat=ev.mulai[:10], riwayat=json.dumps(history, ensure_ascii=False), diubah_pada=now())
        if status == 'Dibatalkan':
            cancel_task_tickets(row['id'], user)


def cancel_task_tickets(kid, user):
    for ticket in REQ.load().loc[lambda f: (f.kegiatan_id == kid) & f.status.isin(['Baru', 'Diproses'])].to_dict('records'):
        history = thread(ticket) + [_entry(user, 'Kegiatan dibatalkan', 'Dibatalkan')]
        REQ.update(ticket['id'], status='Dibatalkan', riwayat=json.dumps(history, ensure_ascii=False), diubah_pada=now())


def reopen_task_tickets(kid, user):
    for ticket in REQ.load().loc[lambda f: (f.kegiatan_id == kid) & f.status.eq('Dibatalkan')].to_dict('records'):
        history = thread(ticket) + [_entry(user, 'Kegiatan diaktifkan kembali; mohon proses ulang', 'Baru')]
        REQ.update(ticket['id'], status='Baru', riwayat=json.dumps(history, ensure_ascii=False), diubah_pada=now())


def transfer_work(cid, to_rm, user):
    """Move open work with the prospect; keep completed work as historical evidence."""
    for table, terminal in [(KEGIATAN, ['Selesai', 'Dibatalkan']), (REQ, ['Selesai', 'Ditolak', 'Dibatalkan'])]:
        for row in table.load().loc[lambda f: (f.company_id == cid) & ~f.status.isin(terminal)].to_dict('records'):
            history = thread(row) + [_entry(user, f"Serah terima dari {row['rm_id']} ke {to_rm}")]
            table.update(row['id'], rm_id=to_rm, riwayat=json.dumps(history, ensure_ascii=False), diubah_pada=now())
    data.audit('serah_terima_prospect', user=user, company=cid, ke=to_rm)


@transactional
def set_kegiatan(kid, selesai: bool, user):
    row = KEGIATAN.load().set_index('id').loc[kid]
    from . import auth
    actor = auth.current()
    division_completion = bool(actor and actor['role'] == 'divisi' and selesai and
                               len(REQ.load().loc[lambda f: (f.kegiatan_id == kid) & (f.divisi == actor['rm_id']) & f.status.eq('Selesai')]))
    if not auth.can_edit(row.rm_id) and not division_completion:
        raise ValueError('Kegiatan berada di luar akses akun Anda.')
    if selesai and completion_block(kid):
        raise ValueError(completion_block(kid))
    if row.kal_id:
        K.set_status(row.kal_id, 'Selesai' if selesai else 'Terjadwal', user, _internal=division_completion)
    _catat(kid, user, 'Ditandai selesai' if selesai else 'Tanda selesai dibatalkan',
           status='Selesai' if selesai else 'Belum', selesai_pada=now() if selesai else '')
    data.audit('progres_kegiatan', user=user, id=kid, selesai=selesai)


def kanal_kegiatan(row) -> str:
    """Kanal kalender untuk sebuah kegiatan: dari jenis (kegiatan dadakan) atau ditebak dari teksnya."""
    if row.get('jenis') in JENIS_DADAKAN:
        return JENIS_DADAKAN[row['jenis']]
    if row.get('jenis') in K.KANAL:
        return row['jenis']
    t = f"{row.get('judul', '')} {row.get('aksi', '')}".lower()
    if 'rapat' in t or 'koordinasi' in t or 'diskusi internal' in t:
        return 'Kunjungan' if 'nasabah' in t or 'direksi' in t else 'Rapat internal'
    if any(w in t for w in ('telepon', 'telpon', 'hubungi', 'whatsapp', 'konfirmasi')):
        return 'Telepon'
    if any(w in t for w in ('kunjung', 'presentasi', 'bertemu', 'datang')):
        return 'Kunjungan'
    if any(w in t for w in ('kirim', 'email', 'surel', 'dokumen', 'proposal', 'simulasi')):
        return 'Email'
    return 'Rapat internal' if row.get('pemilik') not in ('', 'RM', None) else 'Telepon'


@transactional
def reschedule_kegiatan(kid, tanggal: date, alasan, user, jam=None, kanal=None, nama=''):
    """Jadwal ulang mendadak untuk tahap apa pun. Tahap yang sudah punya jadwal kalender digeser; tahap yang baru punya
    tenggat otomatis dibuatkan jadwal di kalender RM pada tanggal & jam baru (lalu dipakai lagi untuk jadwal ulang berikutnya)."""
    row = KEGIATAN.load().set_index('id').loc[kid]
    from . import auth
    if not auth.can_edit(row.rm_id):
        raise ValueError('Kegiatan berada di luar akses akun Anda.')
    if row.status == 'Selesai':
        raise ValueError('Kegiatan selesai tidak dapat dijadwalkan ulang. Tambahkan kegiatan baru bila diperlukan.')
    lama = row.jadwal or row.tenggat
    m0 = datetime.fromisoformat(row.jadwal) if row.jadwal else None
    jam = jam or (m0.time() if m0 else datetime.strptime('10:00', '%H:%M').time())
    m = datetime.combine(tanggal, jam); jadwal = m.isoformat(timespec='minutes')
    kanal = kanal if kanal in K.KANAL else kanal_kegiatan(row.to_dict())
    ev = K.load().set_index('id')
    kal_id = row.kal_id if row.kal_id and row.kal_id in ev.index else ''
    if kal_id:                                               # geser jadwal yang sudah ada (durasi tetap)
        e = ev.loc[kal_id]
        dur = datetime.fromisoformat(e.selesai) - datetime.fromisoformat(e.mulai) if e.selesai else timedelta(minutes=60)
        edited = {**e.to_dict(), 'id': kal_id, 'mulai': jadwal, 'selesai': (m + dur).isoformat(timespec='minutes'),
                  'kanal': kanal, 'status': 'Terjadwal'}
        _, _, rejected = K.upsert([edited], user)
        if rejected:
            raise ValueError(rejected[0][1])
    else:                                                    # tahap tanpa jadwal → buat jadwal baru di kalender
        kal_id = _buat_jadwal({**row.to_dict(), 'id': kid}, m, kanal, nama, user, catatan=f'Dijadwal ulang · alasan: {alasan}')
    n = int(float(row.n_jadwal_ulang or 0)) + 1
    _catat(kid, user, f'Dijadwal ulang dari {str(lama)[:16].replace("T", " ")} ke {jadwal.replace("T", " ")} ({kanal}) · alasan: {alasan}'
           + ('' if row.kal_id else ' · masuk kalender'),
           tenggat=tanggal.isoformat(), jadwal=jadwal, kal_id=kal_id, jenis=row.jenis or kanal, n_jadwal_ulang=n, alasan=alasan,
           status='Belum' if row.status == 'Dibatalkan' else row.status)
    data.audit('jadwal_ulang_kegiatan', user=user, id=kid, ke=jadwal, kanal=kanal, kalender=kal_id, alasan=alasan)
    return kal_id


@transactional
def batal_kegiatan(kid, alasan, user):
    row = KEGIATAN.load().set_index('id').loc[kid]
    from . import auth
    if not auth.can_edit(row.rm_id):
        raise ValueError('Kegiatan berada di luar akses akun Anda.')
    if row.kal_id:
        K.set_status(row.kal_id, 'Dibatalkan', user)
    _catat(kid, user, f'Dibatalkan · alasan: {alasan}', status='Dibatalkan', alasan=alasan, selesai_pada='')
    cancel_task_tickets(kid, user)
    data.audit('batal_kegiatan', user=user, id=kid, alasan=alasan)


@transactional
def aktifkan_kegiatan(kid, user):
    row = KEGIATAN.load().set_index('id').loc[kid]
    from . import auth
    if not auth.can_edit(row.rm_id):
        raise ValueError('Kegiatan berada di luar akses akun Anda.')
    if row.kal_id:
        K.set_status(row.kal_id, 'Terjadwal', user)
    _catat(kid, user, 'Diaktifkan kembali', status='Belum', alasan='')
    reopen_task_tickets(kid, user)
    data.audit('aktifkan_kegiatan', user=user, id=kid)


@transactional
def tambah_dadakan(store, *, company_id, rm_id, feedback_id, event_id, tanggal_kunjungan, setelah, jenis, judul, agenda, mulai: datetime, menit,
                   pemilik, divisi, ke_kalender, undang_divisi, user):
    """Rapat / kegiatan dadakan: disisipkan ke alur setelah tahap `setelah` (urutan tahap berikutnya digeser),
    opsional masuk kalender dan mengundang divisi lewat tiket. → id kegiatan baru."""
    from . import auth
    if not auth.can_edit(rm_id) or company_id not in assignment_ids(store, rm_id, auth.current()):
        raise ValueError('Kegiatan berada di luar akses akun Anda.')
    if undang_divisi and divisi and not ke_kalender:
        raise ValueError('Undangan divisi memerlukan agenda kalender. Aktifkan Masukkan ke kalender.')
    df = KEGIATAN.load()
    alur = df[df.feedback_id == feedback_id]
    for r in alur.itertuples():                              # geser tahap sesudahnya
        if int(float(r.urutan)) > setelah:
            KEGIATAN.update(r.id, urutan=int(float(r.urutan)) + 1)
    nama = store.co.name.get(company_id, company_id)
    kid = f'{feedback_id}-D{uuid.uuid4().hex[:12]}'
    kal_id = ''
    if ke_kalender:
        kal_id = uuid.uuid4().hex[:12]
        _, _, rejected = K.upsert([{'id': kal_id, 'rm_id': rm_id, 'company_id': company_id, 'judul': f'{nama} ({company_id}) · {judul}', 'kanal': JENIS_DADAKAN.get(jenis, 'Rapat internal'),
                                 'mulai': mulai.isoformat(timespec='minutes'), 'selesai': (mulai + timedelta(minutes=int(menit))).isoformat(timespec='minutes'),
                                 'lokasi': '', 'catatan': f'{jenis} (dadakan): {agenda}', 'status': 'Terjadwal', 'sumber': 'Rapat dadakan'}],
                               user)
        if rejected:
            raise ValueError(rejected[0][1])
    tiket = []
    if undang_divisi and divisi:
        tiket = create_tickets(divisi, jenis='Undangan rapat dadakan', rm_id=rm_id, company_id=company_id, judul=f'{judul} · {nama}',
                               isi=f"{rm_id} mengundang divisi Anda ke {jenis.lower()} pada {mulai:%A %d %b %Y, %H.%M} WIB ({int(menit)} menit).\nAgenda: {agenda}",
                               prioritas='Tinggi', tenggat=mulai.date(), ref=feedback_id, event_id=kal_id or event_id, kegiatan_id=kid, user=user)
    KEGIATAN.upsert([{'id': kid, 'feedback_id': feedback_id, 'event_id': event_id, 'rm_id': rm_id, 'company_id': company_id,
                      'tanggal_kunjungan': tanggal_kunjungan, 'urutan': setelah + 1, 'judul': judul, 'aksi': agenda or judul, 'pemilik': pemilik,
                      'divisi': ';'.join(DIVISI.get(d, d) for d in divisi), 'sumber': 'Dadakan', 'jenis': jenis, 'jadwal': mulai.isoformat(timespec='minutes'),
                      'kal_id': kal_id, 'tenggat': mulai.date().isoformat(), 'status': 'Belum', 'selesai_pada': '', 'n_jadwal_ulang': 0,
                      'riwayat': json.dumps([_entry(user, f'Ditambahkan sebagai {jenis.lower()} dadakan'
                                                   + (f' · undangan ke {len(tiket)} divisi' if tiket else ''))], ensure_ascii=False),
                      'dibuat_oleh': user, 'dibuat_pada': now()}], {'diubah_pada': now()})
    data.audit('kegiatan_dadakan', user=user, id=kid, jenis=jenis, kalender=bool(kal_id), tiket=len(tiket))
    if kal_id:
        sync_calendar_event(kal_id, user)
    return kid, kal_id, tiket


# ------------------------------------------------------------------ pengajuan kunjungan
@transactional
def submit_visit(*, rm_id, company_id, nama, mulai, selesai, kanal, tujuan, produk, divs, catatan, user):
    from . import auth, profile_workspace
    if not auth.can_edit(rm_id) or company_id not in profile_workspace.accessible_ids(data.get_store(), auth.current()):
        raise ValueError('Perusahaan berada di luar cakupan akun Anda.')
    if mulai < datetime.now():
        raise ValueError('Pengajuan kunjungan harus menggunakan waktu mendatang.')
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


@transactional
def decide_visit(store, req: dict, approve: bool, komentar, user):
    from . import auth
    if not auth.current() or auth.current()['role'] != 'supervisor':
        raise ValueError('Persetujuan hanya dapat diberikan oleh supervisor.')
    req = REQ.load().set_index('id').loc[req['id']].to_dict() | {'id': req['id']}
    if req['status'] != 'Diajukan':
        raise ValueError('Pengajuan sudah diproses; muat ulang halaman.')
    if approve and pd.Timestamp(req['usulan_mulai']) <= pd.Timestamp.now():
        raise ValueError('Waktu pengajuan telah lewat. Minta RM mengajukan jadwal baru.')
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
    sync_calendar_event(ev_id, user)
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
    keg = kegiatan_for(user['rm_id'] if user['role'] == 'rm' else 'Semua RM')
    out['kegiatan terlambat'] = int((keg.status_tampil == 'terlambat').sum()) if len(keg) else 0      # yang dibatalkan tidak dihitung
    if user['role'] == 'supervisor':
        out['pengajuan menunggu'] = int(((df.jenis == 'Pengajuan kunjungan') & (df.status == 'Diajukan')).sum())
    return out
