"""Disk geometry, partition layout and MBR for a rebuilt QuickRestore disk.

Windows 95 RTM boots with CHS-only code (MBR, FAT16 boot sector, IO.SYS), so the geometry
written into the partition table and boot sectors must match what the BIOS reports for the
target disk. BIOSes of the era use "LBA-assisted" translation: 63 sectors per track and the
fewest of 16/32/64/128/255 heads that keeps the cylinder count at or below 1024.
"""
import struct
from dataclasses import dataclass

SECTOR = 512
FAT16_MAX_CLUSTERS = 65524
FAT16_MAX_SPC = 64                      # 32 KB clusters; Win95 cannot use 64 KB clusters
DIAG_MIN_SECTORS = 6000                 # Compaq Diagnostics needs ~2.5 MB


def lba_assisted_heads(total_sectors, spt=63):
    cyl16 = total_sectors // (16 * spt)
    for heads in (16, 32, 64, 128, 255):
        if cyl16 * 16 // heads <= 1024:
            return heads
    return 255


def win95_cluster_sectors(volume_bytes):
    """Sectors per cluster that Windows 95 FORMAT picks for a FAT16 volume of this size."""
    mib = volume_bytes / 2 ** 20
    for limit, spc in ((128, 4), (256, 8), (512, 16), (1024, 32)):
        if mib <= limit:
            return spc
    return 64


@dataclass
class Layout:
    disk_sectors: int
    heads: int
    spt: int
    diag_start: int
    diag_sectors: int
    c_start: int
    c_sectors: int
    c_cluster_sectors: int

    @property
    def image_sectors(self):
        return self.c_start + self.c_sectors

    @property
    def cylinder(self):
        return self.heads * self.spt


def plan(disk_sectors, heads=None, spt=63):
    """Lay out MBR, Compaq diagnostics partition and the largest FAT16 C: the disk allows."""
    heads = heads or lba_assisted_heads(disk_sectors, spt)
    cyl = heads * spt
    bios_cyls = min(disk_sectors // cyl, 1024)
    diag_cyls = -(-(DIAG_MIN_SECTORS + spt) // cyl)
    max_c_sectors = FAT16_MAX_CLUSTERS * FAT16_MAX_SPC + 1 + 2 * 256 + 32
    c_cyls = min(bios_cyls - diag_cyls, max_c_sectors // cyl)
    if c_cyls < 1:
        raise ValueError('the target disk is too small')
    c_sectors = c_cyls * cyl
    return Layout(disk_sectors, heads, spt, spt, diag_cyls * cyl - spt,
                  diag_cyls * cyl, c_sectors, win95_cluster_sectors(c_sectors * SECTOR))


def chs(lba, heads, spt):
    c, rem = divmod(lba, heads * spt)
    h, s = divmod(rem, spt)
    if c > 1023:
        c, h, s = 1023, heads - 1, spt
    else:
        s += 1
    return bytes([h, ((c >> 2) & 0xC0) | s, c & 0xFF])


def mbr(template, layout):
    """MBR from Compaq's MASTER.BOO code with a diag (0x12) + active FAT16 (0x06) table."""
    m = bytearray(template)
    if len(m) != SECTOR or m[510:512] != b'\x55\xaa':
        raise ValueError('MBR template is not a valid 512-byte boot sector')
    m[446:510] = bytes(64)
    parts = [(0x00, 0x12, layout.diag_start, layout.diag_sectors),
             (0x80, 0x06, layout.c_start, layout.c_sectors)]
    for i, (boot, ptype, start, n) in enumerate(parts):
        struct.pack_into('<B3sB3sII', m, 446 + 16 * i, boot, chs(start, layout.heads, layout.spt),
                         ptype, chs(start + n - 1, layout.heads, layout.spt), start, n)
    return bytes(m)


def parse_size(text):
    """'7962192' (sectors), '4GB', '4000MB', '2GiB' ... -> sectors."""
    t = text.strip().upper().replace(' ', '')
    units = {'KIB': 2 ** 10, 'MIB': 2 ** 20, 'GIB': 2 ** 30,
             'KB': 10 ** 3, 'MB': 10 ** 6, 'GB': 10 ** 9, 'K': 10 ** 3, 'M': 10 ** 6, 'G': 10 ** 9}
    for unit in sorted(units, key=len, reverse=True):
        if t.endswith(unit):
            return int(float(t[:-len(unit)]) * units[unit]) // SECTOR
    if t.isdigit():
        return int(t)
    raise ValueError(f'cannot parse size {text!r} (use sectors, or e.g. 4GB / 4000MB / 2GiB)')


def device_sectors(path):
    """Size of a block device (or file) in 512-byte sectors; works on Linux and macOS."""
    import os
    fd = os.open(path, os.O_RDONLY)
    try:
        return os.lseek(fd, 0, os.SEEK_END) // SECTOR
    finally:
        os.close(fd)
