"""compaq-qrst-rebuild command line."""
import argparse
import os
import sys

from . import __version__, disk
from .build import build_image
from .cd import KNOWN_ISOS, QuickRestoreCD, UnsupportedCD, sha256_file
from .diskettes import LANGUAGES, build_diskettes
from .userinfo import check as check_userinfo
from .iso9660 import IsoError
from .verify import verify_image


def _open_cd(path, check=True):
    if not os.path.isfile(path):
        sys.exit(f'error: {path}: no such file')
    if check:
        digest = sha256_file(path)
        known = KNOWN_ISOS.get(digest)
        if known:
            print(f'CD: {known}')
        else:
            print(f'warning: {os.path.basename(path)} (sha256 {digest[:16]}...) is not a CD this '
                  'tool was tested with; continuing, but results are untested.', file=sys.stderr)
    try:
        return QuickRestoreCD(path)
    except (UnsupportedCD, IsoError) as e:
        sys.exit(f'error: {e}')


def cmd_models(a):
    with _open_cd(a.iso) as cd:
        print(f'\n{"Model":<8} {"SKU":<12} {"BOM":<7} {"Archive":<10} Description')
        for m in cd.models:
            print(f'{m.model:<8} {m.sku:<12} {m.bom_id:<7} {m.archive_stem:<10} {m.description}')


def _target_sectors(a):
    if a.size_of:
        try:
            n = disk.device_sectors(a.size_of)
        except PermissionError:
            sys.exit(f'error: permission denied reading {a.size_of} (try sudo, or use --size)')
        except OSError as e:
            sys.exit(f'error: {a.size_of}: {e.strerror}')
        if not n:
            sys.exit(f'error: could not read the size of {a.size_of}; use --size instead')
        return n
    try:
        return disk.parse_size(a.size)
    except ValueError as e:
        sys.exit(f'error: {e}')


def _userinfo(a):
    try:
        check_userinfo(a.user, a.company, a.coa)
    except ValueError as e:
        sys.exit(f'error: {e}')
    return {'user': a.user, 'company': a.company, 'coa': a.coa}


def cmd_build(a):
    if os.path.exists(a.output) and not a.force:
        sys.exit(f'error: {a.output} exists (use --force to overwrite)')
    info = _userinfo(a)
    sectors = _target_sectors(a)
    with _open_cd(a.iso) as cd:
        try:
            model = cd.find_model(a.model)
        except KeyError as e:
            sys.exit(f'error: {e.args[0]}')
        try:
            layout = disk.plan(sectors, a.heads)
        except ValueError as e:
            sys.exit(f'error: {e}')
        print(f'Model:    {model.name} (SKU {model.sku}, {len(model.c_drive)} archives)')
        print(f'Target:   {sectors} sectors ({sectors * 512 / 1e9:.2f} GB), '
              f'geometry {layout.heads} heads x {layout.spt} sectors')
        print('Building...', flush=True)
        try:
            r = build_image(cd, model, a.output, sectors, a.heads, **info)
        except Exception as e:  # noqa: BLE001 - report cleanly, remove the partial image
            if os.path.exists(a.output):
                os.remove(a.output)
            sys.exit(f'error: {e}')
        if not a.no_verify:
            print('Verifying...', flush=True)
            problems = verify_image(cd, model, a.output, **info)
            if problems:
                print('\n'.join(problems[:20]), file=sys.stderr)
                sys.exit(f'error: verification failed ({len(problems)} problems)')
    L = r.layout
    print(f'\nWrote {a.output}: {L.image_sectors * 512 / 2 ** 20:.0f} MiB')
    print(f'  partition 1  Compaq diagnostics  {L.diag_sectors * 512 / 2 ** 20:.1f} MiB')
    print(f'  partition 2  C: FAT16            {L.c_sectors * 512 / 2 ** 20:.0f} MiB, '
          f'{r.c_cluster_bytes // 1024} KB clusters, {r.c_used_bytes / 2 ** 20:.0f} MiB used')
    if sectors > L.image_sectors:
        print(f'  ({(sectors - L.image_sectors) * 512 / 2 ** 20:.0f} MiB of the disk is left '
              'unpartitioned: Win95 RTM partitions max out at 2 GB)')
    print('\nNext: write the image to the whole disk (README, section 5).')


def _parse_when(text):
    from datetime import datetime
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            t = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if not 1980 <= t.year <= 2107:
            break
        return (t.year, t.month, t.day, t.hour, t.minute, t.second)
    sys.exit(f'error: --date {text!r}: use YYYY-MM-DD [HH:MM[:SS]] between 1980 and 2107')


