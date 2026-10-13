"""The PC_MFR_ID in PISETUP.INF: Microsoft's OEM_ID.EXE code that switches PISETUP features.

PISETUP hashes the Manufacturer= name in WINDOWS\\SYSTEM\\OEMINFO.INI and requires 8 of the
13 hex digits to equal that hash. The other 5 encode a set of feature flags: minus the
hash's low 16 bits and masked to 20 bits, the value must be an exact sum of entries from a
fixed table, each entry being one flag, and flag 0 must be set.

Flag 3 makes PISETUP keep a Certificate of Authenticity number pre-loaded from
[UserInfo] COANUMBER= in its INF instead of clearing it. Compaq's ID (21B80F15D0DA6) has
flags 0, 2 and 5, without it.
"""
WEIGHTS = (0x3ADC75, 0x970, 0xD0A1A14, 0x5, 0xD27BA)
FLAG_VALUES = (0x17E97, 0xBE5B, 0x5DFD, 0x2E25, 0x16A9, 0xB23, 0x58F, 0x2C5,
               0x15B, 0xA3, 0x4F, 0x25, 0x11, 7, 3, 1)
HASH_DIGITS = (1, 4, 5, 6, 8, 9, 11, 12)      # positions of the hash in the 13-digit ID
FLAG_DIGITS = (0, 2, 3, 7, 10)
FLAG_KEEP_COA = 1 << 3


def manufacturer_hash(name):
    h = 0
    for i, c in enumerate(name.encode('cp437')):
        h += (c - 256 if c >= 128 else c) * WEIGHTS[i % len(WEIGHTS)]   # signed chars
    return h & 0xFFFFFFFF


def decode(pc_mfr_id, manufacturer):
    """Return the feature flags, or 0 for an ID that PISETUP would reject."""
    if len(pc_mfr_id) != 13:
        return 0
    try:
        hashed = int(''.join(pc_mfr_id[i] for i in HASH_DIGITS), 16)
        value = int(''.join(pc_mfr_id[i] for i in FLAG_DIGITS), 16)
    except ValueError:
        return 0
    h = manufacturer_hash(manufacturer)
    if hashed != h:
        return 0
    value = (value - (h & 0xFFFF)) & 0xFFFFF
    flags = 0
    for i, v in enumerate(FLAG_VALUES):
        if not value:
            break
        if v <= value:
            value -= v
            flags |= 1 << i
    return flags if flags & 1 and not value else 0


def encode(flags, manufacturer):
    """Return a PC_MFR_ID for these flags (flag 0 is required) and manufacturer name."""
    if not flags & 1 or flags >> len(FLAG_VALUES):
        raise ValueError('invalid PC_MFR_ID flags')
    h = manufacturer_hash(manufacturer)
    value = sum(v for i, v in enumerate(FLAG_VALUES) if flags >> i & 1)
    digits = [''] * 13
    for pos, d in zip(HASH_DIGITS, '%08X' % h):
        digits[pos] = d
    for pos, d in zip(FLAG_DIGITS, '%05X' % ((value + (h & 0xFFFF)) & 0xFFFFF)):
        digits[pos] = d
    return ''.join(digits)
