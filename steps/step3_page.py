"""Step 3: one 4096-byte page that keeps rows sorted by id.
Slotted page: header, cell pointers growing forward, cells packed from the end."""
import struct
from step2_records import encode, decode

PAGE_SIZE = 4096
HEADER = 9  # page type (1) + cell count (2) + content start (2) + right child (4)
LEAF = 1


class Page:
    def __init__(self):
        self.keys = []   # sorted ids
        self.vals = []   # row bytes, same order
        self.used = HEADER

    def cell_size(self, key, val):  # pointer + key length + key + row length + row
        return 2 + 2 + len(encode(key)) + 2 + len(val)

    def insert(self, key, val):
        """Binary search for the slot, then slide only the small pointers, not the rows."""
        lo, hi = 0, len(self.keys)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.keys[mid] < key:
                lo = mid + 1
            else:
                hi = mid
        if self.used + self.cell_size(key, val) > PAGE_SIZE:
            return False  # full: step 4 splits it
        self.keys.insert(lo, key)
        self.vals.insert(lo, val)
        self.used += self.cell_size(key, val)
        return True

    def find(self, key):
        lo, hi, steps = 0, len(self.keys), 0
        while lo < hi:
            steps += 1
            mid = (lo + hi) // 2
            if self.keys[mid] == key:
                return self.vals[mid], steps
            if self.keys[mid] < key:
                lo = mid + 1
            else:
                hi = mid
        return None, steps

    def to_bytes(self):
        page = bytearray(PAGE_SIZE)
        end = PAGE_SIZE
        for i, key in enumerate(self.keys):
            k = encode(key)
            cell = struct.pack('>H', len(k)) + k + struct.pack('>H', len(self.vals[i])) + self.vals[i]
            end -= len(cell)
            page[end:end + len(cell)] = cell
            struct.pack_into('>H', page, HEADER + 2 * i, end)
        struct.pack_into('>BHHI', page, 0, LEAF, len(self.keys), end, 0)
        return bytes(page)


def parse(page):
    _, count, _, _ = struct.unpack_from('>BHHI', page, 0)
    p = Page()
    for i in range(count):
        at = struct.unpack_from('>H', page, HEADER + 2 * i)[0]
        klen = struct.unpack_from('>H', page, at)[0]
        key = decode(page, at + 2)
        at += 2 + klen
        vlen = struct.unpack_from('>H', page, at)[0]
        p.keys.append(key)
        p.vals.append(bytes(page[at + 2:at + 2 + vlen]))
        p.used += p.cell_size(key, p.vals[-1])
    return p


if __name__ == '__main__':
    page = Page()
    for i in [3, 1, 2]:
        page.insert((i,), encode((i, f'User {i}', f'user{i}@mail.com')))
    data = page.to_bytes()
    print('header:', data[:9].hex(' '), '| pointers:', data[9:15].hex(' '))
    print('keys in order:', [k[0] for k in page.keys])
    n = 4
    while page.insert((n,), encode((n, f'User {n}', f'user{n}@mail.com'))):
        n += 1
    print(f'page full after {len(page.keys)} rows, {page.used} of {PAGE_SIZE} bytes used')
    with open('one-page.db', 'wb') as f:
        f.write(page.to_bytes())
    with open('one-page.db', 'rb') as f:
        again = parse(f.read(PAGE_SIZE))
    val, steps = again.find((57,))
    print('read back from disk, find id 57:', decode(val), f'in {steps} comparisons')
