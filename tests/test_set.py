import collections.abc
import gc
import itertools
import pickle
import random
import sys
import unittest
import weakref

from immutables.set import Set as PySet


class HashKey:
    _crasher = None

    def __init__(self, hash, name, *, error_on_eq_to=None):
        assert hash != -1
        self.name = name
        self.hash = hash
        self.error_on_eq_to = error_on_eq_to

    def __repr__(self):
        if self._crasher is not None and self._crasher.error_on_repr:
            raise ReprError
        return '<Key name:{} hash:{}>'.format(self.name, self.hash)

    def __hash__(self):
        if self._crasher is not None and self._crasher.error_on_hash:
            raise HashingError

        return self.hash

    def __eq__(self, other):
        if not isinstance(other, HashKey):
            return NotImplemented

        if self._crasher is not None and self._crasher.error_on_eq:
            raise EqError

        if self.error_on_eq_to is not None and self.error_on_eq_to is other:
            raise ValueError('cannot compare {!r} to {!r}'.format(self, other))
        if other.error_on_eq_to is not None and other.error_on_eq_to is self:
            raise ValueError('cannot compare {!r} to {!r}'.format(other, self))

        return (self.name, self.hash) == (other.name, other.hash)


class KeyStr(str):

    def __hash__(self):
        if HashKey._crasher is not None and HashKey._crasher.error_on_hash:
            raise HashingError
        return super().__hash__()

    def __eq__(self, other):
        if HashKey._crasher is not None and HashKey._crasher.error_on_eq:
            raise EqError
        return super().__eq__(other)

    def __repr__(self):
        # TODO: test_map has a error on this
        if HashKey._crasher is not None and HashKey._crasher.error_on_repr:
            raise ReprError
        return super().__repr__()


class HashKeyCrasher:

    def __init__(self, *, error_on_hash=False, error_on_eq=False,
                 error_on_repr=False):
        self.error_on_hash = error_on_hash
        self.error_on_eq = error_on_eq
        self.error_on_repr = error_on_repr

    def __enter__(self):
        if HashKey._crasher is not None:
            raise RuntimeError('cannot nest crashers')
        HashKey._crasher = self

    def __exit__(self, *exc):
        HashKey._crasher = None


class HashingError(Exception):
    pass


class EqError(Exception):
    pass


class ReprError(Exception):
    pass


