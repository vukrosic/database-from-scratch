"""Crash in the middle of a commit, with and without the rollback journal (chapter 6 numbers)."""
import os, subprocess, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import minilite

CHILD = r'''
import sys; sys.path.insert(0, {root!r})
import minilite
db = minilite.Database({path!r}, journal={journal})
t = db.tables['users']
db.execute('BEGIN')
for i in range(1, 20001):                    # 20,000 new rows: odd ids 1..39,999
    db.insert_row(t, (2 * i - 1, 'New User %d' % i, 'new%d@mail.com' % i))
db.execute('COMMIT')                          # MINILITE_CRASH_AFTER kills us in here
'''


def build(path, n=100_000):
    for f in (path, path + '-journal'):
        if os.path.exists(f):
            os.remove(f)
    db = minilite.Database(path)
    db.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)')
    db.execute('BEGIN')
    t = db.tables['users']
    for i in range(1, n + 1):
        db.insert_row(t, (2 * i, 'User %d' % i, 'user%d@mail.com' % i))   # even ids
    db.execute('COMMIT')


def report(path):
    db = minilite.Database(path)
    note = ' (found a leftover journal: rolled back)' if db.pager.recovered else ''
    try:
        n = db.check(db.tables['users'])
        print(f'  reopen{note}: check passed, {n:,} rows')
    except Exception as e:
        print(f'  reopen{note}: {type(e).__name__}: {e}')
    try:
        print('  SELECT count(*):', db.execute('SELECT count(*) FROM users')[1][0][0])
    except Exception as e:
        print(f'  SELECT count(*): {type(e).__name__}: {e}')


if __name__ == '__main__':
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    for journal in (False, True):
        path = f'crash-{"journal" if journal else "nojournal"}.db'
        build(path)
        print(f'journal={journal}: 100,000 rows, then a 20,000-row transaction, killed after 3 page writes')
        env = dict(os.environ, MINILITE_CRASH_AFTER='3')
        r = subprocess.run([sys.executable, '-c', CHILD.format(root=root, path=path, journal=journal)], env=env)
        print('  child exit signal:', -r.returncode, '| journal file left:', os.path.exists(path + '-journal'))
        report(path)
        for f in (path, path + '-journal'):
            if os.path.exists(f):
                os.remove(f)
