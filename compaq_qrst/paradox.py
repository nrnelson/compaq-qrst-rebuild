"""Just enough of a Paradox 3.x/4.x .DB table reader to read QuickRestore's DATABASE folder.

Only alphanumeric (type 1) fields are decoded; other field types come back as raw bytes.
"""
import struct


def read_table(data: bytes):
    """Return a list of records (lists of field values) from a Paradox table."""
    rec_size, hdr_size, _ftype, block_kb = struct.unpack_from('<HHBB', data, 0)
    first_block = struct.unpack_from('<H', data, 0x0E)[0]
    nfields = struct.unpack_from('<H', data, 0x21)[0]
    fields = [struct.unpack_from('<BB', data, 0x78 + 2 * i) for i in range(nfields)]
    block_size = block_kb * 1024
    records, block, seen = [], first_block, set()
    while block and block not in seen:
        seen.add(block)
        off = hdr_size + (block - 1) * block_size
        if off + 6 > len(data):
            raise ValueError('Paradox table: block outside file (encrypted or corrupt table?)')
        nxt, _prev, last = struct.unpack_from('<HHh', data, off)
        for r in range(last // rec_size + 1 if last >= 0 else 0):
            p = off + 6 + r * rec_size
            rec = []
            for ftype, size in fields:
                raw = data[p:p + size]
                rec.append(raw.split(b'\0')[0].decode('latin-1') if ftype == 1 else raw)
                p += size
            records.append(rec)
        block = nxt
    return records
