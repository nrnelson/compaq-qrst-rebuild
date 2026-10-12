"""Unpacker for PKLITE 1.x (1991) compressed .COM programs.

A port of the decompressor each such program carries in its own stub: a bit stream of
16-bit little-endian words interleaved with literal bytes, LZ77 back-references with
lengths and distance high bytes taken from two small tables inside the stub.
Used to get at FMT.COM's diskette boot sector, which exists on the CD only packed.
"""
import struct


class NotPklite(ValueError):
    pass


def unpack_com(data):
    """Return the original program image of a PKLITE-compressed .COM file."""
    if len(data) < 0x80 or data[0] != 0xB8 or data[3] != 0xBA or b'PKLITE' not in data[:0x80]:
        raise NotPklite('not a PKLITE-compressed .COM file')
    packed_len = struct.unpack_from('<H', data, 4)[0]            # mov dx,imm16
    stub = data[struct.unpack_from('<H', data, 0x18)[0] - 0x100:]  # mov si,imm16: stub source
    if stub[5] != 0xBE:
        raise NotPklite('unsupported PKLITE stub')
    # The stub copies the packed data backwards, one word at a time, from just past mov si.
    start = struct.unpack_from('<H', stub, 6)[0] - 0x100 + 2
    lengths, dist_hi = stub[0x11C:0x12C], stub[0x12C:0x144]
    src = data[start:start + packed_len]
    pos, word, left = 2, struct.unpack_from('<H', src, 0)[0], 16
    out = bytearray()

    def bit():
        nonlocal pos, word, left
        b = word & 1
        word >>= 1
        left -= 1
        if not left:
            word, left = struct.unpack_from('<H', src, pos)[0], 16
            pos += 2
        return b

    def bits(v, n):
        for _ in range(n):
            v = v << 1 | bit()
        return v

    def byte():
        nonlocal pos
        pos += 1
        return src[pos - 1]

    while True:
        if not bit():
            out.append(byte())
            continue
        code = bits(0, 2)
        if code:
            code = bits(code, 1)
            if code >= 6:
                code = bits(code, 1)
        count = lengths[code]
        if count == 10:                    # long match: length in the next byte, 0xFF ends
            extra = byte()
            if extra == 0xFF:
                return bytes(out)
            count += extra
        hi = 0
        if count != 2 and not bit():
            code = bits(0, 3)
            if code >= 2:
                code = bits(code, 1)
                if code >= 8:
                    code = bits(code, 1)
                    if code >= 0x17:
                        hi, code = bits(code, 1) & 0xDF, None
            if code is not None:
                hi = dist_hi[code]
        dist = hi << 8 | byte()
        if not 0 < dist <= len(out):
            raise NotPklite('corrupt PKLITE data')
        for _ in range(count):
            out.append(out[-dist])
