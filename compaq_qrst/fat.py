"""FAT12/FAT16 volume writer and reader, tailored to how QuickRestore laid out a disk.

The writer reproduces what Compaq's restore did with PKUNZIP onto a freshly formatted
volume:

* 8.3 names, file attributes and timestamps exactly as stored in the archives;
* every directory is a plain 0x10 entry (PKUNZIP's mkdir never applied the stored
  Archive/Hidden/System bits to directories -- WINSTART.BAT re-applies the few it wants,
  and Microsoft's PISETUP refuses any C:\\PISETUP\\LANG\\* directory whose attribute is
  not exactly 0x10, failing with "Control Module Error 5018");
* IO.SYS and MSDOS.SYS are the first two root entries and the first clusters on the
  volume, as the DOS/Win95 boot sectors require;
* files are written contiguously in archive order; later archives overwrite earlier ones.
"""
import struct
import zlib

SECTOR = 512
ATTR_RO, ATTR_HIDDEN, ATTR_SYSTEM, ATTR_LABEL, ATTR_DIR, ATTR_ARCHIVE = 1, 2, 4, 8, 0x10, 0x20
DEFAULT_TIME = (1995, 9, 18, 0, 0, 0)
LABEL_TIME = (1995, 9, 18, 12, 0, 0)


class VolumeFull(Exception):
    pass


class Node:
    """A file or directory in the tree to be written."""

    def __init__(self, name, is_dir, attr=ATTR_DIR, dt=DEFAULT_TIME):
        self.name, self.is_dir, self.attr, self.dt = name, is_dir, attr, dt
        self.children = {}      # upper-case raw 8.3 name -> Node, in insertion order
        self.source = None      # (ZipFile, ZipInfo) for files
        self.size = 0
        self.cluster = 0


def tree_from_archives(archives):
    """Merge ZipFile objects (in restore order) into one directory tree."""
    root = Node(b'', True)
    for z in archives:
        for zi in z.infolist():
            # zipfile decodes non-UTF-8 names as CP437; encode back to the on-disk OEM bytes
            parts = zi.filename.encode('cp437').rstrip(b'/').split(b'/')
            node = root
            for p in parts[:-1]:
                node = node.children.setdefault(p.upper(), Node(p.upper(), True))
            leaf = parts[-1].upper()
            if zi.filename.endswith('/'):
                d = node.children.setdefault(leaf, Node(leaf, True))
                d.dt = zi.date_time
                continue
            attr = zi.external_attr & 0xFF
            if attr & ATTR_DIR or attr == 0:          # entries stored by Unix-style zippers
                attr = ATTR_ARCHIVE
            f = Node(leaf, False, attr & (ATTR_RO | ATTR_HIDDEN | ATTR_SYSTEM | ATTR_ARCHIVE),
                     zi.date_time)
            f.source, f.size = (z, zi), zi.file_size
            node.children.pop(leaf, None)
            node.children[leaf] = f
    return root


