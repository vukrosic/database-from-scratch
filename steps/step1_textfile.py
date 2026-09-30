"""Step 1: the naive database -- one line of text per row.

    python3 steps/step1_textfile.py
"""
import os


def insert(path, row):
    with open(path, 'a') as f:
        f.write(','.join(str(v) for v in row) + '\n')


def find(path, id):
    with open(path) as f:
        for line in f:
            fields = line.rstrip('\n').split(',')
            if int(fields[0]) == id:
                return fields
    return None


def update(path, id, new_row):
    """Changing one row means rewriting the whole file."""
    with open(path) as f:
        lines = f.readlines()
    with open(path, 'w') as f:
        for line in lines:
            if int(line.split(',')[0]) == id:
                line = ','.join(str(v) for v in new_row) + '\n'
            f.write(line)


if __name__ == '__main__':
    path = 'users.txt'
    if os.path.exists(path):
        os.remove(path)
    insert(path, (1, 'Ada Lovelace', 'ada@mail.com'))
    insert(path, (2, 'Grace Hopper', 'grace@mail.com'))
    insert(path, (3, 'Alan Turing', 'alan@mail.com'))
    print(open(path).read(), end='')
    print(find(path, 2))
    update(path, 2, (2, 'Grace Hopper', 'grace@navy.mil'))
    print(find(path, 2))
