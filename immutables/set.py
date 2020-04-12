import collections.abc
import itertools
import reprlib
import sys


__all__ = ('Set',)


# Thread-safe counter.
_mut_id = itertools.count(1).__next__

# Python version of _map.c.  The topmost comment there explains
# all datastructures and algorithms.
# The code here follows C code closely on purpose to make
# debugging and testing easier.


def set_hash(o):
    x = hash(o)
    return (x & 0xffffffff) ^ ((x >> 32) & 0xffffffff)


def set_mask(hash, shift):
    return (hash >> shift) & 0x01f


def set_bitpos(hash, shift):
    return 1 << set_mask(hash, shift)


def set_bitcount(v):
    v = v - ((v >> 1) & 0x55555555)
    v = (v & 0x33333333) + ((v >> 2) & 0x33333333)
    v = (v & 0x0F0F0F0F) + ((v >> 4) & 0x0F0F0F0F)
    v = v + (v >> 8)
    v = (v + (v >> 16)) & 0x3F
    return v


def set_bitindex(bitmap, bit):
    return set_bitcount(bitmap & (bit - 1))


W_EMPTY, W_NEWNODE, W_NOT_FOUND = range(3)
void = object()


def is_set_node(arg):
    return isinstance(arg, (BitmapNode, CollisionNode))


class BitmapNode:

    def __init__(self, size, bitmap, array, mutid):
        self.size = size
        self.bitmap = bitmap
        assert isinstance(array, list) and len(array) == size
        self.array = array
        self.mutid = mutid

    def clone(self, mutid):
        return BitmapNode(self.size, self.bitmap, self.array.copy(), mutid)

    def add(self, shift, hash, key, mutid):
        bit = set_bitpos(hash, shift)
        key_idx = set_bitindex(self.bitmap, bit)

        if self.bitmap & bit:
            key_or_node = self.array[key_idx]

            if is_set_node(key_or_node):
                sub_node, added = key_or_node.add(shift + 5, hash, key, mutid)
                if key_or_node is sub_node:
                    return self, added

                if mutid and mutid == self.mutid:
                    ret = self
                else:
                    ret = self.clone(mutid)
                ret.array[key_idx] = sub_node
                return ret, added

            if key == key_or_node:
                return self, False

            existing_key_hash = set_hash(key_or_node)
            if existing_key_hash == hash:
                sub_node = CollisionNode(
                    4, hash, [key_or_node, key], mutid)
            else:
                sub_node = BitmapNode(0, 0, [], mutid)
                sub_node, _ = sub_node.add(
                    shift + 5, existing_key_hash, key_or_node, mutid)
                sub_node, _ = sub_node.add(shift + 5, hash, key, mutid)

            if mutid and mutid == self.mutid:
                ret = self
            else:
                ret = self.clone(mutid)
            ret.array[key_idx] = sub_node
            return ret, True

        else:
            n = set_bitcount(self.bitmap)

            new_array = self.array[:key_idx]
            new_array.append(key)
            new_array.extend(self.array[key_idx:])

            if mutid and mutid == self.mutid:
                self.size = n + 1
                self.bitmap |= bit
                self.array = new_array
                return self, True
            else:
                return (BitmapNode(n + 1, self.bitmap | bit, new_array, mutid),
                        True)

    def find(self, shift, hash, key):
        bit = set_bitpos(hash, shift)

        if not (self.bitmap & bit):
            return False

        key_idx = set_bitindex(self.bitmap, bit)

        key_or_node = self.array[key_idx]

        if is_set_node(key_or_node):
            return key_or_node.find(shift + 5, hash, key)

        if key == key_or_node:
            return True

        return False

    def without(self, shift, hash, key, mutid):
        bit = set_bitpos(hash, shift)
        if not (self.bitmap & bit):
            return W_NOT_FOUND, None

        key_idx = set_bitindex(self.bitmap, bit)

        key_or_node = self.array[key_idx]

        if is_set_node(key_or_node):
            res, sub_node = key_or_node.without(shift + 5, hash, key, mutid)

            if res is W_EMPTY:
                raise RuntimeError('unreachable code')  # pragma: no cover

            elif res is W_NEWNODE:
                if (type(sub_node) is BitmapNode and
                        sub_node.size == 1 and
                        not is_set_node(sub_node.array[0])):
                    sub_node = sub_node.array[0]

                if mutid and mutid == self.mutid:
                    ret = self
                else:
                    ret = self.clone(mutid)
                ret.array[key_idx] = sub_node
                return W_NEWNODE, ret

            else:
                assert sub_node is None
                return res, None

        else:
            if key == key_or_node:
                if self.size == 1:
                    return W_EMPTY, None

                new_array = self.array[:key_idx]
                new_array.extend(self.array[key_idx + 1:])

                if mutid and mutid == self.mutid:
                    self.size -= 1
                    self.bitmap &= ~bit
                    self.array = new_array
                    return W_NEWNODE, self
                else:
                    new_node = BitmapNode(
                        self.size - 1, self.bitmap & ~bit, new_array, mutid)
                    return W_NEWNODE, new_node

            else:
                return W_NOT_FOUND, None

    def __iter__(self):
        for i in range(0, self.size, 1):
            key_or_node = self.array[i]

            if is_set_node(key_or_node):
                yield from key_or_node
            else:
                yield key_or_node


    def dump(self, buf, level):  # pragma: no cover
        buf.append(
            '    ' * (level + 1) +
            'BitmapNode(size={} bitmap={} id={:0x}):'.format(
                self.size, bin(self.bitmap), id(self)))

        for i in range(0, self.size, 1):
            key_or_node = self.array[i]

            pad = '    ' * (level + 2)

            if is_set_node(key_or_node):
                buf.append(pad + 'Node:')
                key_or_node.dump(buf, level + 2)
            else:
                buf.append(pad + '{!r}'.format(key_or_node))


