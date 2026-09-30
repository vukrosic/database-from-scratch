"""Step 5: SQL. Text -> tokens -> statement -> run it on the B-trees.
Page 0 holds the schema table: one row per CREATE TABLE, so the file describes itself."""
import os
import re
import sys
from step2_records import encode, decode
from step4_btree import Node, Pager, BTree, SQLError


# ---------------------------------------------------------------- 4. SQL text -> statement

TOKEN = re.compile(r"\s*(?:(\d+)|'([^']*)'|(\w+)|(<=|>=|[(),*=<>;]))")


def tokenize(sql):
    tokens, pos, sql = [], 0, sql.rstrip()
    while pos < len(sql):
        m = TOKEN.match(sql, pos)
        if not m:
            raise SQLError(f'unexpected {sql[pos:].strip()[:1]!r} at position {pos}')
        num, text, word, sym = m.groups()
        if num is not None:
            tokens.append(('num', int(num)))
        elif text is not None:
            tokens.append(('text', text))
        elif word is not None:
            tokens.append(('word', word))
        else:
            tokens.append(('sym', sym))
        pos = m.end()
    return tokens


class Parser:
    def __init__(self, sql):
        self.tokens = tokenize(sql)
        self.i = 0

    def peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else ('end', 'the end')

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def keyword(self, *words):
        kind, value = self.peek()
        if kind == 'word' and value.upper() in words:
            self.i += 1
            return value.upper()
        return None

    def expect(self, *words):
        found = self.keyword(*words)
        if not found:
            raise SQLError(f'expected {" or ".join(words)} but found {self.peek()[1]!r}')
        return found

    def symbol(self, s):
        if self.peek() == ('sym', s):
            self.i += 1
            return True
        return False

    def need(self, s):
        if not self.symbol(s):
            raise SQLError(f"expected '{s}' but found {self.peek()[1]!r}")

    def name(self):
        kind, value = self.take()
        if kind != 'word':
            raise SQLError(f'expected a name but found {value!r}')
        return value.lower()

    def value(self):
        kind, value = self.take()
        if kind not in ('num', 'text'):
            raise SQLError(f'expected a value but found {value!r}')
        return value

    def statement(self):
        if self.keyword('CREATE'):
            if self.expect('TABLE'):
                table = self.name()
                self.need('(')
                columns = []
                while True:
                    col = self.name()
                    kind = self.expect('INTEGER', 'TEXT')
                    key = bool(self.keyword('PRIMARY')) and bool(self.expect('KEY'))
                    columns.append((col, kind, key))
                    if not self.symbol(','):
                        break
                self.need(')')
                stmt = {'op': 'create table', 'table': table, 'columns': columns}
        elif self.keyword('INSERT'):
            self.expect('INTO')
            table = self.name()
            self.expect('VALUES')
            rows = []
            while True:
                self.need('(')
                row = [self.value()]
                while self.symbol(','):
                    row.append(self.value())
                self.need(')')
                rows.append(tuple(row))
                if not self.symbol(','):
                    break
            stmt = {'op': 'insert', 'table': table, 'rows': rows}
        elif self.keyword('SELECT'):
            if self.symbol('*'):
                columns = '*'
            elif self.keyword('COUNT'):
                self.need('(')
                self.need('*')
                self.need(')')
                columns = 'count'
            else:
                columns = [self.name()]
                while self.symbol(','):
                    columns.append(self.name())
            self.expect('FROM')
            table = self.name()
            where = None
            if self.keyword('WHERE'):
                column = self.name()
                kind, op = self.take()
                if kind != 'sym' or op not in ('=', '<', '>', '<=', '>='):
                    raise SQLError(f'expected a comparison but found {op!r}')
                where = (column, op, self.value())
            stmt = {'op': 'select', 'table': table, 'columns': columns, 'where': where}
        else:
            raise SQLError(f'unknown statement starting with {self.peek()[1]!r}')
        self.symbol(';')
        if self.peek()[0] != 'end':
            raise SQLError(f'unexpected {self.peek()[1]!r} after the statement')
        return stmt


# ---------------------------------------------------------------- 5. the database

