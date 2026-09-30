"""Same million users in the real SQLite (Python's built-in sqlite3), for comparison."""
import os, sqlite3, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from million_demo import N, user

path = 'real.db'
if os.path.exists(path):
    os.remove(path)
con = sqlite3.connect(path)
print('SQLite version', sqlite3.sqlite_version)
con.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)')
t0 = time.time()
con.executemany('INSERT INTO users VALUES (?, ?, ?)', (user(i) for i in range(1, N + 1)))
con.commit()
print(f'inserted {N:,} rows in {time.time() - t0:.1f} s')
print('page_size', con.execute('PRAGMA page_size').fetchone()[0], 'page_count', f"{con.execute('PRAGMA page_count').fetchone()[0]:,}")
print('first 16 bytes', open(path, 'rb').read(16))


def run(sql):
    plan = ' '.join(r[3] for r in con.execute('EXPLAIN QUERY PLAN ' + sql))
    t0 = time.time()
    rows = con.execute(sql).fetchall()
    print(f'{sql}\n   -> {rows[:1]}  {plan}  {(time.time() - t0) * 1000:,.1f} ms')


run('SELECT * FROM users WHERE id = 777777')
run("SELECT * FROM users WHERE email = 'ken.thompson777777@mail.com'")
run('SELECT count(*) FROM users')
t0 = time.time()
con.execute('CREATE INDEX users_email ON users(email)')
con.commit()
print(f'CREATE INDEX in {time.time() - t0:.1f} s, page_count {con.execute("PRAGMA page_count").fetchone()[0]:,}')
run("SELECT * FROM users WHERE email = 'ken.thompson777777@mail.com'")
con.close()
os.remove(path)
