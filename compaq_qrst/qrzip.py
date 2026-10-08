"""Decode Compaq QuickRestore's obfuscated PKZIP self-extractors.

Each archive on the CD is a PKSFX .EXE whose zip headers were deliberately scrambled so that
ordinary unzip tools refuse them. The data itself is plain deflate. The scrambling is:

* signatures:  local  "PK\\x03\\x04" -> "JT\\x04\\x03"
               central "PK\\x01\\x02" -> "TJ\\x02\\x01"
               end     "PK\\x05\\x06" -> "TJ\\x06\\x05"
* in every local and central header, the file-name-length and extra-field-length
  fields are swapped.

Offsets are absolute within the .EXE (the SFX stub is part of the archive), so the stub is
kept and the result is a valid self-extracting zip that Python's zipfile reads directly.
"""
import io
import struct
import zipfile

LOCAL, CENTRAL, END = b'JT\x04\x03', b'TJ\x02\x01', b'TJ\x06\x05'


class QrZipError(Exception):
    pass


def decode(data: bytes) -> bytes:
    """Return a standard zip (still with its SFX stub) from an obfuscated QuickRestore .EXE."""
    b = bytearray(data)
    end = b.rfind(END)
    if end < 0:
        raise QrZipError('no QuickRestore end-of-central-directory record found')
    b[end:end + 4] = b'PK\x05\x06'
    count, cd_size, cd_off = struct.unpack_from('<HII', b, end + 10)
    p = cd_off
    for i in range(count):
        if b[p:p + 4] != CENTRAL:
            raise QrZipError(f'central header {i} at 0x{p:x}: unexpected signature')
        b[p:p + 4] = b'PK\x01\x02'
        extra_len, name_len, comment_len = struct.unpack_from('<HHH', b, p + 28)
        struct.pack_into('<HH', b, p + 28, name_len, extra_len)
        local = struct.unpack_from('<I', b, p + 42)[0]
        if b[local:local + 4] != LOCAL:
            raise QrZipError(f'local header {i} at 0x{local:x}: unexpected signature')
        b[local:local + 4] = b'PK\x03\x04'
        l_extra, l_name = struct.unpack_from('<HH', b, local + 26)
        struct.pack_into('<HH', b, local + 26, l_name, l_extra)
        p += 46 + name_len + extra_len + comment_len
    if p != cd_off + cd_size:
        raise QrZipError('central directory size mismatch')
    return bytes(b)


def encode(data: bytes) -> bytes:
    """Inverse of decode(); used by the test suite to make synthetic archives."""
    b = bytearray(data)
    end = b.rfind(b'PK\x05\x06')
    count, cd_size, cd_off = struct.unpack_from('<HII', b, end + 10)
    b[end:end + 4] = END
    p = cd_off
    for _ in range(count):
        name_len, extra_len, comment_len = struct.unpack_from('<HHH', b, p + 28)
        local = struct.unpack_from('<I', b, p + 42)[0]
        b[p:p + 4] = CENTRAL
        struct.pack_into('<HH', b, p + 28, extra_len, name_len)
        l_name, l_extra = struct.unpack_from('<HH', b, local + 26)
        b[local:local + 4] = LOCAL
        struct.pack_into('<HH', b, local + 26, l_extra, l_name)
        p += 46 + name_len + extra_len + comment_len
    return bytes(b)


def open_archive(data: bytes) -> zipfile.ZipFile:
    """Decode and open an obfuscated QuickRestore archive; every member's CRC is verified."""
    z = zipfile.ZipFile(io.BytesIO(decode(data)))
    bad = z.testzip()
    if bad:
        raise QrZipError(f'CRC error in member {bad}')
    return z
