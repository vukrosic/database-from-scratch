"""minilite: a tiny SQLite-style database engine, built from scratch.

One file, standard library only:
  1. rows become bytes           (encode / decode)
  2. bytes live in 4096-byte pages (Node, Pager)
  3. pages form B-trees          (BTree)
  4. SQL text becomes a plan     (tokenize, Parser)
  5. plans run on the trees      (Database.execute)
  6. a rollback journal survives crashes (Pager.change / commit / rollback)

    python3 minilite.py users.db
"""
import bisect
import os
import re
import signal
import struct
import sys

PAGE_SIZE = 4096
MAGIC = b'minilite v1\x00\x00\x00\x00\x00'  # 16 bytes at the start of the file


class SQLError(Exception):
    pass


class CorruptError(Exception):
    pass


# ---------------------------------------------------------------- 1. rows -> bytes

def encode(values):
    """(7, 'Ada') -> count, then per value: type 1 + 8-byte int, or type 2 + 2-byte length + text."""
    out = bytearray([len(values)])
    for v in values:
        if isinstance(v, int):
            out += b'\x01' + struct.pack('>q', v)
        else:
            data = v.encode('utf-8')
            out += b'\x02' + struct.pack('>H', len(data)) + data
    return bytes(out)


def decode(buf, i=0):
    count = buf[i]
    i += 1
    values = []
    for _ in range(count):
        kind = buf[i]
        i += 1
        if kind == 1:
            values.append(struct.unpack_from('>q', buf, i)[0])
            i += 8
        elif kind == 2:
            n = struct.unpack_from('>H', buf, i)[0]
            i += 2
            values.append(bytes(buf[i:i + n]).decode('utf-8'))
            i += n
        else:
            raise CorruptError(f'unknown value type {kind}')
    return tuple(values)


# ---------------------------------------------------------------- 2. pages

LEAF, INTERIOR = 1, 2
HEADER = 9  # page type (1) + cell count (2) + content start (2) + right child (4)


class Node:
    """One B-tree page, decoded.
    Leaf:     keys[i] -> vals[i] (the row bytes).
    Interior: kids[i] holds every key <= keys[i]; the last kid holds the rest."""

    def __init__(self, leaf, keys=None, vals=None, kids=None):
        self.leaf = leaf
        self.keys = keys if keys is not None else []
        self.vals = vals if vals is not None else []
        self.kids = kids if kids is not None else []
        self.recount()

    def cell_size(self, key, val):
        if self.leaf:  # pointer + key length + key + row length + row
            return 2 + 2 + len(encode(key)) + 2 + len(val)
        return 2 + 4 + 2 + len(encode(key))  # pointer + child page + key length + key

    def recount(self):
        items = self.vals if self.leaf else self.kids
        self.used = HEADER + sum(self.cell_size(k, v) for k, v in zip(self.keys, items))

    def to_bytes(self, size):
        """Slotted page: header, then cell pointers, free space, cells packed from the end."""
        page = bytearray(size)
        end = size
        for i, key in enumerate(self.keys):
            k = encode(key)
            if self.leaf:
                cell = struct.pack('>H', len(k)) + k + struct.pack('>H', len(self.vals[i])) + self.vals[i]
            else:
                cell = struct.pack('>I', self.kids[i]) + struct.pack('>H', len(k)) + k
            end -= len(cell)
            page[end:end + len(cell)] = cell
            struct.pack_into('>H', page, HEADER + 2 * i, end)
        right = 0 if self.leaf else self.kids[-1]
        struct.pack_into('>BHHI', page, 0, LEAF if self.leaf else INTERIOR, len(self.keys), end, right)
        return bytes(page)


def parse(page):
    kind, count, _, right = struct.unpack_from('>BHHI', page, 0)
    if kind not in (LEAF, INTERIOR):
        raise CorruptError(f'not a b-tree page (type byte {kind})')
    node = Node(kind == LEAF)
    for i in range(count):
        p = struct.unpack_from('>H', page, HEADER + 2 * i)[0]
        if node.leaf:
            klen = struct.unpack_from('>H', page, p)[0]
            node.keys.append(decode(page, p + 2))
            p += 2 + klen
            vlen = struct.unpack_from('>H', page, p)[0]
            node.vals.append(bytes(page[p + 2:p + 2 + vlen]))
        else:
            node.kids.append(struct.unpack_from('>I', page, p)[0])
            node.keys.append(decode(page, p + 6))
    if not node.leaf:
        node.kids.append(right)
    node.recount()
    return node


