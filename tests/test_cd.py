"""End-to-end tests against the real CD. Skipped unless QRST_ISO points at CPQQRS73101.ISO.

    QRST_ISO=/path/to/CPQQRS73101.ISO python -m unittest -v
"""
import hashlib
import os
import tempfile
import unittest

from compaq_qrst.build import build_image
from compaq_qrst.cd import QuickRestoreCD
from compaq_qrst.fat import FatReader
from compaq_qrst.verify import verify_image

ISO = os.environ.get('QRST_ISO')
CF_4GB = 7_962_192          # the 4 GB CF card the 9548 image was hardware-tested on

# Images for a 7,962,192-sector disk. The 9548 image was booted on a real Presario 9548.
EXPECTED = {
    '5528': '39e92b61152af344d812f3878320ec61fd7bbcab5132a9a6e013344cc1698451',
    '9546': 'c80a7db2353819be94e12d24be4bedd137c78cf4b26a2979d5405a1a0d0ab259',
    '9548': 'a3fa10729aad411b91822cd2c0d50578a442c424f5903ca40d13be29e24c48a1',
    '9564': '69591534cab8484b06c70cf1217fd64759e60b76ec9a4a7622d36d200c9b30a3',
}


@unittest.skipUnless(ISO, 'set QRST_ISO to the CPQQRS73101 CD image')
class CdTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cd = QuickRestoreCD(ISO)
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.cd.close()
        cls.tmp.cleanup()

    def test_models(self):
        self.assertEqual([m.model for m in self.cd.models], sorted(EXPECTED))
        m = self.cd.find_model('9548')
        self.assertEqual((m.sku, m.archive_stem, len(m.c_drive)), ('213950-007', 'FERMSABR', 50))

    def test_images_are_reproducible(self):
        for model, digest in EXPECTED.items():
            with self.subTest(model=model):
                out = os.path.join(self.tmp.name, f'{model}.img')
                build_image(self.cd, self.cd.find_model(model), out, CF_4GB)
                with open(out, 'rb') as f:
                    self.assertEqual(hashlib.sha256(f.read()).hexdigest(), digest)

    def test_verify_catches_archive_bit_directory(self):
        """The bug that broke PISETUP (error 5018) must be caught by verify."""
        m = self.cd.find_model('9548')
        out = os.path.join(self.tmp.name, 'bad.img')
        build_image(self.cd, m, out, CF_4GB)
        self.assertEqual(verify_image(self.cd, m, out), [])
        with open(out, 'r+b') as f:
            vol = FatReader(f, 8064)
            pisetup = next(c for n, a, c, s, e in vol.entries() if n == b'PISETUP')
            lang = next(c for n, a, c, s, e in vol.entries(pisetup) if n == b'LANG')
            f.seek((vol.data_start + (lang - 2) * vol.spc) * 512)
            block = bytearray(f.read(512))
            for i in range(0, 512, 32):
                if block[i:i + 3] == b'ENG':
                    block[i + 11] = 0x30
            f.seek((vol.data_start + (lang - 2) * vol.spc) * 512)
            f.write(block)
        problems = verify_image(self.cd, m, out)
        self.assertTrue(any('PISETUP/LANG/ENG' in p and '0x30' in p for p in problems), problems)


if __name__ == '__main__':
    unittest.main()