def dos_datetime(dt):
    y, mo, d, h, mi, s = dt
    return (h << 11) | (mi << 5) | (s // 2), ((y - 1980) << 9) | (mo << 5) | d


def short_name(name):
    if name in (b'.', b'..'):
        return name.ljust(11)
    base, _, ext = name.partition(b'.')
    if not (1 <= len(base) <= 8 and len(ext) <= 3):
        raise ValueError(f'not an 8.3 name: {name!r}')
    raw = base.ljust(8) + ext.ljust(3)
    return b'\x05' + raw[1:] if raw[0] == 0xE5 else raw


def dir_entry(name11, attr, cluster, size, dt):
    t, d = dos_datetime(dt)
    return struct.pack('<11sB10xHHHI', name11, attr, t, d, cluster, size)


class FatWriter:
    """Formats a FAT12/16 volume inside an open image file and fills it from a Node tree."""

    def __init__(self, img, start, nsectors, sectors_per_cluster, fat12, boot_template,
                 label, serial, heads, spt, root_entries=512):
        self.img, self.start, self.spc, self.fat12 = img, start, sectors_per_cluster, fat12
        self.label = label
        self.root_sectors = root_entries * 32 // SECTOR
        fat_sectors = 1
        while True:
            nclusters = (nsectors - 1 - 2 * fat_sectors - self.root_sectors) // sectors_per_cluster
            fat_bytes = (nclusters + 2) * 3 // 2 if fat12 else (nclusters + 2) * 2
            if -(-fat_bytes // SECTOR) <= fat_sectors:
                break
            fat_sectors += 1
        if fat12 and nclusters >= 4085 or not fat12 and not 4085 <= nclusters < 65525:
            raise ValueError(f'{nclusters} clusters is invalid for FAT{12 if fat12 else 16}')
        self.fat_sectors, self.nclusters = fat_sectors, nclusters
        self.cluster_bytes = sectors_per_cluster * SECTOR
        self.data_start = 1 + 2 * fat_sectors + self.root_sectors
        self.fat = [0] * (nclusters + 2)
        self.fat[0], self.fat[1] = (0xFF8, 0xFFF) if fat12 else (0xFFF8, 0xFFFF)
        self.next_cluster = 2

        boot = bytearray(boot_template)
        if len(boot) != SECTOR or boot[510:512] != b'\x55\xaa':
            raise ValueError('boot sector template is not a valid 512-byte boot sector')
        struct.pack_into('<HBHBHHBHHHII', boot, 0x0B, SECTOR, sectors_per_cluster, 1, 2,
                         root_entries, nsectors if nsectors < 65536 else 0, 0xF8, fat_sectors,
                         spt, heads, start, 0 if nsectors < 65536 else nsectors)
        boot[0x24], boot[0x26] = 0x80, 0x29
        struct.pack_into('<I11s8s', boot, 0x27, serial, label.ljust(11),
                         b'FAT12   ' if fat12 else b'FAT16   ')
        self._write_sectors(0, boot)

    @property
    def used_bytes(self):
        return (self.next_cluster - 2) * self.cluster_bytes

    def _write_sectors(self, rel_sector, data):
        self.img.seek((self.start + rel_sector) * SECTOR)
        self.img.write(data)

    def _alloc(self, nbytes):
        n = max(1, -(-nbytes // self.cluster_bytes))
        first = self.next_cluster
        if first + n > self.nclusters + 2:
            raise VolumeFull(f'volume {self.label.decode()} is full: the target disk is too small '
                             '(C: needs roughly 600 MB)')
        for c in range(first, first + n - 1):
            self.fat[c] = c + 1
        self.fat[first + n - 1] = 0xFFF if self.fat12 else 0xFFFF
        self.next_cluster += n
        return first

    def _write_cluster(self, cluster, data):
        self._write_sectors(self.data_start + (cluster - 2) * self.spc, data)

    def _place_file(self, node):
        z, zi = node.source
        data = z.read(zi)
        if zlib.crc32(data) & 0xFFFFFFFF != zi.CRC:
            raise ValueError(f'CRC mismatch extracting {zi.filename}')
        if node.size:
            node.cluster = self._alloc(node.size)
            self._write_cluster(node.cluster, data)

    def _place_dir(self, d, parent_cluster):
        kids = list(d.children.values())
        d.cluster = self._alloc((len(kids) + 2) * 32)
        for k in kids:
            if not k.is_dir:
                self._place_file(k)
        for k in kids:
            if k.is_dir:
                self._place_dir(k, d.cluster)
        entries = [dir_entry(b'.'.ljust(11), ATTR_DIR, d.cluster, 0, d.dt),
                   dir_entry(b'..'.ljust(11), ATTR_DIR, parent_cluster, 0, d.dt)]
        entries += [dir_entry(short_name(k.name), k.attr, k.cluster, 0 if k.is_dir else k.size,
                              k.dt) for k in kids]
        self._write_cluster(d.cluster, b''.join(entries))

    def populate(self, tree, first_files=(b'IO.SYS', b'MSDOS.SYS')):
        order = [tree.children[n] for n in first_files if n in tree.children]
        order += [n for k, n in tree.children.items() if k not in first_files]
        for n in order:
            if not n.is_dir:
                self._place_file(n)
        for n in order:
            if n.is_dir:
                self._place_dir(n, 0)
        root = [dir_entry(short_name(n.name), n.attr, n.cluster, 0 if n.is_dir else n.size, n.dt)
                for n in order]
        root.insert(min(2, len(root)), dir_entry(self.label.ljust(11), ATTR_LABEL, 0, 0,
                                                 LABEL_TIME))
        root = b''.join(root)
        if len(root) > self.root_sectors * SECTOR:
            raise VolumeFull('root directory is full')
        self._finish(root)

    def _finish(self, root):
        if self.fat12:
            fat = bytearray((len(self.fat) * 3 + 1) // 2)
            for i, v in enumerate(self.fat):
                o = i * 3 // 2
                if i & 1:
                    fat[o] |= (v << 4) & 0xF0
                    fat[o + 1] = v >> 4
                else:
                    fat[o] = v & 0xFF
                    fat[o + 1] |= (v >> 8) & 0x0F
        else:
            fat = struct.pack('<%dH' % len(self.fat), *self.fat)
        fat = bytes(fat).ljust(self.fat_sectors * SECTOR, b'\0')
        self._write_sectors(1, fat)
        self._write_sectors(1 + self.fat_sectors, fat)
        self._write_sectors(1 + 2 * self.fat_sectors, root.ljust(self.root_sectors * SECTOR, b'\0'))


class FatReader:
    """Reads a FAT12/16 volume from an image file (used by `verify`)."""

    def __init__(self, f, start):
        self.f, self.start = f, start
        f.seek(start * SECTOR)
        bs = f.read(SECTOR)
        (self.bytes_per_sector, self.spc, reserved, nfats, root_entries, total16, _media,
         fat_sectors) = struct.unpack_from('<HBHBHHBH', bs, 0x0B)
        total = total16 or struct.unpack_from('<I', bs, 0x20)[0]
        self.label = bs[0x2B:0x36].rstrip()
        self.fat_start = start + reserved
        self.root_start = self.fat_start + nfats * fat_sectors
        self.root_sectors = root_entries * 32 // SECTOR
        self.data_start = self.root_start + self.root_sectors
        self.nclusters = (total - (self.data_start - start)) // self.spc
        self.fat12 = self.nclusters < 4085
        f.seek(self.fat_start * SECTOR)
        self.fats = [f.read(fat_sectors * SECTOR) for _ in range(nfats)]

    def next(self, c):
        fat = self.fats[0]
        if self.fat12:
            v = struct.unpack_from('<H', fat, c * 3 // 2)[0]
            v = v >> 4 if c & 1 else v & 0xFFF
            return None if v >= 0xFF8 else v
        v = struct.unpack_from('<H', fat, c * 2)[0]
        return None if v >= 0xFFF8 else v

    def chain(self, c):
        seen = set()
        while c is not None:
            if not 2 <= c < self.nclusters + 2 or c in seen:
                raise ValueError(f'bad cluster chain at {c}')
            seen.add(c)
            yield c
            c = self.next(c)

    def read_chain(self, c, size=None):
        out = bytearray()
        for k in self.chain(c):
            self.f.seek((self.data_start + (k - 2) * self.spc) * SECTOR)
            out += self.f.read(self.spc * SECTOR)
        return bytes(out if size is None else out[:size])

    def entries(self, cluster=None):
        """Yield (name, attr, cluster, size, raw_entry) for a directory (None = root)."""
        if cluster is None:
            self.f.seek(self.root_start * SECTOR)
            data = self.f.read(self.root_sectors * SECTOR)
        else:
            data = self.read_chain(cluster)
        for i in range(0, len(data), 32):
            e = data[i:i + 32]
            if e[0] == 0:
                break
            if e[0] == 0xE5 or e[11] == 0x0F:
                continue
            raw = (b'\xe5' + e[1:11]) if e[0] == 0x05 else e[:11]
            base, ext = raw[:8].rstrip(), raw[8:].rstrip()
            name = base + (b'.' + ext if ext else b'')
            yield name, e[11], struct.unpack_from('<H', e, 26)[0], \
                struct.unpack_from('<I', e, 28)[0], e

    def walk(self, cluster=None, prefix=b''):
        """Yield (path, attr, cluster, size, raw_entry) for every file and directory."""
        for name, attr, c, size, raw in self.entries(cluster):
            if name in (b'.', b'..') or attr & ATTR_LABEL:
                continue
            path = prefix + name
            yield path, attr, c, size, raw
            if attr & ATTR_DIR:
                yield from self.walk(c, path + b'/')
