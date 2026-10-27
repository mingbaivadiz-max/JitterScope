# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 SanyLok
"""Local SQLite history; all writes run outside the GUI thread."""
from __future__ import annotations

import csv
import html
import json
import logging
import math
import queue
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .model import Sample, summarize
from server_catalog import BY_HOST

LOG = logging.getLogger('usb_net.storage')


def utc(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec='seconds')


class HistoryStore:
    def __init__(self, path, retention_days=7):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.retention_days = retention_days
        self.last_error = ''
        self.dropped_rows = 0
        self._queue = queue.Queue(maxsize=3000)
        self._closed = False
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, started REAL NOT NULL, ended REAL,
                    metadata TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS samples (
                    session TEXT NOT NULL, timestamp REAL NOT NULL, role TEXT NOT NULL,
                    address TEXT, mode TEXT, port INTEGER, rtt REAL, error TEXT,
                    dl REAL, ul REAL, adapter TEXT);
                CREATE INDEX IF NOT EXISTS samples_session_time ON samples(session,timestamp);
                CREATE INDEX IF NOT EXISTS samples_session_role_time ON samples(session,role,timestamp);
                CREATE INDEX IF NOT EXISTS samples_timestamp ON samples(timestamp);
                CREATE INDEX IF NOT EXISTS sessions_started ON sessions(started);
            ''')
            if 'status' not in {row['name'] for row in db.execute('PRAGMA table_info(sessions)')}:
                db.execute("ALTER TABLE sessions ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
            db.execute("""UPDATE sessions SET ended=COALESCE((SELECT MAX(timestamp) FROM samples WHERE session=sessions.id),started),
                       status='interrupted' WHERE ended IS NULL""")
        self._thread = threading.Thread(target=self._run, name='history-writer', daemon=False)
        self._thread.start()

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA synchronous=NORMAL')
        return db

    @contextmanager
    def connect(self):
        db = self._connect()
        try:
            with db:
                yield db
        finally:
            db.close()

    def _put(self, operation, critical=False):
        if self._closed:
            return False
        try:
            self._queue.put(operation, timeout=2 if critical else 0)
            return True
        except queue.Full:
            self.last_error = 'Очередь истории переполнена. Часть измерений не записана.'
            LOG.error(self.last_error)
            return False

    def start_session(self, metadata):
        session = uuid.uuid4().hex
        if not self._put(('start', session, time.time(), dict(metadata)), critical=True):
            raise OSError(self.last_error)
        return session

    def end_session(self, session):
        if session:
            self._put(('end', session, time.time()), critical=True)

    def append(self, session, data):
        if not session:
            return
        timestamp = data.get('timestamp', time.time())
        traffic = data.get('traffic') or (None, None)
        rows = []
        for role, node in data.get('nodes', {}).items():
            sample = node['sample']
            rows.append((session, timestamp, role, node.get('address'), node.get('mode', 'icmp'),
                         node.get('port'), sample.rtt, sample.error, traffic[0], traffic[1], data.get('adapter')))
        if not self._put(('samples', rows)):
            self.dropped_rows += len(rows)

    def set_retention(self, days):
        if days not in (1, 7, 30):
            raise ValueError('Допустимо хранение 1, 7 или 30 дней')
        self.retention_days = days
        self._put(('prune',))

    def flush(self, timeout=5):
        event = threading.Event()
        if not self._put(('flush', event), critical=True):
            raise OSError(self.last_error)
        if not event.wait(timeout):
            raise TimeoutError('Не удалось дождаться записи истории')
        if self.last_error:
            raise OSError(self.last_error)

    def close(self):
        if self._closed:
            return
        # Called once network callbacks have stopped. No rows are silently
        # discarded during an ordinary shutdown.
        event = threading.Event()
        self._queue.put(('stop', event), timeout=5)
        self._closed = True
        event.wait(8)
        self._thread.join(2)
        if self._thread.is_alive():
            raise TimeoutError('Запись истории ещё завершается')

    def _prune(self, db):
        cutoff = time.time() - self.retention_days * 86400
        db.execute('DELETE FROM samples WHERE timestamp < ?', (cutoff,))
        db.execute('DELETE FROM sessions WHERE started < ? AND id NOT IN (SELECT DISTINCT session FROM samples)', (cutoff,))

    def _run(self):
        db = self._connect()
        last_prune = 0
        try:
            while True:
                try:
                    first = self._queue.get(timeout=1)
                except queue.Empty:
                    continue
                batch = [first]
                while len(batch) < 256 and batch[-1][0] != 'stop':
                    try:
                        batch.append(self._queue.get_nowait())
                    except queue.Empty:
                        break
                batch_error = ''
                successful_rows = 0
                wrote = False
                try:
                    db.execute('BEGIN')
                    for item in batch:
                        kind = item[0]
                        db.execute('SAVEPOINT operation')
                        try:
                            if kind == 'start':
                                db.execute('INSERT INTO sessions(id,started,metadata) VALUES(?,?,?)',
                                           (item[1],item[2],json.dumps(item[3],ensure_ascii=False)))
                                wrote = True
                            elif kind == 'end':
                                db.execute("UPDATE sessions SET ended=?,status='complete' WHERE id=?",(item[2],item[1]))
                                wrote = True
                            elif kind == 'samples':
                                db.executemany('INSERT INTO samples VALUES(?,?,?,?,?,?,?,?,?,?,?)',item[1])
                                successful_rows += len(item[1])
                                wrote = True
                            if kind == 'prune' or time.monotonic()-last_prune >= 3600:
                                self._prune(db)
                                last_prune = time.monotonic()
                            db.execute('RELEASE SAVEPOINT operation')
                        except Exception as exc:
                            db.execute('ROLLBACK TO SAVEPOINT operation')
                            db.execute('RELEASE SAVEPOINT operation')
                            batch_error = f'Ошибка записи истории: {exc}'
                            if kind == 'samples':
                                self.dropped_rows += len(item[1])
                            LOG.exception('History operation failed')
                    db.commit()
                    if batch_error:
                        self.last_error = batch_error
                    elif wrote:
                        self.last_error = ''
                except Exception as exc:
                    db.rollback()
                    self.last_error = f'Ошибка записи истории: {exc}'
                    self.dropped_rows += successful_rows
                    LOG.exception('History write failed')
                finally:
                    for item in batch:
                        if item[0] in ('flush','stop'):
                            item[1].set()
                        self._queue.task_done()
                if batch[-1][0] == 'stop':
                    break
        finally:
            db.close()

    def list_sessions(self, limit=100):
        with self.connect() as db:
            return [dict(row) for row in db.execute('''
                SELECT s.*, (SELECT COUNT(*) FROM samples p WHERE p.session=s.id AND p.role='target') AS attempts
                FROM sessions s ORDER BY started DESC LIMIT ?''', (limit,))]

    def session_data(self, session):
        with self.connect() as db:
            db.execute('BEGIN')
            metadata = db.execute('SELECT * FROM sessions WHERE id=?', (session,)).fetchone()
            if metadata is None:
                raise ValueError('Сессия не найдена или удалена политикой хранения')
            rows = [dict(row) for row in db.execute('SELECT * FROM samples WHERE session=? ORDER BY timestamp,rowid', (session,))]
        groups = {}
        for row in rows:
            key = row['role']
            groups.setdefault(key, []).append(Sample(row['rtt'], row['error'] or ''))
        return dict(metadata), rows, {role: summarize(samples) for role, samples in groups.items()}

    def compare_sessions(self, first, second):
        result = []
        for session in (first, second):
            metadata, stats, bounds = self.summary_session(session)
            result.append({'session': metadata, 'settings': json.loads(metadata['metadata']),
                           'stats': stats.get('target', summarize([])), 'rows': bounds['rows']})
        return result

    def _summary_db(self, db, session):
        metadata = db.execute('SELECT * FROM sessions WHERE id=?',(session,)).fetchone()
        if metadata is None:
            raise ValueError('Сессия не найдена')
        bounds = dict(db.execute('SELECT COUNT(*) AS rows,MIN(timestamp) AS first,MAX(timestamp) AS last FROM samples WHERE session=?',(session,)).fetchone())
        query = '''WITH ordered AS (
            SELECT role,rtt,COALESCE(error,'') AS error,
            LAG(rtt) OVER(PARTITION BY role ORDER BY timestamp,rowid) AS previous_rtt,
            LAG(COALESCE(error,'')) OVER(PARTITION BY role ORDER BY timestamp,rowid) AS previous_error
            FROM samples WHERE session=?)
            SELECT role,COUNT(*) AS total,SUM(error='') AS count,SUM(error!='') AS errors,
            SUM(error='' AND rtt IS NOT NULL) AS received,
            AVG(CASE WHEN error='' THEN rtt END) AS avg,
            MIN(CASE WHEN error='' THEN rtt END) AS minimum,
            MAX(CASE WHEN error='' THEN rtt END) AS maximum,
            AVG(CASE WHEN error='' AND previous_error='' THEN ABS(rtt-previous_rtt) END) AS jitter,
            SUM(error='' AND rtt IS NULL) AS timeouts FROM ordered GROUP BY role'''
        stats = {}
        for row in db.execute(query,(session,)).fetchall():
            stat = dict(row)
            role = stat.pop('role')
            stat['loss'] = 100 * stat.pop('timeouts') / stat['count'] if stat['count'] else None
            stat['min'],stat['max'] = stat.pop('minimum'),stat.pop('maximum')
            for name, fraction in (('p50',.5),('p95',.95)):
                if not stat['received']:
                    stat[name] = None
                    continue
                rank = (stat['received']-1)*fraction
                lower,upper = math.floor(rank),math.ceil(rank)
                def value(offset):
                    return db.execute("SELECT rtt FROM samples WHERE session=? AND role=? AND COALESCE(error,'')='' AND rtt IS NOT NULL ORDER BY rtt LIMIT 1 OFFSET ?",(session,role,offset)).fetchone()[0]
                left = value(lower)
                stat[name] = left + (value(upper)-left)*(rank-lower) if upper != lower else left
            stats[role] = stat
        return dict(metadata),stats,bounds

    def summary_session(self, session):
        with self.connect() as db:
            db.execute('BEGIN')
            return self._summary_db(db,session)

    def chart_points(self, session, limit=600):
        with self.connect() as db:
            bounds = db.execute("SELECT MIN(timestamp),MAX(timestamp) FROM samples WHERE session=? AND role='target'",(session,)).fetchone()
            if bounds[0] is None:
                return []
            start,end = bounds
            duration = max(.001,end-start)
            rows = db.execute('''SELECT MIN(timestamp) AS timestamp,
                MAX(CASE WHEN COALESCE(error,'')='' THEN rtt END) AS rtt,
                MAX(rtt IS NULL AND COALESCE(error,'')='') AS loss,
                MAX(COALESCE(error,'')!='') AS error FROM samples
                WHERE session=? AND role='target'
                GROUP BY MIN(?,CAST((timestamp-?)*?/? AS INTEGER)) ORDER BY timestamp''',
                (session,limit-1,start,limit,duration)).fetchall()
            return [dict(row) for row in rows]

    def export_session(self, session, directory):
        self.flush()
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        stem = 'network-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + session[:8] + '-' + uuid.uuid4().hex[:4]
        csv_path, html_path = directory / (stem + '.csv'), directory / (stem + '.html')
        fields = ['time_utc','role','address','mode','port','rtt_ms','error','dl_kib_s','ul_kib_s','adapter']
        def cell(value):
            # Neutralize formulas when a report is opened in Excel.
            return "'" + value if isinstance(value, str) and value.startswith(('=', '+', '-', '@', '\t', '\r')) else value
        with self.connect() as db:
            db.execute('BEGIN')
            metadata,stats,bounds = self._summary_db(db,session)
            if not bounds['rows']:
                raise ValueError('В этой сессии пока нет измерений')
            with csv_path.open('x', encoding='utf-8-sig', newline='') as out:
                writer = csv.writer(out)
                writer.writerow(fields)
                for row in db.execute('SELECT * FROM samples WHERE session=? ORDER BY timestamp,rowid',(session,)):
                    writer.writerow([cell(v) for v in (utc(row['timestamp']),row['role'],row['address'],row['mode'],row['port'],
                                                        row['rtt'],row['error'],row['dl'],row['ul'],row['adapter'])])
        esc = lambda value: html.escape(str(value))
        number = lambda value: '—' if value is None else f'{value:.2f}'
        settings = json.loads(metadata['metadata'])
        def role_name(role):
            return BY_HOST.get(role.removeprefix('compare:'),{}).get('name',role.removeprefix('compare:')) if role.startswith('compare:') else {
                'target':'Выбранная цель','gateway':'Шлюз','control':'Контроль интернета'}.get(role,role)
        table = ''.join('<tr>' + ''.join(f'<td>{esc(v)}</td>' for v in (
            role_name(role), s['total'], s['count'], s['errors'], number(s['loss']), number(s['avg']),
            number(s['p50']), number(s['p95']), number(s['jitter']))) + '</tr>' for role,s in stats.items())
        body = f'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
        <title>Отчёт подключения</title><style>body{{font:16px system-ui;max-width:1100px;margin:40px auto;padding:0 20px;color:#182333}}
        table{{border-collapse:collapse;width:100%}}td,th{{padding:10px;border:1px solid #ccd4df;text-align:left}}th{{background:#edf2f7}}
        pre{{white-space:pre-wrap}}small{{color:#536173}}</style><h1>Отчёт подключения</h1>
        <p>Период сохранённых данных (UTC): {esc(utc(bounds['first']))} — {esc(utc(bounds['last']))}</p>
        <p>Профиль: {esc(settings.get('profile') or 'Без профиля')} · Цель: {esc(settings.get('host',''))} · Режим: {esc(settings.get('mode','icmp'))}</p>
        <table><tr><th>Точка</th><th>Всего</th><th>Попытки</th><th>Ошибки</th><th>Потери / тайм-ауты, %</th><th>Среднее, мс</th><th>P50, мс</th><th>P95, мс</th><th>Разброс, мс</th></tr>{table}</table>
        <p>ICMP-ошибки API исключены из доли потерь. В TCP-режиме процент означает тайм-ауты подключений.
        P50 — медиана, P95 — уровень, ниже которого находятся примерно 95% успешных измерений.
        Пропуски разрывают соседние пары для расчёта разброса.</p>
        <p>Отчёт показывает измерения до диагностических адресов, а не точную задержку игрового протокола.
        Адреса могут иметь разные маршруты. Отсутствие ответа не доказывает неисправность провайдера.</p>
        <small>Потеряно строк при записи в текущем запуске: {self.dropped_rows}. CSV содержит подробные измерения и адреса; просмотрите их перед передачей отчёта.</small>
        </html>'''
        with html_path.open('x', encoding='utf-8') as out:
            out.write(body)
        return csv_path, html_path
