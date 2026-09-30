"""Tiny pages (64 bytes: 3 keys per leaf) so every B-tree split is visible (chapter 4 trace).
Writes btree-trace.json: the tree after each insert."""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import minilite

minilite.PAGE_SIZE = 64
KEYS = [50, 20, 80, 10, 30, 40, 70, 90, 60, 25, 35, 45, 15, 85, 95, 55, 65, 75]


def snapshot(pager, n):
    node = pager.cache[n] if n in pager.cache else pager.get(n)
    if node.leaf:
        return {'page': n, 'keys': [k[0] for k in node.keys]}
    return {'page': n, 'keys': [k[0] for k in node.keys], 'kids': [snapshot(pager, k) for k in node.kids]}


def show(t, depth=0):
    line = '  ' * depth + f'p{t["page"]} {t["keys"]}'
    return '\n'.join([line] + [show(k, depth + 1) for k in t.get('kids', [])])


if __name__ == '__main__':
    path = 'trace.db'
    if os.path.exists(path):
        os.remove(path)
    pager = minilite.Pager(path, journal=False)
    pager.new(minilite.Node(True))                       # page 0 (unused here)
    tree = minilite.BTree(pager, pager.new(minilite.Node(True)))
    steps = []
    for k in KEYS:
        before = pager.count
        path_pages, _ = tree.path_to((k,))
        tree.insert((k,), b'')
        snap = snapshot(pager, tree.root)
        steps.append({'insert': k, 'path': path_pages, 'new_pages': list(range(before, pager.count)), 'tree': snap})
        print(f'insert {k}: path {path_pages}, new pages {list(range(before, pager.count))}')
        print(show(snap))
    json.dump(steps, open('btree-trace.json', 'w'), indent=1)
    touched = pager.touched
    print('depth', tree.depth())
    pager.touched = 0
    tree.get((65,))
    print('get(65) touched', pager.touched, 'pages; path', tree.path_to((65,))[0])
    os.remove(path)
