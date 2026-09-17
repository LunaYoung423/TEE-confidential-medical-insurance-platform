# A minimal SM3 implementation for pysmx compatibility
# Based on the structure of the pysmx library

import struct

IV = [
    0x7380166F,
    0x4914B2B9,
    0x172442D7,
    0xDA8A0600,
    0xA96F30BC,
    0x163138AA,
    0xE38DEE4D,
    0xB0FB0E4E,
]


def rotate_left(x, n):
    return ((x << n) & 0xFFFFFFFF) | (x >> (32 - n))


def ff_j(x, y, z, j):
    if j < 16:
        return x ^ y ^ z
    else:
        return (x & y) | (x & z) | (y & z)


def gg_j(x, y, z, j):
    if j < 16:
        return x ^ y ^ z
    else:
        return (x & y) | (~x & z)


def p_0(x):
    return x ^ rotate_left(x, 9) ^ rotate_left(x, 17)


def p_1(x):
    return x ^ rotate_left(x, 15) ^ rotate_left(x, 23)


def cf(v_i, b_i):
    w = []
    for i in range(16):
        w.append(int.from_bytes(b_i[i * 4 : (i + 1) * 4], byteorder="big"))
    for j in range(16, 68):
        w_j = (
            p_1(w[j - 16] ^ w[j - 9] ^ rotate_left(w[j - 3], 15))
            ^ rotate_left(w[j - 13], 7)
            ^ w[j - 6]
        )
        w.append(w_j)

    w_1 = []
    for j in range(64):
        w_1.append(w[j] ^ w[j + 4])

    a, b, c, d, e, f, g, h = v_i

    for j in range(64):
        ss_1 = rotate_left(
            (rotate_left(a, 12) + e + rotate_left(ff_j(a, b, c, j), 7)) & 0xFFFFFFFF, 7
        )
        ss_2 = ss_1 ^ rotate_left(a, 12)
        tt_1 = (ff_j(a, b, c, j) + d + ss_2 + w_1[j]) & 0xFFFFFFFF
        tt_2 = (gg_j(e, f, g, j) + h + ss_1 + w[j]) & 0xFFFFFFFF
        d = c
        c = rotate_left(b, 9)
        b = a
        a = tt_1
        h = g
        g = rotate_left(f, 19)
        f = e
        e = p_0(tt_2)

    return [x ^ y for x, y in zip([a, b, c, d, e, f, g, h], v_i)]


def digest(data):
    msg = data
    msg_len = len(msg)
    msg_bit_len = msg_len * 8

    msg += b"\x80"
    while (len(msg) * 8) % 512 != 448:
        msg += b"\x00"
    msg += struct.pack(">Q", msg_bit_len)

    blocks = [msg[i : i + 64] for i in range(0, len(msg), 64)]

    V = IV[:]
    for block in blocks:
        V = cf(V, block)

    result = b""
    for v in V:
        result += struct.pack(">I", v)
    return result


__all__ = ["digest"]
