# Snap package (experimental)

This is a **classic** snap so Snip and Video can use GNOME Mutter ScreenCast
the same way the native `./run.sh` app does. A strict (sandboxed) snap cannot
talk to those compositor APIs reliably — that is why Flameshot and others
struggle on Ubuntu Wayland.

Classic snaps **do not auto-approve** on the Snap Store. Canonical reviews
them by hand. Until that happens, distribute the `.snap` from GitHub and
install with `--dangerous`.

## Build on your PC

```bash
sudo snap install snapcraft --classic
sudo snap install lxd
sudo lxd init --auto          # once
snapcraft                     # from the QuickSnipp repo root
```

On an **Intel or AMD** PC that produces `quicksnipp_1.2.0_amd64.snap`.
On a **Raspberry Pi 5 / ARM laptop** it produces `quicksnipp_1.2.0_arm64.snap`.
You cannot mix them: an amd64 snap will not run on a Pi.

| Machine | Snap file | Same chip? |
|---|---|---|
| Intel laptop/desktop | `*_amd64.snap` | Yes — Intel and AMD both use amd64 |
| AMD laptop/desktop | `*_amd64.snap` | Same file as Intel |
| Raspberry Pi 5, ARM phones/SBCs | `*_arm64.snap` | Different CPU — needs its own build |

## Install (Linux with snapd)

Intel/AMD:

```bash
sudo snap install --classic --dangerous quicksnipp_1.2.0_amd64.snap
```

Raspberry Pi 5 (64-bit OS):

```bash
sudo snap install --classic --dangerous quicksnipp_1.2.0_arm64.snap
```

Then: `quicksnipp`

`--dangerous` is required for a locally built / GitHub-built snap that is
not signed by the store. `--classic` is required for screen capture.

Remove:

```bash
sudo snap remove quicksnipp
```

## GitHub Actions

The workflow `.github/workflows/snap.yml` builds the snap on Ubuntu 24.04.
Run it from **Actions → Build snap → Run workflow**, then download the
artifact and install as above.

## Snap Store (later)

1. [Create a Snapcraft account](https://snapcraft.io)
2. `snapcraft login`
3. `snapcraft register quicksnipp`  (or another name if taken)
4. Open a thread on the [Snapcraft forum](https://forum.snapcraft.io) asking
   for **classic confinement** (screen recording / screenshot tool).
5. After they grant it: `snapcraft upload --release=edge quicksnipp_*.snap`

Until classic is granted, `snapcraft upload` of this snap will be held.

## Why not strict?

On GNOME 47+ the silent screenshot API is blocked. QuickSnipp captures a
still frame and records video through **Mutter ScreenCast + PipeWire +
GStreamer**. Strict snaps cannot reach `org.gnome.Mutter.ScreenCast` or
host PipeWire the way the native app does. Strict would ship a window that
cannot snip or record on Ubuntu GNOME — the main target.
