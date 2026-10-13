"""Pre-fill the user name and company in the Windows 95 Setup wizard.

On the second boot Microsoft's OEM preinstall wizard (PISETUP) asks for the user's name
and company, the licence agreement and the Certificate of Authenticity number. The
[userinfo] section of C:\\PISETUP\\PISETUP.INF documents Username= and Company= for
pre-filling the first page; the page still appears (PISETUP cannot skip it) but arrives
filled in. The COA number cannot be pre-filled: PISETUP only keeps a pre-loaded number
when the OEM's PC_MFR_ID authorises it, and Compaq's does not.
"""
import re

PISETUP_INF = (b'PISETUP', b'PISETUP.INF')
_SAFE = re.compile(r'[ -~]{1,60}')      # printable ASCII


def check(user=None, company=None):
    """Raise ValueError if a value can't go into the INF as-is."""
    for what, v in (('user name', user), ('company', company)):
        if v is not None and (not _SAFE.fullmatch(v) or set(v) & set(';"[]')):
            raise ValueError(f'{what}: use 1-60 printable ASCII characters without ; " [ ]')


def patch_inf(inf, user=None, company=None):
    """Return PISETUP.INF with Username=/Company= set in its [userinfo] section."""
    check(user, company)
    lines = inf.split(b'\r\n')
    start = next((i for i, l in enumerate(lines) if l.strip().lower() == b'[userinfo]'), None)
    if start is None:
        raise ValueError('PISETUP.INF has no [userinfo] section')
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith(b'[')), len(lines))
    section = lines[start + 1:end]
    for key, value in ((b'Username', user), (b'Company', company)):
        if value is None:
            continue
        line = key + b'=' + value.encode('ascii')
        pat = re.compile(rb';?\s*' + key + rb'\s*=', re.I)
        hit = next((i for i, l in enumerate(section) if pat.match(l)), None)
        if hit is None:
            last = max((i for i, l in enumerate(section)
                        if l.strip() and not l.lstrip().startswith(b';')), default=-1)
            section.insert(last + 1, line)
        else:
            section[hit] = line
    return b'\r\n'.join(lines[:start + 1] + section + lines[end:])


def apply(tree, user=None, company=None):
    """Replace PISETUP.INF in a tree from fat.tree_from_archives; no-op without values."""
    if user is None and company is None:
        return
    node = tree
    for part in PISETUP_INF:
        node = node.children[part]
    z, zi = node.source
    node.data = patch_inf(z.read(zi), user, company)
    node.size = len(node.data)
