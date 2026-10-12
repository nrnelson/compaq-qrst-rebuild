# Troubleshooting

## Nothing boots / "Missing operating system" / "Invalid partition table"

Windows 95 boots using the disk geometry the BIOS reports, and the image is built for one
particular geometry (printed by `build` as "geometry N heads x 63 sectors").

1. In the BIOS, set the drive type to **Auto** with **LBA** translation (not "Normal"/CHS
   or "Large").
2. Make sure you built for the size of *this* disk (`--size` / `--size-of`). Card sizes
   vary even within the same nominal capacity.
3. If it still won't boot, look at the drive geometry the BIOS shows, and rebuild with that
   head count:

   ```
   python -m compaq_qrst build CPQQRS73101.ISO -m 9548 --size 7962192 --heads 255 -o presario.img
   ```

   `--heads` accepts 16, 32, 64, 128 or 255.

## The BIOS reports the disk as smaller than it is, or hangs at POST

Many 1995 BIOSes can't handle disks over 2.1 GB (4096 cylinders), and some hang when they
find one. If yours shows a smaller size, build with `--size` set to what the BIOS reports
(for example `--size 2.1GB`), or use a smaller card. Windows 95 can't use more than 2 GB for
C: anyway.

## "Control Module Error ... 5018 (0x139a)" during Windows 95 Setup

The Setup Wizard couldn't find its language files because a directory on C: has the
wrong attribute. Images built by this tool don't have this problem (`verify` checks for
it). If you copied the files to a disk some other way, make sure no directory under
`C:\PISETUP\LANG` has its Archive bit set (`attrib -a` on the folders from DOS). See
[how-it-works.md](how-it-works.md#reproducing-pkunzip-faithfully).

## Setup asks for a Certificate of Authenticity number

That's normal: it's the 25-character number on the Microsoft COA sticker on the case, in
the form `xxxxx-OEM-xxxxxxx-xxxxx`.

## F10 does nothing

The diagnostics partition is only started by a Compaq BIOS. On other machines, or in
emulators, it's harmless and stays invisible.

## "There is a problem with the Diagnostics Partition"

Images built before this was fixed lack the marks Compaq's tools leave on the
diagnostics partition (see [how it works](how-it-works.md#the-disk-layout)). Computer
Setup still works, but the Compaq Utilities show this warning and "Create a Diagnostics
Diskette" fails. Rebuild the image; `verify` reports an image without the marks. To fix a
written disk in place, partition 1's boot sector needs `EISA` at offset 0x27 and the label
`DIAGS` at 0x2B, and its root-directory label entry `DIAGSETUP`.

## Hardware errors on a non-Compaq machine or in an emulator

The image is configured for the Presario's own hardware (S3 Trio64V+ video, ESS ES1788
sound, Compaq/Tamarack modem with MediaPilot telephony software). Elsewhere you may see:

* "This program has performed an illegal operation" from **Msgsrv32** or **Cpqdmn**: the
  MediaPilot modem drivers (`MEDIAPLT\TAMAUDIO.DRV`, `cpq_dmn.exe`) not finding the modem.
* "Your display adapter is not configured properly", or Compaq's welcome program saying
  it needs 256 colours: a different video card.
* "Setup detected a disk in your floppy drive" when the Setup Wizard restarts: some
  emulated floppy controllers report media even when empty.

None of these mean the image is damaged. On a non-Presario machine, let Windows install
drivers for your hardware, and remove the MediaPilot entries (`wave1=`/`aux1=` in
`SYSTEM.INI`, `run=` in `WIN.INI`) if you have no Compaq modem.

## Verifying a disk you've already written

On Linux:

```
sudo python -m compaq_qrst verify CPQQRS73101.ISO /dev/sdX --model 9548
```

This only works before the first boot; Windows changes files as soon as it starts.

## Using a larger disk

The tool fills C: up to 2 GB and leaves the rest unpartitioned. Windows 95 RTM can't make
a larger partition, but you can add an extended partition with logical drives (D:, E:, ...)
in the remaining space using FDISK once Windows is installed.
