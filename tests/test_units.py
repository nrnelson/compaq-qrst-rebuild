"""Unit tests that need no QuickRestore CD (synthetic archives and boot sectors)."""
import io
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
import zipfile

from compaq_qrst import disk, diskettes, oemid, qrzip, userinfo
from compaq_qrst.fat import ATTR_DIR, FatReader, FatWriter, tree_from_archives

SFX_STUB = b'MZ' + bytes(510)


def make_zip(entries):
    """entries: [(name, data_or_None_for_dir, dos_attr)] -> a zip with an SFX-style stub."""
    buf = io.BytesIO()
    buf.write(SFX_STUB)
    with zipfile.ZipFile(buf, 'a', zipfile.ZIP_DEFLATED) as z:
        for name, data, attr in entries:
            zi = zipfile.ZipInfo(name, (1995, 9, 16, 12, 0, 0))
            zi.create_system = 0
            zi.external_attr = attr
            z.writestr(zi, b'' if data is None else data)
    return buf.getvalue()


def boot_template():
    b = bytearray(512)
    b[0:3] = b'\xeb\x3c\x90'
    b[3:11] = b'TESTBOOT'
    b[510:512] = b'\x55\xaa'
    return bytes(b)


class QrZipTest(unittest.TestCase):
    def test_roundtrip(self):
        plain = make_zip([('IO.SYS', b'x' * 1000, 0x27), ('DIR/', None, 0x30),
                          ('DIR/FILE.TXT', b'hello', 0x20)])
        scrambled = qrzip.encode(plain)
        self.assertNotIn(b'PK\x01\x02', scrambled)
        self.assertEqual(qrzip.decode(scrambled), plain)
        z = qrzip.open_archive(scrambled)
        self.assertEqual(z.read('DIR/FILE.TXT'), b'hello')

    def test_rejects_plain_garbage(self):
        with self.assertRaises(qrzip.QrZipError):
            qrzip.decode(b'MZ' + bytes(100))


