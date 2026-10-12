"""Rebuild the DIAGNOSTICS and SETUP diskettes that the Compaq Utilities make.

"Create a Diagnostics Diskette" (DOD.EXE B) backs the diagnostics partition up onto two
1.44 MB diskettes. This module replays exactly what it does, from the CD's DIAGS archive:

* FMT.COM formats each diskette: its own boot sector (packed inside FMT.COM), serial
  field 'EISA', boot-sector label DIAGS / 'DIAGSETU.P' (FMT is handed DOD's 8.3 spelling
  of DIAGSETUP), free space filled with 0xF6;
* DIAGNOSTICS: DFC copies the files named in DIAGDSK1.IN, then DIAGMSG1.IN with -S (only
  its first entry), then ONELANGF writes one-language MSGDATA, DD_MSG and DOD_MSG;
* SETUP: DFC copies DIAGDSK2.IN, then all of DIAGMSG2.IN (LANGFILE is copied twice);
* DOD adds the volume label (DIAGS / DIAGSETUP) and stamps every .COM/.EXE root entry.

Files go where DOS 6 would put them: a new file takes the first free root entry, an
existing one is truncated in place, and clusters are allocated after the last one handed
out (DOS's next-free hint survives deletes, which is what leaves a hole on SETUP).

What cannot be reproduced is file slack -- the unused tail of each file's last sector,
which DOS fills from whatever was in its buffers -- so it is written as zeros. The label
and ONELANGF output get the current time on a real machine; here they get `when`.
"""
import struct
from dataclasses import dataclass

from .fat import ATTR_ARCHIVE, ATTR_LABEL, dir_entry, dos_datetime, short_name, tree_from_archives
from .pklite import unpack_com

SECTOR = 512
SECTORS, ROOT_ENTRIES, FAT_SECTORS = 2880, 224, 9
DATA_START = 1 + 2 * FAT_SECTORS + ROOT_ENTRIES * 32 // SECTOR      # sector 33
CLUSTERS = SECTORS - DATA_START                                     # clusters 2..2848
FORMAT_FILL = 0xF6
LANGUAGES = ('ENGLISH', 'FRENCH', 'GERMAN', 'ITALIAN', 'SPANISH')   # message-file slots
MSG_HEADER, MSG_SLOT = 0x6E, 10


@dataclass
class Diskette:
    name: str           # DIAGNOSTICS / SETUP
    image: bytes
    slack: list         # (offset, length) byte ranges written as zeros because unknowable


# --- ONELANGF ---------------------------------------------------------------------------

def _trim_block(block, slot):
    count, off, ulen, clen = struct.unpack_from('<HIHH', block, MSG_SLOT * slot)
    if not count:
        raise KeyError('language not in message file')
    header = bytearray(block[:MSG_HEADER])
    header[:MSG_SLOT * 11] = bytes(MSG_SLOT * 11)
    struct.pack_into('<HIHH', header, MSG_SLOT * slot, count, MSG_HEADER, ulen, clen)
    return bytes(header) + block[off:off + (clen or ulen)]


def one_language(data, language, name):
    """What ONELANGF.EXE writes: the message file cut down to one language."""
    slot = LANGUAGES.index(language)
    if name != b'MSGDATA':
        return _trim_block(data, slot)
    first = struct.unpack_from('<I', data, 26)[0]     # MSGDATA: 32-byte module directory
    out = bytearray(data[:first])
    for p in range(0, first, 32):
        if not data[p]:
            break
        off, length = struct.unpack_from('<IH', data, p + 26)
        block = _trim_block(data[off:off + length], slot)
        struct.pack_into('<IH', out, p + 26, len(out), len(block))
        out += block
    return bytes(out)


# --- a 1.44 MB FAT12 diskette written the way DOS 6 writes it --------------------------

