# compaq-qrst-rebuild

Rebuild a 1995 **Compaq Presario QuickRestore CD** into a bootable raw disk image that you
can write straight to an IDE hard disk or CompactFlash card. The result is the machine
exactly as it left the factory: Windows 95, the Compaq software bundle, and the hidden
Compaq Diagnostics / Computer Setup partition behind **F10**.

Why not just run the CD? Compaq's QuickRestore always formats the *whole* disk as one
FAT16 partition, so on anything larger than about 2 GB it stops with
`BPB: too big for FAT`. It also needs a working CD-ROM drive and boot floppy. This tool
does what QuickRestore did, but sizes the disk correctly and runs on your modern PC.

| CD | Models | Status |
|---|---|---|
| `CPQQRS73101` (Sept 1995) | Presario **5528**, **9546**, **9548**, **9564** | 9548 tested on real hardware (4 GB CF). The other models are built from the same data and checked in an emulator, but haven't been booted on real hardware. |

Other 1995-era Compaq QuickRestore CDs use the same format and may work. The tool reads
everything from the CD itself and warns you that the result is untested.

## Requirements

* Python 3.9 or newer. Nothing else: no packages, no external tools. Works on Windows,
  macOS and Linux.
* The QuickRestore CD image (see below).
* A target disk: the original drive, any IDE disk, or a CompactFlash card in a CF-to-IDE
  adapter.

## 1. Get the CD image

This project contains no Compaq or Microsoft files; everything comes from your copy of
the CD.