class DiskTest(unittest.TestCase):
    def test_lba_assisted_heads(self):
        for sectors, heads in [(1_000_000, 16), (1_056_384, 32), (2_100_000, 64),
                               (3_173_184, 64), (7_962_192, 128), (16_000_000, 255)]:
            self.assertEqual(disk.lba_assisted_heads(sectors), heads, sectors)

    def test_plan_4gb_cf(self):
        L = disk.plan(7_962_192)
        self.assertEqual((L.heads, L.diag_start, L.diag_sectors), (128, 63, 8001))
        self.assertEqual((L.c_start, L.c_sectors, L.c_cluster_sectors), (8064, 4_193_280, 64))
        self.assertLessEqual(L.c_sectors // 64, 65524)

    def test_plan_small_disk_uses_whole_cylinders_for_diags(self):
        L = disk.plan(3_173_184)                       # 1.6 GB factory drive
        self.assertEqual(L.heads, 64)
        self.assertGreaterEqual(L.diag_sectors, disk.DIAG_MIN_SECTORS)
        self.assertEqual(L.c_start % L.cylinder, 0)

    def test_parse_size(self):
        self.assertEqual(disk.parse_size('7962192'), 7962192)
        self.assertEqual(disk.parse_size('4GB'), 4 * 10 ** 9 // 512)
        self.assertEqual(disk.parse_size('2GiB'), 2 ** 31 // 512)
        with self.assertRaises(ValueError):
            disk.parse_size('lots')

    def test_mbr_chs(self):
        self.assertEqual(disk.chs(63, 128, 63), bytes([1, 1, 0]))
        self.assertEqual(disk.chs(8064, 128, 63), bytes([0, 1, 1]))


class FatTest(unittest.TestCase):
    def build(self, fat12, nsectors, spc, entries):
        z = zipfile.ZipFile(io.BytesIO(make_zip(entries)))
        fd, path = tempfile.mkstemp()
        os.close(fd)
        self.addCleanup(os.remove, path)
        with open(path, 'w+b') as img:
            img.truncate(nsectors * 512)
            w = FatWriter(img, 0, nsectors, spc, fat12, boot_template(), b'TEST', 0x1234, 16, 63)
            w.populate(tree_from_archives([z]))
        return path, z

    def check(self, fat12, nsectors, spc):
        entries = [('README.TXT', b'r' * 3000, 0x20), ('IO.SYS', b'i' * 5000, 0x27),
                   ('MSDOS.SYS', b'm' * 1700, 0x27), ('LANG/', None, 0x30),
                   ('LANG/ENG/OLANG.INF', b'[Languages]\r\nName=English\r\n', 0x20),
                   ('SYSTEM.SAV/', None, 0x32), ('EMPTY.DAT', b'', 0x20)]
        path, z = self.build(fat12, nsectors, spc, entries)
        with open(path, 'rb') as f:
            vol = FatReader(f, 0)
            root = [n for n, *_ in vol.entries()]
            self.assertEqual(root[:3], [b'IO.SYS', b'MSDOS.SYS', b'TEST'])
            found = {p: (a, c, s) for p, a, c, s, _ in vol.walk()}
            for p, (attr, cluster, size) in found.items():
                if attr & ATTR_DIR:
                    self.assertEqual(attr, ATTR_DIR, f'{p} must be a plain 0x10 directory')
                else:
                    data = vol.read_chain(cluster, size) if size else b''
                    self.assertEqual(data, z.read(p.decode()), p)
            self.assertEqual(found[b'IO.SYS'][0], 0x27)
            self.assertEqual(found[b'IO.SYS'][1], 2, 'IO.SYS must start at the first cluster')
        if shutil.which('fsck.fat'):
            r = subprocess.run(['fsck.fat', '-n', path], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_fat12(self):
        self.check(True, 8001, 2)

    def test_fat16(self):
        self.check(False, 70_000, 4)

    def test_later_archive_overwrites(self):
        a = zipfile.ZipFile(io.BytesIO(make_zip([('A.TXT', b'old', 0x20)])))
        b = zipfile.ZipFile(io.BytesIO(make_zip([('A.TXT', b'new', 0x21)])))
        tree = tree_from_archives([a, b])
        node = tree.children[b'A.TXT']
        self.assertEqual((node.source[0].read(node.source[1]), node.attr), (b'new', 0x21))


if __name__ == '__main__':
    unittest.main()


class DisketteTest(unittest.TestCase):
    @staticmethod
    def message_file(blobs):
        """A DOD_MSG-style file: 11 language slots of (count, offset, ulen, clen), then data."""
        hdr, data = bytearray(diskettes.MSG_HEADER), b''
        for k, blob in enumerate(blobs):
            struct.pack_into('<HIHH', hdr, 10 * k, 3, diskettes.MSG_HEADER + len(data),
                             len(blob), 0)
            data += blob
        return bytes(hdr) + data

    def test_one_language(self):
        f = self.message_file([b'english', b'francais', b'deutsch'])
        out = diskettes.one_language(f, 'FRENCH', b'DOD_MSG')
        self.assertEqual(out[diskettes.MSG_HEADER:], b'francais')
        self.assertEqual(struct.unpack_from('<HIHH', out, 10), (3, 0x6E, 8, 0))
        self.assertEqual(out[:10] + out[20:diskettes.MSG_HEADER], bytes(diskettes.MSG_HEADER - 10))
        with self.assertRaises(KeyError):
            diskettes.one_language(f, 'SPANISH', b'DOD_MSG')

    def test_rewrite_leaves_hole_like_dos(self):
        fd = diskettes.Floppy(bytes(510) + b'\x55\xaa')
        fd.write(b'A.TXT', b'a' * 600, (1995, 8, 10, 10, 6, 4))     # clusters 2-3
        fd.write(b'B.TXT', b'b', (1995, 8, 10, 10, 6, 4))           # cluster 4
        fd.write(b'A.TXT', b'A' * 10, (1995, 8, 10, 10, 6, 4))      # truncated, moved to 5
        self.assertEqual([e[2] for e in fd.root if e], [5, 4])
        self.assertEqual(fd.fat[2:6], [0, 0, 0xFFF, 0xFFF])

    def test_executable_stamp(self):
        fd = diskettes.Floppy(bytes(510) + b'\x55\xaa')
        fd.write(b'DIAG.EXE', bytes(206066), (1995, 8, 10, 10, 6, 4))
        fd.write(b'DIAG.INF', bytes(488), (1995, 8, 10, 10, 6, 4))
        root = fd.image()[19 * 512:]
        self.assertEqual(root[0x14:0x16], b'\x6b\x3e')     # as on a real DIAGNOSTICS diskette
        self.assertEqual(root[32 + 0x14:32 + 0x16], b'\0\0')


class UserInfoTest(unittest.TestCase):
    INF = (b'[Settings]\r\nPC_MFR_ID=X\r\n\r\n[userinfo]\r\n\r\nDefLang=ENG\r\n\r\n'
           b';Username=\r\n;Company=\r\n\r\n; trailing comment\r\n\r\n[Network]\r\n')

    def test_uncomments_documented_keys(self):
        out = userinfo.patch_inf(self.INF, 'Test User', 'Test Co')
        self.assertIn(b'\r\nUsername=Test User\r\nCompany=Test Co\r\n', out)
        self.assertEqual(out.count(b'['), 3)

    def test_adds_missing_key_after_last_setting(self):
        out = userinfo.patch_inf(self.INF.replace(b';Company=\r\n', b''), company='Co')
        self.assertIn(b'DefLang=ENG\r\nCompany=Co\r\n', out)

    def test_rejects_unsafe_values(self):
        for bad in ('', 'a;b', 'x' * 61, 'café', '[x]'):
            with self.assertRaises(ValueError):
                userinfo.check(user=bad)


class OemIdTest(unittest.TestCase):
    COMPAQ = 'Compaq Computer Corporation'

    def test_decodes_compaqs_id(self):
        self.assertEqual(oemid.manufacturer_hash(self.COMPAQ), 0x10F1D0A6)
        self.assertEqual(oemid.decode('21B80F15D0DA6', self.COMPAQ), 0b100101)
        self.assertEqual(oemid.encode(0b100101, self.COMPAQ), '21B80F15D0DA6')

    def test_coa_flag(self):
        # the ID that made PISETUP keep a pre-loaded COA number in an emulator
        self.assertEqual(oemid.encode(0b101101, self.COMPAQ), '21E60F18D02A6')

    def test_rejects_wrong_manufacturer_and_garbage(self):
        self.assertEqual(oemid.decode('21B80F15D0DA6', 'Other Corp'), 0)
        self.assertEqual(oemid.decode('ZZZ', self.COMPAQ), 0)
        with self.assertRaises(ValueError):
            oemid.encode(0b100, self.COMPAQ)


class CoaTest(unittest.TestCase):
    INF = (b'[Settings]\r\nPC_MFR_ID=21B80F15D0DA6\r\n\r\n[userinfo]\r\n'
           b'DefLang=ENG\r\n;Username=\r\n\r\n[Network]\r\n')

    def test_sets_id_and_number(self):
        out = userinfo.patch_inf(self.INF, coa='12345-OEM-1234567-12345',
                                 manufacturer='Compaq Computer Corporation')
        self.assertIn(b'PC_MFR_ID=21E60F18D02A6\r\n', out)
        self.assertIn(b'DefLang=ENG\r\nCOANUMBER=12345-OEM-1234567-12345\r\n', out)

    def test_refuses_an_id_that_does_not_validate(self):
        with self.assertRaises(ValueError):
            userinfo.patch_inf(self.INF, coa='1', manufacturer='Other Corp')
