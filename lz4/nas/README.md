# LZ4 Compression on a NAS

This runs the whole LZ4 Compression engine on your NAS. Nothing is installed
on or runs on the PS5. You open the same web page from a PC or phone at
`http://<NAS IP>:5920`, and it works on game folders stored on the NAS. Copy
the finished games to the console however you normally do.

It is the same engine as the PS5 payload, built for Linux. The packer, the
`.ffpfsc` compressor, verification and the web page are all shared code. Only
the parts that talk to the console itself are swapped out (see
[What's different from the PS5 version](#whats-different-from-the-ps5-version)).

## Install with Docker (Synology, QNAP, Unraid, TrueNAS, any Linux box)

1. Copy this repository to the NAS, or clone it there.
2. Edit `nas/docker-compose.yml`:
   - Change `/volume1/PS5/games` to the share that holds your games. Use one
     folder per game, like the PS5's `homebrew` folder, or `.exfat` /
     `.ffpfs` / `.ffpfsc` images.
   - Set `PUID` and `PGID` to your NAS user (`id <user>` over SSH) so the
     files it writes stay editable over SMB/NFS.
3. Start it:

   ```sh
   docker compose -f nas/docker-compose.yml up -d --build
   ```

4. Open `http://<NAS IP>:5920`.

On Synology you can also do this in Container Manager: **Project → Create**,
point it at the repository folder and pick `nas/docker-compose.yml`.

### Folders

| Container path              | What it is                                     | Shown in the page as |
| --------------------------- | ---------------------------------------------- | -------------------- |
| `/data/homebrew`            | Your game library (required)                   | Internal SSD         |
| `/mnt/ext0/homebrew`        | Optional second library and copy/move target   | External SSD         |
| `/mnt/usb0` … `/mnt/usb7`   | Optional more targets                          | USB 0 … USB 7        |
| `/data/LZ4Compression`      | Settings, history, logs, uploaded TOML profiles | -                    |
| `/data/LZ4Compression/import` | TOML profiles for **Import From Console**    | -                    |

The labels come from the PS5 layout the engine was written for. On the NAS
they are simply the folders you mounted.

Games under 2 GiB are treated as apps and hidden from the library, the same
as on the PS5.

## Build without Docker

On any Linux machine with `gcc`, `make` and `python3`:

```sh
make -f nas/Makefile
sudo mkdir -p /data/homebrew
sudo mount --bind /path/to/your/games /data/homebrew
sudo ./build/nas/lz4-compression
```

The engine expects the PS5 paths above, so bind-mount your folders there. It
keeps its settings in `/data/LZ4Compression`.

## What's different from the PS5 version

- **No console integration.** The engine has no PS5 to talk to, so there are
  no PS5 notifications (they go to the log), no home screen tile, no Payload
  Manager, no closing a running game and no ShadowMountPlus. Jobs finish
  with the result `not-mounted`, which means "done; the console hasn't
  mounted it yet". ShadowMountPlus picks the game up once it's on the
  console.
- **LZ4 packs are fully checked on the NAS.** Packing, the byte-for-byte check
  against the original files, `Verify LZ4 Packs` and `Uncompress LZ4` don't
  need the console.
- **`.ffpfsc` compression always keeps the original.** On the PS5, after
  compressing, the engine reads the image back through the console's own
  PFSC driver and patches any block the console would decode differently
  (**Validate & Repair**). That needs a PS5, so on the NAS the `.ffpfsc` is
  built but the original is never deleted, whatever you pick under
  **Original handling** (the log notes it). Delete the original yourself once
  the game runs. LZ4 packs don't have this limitation: every packed file is
  checked byte for byte on the NAS before anything is removed, so
  **Delete after verified** and **Pack in place** work as usual.
- **`.exfat` images** have to be mounted to be read. On the NAS that uses a
  Linux loop mount, which needs a privileged container (`privileged: true`,
  `PUID=0`) and exFAT support in the NAS kernel (Linux 5.7 or later). Folder
  games never need this, so converting images to folders first is easiest.
- **Other copies of the same game aren't renamed during a job.** On the PS5
  the engine hides duplicates so ShadowMountPlus mounts the right one. That
  isn't needed on a NAS, so your folders are left alone.

## Updating

```sh
git pull
docker compose -f nas/docker-compose.yml up -d --build
```

Restarting during a job is safe in the same cases as on the PS5: the engine
resumes or cleans up interrupted work when it starts.
