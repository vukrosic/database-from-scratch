"""python3 tests.py  -- checks every layer of minilite."""
import os, random, subprocess, sys, tempfile
import minilite
from minilite import Database, Node, SQLError, decode, encode, parse

tmp = tempfile.mkdtemp()
passed = 0


def fresh(name):
    path = os.path.join(tmp, name)
    for f in (path, path + '-journal'):
        if os.path.exists(f):
            os.remove(f)
    return path


def ok(cond, what):
    global passed
    if not cond:
        raise AssertionError(what)
    passed += 1


def raises(sql, db, text):
    try:
        db.execute(sql)
    except SQLError as e:
        ok(text in str(e), f'{sql!r} gave {e!r}, wanted {text!r}')
        return
    raise AssertionError(f'{sql!r} did not fail')


# rows -> bytes
for row in [(1, 'Ada'), (-5, ''), (2**63 - 1, 'Hopper, Grace'), ('ünïcode ✓', 0)]:
    ok(decode(encode(row)) == row, f'round trip {row}')

# one page -> bytes -> page
node = Node(True, [(i,) for i in range(50)], [encode((i, 'x' * i)) for i in range(50)])
again = parse(node.to_bytes(4096))
ok(again.keys == node.keys and again.vals == node.vals, 'leaf page round trip')
inner = Node(False, [(10,), (20,)], kids=[3, 4, 5])
again = parse(inner.to_bytes(4096))
ok(again.keys == inner.keys and again.kids == inner.kids, 'interior page round trip')

# b-tree: random inserts, every key found, scan sorted, invariants hold
path = fresh('tree.db')
db = Database(path)
db.execute('CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)')
ids = list(range(20000))
random.seed(7)
random.shuffle(ids)
db.execute('BEGIN')
for i in ids:
    db.insert_row(db.tables['t'], (i, f'value {i}'))
db.execute('COMMIT')
db = Database(path)
t = db.tables['t']
ok(t.tree.depth() == 3, f'depth {t.tree.depth()}')
ok(db.check(t) == 20000, 'check counts every row')
ok([k[0] for k, _ in t.tree.scan()] == list(range(20000)), 'scan is sorted')
ok(all(decode(t.tree.get((i,)))[1] == f'value {i}' for i in range(0, 20000, 97)), 'get finds rows')
ok(t.tree.get((20000,)) is None, 'missing key')
db.execute('SELECT * FROM t WHERE id = 12345')
ok(db.reads == 3, f'point lookup reads one page per level, got {db.reads}')

# SQL
path = fresh('sql.db')
db = Database(path)
db.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT);')
db.execute("INSERT INTO users VALUES (1, 'Ada', 'ada@mail.com'), (2, 'Grace', 'grace@mail.com'), (3, 'Linus', 'linus@mail.com')")
ok(db.execute('SELECT name FROM users WHERE id = 2') == (['name'], [('Grace',)]), 'select by key')
ok(db.execute('SELECT id FROM users WHERE id >= 2')[1] == [(2,), (3,)], 'range >=')
ok(db.execute('SELECT id FROM users WHERE id < 3')[1] == [(1,), (2,)], 'range <')
ok(db.execute('SELECT count(*) FROM users')[1] == [(3,)], 'count')
raises('SELEC * FROM users', db, 'unknown statement')
raises('SELECT * FROM nope', db, 'no such table')
raises("INSERT INTO users VALUES ('x', 'a', 'b')", db, 'expects INTEGER')
raises("INSERT INTO users VALUES (1, 'again', 'a')", db, 'duplicate key')
raises("INSERT INTO users VALUES (9, 'nine', 'a'), (1, 'dup', 'b')", db, 'duplicate key')
ok(db.execute('SELECT count(*) FROM users')[1] == [(3,)], 'failed statement changed nothing')
raises('CREATE TABLE bad (name TEXT)', db, 'INTEGER PRIMARY KEY')
raises('SELECT * FROM users WHERE id = ', db, 'expected a value')

# index + planner
db.execute('CREATE INDEX users_email ON users(email)')
db.execute("INSERT INTO users VALUES (4, 'Ken', 'ken@mail.com')")
db = Database(path)  # the index survives reopening
ok(db.execute("SELECT id FROM users WHERE email = 'ken@mail.com'")[1] == [(4,)], 'index finds new row')
ok(db.plan == 'SEARCH users USING INDEX users_email (email=?)', db.plan)
db.execute("SELECT id FROM users WHERE name = 'Ken'")
ok(db.plan == 'SCAN users', db.plan)

# transactions: ROLLBACK forgets, COMMIT keeps
db.execute('BEGIN')
db.execute("INSERT INTO users VALUES (5, 'Barbara', 'b@mail.com')")
db.execute('ROLLBACK')
ok(db.execute('SELECT count(*) FROM users')[1] == [(4,)], 'rollback')
ok(db.execute("SELECT id FROM users WHERE email = 'b@mail.com'")[1] == [], 'rollback reaches the index')

# crash in the middle of COMMIT: the journal puts the old pages back
path = fresh('crash.db')
db = Database(path)
db.execute('CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)')
db.execute('BEGIN')
for i in range(0, 20000, 2):
    db.insert_row(db.tables['t'], (i, 'old'))
db.execute('COMMIT')
child = f"""
import minilite
db = minilite.Database({path!r})
db.execute('BEGIN')
for i in range(1, 8001, 2):
    db.insert_row(db.tables['t'], (i, 'new'))
db.execute('COMMIT')
"""
env = dict(os.environ, MINILITE_CRASH_AFTER='3', PYTHONPATH=os.path.dirname(os.path.abspath(__file__)))
r = subprocess.run([sys.executable, '-c', child], env=env)
ok(r.returncode == -9, 'child was killed mid-commit')
ok(os.path.exists(path + '-journal'), 'journal left behind')
db = Database(path)
ok(db.pager.recovered and not os.path.exists(path + '-journal'), 'journal rolled back and removed')
ok(db.check(db.tables['t']) == 10000, 'old rows intact after the crash')

print(f'{passed} checks passed')