def cmd_diskettes(a):
    os.makedirs(a.output, exist_ok=True)
    names = [os.path.join(a.output, f'{n}.img') for n in ('DIAGNOSTICS', 'SETUP')]
    clash = [n for n in names if os.path.exists(n)]
    if clash and not a.force:
        sys.exit(f'error: {clash[0]} exists (use --force to overwrite)')
    with _open_cd(a.iso) as cd:
        try:
            model = cd.find_model(a.model) if a.model else cd.models[0]
        except KeyError as e:
            sys.exit(f'error: {e.args[0]}')
        disks = build_diskettes(cd, model, a.language, _parse_when(a.date) if a.date else None)
    for d, path in zip(disks, names):
        with open(path, 'wb') as f:
            f.write(d.image)
        print(f'Wrote {path}: 1.44 MB {d.name} diskette')
    print('\nNext: write each image to a 1.44 MB diskette (README, section 7).')


def cmd_verify(a):
    with _open_cd(a.iso, check=False) as cd:
        try:
            model = cd.find_model(a.model)
        except KeyError as e:
            sys.exit(f'error: {e.args[0]}')
        problems = verify_image(cd, model, a.image,
                                progress=lambda label, n: print(f'{label}: {n} files checked'),
                                **_userinfo(a))
    if problems:
        print('\n'.join(problems[:50]))
        if any('PISETUP/PISETUP.INF' in p for p in problems):
            print('(built with --user/--company/--coa? pass the same options to verify)')
        sys.exit(f'FAILED: {len(problems)} problems')
    custom = ' (with the given setup answers)' if a.user or a.company or a.coa else ' exactly'
    print(f'OK: image matches the CD{custom}')


def _userinfo_args(p, verify=False):
    how = 'it was built with' if verify else 'to pre-fill in the Windows 95 Setup wizard'
    p.add_argument('--user', help=f'user name {how}')
    p.add_argument('--company', help=f'company name {how}')
    p.add_argument('--coa', metavar='NUMBER',
                   help=f'Certificate of Authenticity number {how}, e.g. 12345-OEM-1234567-12345')


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='compaq-qrst-rebuild',
        description='Rebuild a Compaq Presario QuickRestore CD into a bootable raw disk image.')
    ap.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    sub = ap.add_subparsers(dest='command', required=True)

    p = sub.add_parser('models', help='list the models a QuickRestore CD can restore')
    p.add_argument('iso', help='QuickRestore CD image (.iso)')
    p.set_defaults(func=cmd_models)

    p = sub.add_parser('build', help='build a raw disk image for one model')
    p.add_argument('iso', help='QuickRestore CD image (.iso)')
    p.add_argument('-m', '--model', required=True, help='model number (e.g. 9548) or SKU')
    p.add_argument('-o', '--output', required=True, help='output image file')
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('-s', '--size', help='target disk size: sectors, or e.g. 4GB, 1.6GB, 2GiB')
    g.add_argument('--size-of', metavar='DEVICE', help='read the size from a disk (Linux)')
    p.add_argument('--heads', type=int, choices=(16, 32, 64, 128, 255),
                   help="override the BIOS's translated head count")
    _userinfo_args(p)
    p.add_argument('--no-verify', action='store_true', help='skip the read-back verification')
    p.add_argument('-f', '--force', action='store_true', help='overwrite the output file')
    p.set_defaults(func=cmd_build)

    p = sub.add_parser('diskettes', help='build the DIAGNOSTICS and SETUP diskette images')
    p.add_argument('iso', help='QuickRestore CD image (.iso)')
    p.add_argument('-o', '--output', required=True, help='directory for DIAGNOSTICS.img, SETUP.img')
    p.add_argument('-m', '--model', help='model (all models on this CD share the diagnostics)')
    p.add_argument('-l', '--language', default='ENGLISH', type=str.upper, choices=LANGUAGES,
                   help='language of the DIAGNOSTICS diskette messages (default ENGLISH)')
    p.add_argument('--date', help='date-time for the labels and trimmed message files, as '
                   "'YYYY-MM-DD HH:MM'; default: the diagnostics' own file date")
    p.add_argument('-f', '--force', action='store_true', help='overwrite existing images')
    p.set_defaults(func=cmd_diskettes)

    p = sub.add_parser('verify', help='check an image or written disk against the CD')
    p.add_argument('iso', help='QuickRestore CD image (.iso)')
    p.add_argument('image', help='image file or disk device')
    p.add_argument('-m', '--model', required=True, help='model the image was built for')
    _userinfo_args(p, verify=True)
    p.set_defaults(func=cmd_verify)

    a = ap.parse_args(argv)
    a.func(a)


if __name__ == '__main__':
    main()