class CollisionNode:

    def __init__(self, size, hash, array, mutid):
        self.size = size
        self.hash = hash
        self.array = array
        self.mutid = mutid

    def find_index(self, key):
        for i in range(0, self.size, 1):
            if self.array[i] == key:
                return i
        return -1

    def find(self, shift, hash, key):
        for i in range(0, self.size, 1):
            if self.array[i] == key:
                return True
        return False

    def add(self, shift, hash, key, mutid):
        if hash == self.hash:
            key_idx = self.find_index(key)

            if key_idx == -1:
                new_array = self.array.copy()
                new_array.append(key)

                if mutid and mutid == self.mutid:
                    self.size += 1
                    self.array = new_array
                    return self, True
                else:
                    new_node = CollisionNode(
                        self.size + 1, hash, new_array, mutid)
                    return new_node, True

            return self, False

        else:
            new_node = BitmapNode(
                1, set_bitpos(self.hash, shift), [self], mutid)
            return new_node.add(shift, hash, key, mutid)

    def without(self, shift, hash, key, mutid):
        if hash != self.hash:
            return W_NOT_FOUND, None

        key_idx = self.find_index(key)
        if key_idx == -1:
            return W_NOT_FOUND, None

        new_size = self.size - 1
        if new_size == 0:
            # Shouldn't be ever reachable
            return W_EMPTY, None  # pragma: no cover

        if new_size == 1:
            if key_idx == 0:
                new_array = [self.array[1]]
            else:
                assert key_idx == 1
                new_array = [self.array[0]]

            new_node = BitmapNode(
                1, set_bitpos(hash, shift), new_array, mutid)
            return W_NEWNODE, new_node

        new_array = self.array[:key_idx]
        new_array.extend(self.array[key_idx + 1:])
        if mutid and mutid == self.mutid:
            self.array = new_array
            self.size -= 1
            return W_NEWNODE, self
        else:
            new_node = CollisionNode(
                self.size - 1, self.hash, new_array, mutid)
            return W_NEWNODE, new_node

    def __iter__(self):
        yield from self.array

    def dump(self, buf, level):  # pragma: no cover
        pad = '    ' * (level + 1)
        buf.append(
            pad + 'CollisionNode(size={} id={:0x}):'.format(
                self.size, id(self)))

        pad = '    ' * (level + 2)
        for i in range(0, self.size, 1):
            key = self.array[i]
            buf.append('{}{!r}'.format(pad, key))


