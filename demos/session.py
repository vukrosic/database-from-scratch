"""A REPL session with the input echoed, as shown in the video."""
import builtins, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import minilite

SESSION = """CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT);
INSERT INTO users VALUES (1, 'Ada Lovelace', 'ada@mail.com'), (2, 'Grace Hopper', 'grace@mail.com'), (3, 'Linus Torvalds', 'linus@mail.com');
SELECT * FROM users;
SELECT name FROM users WHERE id = 2;
SELECT * FROM users WHERE email = 'linus@mail.com';
CREATE INDEX users_email ON users(email);
SELECT * FROM users WHERE email = 'linus@mail.com';
SELECT id, name FROM users WHERE id >= 2;
BEGIN;
INSERT INTO users VALUES (4, 'Ken Thompson', 'ken@mail.com');
SELECT count(*) FROM users;
ROLLBACK;
SELECT count(*) FROM users;
INSERT INTO users VALUES (2, 'Someone', 'x@mail.com');
SELEC * FROM users;""".splitlines()

if __name__ == '__main__':
    path = 'session.db'
    for f in (path, path + '-journal'):
        if os.path.exists(f):
            os.remove(f)
    lines = iter(SESSION)

    def fake_input(prompt):
        line = next(lines, None)
        if line is None:
            raise EOFError
        print(prompt + line)
        return line

    builtins.input = fake_input
    sys.argv = ['minilite.py', path]
    minilite.main()
    data = open(path, 'rb').read()
    print(f'\n{path}: {len(data):,} bytes = {len(data) // 4096} pages')
    for n in range(len(data) // 4096):
        page = data[n * 4096:(n + 1) * 4096]
        body = page[16:] if n == 0 else page
        kind, count, start, right = minilite.struct.unpack_from('>BHHI', body, 0)
        what = {0: 'schema', 1: 'table users', 2: 'index users_email'}.get(n, '?')
        print(f'page {n} ({what}): first bytes {page[:16]!r}' if n == 0 else f'page {n} ({what}):', 
              f'type {kind}, {count} cells, cells start at byte {start}')
    os.remove(path)
