"""Check a built image (or a written disk) against the CD it was built from."""
import struct

from . import userinfo
from .build import DIAG_BOOT_LABEL, DIAG_SERIAL
from .fat import ATTR_DIR, FatReader, tree_from_archives

SECTOR = 512


def _expected(cd, paths, fill=None):
    """{path: (attr, size, contents loader)} for every file the archives produce (last wins)."""
    out = {}

    def walk(node, prefix):
        for name, n in node.children.items():
            p = prefix + name
            if n.is_dir:
                walk(n, p + b'/')
            else:
                z, zi = n.source
                out[p] = (n.attr, n.size,
                          (lambda z=z, zi=zi: z.read(zi)) if n.data is None else (lambda d=n.data: d))
    tree = tree_from_archives([cd.archive(p) for p in paths])
    if fill:
        userinfo.apply(tree, *fill)
    walk(tree, b'')
    return out


def verify_image(cd, model, image_path, progress=None, user=None, company=None):
    """Return a list of problems (empty = image matches the CD exactly)."""
    problems = []
    with open(image_path, 'rb') as f:
        mbr = f.read(SECTOR)
        if mbr[510:512] != b'\x55\xaa':
            return ['no MBR signature']
        parts = [struct.unpack_from('<BxxxBxxxII', mbr, 446 + 16 * i) for i in range(2)]
        if [p[1] for p in parts] != [0x12, 0x06] or parts[1][0] != 0x80:
            return ['partition table is not diag (0x12) + active FAT16 (0x06)']
        for (_, _, start, _), paths, label in ((parts[0], model.diags, 'diagnostics'),
                                              (parts[1], model.c_drive, 'C:')):
            vol = FatReader(f, start)
            if paths is model.diags and (vol.serial, vol.label) != (DIAG_SERIAL, DIAG_BOOT_LABEL):
                problems.append(f'{label}: boot sector has serial {vol.serial!r} and label '
                                f'{vol.label.decode("cp437")!r}; Compaq Utilities need '
                                f'{DIAG_SERIAL!r} and {DIAG_BOOT_LABEL.decode()!r}')
            if vol.fats[0] != vol.fats[1]:
                problems.append(f'{label}: the two FAT copies differ')
            expected = _expected(cd, paths, None if paths is model.diags else (user, company))
            seen = set()
            for path, attr, cluster, size, _raw in vol.walk():
                if attr & ATTR_DIR:
                    if attr != ATTR_DIR:
                        problems.append(f'{label}: directory {path.decode("cp437")} has attribute '
                                        f'0x{attr:02x}, expected 0x10')
                    continue
                exp = expected.get(path)
                if exp is None:
                    problems.append(f'{label}: unexpected file {path.decode("cp437")}')
                    continue
                seen.add(path)
                e_attr, e_size, contents = exp
                if attr != e_attr or size != e_size:
                    problems.append(f'{label}: {path.decode("cp437")} attr/size '
                                    f'0x{attr:02x}/{size} != 0x{e_attr:02x}/{e_size}')
                elif size and vol.read_chain(cluster, size) != contents():
                    problems.append(f'{label}: {path.decode("cp437")} content differs')
            for path in sorted(set(expected) - seen):
                problems.append(f'{label}: missing {path.decode("cp437")}')
            if progress:
                progress(label, len(expected))
    return problems
