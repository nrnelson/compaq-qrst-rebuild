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
    '5528': 'd2c50e36ae2b37b94d2a5e8b746eea1fe4441a3633bb088d4d2b25fb5c02afbe',
    '9546': 'ed7412e9fa527ea3336a0681e15f609b5ef0829dab25c4e509f15e9b2147c2e0',
    '9548': '9b2115bee7265eb5f8b8af2f47ea76767741e21db8f64043c2f6808b072c1843',
    '9564': 'c22932bc5ff88b53bc37fd6f5903c3d76514e4279a472131cadd84cdbeab77bd',
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
