"""Minimal read-only ISO 9660 reader (primary volume descriptor, plain 8.3 names).

The QuickRestore CDs are plain ISO 9660 level 1 with no Joliet or Rock Ridge, so this is
all that's needed and it keeps the tool free of external dependencies.
"""
import struct

SECTOR = 2048


class IsoError(Exception):
    pass


class IsoImage:
    def __init__(self, path):
        self.path = path
        self._f = open(path, 'rb')
        pvd = self._read(16 * SECTOR, SECTOR)
        if pvd[0:1] != b'\x01' or pvd[1:6] != b'CD001':
            raise IsoError(f'{path}: not an ISO 9660 image (no primary volume descriptor)')
        self.volume_id = pvd[40:72].decode('ascii', 'replace').strip()
        self._root = self._parse_record(pvd[156:156 + 34])

    def close(self):
        self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _read(self, offset, length):
        self._f.seek(offset)
        data = self._f.read(length)
        if len(data) != length:
            raise IsoError(f'{self.path}: not an ISO 9660 image (file too short)')
        return data

    @staticmethod
    def _parse_record(rec):
        extent = struct.unpack_from('<I', rec, 2)[0]
        size = struct.unpack_from('<I', rec, 10)[0]
        is_dir = bool(rec[25] & 0x02)
        name_len = rec[32]
        name = rec[33:33 + name_len]
        return name, extent, size, is_dir

    def _listdir(self, extent, size):
        data = self._read(extent * SECTOR, size)
        pos, entries = 0, {}
        while pos < len(data):
            length = data[pos]
            if length == 0:                       # records never span sectors; skip padding
                pos = (pos // SECTOR + 1) * SECTOR
                continue
            name, ext, sz, is_dir = self._parse_record(data[pos:pos + length])
            pos += length
            if name in (b'\x00', b'\x01'):        # . and ..
                continue
            name = name.decode('ascii').split(';')[0].rstrip('.').upper()
            entries[name] = (ext, sz, is_dir)
        return entries

    def _lookup(self, path):
        _, ext, size, is_dir = self._root
        for part in [p for p in path.upper().replace('\\', '/').split('/') if p]:
            if not is_dir:
                raise FileNotFoundError(path)
            entries = self._listdir(ext, size)
            if part not in entries:
                raise FileNotFoundError(path)
            ext, size, is_dir = entries[part]
        return ext, size, is_dir

    def listdir(self, path='/'):
        ext, size, is_dir = self._lookup(path)
        if not is_dir:
            raise NotADirectoryError(path)
        return {n: d for n, (_, _, d) in self._listdir(ext, size).items()}

    def exists(self, path):
        try:
            self._lookup(path)
            return True
        except FileNotFoundError:
            return False

    def read(self, path):
        ext, size, is_dir = self._lookup(path)
        if is_dir:
            raise IsADirectoryError(path)
        return self._read(ext * SECTOR, size)
