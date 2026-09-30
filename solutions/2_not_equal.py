"""Exercise 2: WHERE col != value.
Three layers change: the tokenizer learns the symbol, the parser accepts it,
and the planner can only SCAN (no index helps with 'everything except one value')."""
import os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import minilite
from minilite import Database, Parser, decode

# 1. tokenizer: '!=' is one symbol
minilite.TOKEN = re.compile(r"\s*(?:(\d+)|'([^']*)'|(\w+)|(<=|>=|!=|[(),*=<>;]))")

# 2. parser: the WHERE check only allows = < > <= >=, so parse '!=' as '=' and put it back after
statement = Parser.statement


def parse_not_equal(self):
    ne = [i for i, tok in enumerate(self.tokens) if tok == ('sym', '!=')]
    for i in ne:
        self.tokens[i] = ('sym', '=')
    stmt = statement(self)
    if ne and stmt.get('where'):
        column, _, value = stmt['where']
        stmt['where'] = (column, '!=', value)
    return stmt


# 3. planner: always a scan
find = Database.find


def find_not_equal(self, t, where):
    if where is None or where[1] != '!=':
        return find(self, t, where)
    column, _, value = where
    col = t.columns.index(column)
    self.plan = f'SCAN {t.name}'
    return (val for _, val in t.tree.scan() if decode(val)[col] != value)


Parser.statement = parse_not_equal
Database.find = find_not_equal

if __name__ == '__main__':
    path = 'ne-demo.db'
    for f in (path, path + '-journal'):
        if os.path.exists(f):
            os.remove(f)
    db = Database(path)
    db.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)')
    db.execute("INSERT INTO users VALUES (1, 'Ada'), (2, 'Grace'), (3, 'Linus')")
    print(db.execute("SELECT name FROM users WHERE name != 'Grace'")[1], db.plan)
    os.remove(path)
