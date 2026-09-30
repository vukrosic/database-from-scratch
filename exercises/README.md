# Exercises

Work on a copy: `cp minilite.py my_minilite.py`, then change `my_minilite.py`. Solutions are in `../solutions/` and patch `minilite.py` from the outside, so you can read each one next to the original.

## 0. Predict first (no code)
Insert the keys 50, 20, 80, 10, 30, 40 into a B-tree whose pages hold 3 keys. Draw the tree after every insert. Then run `python3 ../demos/btree_trace.py` and compare.

## 1. DELETE FROM users WHERE id = 2
Remove the row's cell from its leaf page, and remove `(email, id)` from every index. Leave emptier pages as they are (real SQLite merges them).
Solution: `../solutions/1_delete.py`

## 2. WHERE name != 'Grace'
Three layers change: the tokenizer must know `!=`, the parser must accept it, and the planner must choose a scan (no index helps with "everything except one value").
Solution: `../solutions/2_not_equal.py`

## 3. Stretch: fill the pages
One million ids inserted in order take 36,217 pages in minilite and 12,802 in real SQLite. A 50/50 split leaves every left page half empty forever, because new ids only ever go to the right. When the new key lands at the very end of the rightmost page, split off just the last cell instead.
Solution: `../solutions/3_full_pages.py` (100,000 rows: 2,958 pages → 1,475 pages)
