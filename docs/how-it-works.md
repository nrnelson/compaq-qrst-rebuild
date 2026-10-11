# How it works

This page explains what's on a 1995 Compaq QuickRestore CD and how `compaq-qrst-rebuild`
turns it into a disk image. You don't need any of it to use the tool; it's here for the
curious and for anyone adapting the tool to another CD.

## The CD

```
BOOTDISK/   QRST5.EXE + QUICKRST._01   writes the QuickRestore boot floppy
QUICKRST/   QUICKRST.EXE               the restore program (a Windows 3.1 app)
            MASTER.BOO                 MBR template (standard Microsoft MBR code)
            PRIMARY.BOO                Windows 95 FAT16 boot sector template ("MSWIN4.0")
            SYSTEM.BOO                 FAT12 boot sector template for the diagnostics partition
            QUICKRST.INI
DATABASE/   *.DB                       Paradox tables: SKU -> model, bill of materials
FINAL/      VERC161A/HIDDEN/           Compaq Diagnostics -> hidden partition
            VERC163/UNZIPNOW/          DOS startup files (unpacked first)
            VERC163A/UNZIPNOW/         48 "common" archives: Windows 95 + the software bundle
            VERC163A/UNZIPLTR/         one model-specific archive per model
WINDOWS/    a minimal Windows 3.1 that the boot floppy runs QUICKRST.EXE in
```

The CD does not contain a disk image. QUICKRST.EXE partitions and formats the disk
itself, then unpacks the archives onto it in the order given by the model's bill of
materials. Each model-specific archive carries a copy of that list as
`SYSTEM.SAV\INFO.BOM`:

```
SKU Number:      213950-007
BOM ID:          R2015
File #  1,       RTR PRODUCTION STARTUP FILE VERC163
File #  2,       RTR COMMON ZIP 1 VERC163A
  ...
File # 49,       RTR COMMON ZIP 48 VERC163A
File # 50,       RTR R2015 SKU SPECIFIC VERC163A
File # 51,       RTR QUICKRESTORE US CFG VERC163A
File # 52,       DIAGS PC 10.06 VERC161A
```

The tool reads this list from each model's archive (and the model names from
`DATABASE\SKUMODEL.DB`), so nothing about this particular CD is hard-coded except the
checksum used to recognise it.

## Compaq's scrambled archives