class BaseSetTest:

    Set = None

    def test_hashkey_helper_1(self):
        k1 = HashKey(10, 'aaa')
        k2 = HashKey(10, 'bbb')

        self.assertNotEqual(k1, k2)
        self.assertEqual(hash(k1), hash(k2))

        d = dict()
        d[k1] = 'a'
        d[k2] = 'b'

        self.assertEqual(d[k1], 'a')
        self.assertEqual(d[k2], 'b')

    def test_set_basics_1(self):
        h = self.Set()
        h = None  # NoQA

    def test_set_basics_2(self):
        h = self.Set()
        self.assertEqual(len(h), 0)

        h2 = h.include('a')
        self.assertIsNot(h, h2)
        self.assertEqual(len(h), 0)
        self.assertEqual(len(h2), 1)

        self.assertFalse('a' in h)
        self.assertTrue('a' in h2)

        h3 = h2.include('b')
        self.assertIsNot(h2, h3)
        self.assertEqual(len(h), 0)
        self.assertEqual(len(h2), 1)
        self.assertEqual(len(h3), 2)
        self.assertTrue('a' in h3)
        self.assertTrue('b' in h3)

        self.assertFalse('b' in h)
        self.assertFalse('b' in h2)

        self.assertFalse('a' in h)
        self.assertTrue('a' in h2)

        h = h2 = h3 = None

    def test_set_basics_3(self):
        h = self.Set()
        h1 = h.include('1')
        h2 = h1.include('1')
        self.assertIs(h1, h2)
        self.assertEqual(len(h1), 1)

    def test_set_collision_1(self):
        k1 = HashKey(10, 'aaa')
        k2 = HashKey(10, 'bbb')
        k3 = HashKey(10, 'ccc')

        h = self.Set()
        h2 = h.include(k1)
        h3 = h2.include(k2)

        self.assertIs(k1 in h, False)
        self.assertIs(k2 in h, False)

        self.assertIs(k1 in h2, True)
        self.assertIs(k2 in h2, False)

        self.assertIs(k1 in h3, True)
        self.assertIs(k2 in h3, True)

        h4 = h3.include(k2)
        h5 = h4.include(k3)

        self.assertIs(k1 in h3, True)
        self.assertIs(k2 in h3, True)
        self.assertIs(k1 in h4, True)
        self.assertIs(k2 in h4, True)
        self.assertIs(k3 in h4, False)
        self.assertIs(k1 in h5, True)
        self.assertIs(k2 in h5, True)
        self.assertIs(k2 in h5, True)
        self.assertIs(k3 in h5, True)

        self.assertEqual(len(h), 0)
        self.assertEqual(len(h2), 1)
        self.assertEqual(len(h3), 2)
        self.assertEqual(len(h4), 2)
        self.assertEqual(len(h5), 3)

    def test_set_collision_2(self):
        A = HashKey(100, 'A')
        B = HashKey(101, 'B')
        C = HashKey(0b011000011100000100, 'C')
        D = HashKey(0b011000011100000100, 'D')
        E = HashKey(0b1011000011100000100, 'E')

        h = self.Set()
        h = h.include(A)
        h = h.include(B)
        h = h.include(C)
        h = h.include(D)

        # BitmapNode(size=6 bitmap=0b100110000):
        #     NULL:
        #         BitmapNode(size=4 bitmap=0b1000000000000000000001000):
        #             <Key name:A hash:100>: 'a'
        #             NULL:
        #                 CollisionNode(size=4 id=0x108572410):
        #                     <Key name:C hash:100100>: 'c'
        #                     <Key name:D hash:100100>: 'd'
        #     <Key name:B hash:101>: 'b'

        h = h.include(E)

        # BitmapNode(size=4 count=2.0 bitmap=0b110000 id=10b8ea5c0):
        #     None:
        #         BitmapNode(size=4 count=2.0
        #                    bitmap=0b1000000000000000000001000 id=10b8ea518):
        #             <Key name:A hash:100>: 'a'
        #             None:
        #                 BitmapNode(size=2 count=1.0 bitmap=0b10
        #                            id=10b8ea4a8):
        #                     None:
        #                         BitmapNode(size=4 count=2.0
        #                                    bitmap=0b100000001000
        #                                    id=10b8ea4e0):
        #                             None:
        #                                 CollisionNode(size=4 id=10b8ea470):
        #                                     <Key name:C hash:100100>: 'c'
        #                                     <Key name:D hash:100100>: 'd'
        #                             <Key name:E hash:362244>: 'e'
        #     <Key name:B hash:101>: 'b'

    def test_set_stress(self):
        COLLECTION_SIZE = 7000
        TEST_ITERS_EVERY = 647
        CRASH_HASH_EVERY = 97
        CRASH_EQ_EVERY = 11
        RUN_XTIMES = 3

        for _ in range(RUN_XTIMES):
            h = self.Set()
            d = set()

            for i in range(COLLECTION_SIZE):
                key = KeyStr(i)

                if not (i % CRASH_HASH_EVERY):
                    with HashKeyCrasher(error_on_hash=True):
                        with self.assertRaises(HashingError):
                            h.include(key)

                h = h.include(key)

                if not (i % CRASH_EQ_EVERY):
                    with HashKeyCrasher(error_on_eq=True):
                        with self.assertRaises(EqError):
                            KeyStr(i) in h # really trigger __eq__

                d.add(key)
                self.assertEqual(len(d), len(h))

                if not (i % TEST_ITERS_EVERY):
                    self.assertEqual(set(h), set(d))

            self.assertEqual(len(h), COLLECTION_SIZE)

            for key in range(COLLECTION_SIZE):
                self.assertIs(KeyStr(key) in h, True)

            keys_to_delete = list(range(COLLECTION_SIZE))
            random.shuffle(keys_to_delete)
            for iter_i, i in enumerate(keys_to_delete):
                key = KeyStr(i)

                if not (iter_i % CRASH_HASH_EVERY):
                    with HashKeyCrasher(error_on_hash=True):
                        with self.assertRaises(HashingError):
                            h.exclude(key)

                if not (iter_i % CRASH_EQ_EVERY):
                    with HashKeyCrasher(error_on_eq=True):
                        with self.assertRaises(EqError):
                            h.exclude(KeyStr(i))

                h = h.exclude(key)
                self.assertIs(key in h, False)
                d.remove(key)
                self.assertEqual(len(d), len(h))

                if iter_i == COLLECTION_SIZE // 2:
                    hm = h
                    dm = d.copy()

                if not (iter_i % TEST_ITERS_EVERY):
                    self.assertEqual(set(h), set(d))
                    self.assertEqual(len(h), len(d))

            self.assertEqual(len(d), 0)
            self.assertEqual(len(h), 0)

            # ============

            for key in dm:
                self.assertIs(str(key) in hm, True)
            self.assertEqual(len(dm), len(hm))

            for i, key in enumerate(keys_to_delete):
                if str(key) in dm:
                    hm = hm.exclude(str(key))
                    dm.remove(str(key))
                self.assertEqual(str(key) in hm, False)
                self.assertEqual(len(d), len(h)) # Error?
                self.assertEqual(len(dm), len(hm))

                if not (i % TEST_ITERS_EVERY):
                    self.assertEqual(set(h), set(d))
                    self.assertEqual(len(h), len(d))
                    self.assertEqual(set(dm), set(hm))
                    self.assertEqual(len(dm), len(hm))

            self.assertEqual(len(d), 0)
            self.assertEqual(len(h), 0)
            self.assertEqual(list(h), [])
            self.assertEqual(len(dm), 0)
            self.assertEqual(len(hm), 0)
            self.assertEqual(list(hm), [])

    def test_set_exclude_1(self):
        A = HashKey(100, 'A')
        B = HashKey(101, 'B')
        C = HashKey(102, 'C')
        D = HashKey(103, 'D')
        E = HashKey(104, 'E')
        Z = HashKey(-100, 'Z')

        Er = HashKey(103, 'Er', error_on_eq_to=D)

        h = self.Set()
        h = h.include(A)
        h = h.include(A)
        h = h.include(B)
        h = h.include(C)
        h = h.include(D)
        h = h.include(E)

        orig_len = len(h)

        # BitmapNode(size=10 bitmap=0b111110000 id=0x10eadc618):
        #     <Key name:A hash:100>: 'a'
        #     <Key name:B hash:101>: 'b'
        #     <Key name:C hash:102>: 'c'
        #     <Key name:D hash:103>: 'd'
        #     <Key name:E hash:104>: 'e'

        h = h.exclude(C)
        self.assertEqual(len(h), orig_len - 1)

        with self.assertRaisesRegex(ValueError, 'cannot compare'):
            h.exclude(Er)

        h = h.exclude(D)
        self.assertEqual(len(h), orig_len - 2)

        with self.assertRaises(KeyError) as ex:
            h.exclude(Z)
        self.assertIs(ex.exception.args[0], Z)

        h = h.exclude(A)
        self.assertEqual(len(h), orig_len - 3)

        self.assertIs(A in h, False)
        self.assertIs(B in h, True)
        self.assertIs(E in h, True)

    def test_set_delete_2(self):
        A = HashKey(100, 'A')
        B = HashKey(201001, 'B')
        C = HashKey(101001, 'C')
        BLike = HashKey(201001, 'B-like')
        D = HashKey(103, 'D')
        E = HashKey(104, 'E')
        Z = HashKey(-100, 'Z')

        Er = HashKey(201001, 'Er', error_on_eq_to=B)

        h = self.Set()
        h = h.include(A)
        h = h.include(B)
        h = h.include(C)
        h = h.include(D)
        h = h.include(E)

        h = h.include(B)  # trigger branch in BitmapNode.add

        with self.assertRaises(KeyError):
            h.exclude(BLike)    # trigger branch in BitmapNode.without

        orig_len = len(h)

        # BitmapNode(size=8 bitmap=0b1110010000):
        #     <Key name:A hash:100>: 'a'
        #     <Key name:D hash:103>: 'd'
        #     <Key name:E hash:104>: 'e'
        #     NULL:
        #         BitmapNode(size=4 bitmap=0b100000000001000000000):
        #             <Key name:B hash:201001>: 'b'
        #             <Key name:C hash:101001>: 'c'

        with self.assertRaisesRegex(ValueError, 'cannot compare'):
            h.exclude(Er)

        with self.assertRaises(KeyError) as ex:
            h.exclude(Z)
        self.assertIs(ex.exception.args[0], Z)
        self.assertEqual(len(h), orig_len)

        h = h.exclude(C)
        self.assertEqual(len(h), orig_len - 1)

        h = h.exclude(B)
        self.assertEqual(len(h), orig_len - 2)

        h = h.exclude(A)
        self.assertEqual(len(h), orig_len - 3)

        self.assertIs(D in h, True)
        self.assertEqual(E in h, True)

        with self.assertRaises(KeyError):
            h = h.exclude(A)
        with self.assertRaises(KeyError):
            h = h.exclude(B)
        h = h.exclude(D)
        h = h.exclude(E)
        self.assertEqual(len(h), 0)

    def test_set_exclude_3(self):
        A = HashKey(0b00000000001100100, 'A')
        B = HashKey(0b00000000001100101, 'B')

        C = HashKey(0b11000011100000100, 'C')
        D = HashKey(0b11000011100000100, 'D')
        X = HashKey(0b01000011100000100, 'Z') # X?
        Y = HashKey(0b11000011100000100, 'Y')

        E = HashKey(0b00000000001101000, 'E')

        h = self.Set()
        h = h.include(A)
        h = h.include(B)
        h = h.include(C)
        h = h.include(D)
        h = h.include(E)

        self.assertEqual(len(h), 5)
        h = h.include(C)  # trigger branch in CollisionNode.add
        self.assertEqual(len(h), 5)

        orig_len = len(h)

        with self.assertRaises(KeyError):
            h.exclude(X)
        with self.assertRaises(KeyError):
            h.exclude(Y)

        # BitmapNode(size=6 bitmap=0b100110000):
        #     NULL:
        #         BitmapNode(size=4 bitmap=0b1000000000000000000001000):
        #             <Key name:A hash:100>: 'a'
        #             NULL:
        #                 CollisionNode(size=4 id=0x108572410):
        #                     <Key name:C hash:100100>: 'c'
        #                     <Key name:D hash:100100>: 'd'
        #     <Key name:B hash:101>: 'b'
        #     <Key name:E hash:104>: 'e'

        h = h.exclude(A)
        self.assertEqual(len(h), orig_len - 1)

        h = h.exclude(E)
        self.assertEqual(len(h), orig_len - 2)

        self.assertIs(C in h, True)
        self.assertIs(B in h, True)

        h2 = h.exclude(C)
        self.assertEqual(len(h2), orig_len - 3)

        h2 = h.exclude(D)
        self.assertEqual(len(h2), orig_len - 3)

        self.assertEqual(len(h), orig_len - 2)

    def test_set_exclude_4(self):
        A = HashKey(100, 'A')
        B = HashKey(101, 'B')
        C = HashKey(100100, 'C')
        D = HashKey(100100, 'D')
        E = HashKey(100100, 'E')

        h = self.Set()
        h = h.include(A)
        h = h.include(B)
        h = h.include(C)
        h = h.include(D)
        h = h.include(E)

        orig_len = len(h)

        # BitmapNode(size=4 bitmap=0b110000):
        #     NULL:
        #         BitmapNode(size=4 bitmap=0b1000000000000000000001000):
        #             <Key name:A hash:100>: 'a'
        #             NULL:
        #                 CollisionNode(size=6 id=0x10515ef30):
        #                     <Key name:C hash:100100>: 'c'
        #                     <Key name:D hash:100100>: 'd'
        #                     <Key name:E hash:100100>: 'e'
        #     <Key name:B hash:101>: 'b'

        h = h.exclude(D)
        self.assertEqual(len(h), orig_len - 1)

        h = h.exclude(E)
        self.assertEqual(len(h), orig_len - 2)

        h = h.exclude(C)
        self.assertEqual(len(h), orig_len - 3)

        h = h.exclude(A)
        self.assertEqual(len(h), orig_len - 4)

        h = h.exclude(B)
        self.assertEqual(len(h), 0)

    def test_map_exclude_5(self):
        h = self.Set()

        keys = []
        for i in range(17):
            key = HashKey(i, str(i))
            keys.append(key)
            h = h.include(key)

        collision_key16 = HashKey(16, '18')
        h = h.include(collision_key16)

        # ArrayNode(id=0x10f8b9318):
        #     0::
        #     BitmapNode(size=2 count=1 bitmap=0b1):
        #         <Key name:0 hash:0>: 'val-0'
        #
        # ... 14 more BitmapNodes ...
        #
        #     15::
        #     BitmapNode(size=2 count=1 bitmap=0b1):
        #         <Key name:15 hash:15>: 'val-15'
        #
        #     16::
        #     BitmapNode(size=2 count=1 bitmap=0b1):
        #         NULL:
        #             CollisionNode(size=4 id=0x10f2f5af8):
        #                 <Key name:16 hash:16>: 'val-16'
        #                 <Key name:18 hash:16>: 'collision'

        self.assertEqual(len(h), 18)

        h = h.exclude(keys[2])
        self.assertEqual(len(h), 17)

        h = h.exclude(collision_key16)
        self.assertEqual(len(h), 16)
        h = h.exclude(keys[16])
        self.assertEqual(len(h), 15)

        h = h.exclude(keys[1])
        self.assertEqual(len(h), 14)
        with self.assertRaises(KeyError) as ex:
            h.exclude(keys[1])
        self.assertIs(ex.exception.args[0], keys[1])
        self.assertEqual(len(h), 14)

        for key in keys:
            if key in h:
                h = h.exclude(key)
        self.assertEqual(len(h), 0)

    def test_set_exclude_6(self):
        h = self.Set()
        h = h.include(1)
        h = h.exclude(1)
        self.assertEqual(len(h), 0)
        self.assertEqual(h, self.Set())

    def test_set_iter_1(self):
        A = HashKey(100, 'A')
        B = HashKey(201001, 'B')
        C = HashKey(101001, 'C')
        D = HashKey(103, 'D')
        E = HashKey(104, 'E')
        F = HashKey(110, 'F')

        h = self.Set()
        h = h.include(A)
        h = h.include(B)
        h = h.include(C)
        h = h.include(D)
        h = h.include(E)
        h = h.include(F)

        it = iter(h)
        self.assertEqual(set(list(it)), {A, B, C, D, E, F})
        self.assertEqual(set(h), {A, B, C, D, E, F})

    def test_set_iter_2(self):
        A = HashKey(100, 'A')
        B = HashKey(101, 'B')
        C = HashKey(100100, 'C')
        D = HashKey(100100, 'D')
        E = HashKey(100100, 'E')
        F = HashKey(110, 'F')

        h = self.Set()
        h = h.include(A)
        h = h.include(B)
        h = h.include(C)
        h = h.include(D)
        h = h.include(E)
        h = h.include(F)

        it = iter(h)
        self.assertEqual(set(list(it)), {A, B, C, D, E, F})
        self.assertEqual(set(h), {A, B, C, D, E, F})

    def test_set_iter_3(self):
        h = self.Set()
        self.assertEqual(len(h), 0)
        self.assertEqual(list(h), [])
        it = iter(h)
        self.assertEqual(list(it), [])

    def test_set_iter_4(self):
        h = self.Set(['a', 'b', 'c'])
        self.assertEqual(set(h), {'a', 'b', 'c'})
        it = iter(h)
        self.assertEqual(set(h), {'a', 'b', 'c'})
        self.assertEqual(set(it), {'a', 'b', 'c'})

    def test_set_eq_1(self):
        A = HashKey(100, 'A')
        B = HashKey(101, 'B')
        C = HashKey(100100, 'C')
        D = HashKey(100100, 'D')
        E = HashKey(120, 'E')

        h1 = self.Set()
        h1 = h1.include(A)
        h1 = h1.include(B)
        h1 = h1.include(C)
        h1 = h1.include(D)

        h2 = self.Set()
        h2 = h2.include(A)

        self.assertFalse(h1 == h2)
        self.assertTrue(h1 != h2)

        h2 = h2.include(B)
        self.assertFalse(h1 == h2)
        self.assertTrue(h1 != h2)

        h2 = h2.include(C)
        self.assertFalse(h1 == h2)
        self.assertTrue(h1 != h2)

        h2 = h2.include(D)
        self.assertTrue(h1 == h2)
        self.assertFalse(h1 != h2)

        h2 = h2.include(E)
        self.assertFalse(h1 == h2)
        self.assertTrue(h1 != h2)

        h2 = h2.exclude(D)
        self.assertFalse(h1 == h2)
        self.assertTrue(h1 != h2)

        h1 = h1.include(E)
        self.assertFalse(h1 == h2)
        self.assertTrue(h1 != h2)

        h1 = h1.exclude(D)
        self.assertTrue(h1 == h2)
        self.assertFalse(h1 != h2)

    def test_set_eq_2(self):
        A = HashKey(100, 'A')
        Er = HashKey(100, 'Er', error_on_eq_to=A)

        h1 = self.Set()
        h1 = h1.include(A)

        h2 = self.Set()
        h2 = h2.include(Er)

        with self.assertRaisesRegex(ValueError, 'cannot compare'):
            h1 == h2

        with self.assertRaisesRegex(ValueError, 'cannot compare'):
            h1 != h2

    def test_set_eq_3(self):
        self.assertNotEqual(self.Set(), 1)

    def test_set_gc_1(self):
        A = HashKey(100, 'A')

        h = self.Set()
        h = h.include(0)  # empty Map node is memoized in _map.c
        ref = weakref.ref(h)

        a = []
        a.append(a)
        a.append(h)
        b = []
        a.append(b)
        b.append(a)
        A.payload = b
        h = h.include(A)

        del h, a, b, A

        gc.collect()
        gc.collect()
        gc.collect()

        self.assertIsNone(ref())

    def test_set_gc_2(self):
        A = HashKey(100, 'A')

        h = self.Set()
        h = h.include(A)
        A.payload = h
        h = h.include(A)

        ref = weakref.ref(h)
        hi = iter(h)
        next(hi)

        del h, hi, A

        gc.collect()
        gc.collect()
        gc.collect()

        self.assertIsNone(ref())

    def test_set_in_1(self):
        A = HashKey(100, 'A')
        AA = HashKey(100, 'A')

        B = HashKey(101, 'B')

        h = self.Set()
        h = h.include(A)

        self.assertTrue(A in h)
        self.assertFalse(B in h)

        with self.assertRaises(EqError):
            with HashKeyCrasher(error_on_eq=True):
                AA in h

        with self.assertRaises(HashingError):
            with HashKeyCrasher(error_on_hash=True):
                AA in h

        self.assertTrue(AA in h)

    def test_repr_1(self):
        h = self.Set()
        self.assertTrue(repr(h).startswith('<immutables.Set({}) at 0x'))

        h = h.include(1).include(2).include(3)
        self.assertTrue(repr(h).startswith(
            '<immutables.Set({1, 2, 3}) at 0x'))

    def test_repr_2(self):
        h = self.Set()
        A = HashKey(100, 'A')

        with self.assertRaises(ReprError):
            with HashKeyCrasher(error_on_repr=True):
                repr(h.include(1).include(A).include(3))

    def test_repr_3(self):
        class Key:
            def __init__(self):
                self.val = None

            def __hash__(self):
                return 123

            def __repr__(self):
                return repr(self.val)

        h = self.Set()
        k = Key()
        h = h.include(k)
        k.val = h

        self.assertTrue(repr(h).startswith(
            '<immutables.Set({{...}}) at 0x'))

    def test_hash_1(self):
        h = self.Set()
        self.assertNotEqual(hash(h), -1)
        self.assertEqual(hash(h), hash(h))

        h = h.include(1).include('a')
        self.assertNotEqual(hash(h), -1)
        self.assertEqual(hash(h), hash(h))

        self.assertEqual(
            hash(h.include(1).include('a')),
            hash(h.include('a').include(1)))

    def test_hash_2(self):
        h = self.Set()
        A = HashKey(100, 'A')

        m = h.include(1).include(A).include(3)
        with self.assertRaises(HashingError):
            with HashKeyCrasher(error_on_hash=True):
                hash(m)

    def test_abc_1(self):
        self.assertTrue(issubclass(self.Set, collections.abc.Set))

    def test_set_mut_1(self):
        h = self.Set()
        h = h.include('a')

        hm1 = h.mutate()
        hm2 = h.mutate()

        self.assertFalse(isinstance(hm1, self.Set))

        self.assertIsNot(hm1, hm2)
        self.assertTrue('a' in hm1)
        self.assertTrue('a' in hm2)

        hm1.include('b')
        hm1.include('c')

        hm2.include('x')
        hm2.include('a')

        self.assertTrue('a' in hm1)
        self.assertFalse('x' in hm1)

        self.assertTrue('a' in hm2)
        self.assertTrue('x' in hm2)

        self.assertFalse('b' in hm2)
        self.assertFalse('c' in hm2)

        self.assertTrue('b' in hm1)
        self.assertTrue('c' in hm1)

        h1 = hm1.finish()
        h2 = hm2.finish()

        self.assertTrue(isinstance(h1, self.Set))

        self.assertEqual(set(h), {'a'})
        self.assertEqual(set(h1), {'a', 'b', 'c'})
        self.assertEqual(set(h2), {'a', 'x'})

    def test_set_mut_2(self):
        h = self.Set()
        h = h.include('a')

        hm1 = h.mutate()
        hm1.include('a')
        hm1.include('a')
        hm1.include('a')
        h2 = hm1.finish()

        self.assertEqual(set(h), {'a'})
        self.assertEqual(set(h2), {'a'})
        self.assertEqual(h, h2)

    def test_set_mut_3(self):
        h = self.Set()
        h = h.include('a')
        hm1 = h.mutate()

        self.assertTrue(repr(hm1).startswith(
            "<immutables.SetMutation({'a'})"))

        with self.assertRaisesRegex(TypeError, 'unhashable type'):
            hash(hm1)

    def test_set_mut_4(self):
        h = self.Set()
        h = h.include('a')
        h = h.include('b')

        hm1 = h.mutate()
        hm2 = h.mutate()

        self.assertEqual(hm1, hm2)

        hm1.include('a')
        self.assertEqual(hm1, hm2)

        hm2.include('a')
        self.assertEqual(hm1, hm2)

        hm2.exclude('a')
        self.assertNotEqual(hm1, hm2)

    def test_set_mut_5(self):
        h = self.Set({'a', 'b', 'z'})
        self.assertTrue(isinstance(h, self.Set))
        self.assertEqual(set(h), {'a', 'b', 'z'})

        h2 = h.update(('z', 'y'))
        self.assertEqual(set(h), {'a', 'b', 'z'})
        self.assertEqual(set(h2), {'a', 'b', 'z', 'y'})

        h3 = h2.update((1, 2), (3, 4))
        self.assertEqual(set(h), {'a', 'b', 'z'})
        self.assertEqual(set(h2), {'a', 'b', 'z', 'y'})
        self.assertEqual(set(h3), {'a', 'b', 'z', 'y', 1, 2, 3, 4})

        h4 = h3.update()
        self.assertIs(h4, h3)

        h5 = h4.update(self.Set({'zzz', 'yyz'}))

        self.assertEqual(set(h5),
                         {'a', 'b', 'z', 'y', 1, 2, 3, 4, 'zzz', 'yyz'})

    def test_set_mut_6(self):
        h = self.Set({'a', 'b', 'z'})
        self.assertEqual(set(h), {'a', 'b', 'z'})

        with self.assertRaisesRegex(TypeError, 'not iterable'):
            h.update(1)

        with self.assertRaisesRegex(TypeError, 'not iterable'):
            h.update((1, 2), 1)

        self.assertEqual(set(h), {'a', 'b', 'z'})

    def test_set_mut_7(self):
        key = HashKey(123, 'aaa')

        h = self.Set({'a', 'b', 'z'})
        self.assertEqual(set(h), {'a', 'b', 'z'})

        upd = {key}
        with HashKeyCrasher(error_on_hash=True):
            with self.assertRaises(HashingError):
                h.update(upd)

        upd = self.Set({key})
        with HashKeyCrasher(error_on_hash=True):
            with self.assertRaises(HashingError):
                h.update(upd)

        upd = [(1, 2), (key, 'zzz')]
        with HashKeyCrasher(error_on_hash=True):
            with self.assertRaises(HashingError):
                h.update(*upd)

        self.assertEqual(set(h), {'a', 'b', 'z'})

    def test_set_mut_8(self):
        key1 = HashKey(123, 'aaa')
        key2 = HashKey(123, 'bbb')

        h = self.Set({key1})
        self.assertEqual(set(h), {key1})

        upd = {key2}
        with HashKeyCrasher(error_on_eq=True):
            with self.assertRaises(EqError):
                h.update(upd)

        upd = self.Set({key2})
        with HashKeyCrasher(error_on_eq=True):
            with self.assertRaises(EqError):
                h.update(upd)

        upd = [(1, 2), (key2, 'zzz')]
        with HashKeyCrasher(error_on_eq=True):
            with self.assertRaises(EqError):
                h.update(*upd)

        self.assertEqual(set(h), {key1})

    def test_set_mut_9(self):
        key1 = HashKey(123, 'aaa')

        src = {key1}
        with HashKeyCrasher(error_on_hash=True):
            with self.assertRaises(HashingError):
                self.Set(src)

        src = [(1), (key1)]
        with HashKeyCrasher(error_on_hash=True):
            with self.assertRaises(HashingError):
                self.Set(src)

    def test_set_mut_10(self):
        key1 = HashKey(123, 'aaa')

        m = self.Set({key1})

        mm = m.mutate()
        with HashKeyCrasher(error_on_hash=True):
            with self.assertRaises(HashingError):
                mm.exclude(key1)

        mm = m.mutate()
        with HashKeyCrasher(error_on_hash=True):
            with self.assertRaises(HashingError):
                mm.include(key1)

    def test_set_mut_11(self):
        m = self.Set({'a', 'b'})

        mm = m.mutate()
        self.assertTrue('a' in mm)
        mm.exclude('a')
        self.assertEqual(mm.finish(), self.Set({'b': 2}))

        mm = m.mutate()
        self.assertTrue('b' in mm)
        mm.exclude('b')
        self.assertEqual(mm.finish(), self.Set({'a': 1}))

        mm = m.mutate()
        self.assertTrue('b' in mm)
        mm.exclude('b')
        self.assertFalse('b' in mm)
        mm.exclude('a')
        self.assertEqual(mm.finish(), self.Set())

    def test_set_mut_12(self):
        m = self.Set({'a', 'b'})

        mm = m.mutate()
        mm.finish()

        with self.assertRaisesRegex(ValueError, 'has been finished'):
            mm.exclude('a')

        with self.assertRaisesRegex(ValueError, 'has been finished'):
            mm.include('a')

        with self.assertRaisesRegex(ValueError, 'has been finished'):
            mm.update({'a', 'b'})

    def test_set_mut_13(self):
        key1 = HashKey(123, 'aaa')
        key2 = HashKey(123, 'aaa')

        m = self.Set({key1})

        mm = m.mutate()
        with HashKeyCrasher(error_on_eq=True):
            with self.assertRaises(EqError):
                mm.exclude(key2)

        mm = m.mutate()
        with HashKeyCrasher(error_on_eq=True):
            with self.assertRaises(EqError):
                mm.include(key2)

    def test_set_mut_14(self):
        m = self.Set(['a', 'b'])

        with m.mutate() as mm:
            mm.include('z')
            mm.exclude('a')

        self.assertEqual(mm.finish(), self.Set(['z', 'b']))

    def test_set_mut_15(self):
        m = self.Set(['a', 'b'])

        with self.assertRaises(ZeroDivisionError):
            with m.mutate() as mm:
                mm.include('z')
                mm.exclude('a')
                1 / 0

        self.assertEqual(mm.finish(), self.Set(['z', 'b']))
        self.assertEqual(m, self.Set(['a', 'b']))

    def test_set_mut_16(self):
        m = self.Set(['a', 'b'])
        hash(m)

        m2 = self.Set(m)
        m3 = self.Set(itertools.chain(m, ['c']))

        self.assertEqual(m, m2)
        self.assertEqual(len(m), len(m2))
        self.assertEqual(hash(m), hash(m2))

        self.assertIsNot(m, m2)
        self.assertEqual(m3, self.Set(['a', 'b', 'c']))

    def test_set_mut_17(self):
        m = self.Set('a')
        with m.mutate() as mm:
            with self.assertRaisesRegex(
                    TypeError, 'cannot create Sets from SetMutations'):
                self.Set(mm)

    def test_set_mut_18(self):
        m = self.Set('ab')
        with m.mutate() as mm:
            mm.update(self.Set('x'), 'z')
            mm.update('c')
            mm.update({'n', 'a'})
            m2 = mm.finish()

        expected = self.Set({'b', 'c', 'n', 'z', 'x', 'a'})

        self.assertEqual(len(m2), 6)
        self.assertEqual(m2, expected)
        self.assertEqual(m, self.Set({'a', 'b'}))

    def test_set_mut_19(self):
        m = self.Set('ab')
        m2 = m.update({'a'})
        self.assertEqual(len(m2), 2)

    def test_set_mut_stress(self):
        COLLECTION_SIZE = 7000
        TEST_ITERS_EVERY = 647
        RUN_XTIMES = 3

        for _ in range(RUN_XTIMES):
            h = self.Set()
            d = set()

            for i in range(COLLECTION_SIZE // TEST_ITERS_EVERY):

                hm = h.mutate()
                for j in range(TEST_ITERS_EVERY):
                    key = random.randint(1, 100000)
                    key = HashKey(key % 271, str(key))

                    hm.include(key)
                    d.add(key)

                    self.assertEqual(len(hm), len(d))

                h2 = hm.finish()
                self.assertEqual(set(h2), d)
                h = h2

            self.assertEqual(set(h), d)
            self.assertEqual(len(h), len(d))

            it = iter(tuple(d))
            for i in range(COLLECTION_SIZE // TEST_ITERS_EVERY):

                hm = h.mutate()
                for j in range(TEST_ITERS_EVERY):
                    try:
                        key = next(it)
                    except StopIteration:
                        break

                    d.remove(key)
                    hm.exclude(key)

                    self.assertEqual(len(hm), len(d))

                h2 = hm.finish()
                self.assertEqual(set(h2), d)
                h = h2

            self.assertEqual(set(h), d)
            self.assertEqual(len(h), len(d))

    def test_set_pickle(self):
        h = self.Set('ab')
        for proto in range(pickle.HIGHEST_PROTOCOL):
            p = pickle.dumps(h, proto)
            uh = pickle.loads(p)

            self.assertTrue(isinstance(uh, self.Set))
            self.assertEqual(h, uh)

        with self.assertRaisesRegex(TypeError, "can('t|not) pickle"):
            pickle.dumps(h.mutate())

    @unittest.skipIf(sys.version_info < (3, 7, 0),
                     "__class_getitem__ is not available")
    def test_set_is_subscriptable(self):
        self.assertIs(self.Set[int], self.Set)


class PySetTest(BaseSetTest, unittest.TestCase):

    Set = PySet


try:
    from immutables._set import Set as CSet
except ImportError:
    CSet = None


@unittest.skipIf(CSet is None, 'C Set is not available')
class CMapTest(BaseSetTest, unittest.TestCase):

    Set = CSet


if __name__ == "__main__":
    unittest.main()
