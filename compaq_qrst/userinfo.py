"""Pre-fill the Windows 95 Setup wizard: user name, company and COA number.

On the second boot Microsoft's OEM preinstall wizard (PISETUP) asks for the user's name
and company, the licence agreement and the Certificate of Authenticity number. Every
start it copies C:\\PISETUP\\PISETUP.INF to C:\\WINDOWS\\INF\\MSBATCH.INF and reads that:

* [userinfo] Username= and Company= (documented in the INF) fill in the first page;
* [userinfo] COANUMBER= (undocumented) fills in the COA box, but only if the
  [Settings] PC_MFR_ID enables it (oemid.FLAG_KEEP_COA). Compaq's ID doesn't, so the ID
  is re-issued with that one flag added and every other flag kept.

The pages still appear -- PISETUP cannot skip them -- but arrive filled in.
"""
import re

from . import oemid

PISETUP_INF = (b'PISETUP', b'PISETUP.INF')
OEMINFO_INI = (b'WINDOWS', b'SYSTEM', b'OEMINFO.INI')
_SAFE = re.compile(r'[ -~]{1,60}')      # printable ASCII
COA_FORMAT = 'DDDYY-OEM-0NNNNNN-NNNNN'


def normalize_coa(coa):
    """The COA number as PISETUP sees it: dashes and spaces dropped, re-dashed 5-3-7-5."""
    s = coa.replace('-', '').replace(' ', '').upper()
    if len(s) != 20:
        raise ValueError(f'COA number {coa!r}: expected {COA_FORMAT} (20 characters without '
                         f'the dashes), got {len(s)}')
    return f'{s[:5]}-{s[5:8]}-{s[8:15]}-{s[15:]}'


def coa_problem(coa):
    """Why SETUPX's PIDVALIDATE would reject this Windows 95 OEM COA number, or None.

    PISETUP validates the COA page with SETUPX.DLL PIDVALIDATE, product type "8" (OEM):
    DDDYY-OEM-0NNNNNN-NNNNN with DDD a day 001-366, YY 95-99 or 00-02, 'OEM' in any
    case, the 7-digit block starting with 0, ending in 1-7 and summing to a multiple of 7.
    """
    try:
        key = normalize_coa(coa)
    except ValueError as e:
        return str(e)
    day, year, oem, block, tail = key[:3], key[3:5], key[6:9], key[10:17], key[18:]
    if not (day + year).isdigit():
        return 'the first block must be 5 digits (day of year and year)'
    if not 1 <= int(day) <= 366:
        return f'the first three digits are a day of the year (001-366), not {day}'
    if not (int(year) >= 95 or int(year) <= 2):
        return f'digits 4-5 are the year (95-99 or 00-02), not {year}'
    if oem != 'OEM':
        return f"the second block must be OEM, not {oem}"
    if not block.isdigit() or not tail.isdigit():
        return 'the third and fourth blocks must be digits'
    if block[0] != '0':
        return 'the third block must start with 0'
    if not '1' <= block[6] <= '7':
        return 'the third block must end in a digit from 1 to 7'
    if sum(map(int, block)) % 7:
        return 'the digits of the third block must add up to a multiple of 7 (typo?)'
    return None


def check(user=None, company=None, coa=None):
    """Raise ValueError if a value can't go into the INF, or Setup would refuse it."""
    for what, v in (('user name', user), ('company', company)):
        if v is not None and (not _SAFE.fullmatch(v) or set(v) & set(';"[]')):
            raise ValueError(f'{what}: use 1-60 printable ASCII characters without ; " [ ]')
    if coa is not None:
        problem = coa_problem(coa)
        if problem:
            raise ValueError(f'COA number {coa!r} would be rejected by Windows 95 Setup: '
                             f'{problem}')


def _section(lines, name):
    header = (b'[' + name + b']').lower()
    start = next((i for i, l in enumerate(lines) if l.strip().lower() == header), None)
    if start is None:
        raise ValueError(f'PISETUP.INF has no [{name.decode()}] section')
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith(b'[')), len(lines))
    return start + 1, end


def _get(lines, section, key):
    start, end = _section(lines, section)
    pat = re.compile(rb'\s*' + key + rb'\s*=\s*(.*?)\s*$', re.I)
    return next((m.group(1) for m in map(pat.match, lines[start:end]) if m), None)


def _set(lines, section, key, value):
    """Set key=value, replacing the (possibly commented-out) key or adding it."""
    start, end = _section(lines, section)
    line = key + b'=' + value
    pat = re.compile(rb';?\s*' + key + rb'\s*=', re.I)
    hit = next((i for i in range(start, end) if pat.match(lines[i])), None)
    if hit is None:
        hit = max((i for i in range(start, end)
                   if lines[i].strip() and not lines[i].lstrip().startswith(b';')),
                  default=start - 1) + 1
        lines.insert(hit, line)
    else:
        lines[hit] = line


def _manufacturer(oeminfo):
    m = re.search(rb'^\s*Manufacturer\s*=\s*(.*?)\s*$', oeminfo, re.I | re.M)
    if not m:
        raise ValueError('OEMINFO.INI has no Manufacturer=')
    return m.group(1).decode('cp437')


def patch_inf(inf, user=None, company=None, coa=None, manufacturer=None):
    """Return PISETUP.INF with the given values set (`manufacturer` is needed for coa)."""
    check(user, company, coa)
    lines = inf.split(b'\r\n')
    for key, value in ((b'Username', user), (b'Company', company)):
        if value is not None:
            _set(lines, b'userinfo', key, value.encode('ascii'))
    if coa is not None:
        old = (_get(lines, b'Settings', b'PC_MFR_ID') or b'').decode('ascii', 'replace')
        flags = oemid.decode(old, manufacturer)
        if not flags:
            raise ValueError(f'PC_MFR_ID {old!r} is not valid for {manufacturer!r}')
        new = oemid.encode(flags | oemid.FLAG_KEEP_COA, manufacturer)
        _set(lines, b'Settings', b'PC_MFR_ID', new.encode('ascii'))
        _set(lines, b'userinfo', b'COANUMBER', normalize_coa(coa).encode('ascii'))
    return b'\r\n'.join(lines)


def _read(tree, path):
    node = tree
    for part in path:
        node = node.children[part]
    return node


def apply(tree, user=None, company=None, coa=None):
    """Replace PISETUP.INF in a tree from fat.tree_from_archives; no-op without values."""
    if user is None and company is None and coa is None:
        return
    node = _read(tree, PISETUP_INF)
    manufacturer = None
    if coa is not None:
        z, zi = _read(tree, OEMINFO_INI).source
        manufacturer = _manufacturer(z.read(zi))
    z, zi = node.source
    node.data = patch_inf(z.read(zi), user, company, coa, manufacturer)
    node.size = len(node.data)
