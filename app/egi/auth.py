"""Login sederhana: satu akun per RM + akun supervisor (lihat semua RM).

Akun disimpan di outputs/app/users.json (tidak masuk git); password di-hash PBKDF2-SHA256 + salt.
Password awal:
  - APP_DEMO_PASSWORD (di .env atau st.secrets) → dipakai semua akun baru;
  - kalau tidak diisi → password acak per akun, ditulis ke outputs/app/akun_awal.csv (hanya di mesin lokal).
Setiap pengguna bisa mengganti passwordnya sendiri dari sidebar.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time

import streamlit as st

from . import data

USERS = data.APP_OUT / 'users.json'
FIRST = data.APP_OUT / 'akun_awal.csv'
ADMIN = 'supervisor'
MAX_FAIL = 5
_lock = threading.Lock()


def _hash(pw: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'), bytes.fromhex(salt), 200_000).hex()


def _record(name, role, rm_id, pw):
    salt = secrets.token_hex(16)
    return {'nama': name, 'role': role, 'rm_id': rm_id, 'salt': salt, 'hash': _hash(pw, salt)}


def _demo_password():
    try:
        v = st.secrets.get('APP_DEMO_PASSWORD')
    except Exception:            # tidak ada secrets.toml
        v = None
    return v or os.getenv('APP_DEMO_PASSWORD') or None


def _load(rms):
    """Baca users.json; buat akun yang belum ada (RM baru di data, atau file belum ada)."""
    with _lock:
        users = json.loads(USERS.read_text(encoding='utf-8')) if USERS.exists() else {}
        want = {r.lower(): ('rm', r, r) for r in rms}
        want[ADMIN] = ('supervisor', 'Semua RM', 'Supervisor')
        from .tindak import DIVISI       # akun divisi: menerima tiket koordinasi
        want.update({f'div-{k}': ('divisi', k, v) for k, v in DIVISI.items()})
        new = {u: v for u, v in want.items() if u not in users}
        if new:
            demo, created = _demo_password(), []
            for u, (role, rm_id, name) in new.items():
                pw = demo or secrets.token_urlsafe(8)
                users[u] = _record(name, role, rm_id, pw)
                created.append((u, role, pw if not demo else '(APP_DEMO_PASSWORD)'))
            data.APP_OUT.mkdir(parents=True, exist_ok=True)
            USERS.write_text(json.dumps(users, indent=1), encoding='utf-8')
            if not demo:
                head = not FIRST.exists()
                with open(FIRST, 'a', encoding='utf-8') as f:
                    if head:
                        f.write('username,role,password_awal\n')
                    f.writelines(f'{u},{r},{p}\n' for u, r, p in created)
        return users


def _save(users):
    with _lock:
        USERS.write_text(json.dumps(users, indent=1), encoding='utf-8')


def current():
    return st.session_state.get('user')


def login_page(rms):
    """Halaman login (satu-satunya halaman yang didaftarkan ke navigasi selama belum masuk)."""
    ss = st.session_state
    users = _load(rms)
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.markdown('<div style="height:8vh"></div>', unsafe_allow_html=True)
        st.markdown('<div style="display:flex;gap:10px;align-items:center;margin-bottom:6px"><div style="width:38px;height:38px;border-radius:8px;'
                    'background:#C2500A;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700">EG</div>'
                    '<div><strong>Growth Intelligence</strong><br><span style="font-size:12px;color:#4B5563">Ruang kerja RM</span></div></div>',
                    unsafe_allow_html=True)
        with st.form('login'):
            u = st.text_input('Username', placeholder='mis. rm-017, supervisor, atau div-kredit').strip().lower()
            p = st.text_input('Password', type='password')
            ok = st.form_submit_button('Masuk', type='primary', use_container_width=True)
        if ok:
            if ss.get('login_fail', 0) >= MAX_FAIL and time.time() - ss.get('login_fail_t', 0) < 60:
                st.error('Terlalu banyak percobaan. Coba lagi dalam 1 menit.')
            elif u in users and hmac.compare_digest(_hash(p, users[u]['salt']), users[u]['hash']):
                rec = users[u]
                ss.user = {'username': u, 'nama': rec['nama'], 'role': rec['role'], 'rm_id': rec['rm_id']}
                ss.rm = rec['rm_id'] if rec['role'] == 'rm' else 'Semua RM'
                ss.login_fail = 0
                data.audit('login', user=u)
                st.rerun()
            else:
                time.sleep(1)
                ss.login_fail = ss.get('login_fail', 0) + 1; ss.login_fail_t = time.time()
                data.audit('login_gagal', user=u)
                st.error('Username atau password salah.')
        st.caption('Username = ID RM huruf kecil (rm-001 … rm-040), "supervisor" untuk melihat semua RM, '
                   'atau akun divisi (div-kredit, div-risiko, div-transaksi, div-trade, …). '
                   + ('Password awal: lihat `outputs/app/akun_awal.csv`.' if FIRST.exists() else 'Password awal: nilai APP_DEMO_PASSWORD.'))


def logout():
    data.audit('logout', user=current()['username'])
    for k in ['user', 'plan', 'chat', 'agent_result', 'focus_company', 'focus_district', 'rm']:
        st.session_state.pop(k, None)
    st.query_params.clear()
    st.rerun()


def change_password_form():
    u = current()['username']
    with st.form('ganti_pw', clear_on_submit=True):
        old = st.text_input('Password lama', type='password')
        new = st.text_input('Password baru (min. 8 karakter)', type='password')
        new2 = st.text_input('Ulangi password baru', type='password')
        if st.form_submit_button('Simpan', use_container_width=True):
            users = json.loads(USERS.read_text(encoding='utf-8'))
            rec = users[u]
            if not hmac.compare_digest(_hash(old, rec['salt']), rec['hash']):
                st.error('Password lama salah.')
            elif len(new) < 8 or new != new2:
                st.error('Password baru minimal 8 karakter dan harus sama.')
            else:
                users[u] = _record(rec['nama'], rec['role'], rec['rm_id'], new)
                _save(users)
                data.audit('ganti_password', user=u)
                st.success('Password diganti.')


def can_edit(rm_id) -> bool:
    """RM hanya boleh mengubah data miliknya; supervisor boleh semua."""
    u = current()
    return bool(u) and (u['role'] == 'supervisor' or u['rm_id'] == rm_id)
