"""One million rows in minilite: how many pages does each query read?"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import minilite

FIRST = ['Ada', 'Grace', 'Linus', 'Alan', 'Barbara', 'Dennis', 'Margaret', 'Ken', 'Guido', 'Katherine']
LAST = ['Lovelace', 'Hopper', 'Torvalds', 'Turing', 'Liskov', 'Ritchie', 'Hamilton', 'Thompson', 'Rossum', 'Johnson']
N = 1_000_000


def user(i):
    f, l = FIRST[i % 10], LAST[(i // 10) % 10]
    return (i, f'{f} {l}', f'{f.lower()}.{l.lower()}{i}@mail.com')


def run(db, sql):
    t0 = time.time()
    rows = db.execute(sql)
    ms = (time.time() - t0) * 1000
    print(f'{sql}\n   -> {rows[1][:1]}  {db.plan}  {db.reads:,} pages read  {ms:,.1f} ms')


if __name__ == '__main__':
    path = 'million.db'
    for f in (path, path + '-journal'):
        if os.path.exists(f):
            os.remove(f)
    db = minilite.Database(path)
    db.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)')
    t0 = time.time()
    db.execute('BEGIN')
    t = db.tables['users']
    for i in range(1, N + 1):
        db.insert_row(t, user(i))
    db.execute('COMMIT')
    size = os.path.getsize(path)
    print(f'inserted {N:,} rows in {time.time() - t0:.1f} s, file {size:,} bytes = {size // 4096:,} pages')
    db = minilite.Database(path)
    print('table depth', db.tables['users'].tree.depth())
    run(db, 'SELECT * FROM users WHERE id = 777777')
    run(db, "SELECT * FROM users WHERE email = 'ken.thompson777777@mail.com'")
    run(db, 'SELECT count(*) FROM users')
    t0 = time.time()
    db.execute('CREATE INDEX users_email ON users(email)')
    size2 = os.path.getsize(path)
    print(f'CREATE INDEX in {time.time() - t0:.1f} s, file now {size2 // 4096:,} pages (+{(size2 - size) // 4096:,})')
    db = minilite.Database(path)
    print('index depth', db.tables['users'].indexes[2][1].depth())
    run(db, "SELECT * FROM users WHERE email = 'ken.thompson777777@mail.com'")
    print('check:', db.check(db.tables['users']), 'rows ok')
    os.remove(path)
