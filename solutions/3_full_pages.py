"""Exercise 3: appending ids in order leaves every page half empty (a 50/50 split, then nothing
ever lands in the left half again). Real SQLite packs them full. When the new key went to the very
end of the rightmost page, split off only the last cell instead of half."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import minilite
from minilite import BTree, Database, Node

insert = BTree.insert


def insert_tracking(self, key, val):
    _, node = self.path_to(key)
    self.appending = not node.keys or key > node.keys[-1]
    insert(self, key, val)


def split_if_full(self, path):
    n = path.pop()
    node = self.pager.get(n)
    if node.used <= self.pager.capacity(n):
        return
    rightmost = getattr(self, 'appending', False) and len(node.keys) > 2
    mid = len(node.keys) - (1 if node.leaf else 2) if rightmost else len(node.keys) // 2
    if node.leaf:
        right = Node(True, node.keys[mid:], node.vals[mid:])
        del node.keys[mid:]
        del node.vals[mid:]
        up = node.keys[-1]
    else:
        up = node.keys[mid]
        right = Node(False, node.keys[mid + 1:], kids=node.kids[mid + 1:])
        del node.keys[mid:]
        del node.kids[mid + 1:]
    node.recount()
    if not path:
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
    split_if_full(self, path)


def pages_for(n, packed):
    path = 'full-demo.db'
    for f in (path, path + '-journal'):
        if os.path.exists(f):
            os.remove(f)
    BTree.insert = insert_tracking if packed else insert
    BTree.split_if_full = split_if_full if packed else original_split
    db = Database(path)
    db.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)')
    db.execute('BEGIN')
    for i in range(1, n + 1):
        db.insert_row(db.tables['users'], (i, f'User {i}', f'user{i}@mail.com'))
    db.execute('COMMIT')
    db = Database(path)
    rows = db.check(db.tables['users'])
    size = os.path.getsize(path) // minilite.PAGE_SIZE
    os.remove(path)
    return size, rows


original_split = BTree.split_if_full

if __name__ == '__main__':
    for packed in (False, True):
        pages, rows = pages_for(100_000, packed)
        print(f'{"packed" if packed else "50/50 "} split: {rows:,} rows in {pages:,} pages')
