"""Local SQLite queue with tenant quotas, fenced leases and bounded settlement.

SQLite is a single-node implementation, not a distributed service or billing.
"""
from contextlib import contextmanager
from pathlib import Path
import datetime, json, secrets, sqlite3, time

class Queue:
    def __init__(self, path, *, quota=10, lease_seconds=30, max_attempts=3, max_total=None):
        self.path = str(path); Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.quota = quota; self.lease_seconds = lease_seconds; self.max_attempts = max_attempts; self.max_total=max_total
        with self.tx() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, tenant TEXT NOT NULL, idem TEXT NOT NULL,
                    period TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL,
                    cap INTEGER NOT NULL, cost INTEGER NOT NULL DEFAULT 0,
                    fence TEXT, expires REAL, tries INTEGER NOT NULL DEFAULT 0,
                    result TEXT, share TEXT UNIQUE, share_expires REAL,
                    created REAL NOT NULL, UNIQUE(tenant,idem));
                CREATE INDEX IF NOT EXISTS ready_jobs ON jobs(state,created);
            ''')

    @contextmanager
    def tx(self):
        db=sqlite3.connect(self.path, timeout=15); db.row_factory=sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL'); db.execute('PRAGMA busy_timeout=15000')
        try:
            db.execute('BEGIN IMMEDIATE'); yield db; db.commit()
        except BaseException: db.rollback(); raise
        finally: db.close()

    def enqueue(self, tenant, idem, payload, *, cap_microusd=250000):
        if not isinstance(tenant,str) or not tenant or not isinstance(idem,str) or not idem:
            raise ValueError('Tenant and request identity required.')
        if type(cap_microusd) is not int or not 0 <= cap_microusd <= 250000:
            raise ValueError('Per-run cap exceeds this local service limit.')
        raw=json.dumps(payload)
        if len(raw.encode()) > 8000: raise ValueError('Bounded job payload required.')
        period=datetime.datetime.now(datetime.timezone.utc).date().isoformat()
        with self.tx() as db:
            prior=db.execute('SELECT * FROM jobs WHERE tenant=? AND idem=?',(tenant,idem)).fetchone()
            if prior:
                if prior['payload'] != raw: raise ValueError('Request identity already used for a different job.')
                return prior['id']
            used=db.execute('SELECT count(*) FROM jobs WHERE tenant=? AND period=?',(tenant,period)).fetchone()[0]
            if used >= self.quota: raise ValueError('Daily check allowance reached.')
            if self.max_total is not None and db.execute('SELECT count(*) FROM jobs').fetchone()[0]>=self.max_total:
                raise ValueError('This preview reached its total check limit.')
            key=secrets.token_hex(16)
            db.execute('INSERT INTO jobs(id,tenant,idem,period,payload,state,cap,created) VALUES(?,?,?,?,?,?,?,?)',
                       (key,tenant,idem,period,raw,'queued',cap_microusd,time.time()))
            return key

    def lease(self):
        now=time.time()
        with self.tx() as db:
            db.execute("UPDATE jobs SET state=CASE WHEN tries>=? THEN 'failed' ELSE 'queued' END, fence=NULL WHERE state='running' AND expires<=?",(self.max_attempts,now))
            row=db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created,id LIMIT 1").fetchone()
            if not row: return None
            fence=secrets.token_hex(16)
            db.execute("UPDATE jobs SET state='running',fence=?,expires=?,tries=tries+1 WHERE id=?",(fence,now+self.lease_seconds,row['id']))
            return {'id':row['id'],'tenant':row['tenant'],'payload':json.loads(row['payload']),'fence':fence,'cap_microusd':row['cap']}

    def heartbeat(self, id, fence):
        now=time.time()
        with self.tx() as db:
            cur=db.execute("UPDATE jobs SET expires=? WHERE id=? AND fence=? AND state='running' AND expires>?",(now+self.lease_seconds,id,fence,now))
            return cur.rowcount==1

    def settle(self, id, fence, result, *, cost_microusd=0, failed=False):
        if type(cost_microusd) is not int or cost_microusd < 0: raise ValueError('Nonnegative integer cost required.')
        now=time.time()
        with self.tx() as db:
            row=db.execute("SELECT * FROM jobs WHERE id=? AND fence=? AND state='running' AND expires>?",(id,fence,now)).fetchone()
            if not row: return False
            over=cost_microusd>row['cap']; state='failed' if failed or over else 'complete'
            value={'error':'Per-run cost cap exceeded; no completion accepted.'} if over else result
            db.execute('UPDATE jobs SET state=?,cost=?,result=?,fence=NULL,expires=NULL WHERE id=?',
                       (state,cost_microusd,json.dumps(value),id)); return True

    def get(self, tenant, id):
        with self.tx() as db:
            row=db.execute('SELECT * FROM jobs WHERE id=? AND tenant=?',(id,tenant)).fetchone()
            if not row:return None
            return {'id':row['id'],'state':row['state'],'payload':json.loads(row['payload']),
                    'result':json.loads(row['result']) if row['result'] else None,'tries':row['tries'],'cost_microusd':row['cost']}

    def share(self, tenant, id):
        with self.tx() as db:
            row=db.execute("SELECT * FROM jobs WHERE id=? AND tenant=? AND state='complete'",(id,tenant)).fetchone()
            if not row: raise ValueError('Only your completed report can be shared.')
            token=secrets.token_urlsafe(24)
            db.execute('UPDATE jobs SET share=?,share_expires=? WHERE id=?',(token,time.time()+7*86400,id));return token

    def shared(self, token):
        with self.tx() as db:
            row=db.execute("SELECT id,result FROM jobs WHERE share=? AND share_expires>? AND state='complete'",(token,time.time())).fetchone()
            return {'id':row['id'],'result':json.loads(row['result'])} if row else None

    def stats(self):
        with self.tx() as db:return dict(db.execute('SELECT state,count(*) FROM jobs GROUP BY state').fetchall())
