"""Measure the naive text-file database on 1,000,000 rows (chapter 1 numbers)."""
import os, signal, subprocess, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'steps'))
from step1_textfile import insert, find, update

FIRST = ['Ada', 'Grace', 'Linus', 'Alan', 'Barbara', 'Dennis', 'Margaret', 'Ken', 'Guido', 'Katherine']
LAST = ['Lovelace', 'Hopper', 'Torvalds', 'Turing', 'Liskov', 'Ritchie', 'Hamilton', 'Thompson', 'Rossum', 'Johnson']
N = 1_000_000


def user(i):
    f, l = FIRST[i % 10], LAST[(i // 10) % 10]
    return (i, f'{f} {l}', f'{f.lower()}.{l.lower()}{i}@mail.com')


if __name__ == '__main__':
    path = 'naive-users.txt'
    if os.path.exists(path):
        os.remove(path)
    t = time.time()
    with open(path, 'a') as f:  # same format as insert(), one open for speed
        for i in range(1, N + 1):
            f.write(','.join(str(v) for v in user(i)) + '\n')
    print(f'wrote {N:,} rows in {time.time() - t:.1f} s, file {os.path.getsize(path):,} bytes')
    # keeping the file sorted: a row that belongs in the middle must push every later byte along
    with open(path, 'rb') as f:
        for _ in range(N // 2):
            f.readline()
        mid = f.tell()
        lengths = [len(f.readline()) for _ in range(1000)]
    print(f'insert in the middle of the sorted file: {os.path.getsize(path) - mid:,} bytes to move')
    print(f'lines are {min(lengths)}..{max(lengths)} bytes long, so line 500,000 has no fixed position')
    t = time.time(); insert(path, user(N + 1)); print(f'append one row: {(time.time() - t) * 1000:.2f} ms')
    t = time.time(); row = find(path, 777777); dt = time.time() - t
    print(f'find(777777) -> {row} in {dt * 1000:.0f} ms')
    t = time.time(); row = find(path, 5_000_000); dt = time.time() - t
    print(f'find(5000000) -> {row} in {dt * 1000:.0f} ms (read all {os.path.getsize(path):,} bytes)')
    t = time.time(); update(path, 2, (2, 'Grace Hopper', 'grace@navy.mil')); dt = time.time() - t
    print(f'update(2) rewrote {os.path.getsize(path):,} bytes in {dt * 1000:.0f} ms')
    # commas inside a value break the format
    insert(path, (N + 2, 'Hopper, Grace', 'g@mail.com'))
    print('comma row reads back as', find(path, N + 2))
    # crash in the middle of update(): the rewrite is half done
    size = os.path.getsize(path)
    p = subprocess.Popen([sys.executable, '-c', f'import sys; sys.path.insert(0, {os.path.abspath("steps")!r}); '
                          f'from step1_textfile import update; update({path!r}, 3, (3, "x", "y"))'])
    while os.path.getsize(path) == 0 or os.path.getsize(path) >= size or os.path.getsize(path) < size // 2:
        if p.poll() is not None: break
    p.send_signal(signal.SIGKILL); p.wait()
    after = os.path.getsize(path)
    lines = sum(1 for _ in open(path, errors='replace'))
    print(f'killed mid-update: file {size:,} -> {after:,} bytes, {lines:,} of {N + 2:,} rows left')
    os.remove(path)
