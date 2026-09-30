"""Exercise 1: DELETE FROM table WHERE id = n.
Remove the cell from its leaf (and from every index). Pages may end up emptier; we don't merge them."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import minilite
from minilite import BTree, Database, Parser, SQLError, decode


def tree_delete(self, key):
    path, node = self.path_to(key)
    i = minilite.bisect.bisect_left(node.keys, key)
    if i == len(node.keys) or node.keys[i] != key:
        return False
    self.pager.change(path[-1])
    node.used -= node.cell_size(key, node.vals[i])
    del node.keys[i]
    del node.vals[i]
    return True


BTree.delete = tree_delete
statement = Parser.statement


def parse_delete(self):
    if not self.keyword('DELETE'):
        return statement(self)
    self.expect('FROM')
    table = self.name()
    self.expect('WHERE')
    column = self.name()
    self.need('=')
    value = self.value()
    self.symbol(';')
    return {'op': 'delete', 'table': table, 'where': (column, '=', value)}


def delete(self, stmt, sql=None):
    t = self.table(stmt['table'])
    column, _, value = stmt['where']
    if column != t.columns[t.key]:
        raise SQLError('DELETE only works on the primary key here')
    val = t.tree.get((value,))
    if val is None:
        return [], []
    row = decode(val)
    t.tree.delete((value,))
    for col, (_, tree) in t.indexes.items():
        tree.delete((row[col], value))
    return [], []


Parser.statement = parse_delete
Database.delete = delete

if __name__ == '__main__':
    path = 'delete-demo.db'
    for f in (path, path + '-journal'):
        if os.path.exists(f):
            os.remove(f)
    db = Database(path)
    db.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)')
    db.execute('CREATE INDEX users_email ON users(email)')
    db.execute("INSERT INTO users VALUES (1, 'Ada', 'ada@mail.com'), (2, 'Grace', 'grace@mail.com')")
    db.execute('DELETE FROM users WHERE id = 1')
    print(db.execute('SELECT * FROM users')[1])
    print(db.execute("SELECT * FROM users WHERE email = 'ada@mail.com'")[1], db.plan)
    os.remove(path)
