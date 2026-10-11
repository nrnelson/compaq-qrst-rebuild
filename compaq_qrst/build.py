"""Assemble a complete restore disk image for one model."""
import zlib
from dataclasses import dataclass

from . import disk
from .fat import FatWriter, tree_from_archives

C_LABEL = b'PRESARIO'
# Compaq's own installer (DOD.EXE) leaves the partition labelled DIAGSETUP, and its
# "Create a Diagnostics Diskette" refuses a partition labelled DIAGS (QuickRestore's choice).
DIAG_LABEL = b'DIAGSETUP'


@dataclass
class BuildResult:
    layout: disk.Layout
    c_clusters: int
    c_cluster_bytes: int
    c_used_bytes: int


def build_image(cd, model, out_path, disk_sectors, heads=None):
    layout = disk.plan(disk_sectors, heads)
    serial = zlib.crc32(model.archive_stem.encode())
    with open(out_path, 'wb') as img:
        img.truncate(layout.image_sectors * disk.SECTOR)
        img.write(disk.mbr(cd.boot_template('MASTER'), layout))

        diag = FatWriter(img, layout.diag_start, layout.diag_sectors,
                         2 if layout.diag_sectors < 8200 else 4, True,
                         cd.boot_template('SYSTEM'), DIAG_LABEL, serial ^ 0x5A5A5A5A,
                         layout.heads, layout.spt)
        diag.populate(tree_from_archives([cd.archive(p) for p in model.diags]))

        c = FatWriter(img, layout.c_start, layout.c_sectors, layout.c_cluster_sectors, False,
                      cd.boot_template('PRIMARY'), C_LABEL, serial, layout.heads, layout.spt)
        c.populate(tree_from_archives([cd.archive(p) for p in model.c_drive]))
    return BuildResult(layout, c.nclusters, c.cluster_bytes, c.used_bytes)