1. Log in to archive.org, then open
   [Compaq Presario 9548 Restore CD (1995)](https://archive.org/download/BetaArchive_PC_OS_Recovery_Archive/PC%20OS%20Recovery%20Kits/pre-2006/Compaq%20Presario%209548%20Restore%20CD%20%281995%29/)
   and download **`media_iso.rar`** (258.7 MB).
2. Extract the `.iso` from it with [7-Zip](https://www.7-zip.org/) (Windows) or
   `unrar x media_iso.rar` / `7z x media_iso.rar` (Linux/macOS).

The ISO this tool was tested with has this SHA-256 (the tool checks it for you):

```
9882c0932749825cdf483b31ed2667ebdd5e7419aa6e2c6b3d09523784815808  CPQQRS73101.ISO
```

## 2. Get this tool

Download this repository (green **Code** button, **Download ZIP**, or `git clone`) and open
a terminal in its folder. You can run it in place:

```
python -m compaq_qrst --help          (Windows: py -m compaq_qrst --help)
```

or install it as a command with `pip install .`, after which it's called
`compaq-qrst-rebuild`. The examples below use `python -m compaq_qrst`.

## 3. Pick your model

```
$ python -m compaq_qrst models CPQQRS73101.ISO
CD: CPQQRS73101 - Compaq Presario 5528/9546/9548/9564 QuickRestore (Sept 1995)

Model    SKU          BOM     Archive    Description
5528     214150-009   R2013   EDSNHARR   Presario 5528 MOD 1GB DOM
9546     213950-005   R2014   FERMHARR   Presario 9546 M1GB f/m DOM
9548     213950-007   R2015   FERMSABR   Presario 9548 M1.6G f/m DOM
9564     214050-405   R2016   FERMSAB1   Presario 9564 M1.6G f/m DOM
```

Your model number is on the front of the case; the SKU is on the label on the back. The
images differ only in their model-specific drivers and settings:

| | 5528 | 9546 | 9548 | 9564 |
|---|---|---|---|---|
| Family | 5500 | 9500 | 9500 | 9500 |
| Modem driver | Presario 192 Data+Fax+Voice | Presario 192 | Presario 288 Data+Fax+Voice | Presario 288 |
| Monitor profile | 5500 integrated | Presario 1400 | Presario 1400 | Presario 1400 |
| Factory drive | 1 GB | 1 GB | 1.6 GB | 1.6 GB |

The 9548 and 9564 images are the same build (Compaq's 9564 bill of materials uses the
9548's archive). If you're installing on a machine that isn't one of these Presarios,
Windows will re-detect the hardware on first boot, so any of them will do.

## 4. Build the image

You need the **exact size of the target disk**, because Windows 95's boot code uses the
disk geometry the BIOS reports, and the BIOS works that out from the disk's size.

* **Linux:** let the tool read it: `--size-of /dev/sdX`.
* **Windows:** in PowerShell, run `Get-Disk | Format-Table Number,FriendlyName,Size`, divide
  the card's size by 512, and pass that sector count, e.g. `--size 7962192`.
* **macOS:** `diskutil info /dev/diskN` shows "Disk Size: ... (N Bytes)"; divide by 512.
* Approximate sizes such as `--size 4GB` usually work: only the range matters (for example
  2.1–4.2 GB all get the same geometry), but an exact sector count removes any doubt.

```
python -m compaq_qrst build CPQQRS73101.ISO --model 9548 --size 7962192 -o presario-9548.img
```

The image is built, then read back and compared file by file against the CD. Building
takes a few seconds; the image is about 2 GB for any disk of 2 GB or more.

To have the Windows 95 Setup wizard filled in, add `--user "Your Name"`,
`--company "Your Company"` and `--coa 12395-OEM-0000007-12345` (the number from the
Certificate of Authenticity sticker on the case). The wizard's pages still appear, but
already filled in. Pass the same options to `verify`. The COA number is checked with the
same rules Windows 95 Setup uses, so a mistyped number stops the build instead of being
refused at first boot.

### What you get

| Partition | Contents |
|---|---|
| 1 (type 0x12, ~4 MB) | Compaq Diagnostics 10.06 and Computer Setup, started with **F10** at boot on a real Compaq. Invisible to DOS and Windows. |
| 2 (active, FAT16) | Windows 95 (4.00.950) and the Compaq software, as large as the disk allows up to **2 GB**, the FAT16 limit for Windows 95. |

On a disk larger than about 2 GB the rest is left unpartitioned; you can add a D: drive
later with FDISK.

## 5. Write the image

The image is a whole-disk image: write it to the start of the disk, not to a partition.
**Double-check the target: this erases the disk.**

* **Windows:** [Win32 Disk Imager](https://sourceforge.net/projects/win32diskimager/):
  choose the image and the card's drive letter, then **Write**. ([Rufus](https://rufus.ie/)
  also works, but hides card readers unless you tick "List USB Hard Drives".)
* **Linux:** `sudo dd if=presario-9548.img of=/dev/sdX bs=4M conv=fsync status=progress`
* **macOS:** `sudo dd if=presario-9548.img of=/dev/rdiskN bs=4m` (unmount the disk first with
  `diskutil unmountDisk /dev/diskN`).

To check the card afterwards (Linux):
`sudo python -m compaq_qrst verify CPQQRS73101.ISO /dev/sdX --model 9548`

## 6. First boot

Set the disk to **Auto** or **LBA** in the BIOS, then boot. Expect this sequence; it is
Compaq's factory "first customer boot", and it needs a couple of restarts:

1. **First boot:** Windows starts, puts back the long file names, and runs Compaq's
   welcome program: a video tour and an offer to register. Quit when you're done.
2. **Next boot:** the **Windows 95 Setup Wizard** asks for your name, the licence
   agreement, and the **Certificate of Authenticity number** from the Microsoft sticker
   on the case. It then installs devices and restarts.
3. **After that:** the normal Windows 95 desktop.

The first boot is slower than usual. Remove any floppy disk before Setup restarts.

## 7. Diagnostics diskettes (optional)

The Compaq Utilities can back the diagnostics partition up onto a DIAGNOSTICS and a SETUP
diskette. The tool builds the same pair from the CD, so you can make them without a
working partition:

```
python -m compaq_qrst diskettes CPQQRS73101.ISO -o diskettes
```

This writes `diskettes/DIAGNOSTICS.img` and `diskettes/SETUP.img`. `--language` picks the
language of the DIAGNOSTICS diskette's messages (English, French, German, Italian or
Spanish; the default is English). Write each image to a 1.44 MB diskette, for example
`sudo dd if=diskettes/DIAGNOSTICS.img of=/dev/fd0 bs=18k` on Linux, or
`gw write --format ibm.1440 diskettes/DIAGNOSTICS.img` with a Greaseweazle. Boot from the
DIAGNOSTICS diskette; it asks for SETUP when it needs it.

## Troubleshooting

See [docs/troubleshooting.md](docs/troubleshooting.md): no boot / "Missing operating
system", geometry overrides, F10 not working, and running the image in an emulator.

## How it works

See [docs/how-it-works.md](docs/how-it-works.md) for the CD format (Compaq's scrambled
PKZIP archives), the disk layout, and the details that matter for getting a clean first boot.

## License

MIT; see [LICENSE](LICENSE). Compaq, Presario and QuickRestore are trademarks of HP;
Windows is a trademark of Microsoft. This project is not affiliated with either and
distributes none of their files.
