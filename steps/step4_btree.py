"""Step 4: many pages, organised as a B+tree. Lookups read one page per level.
Pager: page n lives at byte n * 4096. BTree: split full pages, grow from the root."""
import bisect
import os
import random
import struct
from step2_records import encode, decode

PAGE_SIZE = 4096


class SQLError(Exception):
    pass


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
    """Moves whole pages between the file and memory. Page n lives at byte n * PAGE_SIZE."""

    def __init__(self, path):
        if not os.path.exists(path):
            open(path, 'wb').close()
        self.file = open(path, 'r+b')
        self.count = os.path.getsize(path) // PAGE_SIZE
        self.cache = {}
        self.dirty = set()
        self.touched = 0        # pages visited by lookups

    def capacity(self, n):
        return PAGE_SIZE

    def get(self, n):
        self.touched += 1
        if n not in self.cache:
            self.file.seek(n * PAGE_SIZE)
            self.cache[n] = parse(self.file.read(PAGE_SIZE))
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
        self.dirty.add(n)

    def flush(self):
        for n in sorted(self.dirty):
            self.file.seek(n * PAGE_SIZE)
            self.file.write(self.cache[n].to_bytes(PAGE_SIZE))
        self.file.flush()
        self.dirty = set()


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


if __name__ == '__main__':
    path = 'users-btree.db'
    if os.path.exists(path):
        os.remove(path)
    pager = Pager(path)
    tree = BTree(pager, pager.new(Node(True)))
    ids = list(range(1, 100_001))
    random.seed(1)
    random.shuffle(ids)
    for i in ids:
        tree.insert((i,), encode((i, f'User {i}', f'user{i}@mail.com')))
    pager.flush()
    print(f'100,000 rows in {pager.count:,} pages, depth {tree.depth()}')
    pager = Pager(path)                 # reopen: nothing cached
    tree = BTree(pager, 0)
    pager.touched = 0
    print('get(77777):', decode(tree.get((77777,))), f'- {pager.touched} pages read')
    first = [key[0] for (key, _), _ in zip(tree.scan((500,)), range(5))]
    print('scan from 500:', first)
    os.remove(path)