class Table:
    def __init__(self, name, columns, tree):
        self.name = name
        self.columns = [c[0] for c in columns]
        self.kinds = [c[1] for c in columns]
        keys = [i for i, c in enumerate(columns) if c[2]]
        if len(keys) != 1 or self.kinds[keys[0]] != 'INTEGER':
            raise SQLError('a table needs exactly one INTEGER PRIMARY KEY column')
        self.key = keys[0]
        self.tree = tree


class Database:
    def __init__(self, path):
        self.pager = Pager(path)
        if self.pager.count == 0:
            self.pager.new(Node(True))  # page 0: the schema table
            self.pager.flush()
        self.schema = BTree(self.pager, 0)
        self.plan = ''
        self.load_schema()

    def load_schema(self):
        """The schema table stores each CREATE statement; replay them to rebuild the catalog."""
        self.tables = {}
        for _, val in self.schema.scan():
            kind, name, table, root, sql = decode(val)
            stmt = Parser(sql).statement()
            self.tables[name] = Table(name, stmt['columns'], BTree(self.pager, root))

    def table(self, name):
        if name not in self.tables:
            raise SQLError(f'no such table: {name}')
        return self.tables[name]

    def execute(self, sql):
        stmt = Parser(sql).statement()
        result = getattr(self, stmt['op'].replace(' ', '_'))(stmt, sql)
        self.pager.flush()
        return result

    def create_table(self, stmt, sql):
        name = stmt['table']
        if name in self.tables:
            raise SQLError(f'table {name} already exists')
        root = self.pager.new(Node(True))
        self.tables[name] = Table(name, stmt['columns'], BTree(self.pager, root))
        self.schema.insert((name,), encode(('table', name, name, root, sql.strip().rstrip(';'))))
        return [], []

    def insert(self, stmt, sql=None):
        t = self.table(stmt['table'])
        for row in stmt['rows']:
            if len(row) != len(t.columns):
                raise SQLError(f'{t.name} has {len(t.columns)} columns but {len(row)} values were given')
            for v, kind, col in zip(row, t.kinds, t.columns):
                if (kind == 'INTEGER') != isinstance(v, int):
                    raise SQLError(f'column {col} expects {kind}, got {v!r}')
            t.tree.insert((row[t.key],), encode(row))
        return [], []

    def select(self, stmt, sql=None):
        t = self.table(stmt['table'])
        self.pager.touched = 0
        rows = [decode(val) for val in self.find(t, stmt['where'])]
        self.reads = self.pager.touched
        if stmt['columns'] == 'count':
            return ['count(*)'], [(len(rows),)]
        if stmt['columns'] == '*':
            return t.columns, rows
        for c in stmt['columns']:
            if c not in t.columns:
                raise SQLError(f'no such column: {c}')
        picks = [t.columns.index(c) for c in stmt['columns']]
        return stmt['columns'], [tuple(r[i] for i in picks) for r in rows]

    def find(self, t, where):
        """Primary key =: walk down the tree. Anything else: read every row."""
        if where is None:
            self.plan = f'SCAN {t.name}'
            return (val for _, val in t.tree.scan())
        column, op, value = where
        if column not in t.columns:
            raise SQLError(f'no such column: {column}')
        col = t.columns.index(column)
        test = {'=': lambda v: v == value, '<': lambda v: v < value, '>': lambda v: v > value,
                '<=': lambda v: v <= value, '>=': lambda v: v >= value}[op]
        if col == t.key and op == '=':
            self.plan = f'SEARCH {t.name} USING PRIMARY KEY ({column}=?)'
            val = t.tree.get((value,))
            return [] if val is None else [val]
        self.plan = f'SCAN {t.name}'
        return (val for _, val in t.tree.scan() if test(decode(val)[col]))


def main():
    db = Database(sys.argv[1] if len(sys.argv) > 1 else 'step5.db')
    buf = ''
    while True:
        try:
            line = input('minilite> ' if not buf else '     ...> ')
        except EOFError:
            break
        buf += line + '\n'
        if not buf.strip().endswith(';'):
            continue
        sql, buf = buf, ''
        try:
            columns, rows = db.execute(sql)
        except SQLError as e:
            print('Error:', e)
            continue
        for row in rows:
            print(' | '.join(str(v) for v in row))
        if columns:
            print(f'-- {db.plan}  ({db.reads} page{"" if db.reads == 1 else "s"} read)')


if __name__ == '__main__':
    main()