Every `.EXE` in `FINAL\` is a PKZIP self-extractor whose headers were deliberately
scrambled so ordinary unzip tools refuse it:

| Header | Normal | On the CD |
|---|---|---|
| local file header | `PK 03 04` | `JT 04 03` |
| central directory | `PK 01 02` | `TJ 02 01` |
| end of central directory | `PK 05 06` | `TJ 06 05` |

In addition, the *file name length* and *extra field length* fields are swapped in every
local and central header. The compressed data is untouched, ordinary deflate.
`compaq_qrst/qrzip.py` reverses both changes in memory; every file's CRC is then
checked.

## The disk layout

| Sectors | Contents |
|---|---|
| 0 | MBR: Compaq's `MASTER.BOO` code with a new partition table |
| 63 to the end of the first cylinder(s) | Partition 1, type `0x12`, FAT12, label `DIAGSETUP`: Compaq Diagnostics |
| next cylinder boundary onwards | Partition 2, type `0x06`, active, FAT16, label `PRESARIO`: C: |

**Partition type 0x12** is Compaq's "system partition". DOS and Windows don't recognise
the type, so they never give it a drive letter. On a real Compaq the BIOS boots it when
you press **F10** at the blinking cursor in the top-right corner during the memory count.
It contains its own DOS, `TEST.COM` as the shell, Compaq Diagnostics 10.06C and
**Computer Setup** (`SETUP.EXE`). These Presarios keep their BIOS setup program on the
disk rather than in ROM.

**Volume label.** QuickRestore labels the partition `DIAGS`, but the Compaq Utilities
expect `DIAGSETUP`, the label their own installer (`DOD.EXE`) leaves after copying the
second (Setup) diskette. With `DIAGS`, Computer Setup still runs, but "Create a
Diagnostics Diskette" stops with "There is a problem with the Diagnostics Partition", so
the tool writes `DIAGSETUP`.

**Geometry.** Windows 95 RTM boots with CHS-only code: the MBR, the FAT16 boot sector and
IO.SYS all address the disk as cylinder/head/sector. That geometry has to match the BIOS,
so the tool uses the rule BIOSes of the era use for "LBA" translation: 63 sectors per track
and the fewest of 16, 32, 64, 128 or 255 heads that keeps the disk at or under 1024
cylinders. That is why the image depends on the size of the target disk, and why a single
"universal" image can't exist.

**Size of C:.** FAT16 allows at most 65,524 clusters, and Windows 95 can use clusters of
up to 32 KB, which gives about 2 GB. C: is the largest whole number of cylinders that fits
in that (and in the disk). The cluster size follows the table Windows 95's FORMAT uses:
2 KB up to 128 MB, 4 KB to 256 MB, 8 KB to 512 MB, 16 KB to 1 GB, 32 KB above.

**Boot sectors.** Both volumes use Compaq's own templates (`PRIMARY.BOO`, `SYSTEM.BOO`)
with a freshly computed BIOS Parameter Block. `IO.SYS` and `MSDOS.SYS` are the first two
root directory entries and occupy the first clusters, as the DOS/Windows 95 boot code
expects.

## Reproducing PKUNZIP faithfully

Files are written with the 8.3 names, attributes and timestamps stored in the archives,
in restore order, with later archives overwriting earlier ones. That's what QUICKRST.EXE
did. One detail matters a lot:

**Every directory is written as a plain directory (attribute `0x10`).** PKZIP records
directories with the Archive bit set (`0x30`), and a few with Hidden or System. But
PKUNZIP created directories with a plain DOS `mkdir` and never applied those stored bits.
Compaq relied on that: their first-boot script `WINDOWS\WINSTART.BAT` re-applies exactly
the Hidden/System/Read-only bits the archives record (`attrib +h c:\windows\inf`, and so
on).

Getting this wrong is not cosmetic. Microsoft's OEM Preinstall wizard (`C:\PISETUP`, the
Windows 95 Setup that runs on the second boot) looks for language folders with
`findfirst("C:\PISETUP\LANG\*.*", 0x10)` and accepts only entries whose attribute is
**exactly** `0x10`. With the Archive bit set it finds no language and quits with
**"Control Module Error: Exiting with error code = 5018 (0x139a)"**. `verify` checks
every directory's attribute for this reason.

## The first customer boot

The archives restore the disk as it was *before* the customer's first boot. Compaq's
sequence then runs:

1. `AUTOEXEC.BAT` skips PISETUP while `WINDOWS\WINSTART.BAT` exists. Windows runs
   `WINSTART.BAT`, which restores long file names from `C:\LFNBK.DAT` with `LFNBK /r`
   (the archives only hold 8.3 names), sets folder attributes, saves a copy of the
   configuration to `C:\SYSTEM.SAV`, and deletes itself. `SYSTEM.INI` has
   `shell=CPQOOB.EXE`, Compaq's welcome video and registration, which switches the shell
   to Explorer when it finishes.
2. On the next boot `AUTOEXEC.BAT` runs `C:\PISETUP\PISETUP.EXE`, Microsoft's OEM
   Preinstall wizard (in its own tiny copy of Windows 3.1): name, licence, Certificate of
   Authenticity, device installation. When it succeeds it runs `PIPOST.BAT`, whose
   `PRECLEAN` removes the PISETUP lines from `AUTOEXEC.BAT`.

## Verification

`verify` (also run automatically after `build`) reads the image back with its own FAT
reader and checks the partition table, that both FAT copies match, and that every
file's attributes, size and contents match the archives, with no files missing or extra.
It also checks that every directory is plain `0x10`.

Builds are deterministic: the same CD, model and disk size always give a byte-identical
image. `tests/test_cd.py` pins the expected SHA-256 for each model on a 4 GB CF card,
including the 9548 image that was booted on real hardware.
