"""Understand a Compaq QuickRestore CD: which models it restores and in what order.

Everything is read from the CD itself:

* FINAL/<ver>/UNZIPLTR/*.EXE  -- one model-specific ("SKU specific") archive per model. Each
  contains SYSTEM.SAV/INFO.BOM, the factory bill of materials: the SKU number and the
  ordered list of archives that make up that model's disk.
* DATABASE/SKUMODEL.DB        -- Paradox table mapping SKU numbers to model names.
* QUICKRST/*.BOO              -- Compaq's MBR and boot-sector templates.

INFO.BOM entries look like:
    File #  1,       RTR PRODUCTION STARTUP FILE VERC163
    File #  2,       RTR COMMON ZIP 1 VERC163A
    ...
    File # 50,       RTR R2015 SKU SPECIFIC VERC163A
    File # 51,       RTR QUICKRESTORE US CFG VERC163A
    File # 52,       DIAGS PC 10.06 VERC161A
"""
import hashlib
import re
import zipfile
from dataclasses import dataclass, field

from . import paradox, qrzip
from .iso9660 import IsoImage

# SHA-256 of the CD image this tool was developed and hardware-tested against.
KNOWN_ISOS = {
    '9882c0932749825cdf483b31ed2667ebdd5e7419aa6e2c6b3d09523784815808':
        'CPQQRS73101 - Compaq Presario 5528/9546/9548/9564 QuickRestore (Sept 1995)',
}


class UnsupportedCD(Exception):
    pass


@dataclass
class Model:
    model: str                  # e.g. "9548"
    name: str                   # e.g. "Presario 9548"
    description: str            # e.g. "Presario 9548 M1.6G f/m DOM"
    sku: str                    # e.g. "213950-007"
    bom_id: str                 # e.g. "R2015"
    archive: str                # ISO path of this model's SKU-specific archive
    c_drive: list = field(default_factory=list)     # ISO paths, in restore order
    diags: list = field(default_factory=list)       # ISO paths for the diagnostics partition

    @property
    def archive_stem(self):
        return self.archive.rsplit('/', 1)[-1].rsplit('.', 1)[0]


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(chunk), b''):
            h.update(block)
    return h.hexdigest()


def _numbered(names):
    """Sort archive names by their trailing number (BD9-2 before BD9-10)."""
    def key(n):
        m = re.search(r'(\d+)\.EXE$', n)
        return (int(m.group(1)) if m else -1, n)
    return sorted(names, key=key)


class QuickRestoreCD:
    def __init__(self, iso_path):
        self.iso = IsoImage(iso_path)
        for p in ('QUICKRST/MASTER.BOO', 'QUICKRST/PRIMARY.BOO', 'QUICKRST/SYSTEM.BOO', 'FINAL'):
            if not self.iso.exists(p):
                raise UnsupportedCD(f'{iso_path}: no {p} -- not a Compaq QuickRestore CD')
        self.volume_id = self.iso.volume_id
        self._archives = {}
        self.models = self._discover()

    def close(self):
        self.iso.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def boot_template(self, name):
        return self.iso.read(f'QUICKRST/{name}.BOO')

    def archive(self, iso_path) -> zipfile.ZipFile:
        if iso_path not in self._archives:
            try:
                self._archives[iso_path] = qrzip.open_archive(self.iso.read(iso_path))
            except qrzip.QrZipError as e:
                raise UnsupportedCD(f'{iso_path}: {e}') from None
        return self._archives[iso_path]

    def _exes(self, folder):
        if not self.iso.exists(folder):
            return []
        return _numbered(f'{folder}/{n}' for n, is_dir in self.iso.listdir(folder).items()
                         if not is_dir and n.endswith('.EXE'))

    def _model_names(self):
        try:
            rows = paradox.read_table(self.iso.read('DATABASE/SKUMODEL.DB'))
        except (FileNotFoundError, ValueError):
            return {}
        return {r[0].strip(): (r[1].strip(), r[2].strip() if len(r) > 2 else '') for r in rows}

    def _discover(self):
        names = self._model_names()
        models = []
        for ver in sorted(self.iso.listdir('FINAL')):
            for exe in self._exes(f'FINAL/{ver}/UNZIPLTR'):
                z = self.archive(exe)
                try:
                    bom = z.read('SYSTEM.SAV/INFO.BOM').decode('latin-1')
                except KeyError:
                    continue
                models.append(self._model_from_bom(exe, bom, names))
        if not models:
            raise UnsupportedCD('no model-specific archives (FINAL/*/UNZIPLTR) found on this CD')
        return sorted(models, key=lambda m: m.model)

    def _model_from_bom(self, exe, bom, names):
        sku = re.search(r'SKU Number:\s*(\S+)', bom)
        bom_id = re.search(r'BOM ID:\s*(\S+)', bom)
        if not sku:
            raise UnsupportedCD(f'{exe}: INFO.BOM has no SKU number')
        sku = sku.group(1)
        description, short = names.get(sku, ('', ''))
        name = short or (re.match(r'(Presario \S+)', description) or [None, ''])[1] or f'SKU {sku}'
        m = Model(model=name.split()[-1], name=name, description=description, sku=sku,
                  bom_id=bom_id.group(1) if bom_id else '', archive=exe)
        common_seen = 0
        for line in re.findall(r'File #\s*\d+,\s*(.+)', bom):
            line = line.strip()
            ver = line.split()[-1]
            if 'STARTUP' in line:
                m.c_drive += self._exes(f'FINAL/{ver}/UNZIPNOW')
            elif re.search(r'COMMON ZIP \d+', line):
                n = int(re.search(r'COMMON ZIP (\d+)', line).group(1))
                exes = self._exes(f'FINAL/{ver}/UNZIPNOW')
                if n > len(exes):
                    raise UnsupportedCD(f'{exe}: INFO.BOM wants common zip {n}, CD has {len(exes)}')
                m.c_drive.append(exes[n - 1])
                common_seen += 1
            elif 'SKU SPECIFIC' in line:
                # Use this model's own archive. (The 9564's BOM names the 9548's R2015 archive;
                # the two archives differ only in INFO.BOM and a checksum list.)
                m.c_drive.append(exe)
            elif 'CFG' in line:
                continue                    # QRSTCFG.INI: QuickRestore's own settings, not copied
            elif line.startswith('DIAGS'):
                m.diags += self._exes(f'FINAL/{ver}/HIDDEN')
            else:
                raise UnsupportedCD(f'{exe}: unrecognised INFO.BOM entry {line!r}')
        if not common_seen or not m.diags:
            raise UnsupportedCD(f'{exe}: INFO.BOM lists no common or diagnostics archives')
        return m

    def find_model(self, wanted):
        w = wanted.lower().replace('presario', '').strip()
        hits = [m for m in self.models
                if w in (m.model.lower(), m.sku.lower(), m.archive_stem.lower(), m.bom_id.lower())]
        if len(hits) != 1:
            choices = ', '.join(m.model for m in self.models)
            raise KeyError(f'unknown model {wanted!r}; this CD has: {choices}')
        return hits[0]