class Set(collections.abc.Set):

    def __init__(self, col=None):
        self.__count = 0
        self.__root = BitmapNode(0, 0, [], 0)
        self.__hash = -1

        if isinstance(col, Set):
            self.__count = col.__count
            self.__root = col.__root
            self.__hash = col.__hash
            col = None
        elif isinstance(col, SetMutation):
            raise TypeError('cannot create Sets from SetMutations')

        if col:
            init = self.update(col)
            self.__count = init.__count
            self.__root = init.__root

    @classmethod
    def _new(cls, count, root):
        m = Set.__new__(Set)
        m.__count = count
        m.__root = root
        m.__hash = -1
        return m

    def __reduce__(self):
        return (type(self), (frozenset(self),))

    def __len__(self):
        return self.__count

    def __eq__(self, other):
        if not isinstance(other, Set):
            return NotImplemented

        if len(self) != len(other):
            return False

        for key in self.__root:
            if not other.__root.find(0, set_hash(key), key):
                return False

        return True

    def update(self, *args):
        if not args:
            return self

        mutid = _mut_id()
        root = self.__root
        count = self.__count

        it = itertools.chain.from_iterable(args)
        i = 0
        while True:
            try:
                element = next(it)
            except StopIteration:
                break

            root, added = root.add(0, set_hash(element), element, mutid)
            if added:
                count += 1

            i += 1

        return Set._new(count, root)

    def mutate(self):
        return SetMutation(self.__count, self.__root)

    def include(self, element):
        new_count = self.__count
        new_root, added = self.__root.add(0, set_hash(element), element, 0)

        if new_root is self.__root:
            assert not added
            return self

        if added:
            new_count += 1

        return Set._new(new_count, new_root)

    def exclude(self, element):
        res, node = self.__root.without(0, set_hash(element), element, 0)
        if res is W_EMPTY:
            return Set()
        elif res is W_NOT_FOUND:
            raise KeyError(element)
        else:
            return Set._new(self.__count - 1, node)

    def __contains__(self, element):
        return self.__root.find(0, set_hash(element), element)

    def __iter__(self):
        yield from self.__root

    def __hash__(self):
        if self.__hash != -1:
            return self.__hash

        MAX = sys.maxsize
        MASK = 2 * MAX + 1

        h = 1927868237 * (self.__count + 1)
        h &= MASK

        for key in self.__root:
            hx = hash(key)
            h ^= (hx ^ (hx << 16) ^ 89869747) * 3644798167
            h &= MASK

        h = h * 69069 + 907133923
        h &= MASK

        if h > MAX:
            h -= MASK + 1  # pragma: no cover
        if h == -1:
            h = 590923713  # pragma: no cover

        self.__hash = h
        return h

    @reprlib.recursive_repr("{...}")
    def __repr__(self):
        items = []
        for key in self.__root:
            items.append("{!r}".format(key))
        return '<immutables.Set({{{}}}) at 0x{:0x}>'.format(
            ', '.join(items), id(self))

    def __dump__(self):  # pragma: no cover
        buf = []
        self.__root.dump(buf, 0)
        return '\n'.join(buf)

    def __class_getitem__(cls, item):
        return cls


class SetMutation:

    def __init__(self, count, root):
        self.__count = count
        self.__root = root
        self.__mutid = _mut_id()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.finish()
        return False

    def __iter__(self):
        raise TypeError('{} is not iterable'.format(type(self)))

    def __contains__(self, key):
        return self.__root.find(0, set_hash(key), key)

    def include(self, element):
        if self.__mutid == 0:
            raise ValueError('mutation {!r} has been finished'.format(self))

        self.__root, added = self.__root.add(0, set_hash(element),
                                             element, self.__mutid)
        if added:
            self.__count += 1

    def exclude(self, element):
        if self.__mutid == 0:
            raise ValueError('mutation {!r} has been finished'.format(self))

        res, new_root = self.__root.without(0, set_hash(element),
                                            element, self.__mutid)
        if res is W_EMPTY:
            self.__count = 0
            self.__root = BitmapNode(0, 0, [], self.__mutid)
        elif res is W_NOT_FOUND:
            raise KeyError(element)
        else:
            self.__root = new_root
            self.__count -= 1

    def update(self, *args):
        if self.__mutid == 0:
            raise ValueError('mutation {!r} has been finished'.format(self))

        if not args:
            return self

        root = self.__root
        count = self.__count

        it = itertools.chain.from_iterable(args)
        i = 0
        while True:
            try:
                element = next(it)
            except StopIteration:
                break

            root, added = root.add(0, set_hash(element), element, self.__mutid)
            if added:
                count += 1

            i += 1

        self.__root = root
        self.__count = count

    def finish(self):
        self.__mutid = 0
        return Set._new(self.__count, self.__root)

    @reprlib.recursive_repr("{...}")
    def __repr__(self):
        items = []
        for element in self.__root:
            items.append(repr(element))
        return '<immutables.SetMutation({{{}}}) at 0x{:0x}>'.format(
            ', '.join(items), id(self))

    def __len__(self):
        return self.__count

    def __reduce__(self):
        raise TypeError("can't pickle {} objects".format(type(self).__name__))

    def __hash__(self):
        raise TypeError('unhashable type: {}'.format(type(self).__name__))

    def __eq__(self, other):
        if not isinstance(other, SetMutation):
            return NotImplemented

        if len(self) != len(other):
            return False

        for element in self.__root:
            if not other.__root.find(0, set_hash(element), element):
                return False

        return True


collections.abc.Set.register(Set)
