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
| 63 to the end of the first cylinder(s) | Partition 1, type `0x12`, FAT12, labels `DIAGS` / `DIAGSETUP` (below): Compaq Diagnostics |
| next cylinder boundary onwards | Partition 2, type `0x06`, active, FAT16, label `PRESARIO`: C: |

**Partition type 0x12** is Compaq's "system partition". DOS and Windows don't recognise
the type, so they never give it a drive letter. On a real Compaq the BIOS boots it when
you press **F10** at the blinking cursor in the top-right corner during the memory count.
It contains its own DOS, `TEST.COM` as the shell, Compaq Diagnostics 10.06C and
**Computer Setup** (`SETUP.EXE`). These Presarios keep their BIOS setup program on the
disk rather than in ROM.

**Compaq's marks on the diagnostics partition.** Before the Compaq Utilities touch the
partition they run `PARTABLE.EXE`, which reads the partition's boot sector and insists on
`EISA` in the serial-number field (offset 0x27) and `DIAGS` as the boot-sector label.
Anything else makes it exit with code 0xF6, and the Utilities report "There is a problem
with the Diagnostics Partition" and refuse to make diagnostics diskettes. `DOD.EXE`
separately checks the root-directory label, which its own installer sets to `DIAGSETUP`
after copying the second (Setup) diskette. QuickRestore wrote neither mark, so the tool
writes `EISA` + `DIAGS` in the boot sector and `DIAGSETUP` in the root directory, as a
partition made by Compaq's own tools has.

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

**Pre-filling the wizard.** Each time PISETUP starts it copies `PISETUP.INF` to
`C:\WINDOWS\INF\MSBATCH.INF` and reads its answers from there. `build --user/--company`
sets `Username=` and `Company=` in its `[userinfo]` section, which the INF documents for
pre-filling the first page. `--coa` sets the undocumented `COANUMBER=`, which PISETUP puts
in the Certificate of Authenticity box, but only if the `[Settings]` `PC_MFR_ID` allows it.

That ID is what Microsoft's `OEM_ID.EXE` produced for each manufacturer: 8 of its 13 hex
digits must equal a weighted sum of the characters of `Manufacturer=` in
`WINDOWS\SYSTEM\OEMINFO.INI`, and the other 5 encode a set of feature flags (see
`oemid.py`). Compaq's `21B80F15D0DA6` has flags 0, 2 and 5; flag 3 keeps a pre-loaded COA
number. With `--coa` the tool decodes Compaq's ID and re-encodes it with flag 3 added
(`21E60F18D02A6`), leaving the other flags alone. The flags this PISETUP tests:

| Flag | Allows |
|---|---|
| 0 | the ID at all (required) |
| 1 | the `SelectWindowsVerDialogs` / `DualInstall2` options (choosing between preinstalled Windows versions) |
| 2 | `Win95Install` mode, which skips the version, language, keyboard, regional and hardware-detection pages |
| 3 | keeping a pre-loaded `COANUMBER=` |
| 4 | `BatchInstall` mode, which also skips the "Configuring the computer" and "Finish" pages |

Flags 1, 2 and 4 only permit the INF option; Compaq's INF sets none of those options.
Compaq's flag 5 isn't tested anywhere in PISETUP, and 6-15 are unused.

**Checking the COA number.** On the COA page PISETUP drops dashes and spaces, re-inserts
them as 5-3-7-5, and calls `PIDVALIDATE` in its `SETUPX.DLL` with product type 8 (OEM).
That accepts `DDDYY-OEM-0NNNNNN-NNNNN` where `DDD` is a day 001-366, `YY` is 95-99 or
00-02, `OEM` may be in any case, the 7-digit block starts with 0, ends in 1-7 and its
digits add up to a multiple of 7, and the last block is 5 digits. `--coa` applies the
same rules, so a mistyped number stops the build instead of the first boot.

## The diagnostics diskettes

`diskettes` rebuilds the two 1.44 MB diskettes that the Compaq Utilities' "Create a
Diagnostics Diskette" writes, by replaying what `DOD.EXE` does, from the CD's `DIAGS`
archive:

1. `FMT.COM` formats each diskette. Its boot sector exists on the CD only inside the
   PKLITE-packed `FMT.COM`, so the tool unpacks it (`pklite.py` is a port of PKLITE's own
   decompressor stub). The serial field is `EISA`; the boot-sector label is `DIAGS`, or
   `DIAGSETU.P` on the SETUP diskette (DOD hands FMT its 8.3 spelling of DIAGSETUP).
2. **DIAGNOSTICS:** `DFC.EXE` copies the files named in `DIAGDSK1.IN`, then only the first
   entry of `DIAGMSG1.IN` (`-S`); `ONELANGF.EXE` then writes one-language copies of
   `MSGDATA`, `DD_MSG` and `DOD_MSG` so that everything fits.
3. **SETUP:** `DFC` copies `DIAGDSK2.IN`, then all of `DIAGMSG2.IN` (full message files).
4. `DOD` adds the volume label (`DIAGS` / `DIAGSETUP`) and stamps every `.COM`/`.EXE`
   directory entry with a checksum at offset 0x14: the byte-swapped complement of the sum
   of its time, date and the two halves of its size.

Files are placed the way DOS 6 places them: a new file takes the first free directory
entry, an existing one (`LANGFILE` is copied twice onto SETUP) is truncated in place, and
clusters are allocated after the last one handed out, which leaves the same one-cluster
hole the real SETUP diskette has.

Checked against a pair made by a real Presario 9548: every byte matches except file
slack, the unused tail of each file's last sector. DOS filled that from whatever was in
its buffers, so it can't be derived from the CD; the tool writes zeros there. The labels
and trimmed message files carry the time the diskettes were made; the tool uses the
diagnostics' own file date unless given `--date`.

## Verification

`verify` (also run automatically after `build`) reads the image back with its own FAT
reader and checks the partition table, that both FAT copies match, and that every
file's attributes, size and contents match the archives, with no files missing or extra.
It also checks that every directory is plain `0x10`.

Builds are deterministic: the same CD, model and disk size always give a byte-identical
image. `tests/test_cd.py` pins the expected SHA-256 for each model on a 4 GB CF card,
including the 9548 image that was booted on real hardware.