class Pager:
    """Moves whole pages between the file and memory. Page n lives at byte n * PAGE_SIZE.
    Page 0 starts with the 16-byte MAGIC; its b-tree fills the rest of the page."""

    def __init__(self, path, journal=True):
        self.path = path
        self.journal_path = path + '-journal'
        self.use_journal = journal
        if not os.path.exists(path):
            open(path, 'wb').close()
        self.recovered = os.path.exists(self.journal_path)
        if self.recovered:
            self.rollback_journal()
        self.file = open(path, 'r+b')
        self.count = os.path.getsize(path) // PAGE_SIZE
        self.cache = {}
        self.dirty = set()
        self.reads = 0          # pages fetched from the file
        self.touched = 0        # pages visited by queries
        self.journal = None
        self.saved = set()
        self.start_count = self.count

    def capacity(self, n):
        return PAGE_SIZE - (len(MAGIC) if n == 0 else 0)

    def read(self, n):
        if n >= self.count:
            raise CorruptError(f'page {n} is past the end of the file')
        self.reads += 1
        self.file.seek(n * PAGE_SIZE)
        data = self.file.read(PAGE_SIZE)
        if len(data) < PAGE_SIZE:
            raise CorruptError(f'page {n} is cut short')
        if n == 0:
            if data[:len(MAGIC)] != MAGIC:
                raise CorruptError('not a minilite file')
            data = data[len(MAGIC):]
        return data

    def get(self, n):
        self.touched += 1
        if n not in self.cache:
            self.cache[n] = parse(self.read(n))
        return self.cache[n]

    def new(self, node):
        n = self.count
        self.count += 1
        self.cache[n] = node
        self.dirty.add(n)
        return n

    def put(self, n, node):
        self.change(n)
        self.cache[n] = node

    def change(self, n):
        """Call before modifying page n: copy its old bytes into the journal first."""
        if self.use_journal and n < self.start_count and n not in self.saved:
            if self.journal is None:
                self.journal = open(self.journal_path, 'wb')
                self.journal.write(struct.pack('>I', self.start_count))
            self.file.seek(n * PAGE_SIZE)
            self.journal.write(struct.pack('>I', n) + self.file.read(PAGE_SIZE))
            self.saved.add(n)
        self.dirty.add(n)

    def page_bytes(self, n):
        body = self.cache[n].to_bytes(self.capacity(n))
        return MAGIC + body if n == 0 else body

    def commit(self):
        if self.journal:  # 1. the old pages are safely on disk
            self.journal.flush()
            os.fsync(self.journal.fileno())
        for n in sorted(self.dirty):  # 2. write the new pages over the old ones
            self.file.seek(n * PAGE_SIZE)
            self.file.write(self.page_bytes(n))
            crash_point(self.file)
        self.file.flush()
        os.fsync(self.file.fileno())
        if self.journal:  # 3. deleting the journal is the moment of commit
            self.journal.close()
            os.remove(self.journal_path)
        self.journal, self.saved, self.dirty = None, set(), set()
        self.start_count = self.count
        self.cache.clear()

    def discard(self):
        """ROLLBACK before commit: nothing reached the file yet, so forget the changes."""
        if self.journal:
            self.journal.close()
            os.remove(self.journal_path)
        self.journal, self.saved, self.dirty = None, set(), set()
        self.count = self.start_count
        self.cache.clear()

    def rollback_journal(self):
        """A journal left behind means a crash mid-commit: put every saved page back."""
        with open(self.journal_path, 'rb') as j:
            data = j.read()
        if len(data) >= 4:
            start_count = struct.unpack_from('>I', data, 0)[0]
            with open(self.path, 'r+b') as f:
                i = 4
                while i + 4 + PAGE_SIZE <= len(data):
                    n = struct.unpack_from('>I', data, i)[0]
                    f.seek(n * PAGE_SIZE)
                    f.write(data[i + 4:i + 4 + PAGE_SIZE])
                    i += 4 + PAGE_SIZE
                f.truncate(start_count * PAGE_SIZE)
                f.flush()
                os.fsync(f.fileno())
        os.remove(self.journal_path)


def crash_point(f, _state={'left': int(os.environ.get('MINILITE_CRASH_AFTER', '-1'))}):
    """Test hook: MINILITE_CRASH_AFTER=3 kills the process after 3 page writes."""
    if _state['left'] < 0:
        return
    _state['left'] -= 1
    if _state['left'] == 0:
        f.flush()
        os.kill(os.getpid(), signal.SIGKILL)


# ---------------------------------------------------------------- 3. B-trees

