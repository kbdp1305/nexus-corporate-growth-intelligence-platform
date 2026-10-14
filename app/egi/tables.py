"""Tabel CSV kecil di outputs/app/ yang dibaca & ditulis bersama oleh semua pengguna dashboard.

Semua kolom disimpan sebagai teks. Penulisan atomik (tulis ke .tmp lalu ganti) dan dikunci per proses,
cukup untuk satu server Streamlit.
"""
from __future__ import annotations

import threading
import uuid
from contextlib import contextmanager
from functools import wraps
from datetime import datetime

import pandas as pd

from . import data

WRITE_LOCK = threading.RLock()
TABLES = []


@contextmanager
def transaction():
    """Serialize one workflow and restore its files if any step fails (one server)."""
    with WRITE_LOCK:
        paths = {t.file for t in TABLES} | {data.APP_OUT / 'visit_log.csv', data.APP_OUT / 'audit_log.jsonl'}
        before = {p: p.read_bytes() if p.exists() else None for p in paths}
        try:
            yield
        except Exception:
            for path, content in before.items():
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(content)
            data.get_store().load_app_log()
            raise


def transactional(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with transaction():
            return fn(*args, **kwargs)
    return wrapped


class CsvTable:
    def __init__(self, name, cols):
        self.file = data.APP_OUT / name
        self.cols = cols
        self._lock = WRITE_LOCK
        TABLES.append(self)

    def load(self) -> pd.DataFrame:
        with self._lock:
            if not self.file.exists():
                return pd.DataFrame(columns=self.cols)
            return pd.read_csv(self.file, dtype=str, keep_default_na=False).reindex(columns=self.cols, fill_value='')

    def _write(self, df):
        data.APP_OUT.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix('.tmp')
        df[self.cols].to_csv(tmp, index=False)
        tmp.replace(self.file)

    def upsert(self, rows: list[dict], stamp: dict | None = None):
        """Tambah/perbarui baris berdasarkan kolom id. stamp = kolom yang ditimpa di setiap baris. → (baru, diperbarui, ids)."""
        with self._lock:
            df = self.load()
            new = upd = 0
            ids = []
            for r in rows:
                r = {**r, **(stamp or {}), 'id': r.get('id') or uuid.uuid4().hex[:12]}
                r = {k: '' if r.get(k) is None else str(r.get(k)) for k in self.cols}
                hit = df.index[df.id == r['id']]
                if len(hit):
                    df.loc[hit[0], self.cols] = [r[k] for k in self.cols]; upd += 1
                else:
                    df = pd.concat([df, pd.DataFrame([r])], ignore_index=True); new += 1
                ids.append(r['id'])
            self._write(df)
        return new, upd, ids

    def update(self, row_id, **fields):
        with self._lock:
            df = self.load()
            hit = df.index[df.id == row_id]
            if len(hit):
                for k, v in fields.items():
                    df.loc[hit[0], k] = '' if v is None else str(v)
                self._write(df)

    def delete(self, row_id):
        with self._lock:
            df = self.load()
            self._write(df[df.id != row_id])


def now():
    return datetime.now().isoformat(timespec='seconds')
