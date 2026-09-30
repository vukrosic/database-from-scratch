"""Step 2: turn a row into bytes and back.
No commas to escape: every value says what type it is and how long it is."""
import struct


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
        else:
            n = struct.unpack_from('>H', buf, i)[0]
            i += 2
            values.append(bytes(buf[i:i + n]).decode('utf-8'))
            i += n
    return tuple(values)


if __name__ == '__main__':
    row = (1, 'Ada Lovelace', 'ada@mail.com')
    data = encode(row)
    print(len(data), 'bytes:', data.hex(' '))
    print('back:', decode(data))
    tricky = (2, 'Hopper, Grace', 'g@mail.com')
    print('comma row back:', decode(encode(tricky)))