class Floppy:
    def __init__(self, boot):
        self.img = bytearray(boot) + bytearray(SECTOR * (DATA_START - 1))
        self.img += bytes([FORMAT_FILL]) * (SECTOR * CLUSTERS)
        self.fat = [0] * (CLUSTERS + 2)
        self.fat[0], self.fat[1] = 0xFF0, 0xFFF
        self.root = [None] * ROOT_ENTRIES        # [name11, attr, cluster, size, dt]
        self.last = 1                            # DOS's next-free hint
        self.slack = []

    def _alloc(self, n):
        out, c = [], self.last
        for _ in range(CLUSTERS):
            if len(out) == n:
                break
            c = c + 1 if c + 1 < CLUSTERS + 2 else 2
            if not self.fat[c]:
                out.append(c)
                self.fat[c] = 0xFFF
        if len(out) < n:
            raise OSError('diskette full')
        for a, b in zip(out, out[1:]):
            self.fat[a] = b
        if out:
            self.last = out[-1]
        return out

    def write(self, name, data, dt):
        """Create (or truncate and rewrite) a root-directory file."""
        name11 = short_name(name)
        slot = next((i for i, e in enumerate(self.root) if e and e[0] == name11), None)
        if slot is None:
            slot = self.root.index(None)
        else:
            c = self.root[slot][2]
            while 2 <= c < 0xFF8:
                self.fat[c], c = 0, self.fat[c]
        chain = self._alloc(-(-len(data) // SECTOR))
        for i, c in enumerate(chain):
            piece = data[i * SECTOR:(i + 1) * SECTOR]
            off = (DATA_START + c - 2) * SECTOR
            self.img[off:off + SECTOR] = piece.ljust(SECTOR, b'\0')
            if len(piece) < SECTOR:
                self.slack.append((off + len(piece), SECTOR - len(piece)))
        self.root[slot] = [name11, ATTR_ARCHIVE, chain[0] if chain else 0, len(data), dt]

    def label(self, name11, dt):
        # DOD creates the label like a file, so DOS sets the archive bit on it too
        self.root[self.root.index(None)] = [name11.ljust(11), ATTR_LABEL | ATTR_ARCHIVE, 0, 0, dt]

    def image(self):
        img = bytearray(self.img)
        fat = bytearray(FAT_SECTORS * SECTOR)
        for c in range(0, CLUSTERS + 2, 2):
            v = self.fat[c] | (self.fat[c + 1] << 12 if c + 1 < len(self.fat) else 0)
            fat[c * 3 // 2:c * 3 // 2 + 3] = v.to_bytes(3, 'little')
        for k in range(2):
            img[(1 + k * FAT_SECTORS) * SECTOR:(1 + (k + 1) * FAT_SECTORS) * SECTOR] = fat
        root = bytearray()
        for e in self.root:
            if e is None:
                break
            name11, attr, cluster, size, dt = e
            ent = bytearray(dir_entry(name11, attr, cluster, size, dt))
            if name11[8:] in (b'COM', b'EXE'):
                # DOD.EXE's stamp: byte-swapped complement of time + date + size words
                t, d = dos_datetime(dt)
                v = ~(t + d + (size & 0xFFFF) + (size >> 16)) & 0xFFFF
                struct.pack_into('>H', ent, 0x14, v)
            root += ent
        start = (1 + 2 * FAT_SECTORS) * SECTOR
        img[start:start + len(root)] = root
        return bytes(img)


# --- DOD.EXE's backup ----------------------------------------------------------------

def _boot_sector(fmt_com, label11):
    prog = unpack_com(fmt_com)
    end = prog.index(b'Boot Diags diskette')
    start = prog.rindex(b'\xeb\x3c\x90', 0, end)
    boot = bytearray(prog[start:start + SECTOR])
    if boot[510:512] != b'\x55\xaa':
        raise ValueError("FMT.COM's boot sector template was not found")
    struct.pack_into('<HBHBHHBHHHII', boot, 0x0B, SECTOR, 1, 1, 2, ROOT_ENTRIES, SECTORS,
                     0xF0, FAT_SECTORS, 18, 2, 0, 0)
    boot[0x24], boot[0x26] = 0x00, 0x29
    struct.pack_into('<4s11s8s', boot, 0x27, b'EISA', label11, b'FAT12   ')
    return bytes(boot)


def build_diskettes(cd, model, language='ENGLISH', when=None):
    """Return the DIAGNOSTICS and SETUP diskettes (Diskette objects) for this CD/model.

    `when` is the date-time stamped on the labels and ONELANGF's files: a (y, m, d, h, mi, s)
    tuple, or a callable returning one per stamp. Default: the newest file date in DIAGS.
    """
    language = language.upper()
    if language not in LANGUAGES:
        raise ValueError(f'language must be one of {", ".join(LANGUAGES)}')
    files = tree_from_archives([cd.archive(p) for p in model.diags]).children
    if when is None:
        when = max(n.dt for n in files.values() if not n.is_dir)
    clock = when if callable(when) else (lambda: when)

    def read(name):
        n = files[name]
        z, zi = n.source
        return z.read(zi), n.dt

    def copy_list(fd, listname, first_only=False):     # DFC <src> <dst> LIST [-S]
        for line in read(listname)[0].decode('ascii').splitlines():
            name = line.strip().upper().encode()
            if not name:
                continue
            if name in files:
                fd.write(name, *read(name))
            if first_only:
                break

    fmt = read(b'FMT.COM')[0]

    disk1 = Floppy(_boot_sector(fmt, b'DIAGS      '))
    copy_list(disk1, b'DIAGDSK1.IN')
    copy_list(disk1, b'DIAGMSG1.IN', first_only=True)
    for name in (b'MSGDATA', b'DD_MSG', b'DOD_MSG'):
        data, dt = read(name)
        try:
            disk1.write(name, one_language(data, language, name), clock())
        except KeyError:                           # ONELANGF fails: empty file, then DFC
            disk1.write(name, b'', clock())
            disk1.write(name, data, dt)
    disk1.label(b'DIAGS', clock())

    disk2 = Floppy(_boot_sector(fmt, b'DIAGSETU.P '))
    copy_list(disk2, b'DIAGDSK2.IN')
    copy_list(disk2, b'DIAGMSG2.IN')
    disk2.label(b'DIAGSETUP', clock())

    return [Diskette('DIAGNOSTICS', disk1.image(), disk1.slack),
            Diskette('SETUP', disk2.image(), disk2.slack)]
