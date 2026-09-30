# Build Your Own SQLite From Scratch

**minilite** is a tiny SQLite-style database engine in about 680 lines of standard-library Python. It is the companion code for the animated course *Build Your Own SQLite From Scratch* on YouTube ([@vukrosic](https://www.youtube.com/@vukrosic)); video link: VIDEO_URL.

This is not about *using* a database. It builds the engine underneath: how rows become bytes, bytes become 4096-byte pages, pages become a B-tree, SQL text becomes a plan, and a rollback journal keeps the file intact when the power goes out mid-write.

```
minilite> CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT);
minilite> INSERT INTO users VALUES (1, 'Ada Lovelace', 'ada@mail.com'), (2, 'Grace Hopper', 'grace@mail.com');
minilite> SELECT name FROM users WHERE id = 2;
Grace Hopper
-- SEARCH users USING PRIMARY KEY (id=?)  (1 page read)
```

With one million rows (`demos/million_demo.py`), `WHERE id = 777777` reads 4 of 36,217 pages. `WHERE email = ...` reads 36,216 pages until you `CREATE INDEX`, then 8.

## Run it
Needs Python 3.8 or newer. Nothing to install.
```
python3 minilite.py users.db          # SQL prompt; statements end with ;
python3 tests.py                      # 33 checks passed
python3 demos/crash_demo.py           # kill the process mid-commit, with and without the journal
```

## How it works
| Layer | What it does | In `minilite.py` | Checkpoint |
| --- | --- | --- | --- |
| 0. Text file | One CSV line per row: slow lookups, full rewrites, commas and crashes break it | — | `steps/step1_textfile.py` |
| 1. Records | A row becomes bytes: a type byte and a length before every value | `encode()`, `decode()` | `steps/step2_records.py` |
| 2. Pages | The file is cut into 4096-byte pages. A slotted page keeps sorted cell pointers at the front and rows packed from the back | `Node`, `parse()`, `Pager` | `steps/step3_page.py` |
| 3. B-tree | Full pages split in half and send a key up; the root splits and the tree grows one level. A lookup reads one page per level | `BTree` | `steps/step4_btree.py` |
| 4. SQL | Tokenizer, recursive-descent parser, executor, REPL. Page 0 holds the schema table (each CREATE statement) | `tokenize()`, `Parser`, `Database` | `steps/step5_sql.py` |
| 5. Index + planner | An index is a second B-tree of `(email, id)`; the planner picks SCAN or SEARCH | `create_index`, `find` | `minilite.py` |
| 6. Crash safety | Old pages go to a rollback journal before any page is overwritten; deleting the journal is the commit | `Pager.change/commit/rollback_journal` | `minilite.py` |

Each checkpoint runs on its own (`cd steps && python3 step4_btree.py`) and adds one layer, in the order of the video.

File layout, same idea as SQLite: page `n` lives at byte `n × 4096`; page 0 starts with the 16 bytes `minilite v1\0…` (SQLite's file starts with `SQLite format 3\0`). Every page starts with a 9-byte header: type, cell count, where the cells start, rightmost child.

## Demos
All outputs are in [demo-output.txt](demo-output.txt).
- `demos/naive_demo.py`: the text-file database on 1,000,000 rows (lookup time, rewrite size, what a crash leaves behind).
- `demos/btree_trace.py`: 64-byte pages so every split is visible; writes `btree-trace.json`.
- `demos/session.py`: the REPL session from the video and the resulting file's pages.
- `demos/million_demo.py`: one million rows: pages read per query, before and after `CREATE INDEX`.
- `demos/crash_demo.py`: SIGKILL in the middle of COMMIT. Without the journal the file is corrupt; with it, reopening rolls back.
- `demos/sqlite_compare.py`: the same million rows in the real SQLite (`import sqlite3`).

## What real SQLite adds
Variable-length integers, overflow pages for big rows, page merging on delete, a free-page list, the write-ahead log (WAL) as an alternative to the rollback journal, locking for many processes, a bytecode virtual machine for queries, a cost-based planner, and about 25 years of testing. The file format is documented at https://www.sqlite.org/fileformat.html.

## Exercises
See [exercises/README.md](exercises/README.md): DELETE, `!=`, and packing sequential inserts into full pages like SQLite does. Solutions are in `solutions/`.

## Going further
- SQLite file format: https://www.sqlite.org/fileformat.html
- How SQLite commits atomically: https://www.sqlite.org/atomiccommit.html
- Connor Stack, *Let's Build a Simple Database* (an SQLite clone in C): https://cstack.github.io/db_tutorial/
- *Database Internals* by Alex Petrov (O'Reilly) for B-tree variants, logs and recovery.

MIT license.