class BTree:
    def __init__(self, pager, root):
        self.pager = pager
        self.root = root

    def path_to(self, key):
        """Walk from the root down to the leaf where key belongs: (page numbers, leaf)."""
        path, n = [], self.root
        while True:
            path.append(n)
            node = self.pager.get(n)
            if node.leaf:
                return path, node
            n = node.kids[bisect.bisect_left(node.keys, key)]

    def get(self, key):
        _, node = self.path_to(key)
        i = bisect.bisect_left(node.keys, key)
        if i < len(node.keys) and node.keys[i] == key:
            return node.vals[i]
        return None

    def insert(self, key, val):
        path, node = self.path_to(key)
        n = path[-1]
        i = bisect.bisect_left(node.keys, key)
        if i < len(node.keys) and node.keys[i] == key:
            raise SQLError(f'duplicate key {key[0]!r}')
        if node.cell_size(key, val) > self.pager.capacity(1) // 4:
            raise SQLError('row too big for one page')
        self.pager.change(n)
        node.keys.insert(i, key)
        node.vals.insert(i, val)
        node.used += node.cell_size(key, val)
        self.split_if_full(path)

    def split_if_full(self, path):
        n = path.pop()
        node = self.pager.get(n)
        if node.used <= self.pager.capacity(n):
            return
        mid = len(node.keys) // 2
        if node.leaf:
            right = Node(True, node.keys[mid:], node.vals[mid:])
            del node.keys[mid:]
            del node.vals[mid:]
            up = node.keys[-1]            # the left page's largest key goes up
        else:
            up = node.keys[mid]
            right = Node(False, node.keys[mid + 1:], kids=node.kids[mid + 1:])
            del node.keys[mid:]
            del node.kids[mid + 1:]
        node.recount()
        if not path:                      # the root split: the tree grows one level
            left_n = self.pager.new(Node(node.leaf, node.keys, node.vals, node.kids))
            right_n = self.pager.new(right)
            self.pager.put(n, Node(False, [up], kids=[left_n, right_n]))
            return
        right_n = self.pager.new(right)
        parent_n = path[-1]
        parent = self.pager.get(parent_n)
        self.pager.change(parent_n)
        i = parent.kids.index(n)
        parent.keys.insert(i, up)
        parent.kids.insert(i + 1, right_n)
        parent.used += parent.cell_size(up, right_n)
        self.split_if_full(path)

    def scan(self, start=None, n=None):
        """Every (key, value) in key order, starting at the first key >= start."""
        node = self.pager.get(self.root if n is None else n)
        i = 0 if start is None else bisect.bisect_left(node.keys, start)
        if node.leaf:
            for j in range(i, len(node.keys)):
                yield node.keys[j], node.vals[j]
        else:
            for kid in node.kids[i:]:
                yield from self.scan(start, kid)

    def depth(self):
        d, node = 1, self.pager.get(self.root)
        while not node.leaf:
            d += 1
            node = self.pager.get(node.kids[0])
        return d


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
            if self.expect('TABLE', 'INDEX') == 'TABLE':
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
            else:
                index = self.name()
                self.expect('ON')
                table = self.name()
                self.need('(')
                column = self.name()
                self.need(')')
                stmt = {'op': 'create index', 'index': index, 'table': table, 'column': column}
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
        elif self.keyword('BEGIN', 'COMMIT', 'ROLLBACK'):
            stmt = {'op': self.tokens[self.i - 1][1].lower()}
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
        self.indexes = {}  # column number -> (index name, BTree)


class Database:
    def __init__(self, path, journal=True):
        self.pager = Pager(path, journal)
        if self.pager.count == 0:
            self.pager.new(Node(True))  # page 0: the schema table
            self.pager.commit()
        self.schema = BTree(self.pager, 0)
        self.in_transaction = False
        self.plan = ''
        self.load_schema()

    def load_schema(self):
        """The schema table stores each CREATE statement; replay them to rebuild the catalog."""
        self.tables = {}
        rows = [decode(val) for _, val in self.schema.scan()]
        for kind, name, table, root, sql in sorted(rows, key=lambda r: r[0] != 'table'):
            stmt = Parser(sql).statement()
            if kind == 'table':
                self.tables[name] = Table(name, stmt['columns'], BTree(self.pager, root))
            else:
                t = self.tables[table]
                t.indexes[t.columns.index(stmt['column'])] = (name, BTree(self.pager, root))

    def table(self, name):
        if name not in self.tables:
            raise SQLError(f'no such table: {name}')
        return self.tables[name]

    def execute(self, sql):
        stmt = Parser(sql).statement()
        op = stmt['op']
        if op == 'begin':
            self.in_transaction = True
            return [], []
        if op in ('commit', 'rollback'):
            self.pager.commit() if op == 'commit' else self.pager.discard()
            self.in_transaction = False
            self.load_schema()
            return [], []
        try:
            result = getattr(self, op.replace(' ', '_'))(stmt, sql)
        except Exception:
            if not self.in_transaction:
                self.pager.discard()
                self.load_schema()
            raise
        if op != 'select' and not self.in_transaction:
            self.pager.commit()
        return result

    def create_table(self, stmt, sql):
        name = stmt['table']
        if name in self.tables:
            raise SQLError(f'table {name} already exists')
        root = self.pager.new(Node(True))
        self.tables[name] = Table(name, stmt['columns'], BTree(self.pager, root))
        self.schema.insert((name,), encode(('table', name, name, root, sql.strip().rstrip(';'))))
        return [], []

    def create_index(self, stmt, sql):
        t = self.table(stmt['table'])
        if stmt['column'] not in t.columns:
            raise SQLError(f'no such column: {stmt["column"]}')
        col = t.columns.index(stmt['column'])
        tree = BTree(self.pager, self.pager.new(Node(True)))
        for key, val in t.tree.scan():  # fill the index from every row already there
            tree.insert((decode(val)[col], key[0]), b'')
        t.indexes[col] = (stmt['index'], tree)
        self.schema.insert((stmt['index'],), encode(('index', stmt['index'], t.name, tree.root, sql.strip().rstrip(';'))))
        return [], []

    def insert(self, stmt, sql=None):
        t = self.table(stmt['table'])
        for row in stmt['rows']:
            self.insert_row(t, row)
        return [], []

    def insert_row(self, t, row):
        if len(row) != len(t.columns):
            raise SQLError(f'{t.name} has {len(t.columns)} columns but {len(row)} values were given')
        for v, kind, col in zip(row, t.kinds, t.columns):
            if (kind == 'INTEGER') != isinstance(v, int):
                raise SQLError(f'column {col} expects {kind}, got {v!r}')
        t.tree.insert((row[t.key],), encode(row))
        for col, (_, tree) in t.indexes.items():
            tree.insert((row[col], row[t.key]), b'')

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
        """The query planner: pick the cheapest way to reach the rows."""
        if where is None:
            self.plan = f'SCAN {t.name}'
            return (val for _, val in t.tree.scan())
        column, op, value = where
        if column not in t.columns:
            raise SQLError(f'no such column: {column}')
        col = t.columns.index(column)
        test = {'=': lambda v: v == value, '<': lambda v: v < value, '>': lambda v: v > value,
                '<=': lambda v: v <= value, '>=': lambda v: v >= value}[op]
        if type(value) is not (int if t.kinds[col] == 'INTEGER' else str):
            raise SQLError(f'column {column} expects {t.kinds[col]}, got {value!r}')
        if col == t.key and op == '=':
            self.plan = f'SEARCH {t.name} USING PRIMARY KEY ({column}=?)'
            val = t.tree.get((value,))
            return [] if val is None else [val]
        if col == t.key and op in ('>', '>='):
            self.plan = f'SEARCH {t.name} USING PRIMARY KEY ({column}{op}?)'
            return (val for key, val in t.tree.scan((value,)) if test(key[0]))
        if col in t.indexes and op == '=':
            name, tree = t.indexes[col]
            self.plan = f'SEARCH {t.name} USING INDEX {name} ({column}=?)'
            return self.index_lookup(t, tree, value)
        self.plan = f'SCAN {t.name}'
        return (val for _, val in t.tree.scan() if test(decode(val)[col]))

    def index_lookup(self, t, tree, value):
        for key, _ in tree.scan((value,)):
            if key[0] != value:
                break
            yield t.tree.get((key[1],))

    def check(self, t):
        """Walk every page: keys must be sorted and inside their parent's range. Returns the row count."""
        def walk(n, lo, hi):
            node = self.pager.get(n)
            for a, b in zip(node.keys, node.keys[1:]):
                if not a < b:
                    raise CorruptError(f'page {n}: keys out of order')
            if node.keys and ((lo is not None and node.keys[0] <= lo) or (hi is not None and node.keys[-1] > hi)):
                raise CorruptError(f'page {n}: key outside its parent range')
            if node.leaf:
                return len(node.keys)
            bounds = [lo] + node.keys + [hi]
            return sum(walk(kid, bounds[i], bounds[i + 1]) for i, kid in enumerate(node.kids))
        return walk(t.tree.root, None, None)


def main():
    db = Database(sys.argv[1] if len(sys.argv) > 1 else 'minilite.db')
    if db.pager.recovered:
        print('found a leftover journal: rolled back the unfinished transaction')
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
        except (SQLError, CorruptError) as e:
            print('Error:', e)
            continue
        for row in rows:
            print(' | '.join(str(v) for v in row))
        if columns:
            print(f'-- {db.plan}  ({db.reads} page{"" if db.reads == 1 else "s"} read)')


if __name__ == '__main__':
    main()
