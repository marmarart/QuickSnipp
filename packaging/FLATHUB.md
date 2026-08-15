# Publishing QuickSnipp on Flathub

Everything below is a one-time setup. After the app is accepted, publishing an
update is just: bump the tag, update the commit in the manifest, push to your
Flathub repo branch.

## 1. Put the code on GitHub

```bash
cd /run/media/idiotwind/Storage/Vladimir/MyOwnApps/QuickSnipp
git init
git add -A
git commit -m "QuickSnipp 1.0.0"
# create the repo at https://github.com/new (name: QuickSnipp, public), then:
git remote add origin git@github.com:marmarart/QuickSnipp.git
git branch -M main
git push -u origin main
git tag v1.0.0
git push origin v1.0.0
```

The metainfo file expects `docs/screenshot.png` to exist on the `main`
branch — it is committed by the step above.

## 2. Install the Flatpak tooling (needs sudo)

```bash
sudo apt install flatpak flatpak-builder
flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
flatpak install -y flathub org.kde.Platform//6.10 org.kde.Sdk//6.10 \
  com.riverbankcomputing.PyQt.BaseApp//6.10
```

## 3. Pinned Python sources — not needed

Flathub policy requires PyQt apps to use the official
`com.riverbankcomputing.PyQt.BaseApp` (see the `baseapp` key in the
manifest) instead of bundling PyQt wheels, and QuickSnipp has no other
Python dependencies. If you ever add one, generate
`python3-requirements.json` with flatpak-pip-generator and list it as the
first module.

## 4. Build and test locally

```bash
flatpak-builder --user --install --force-clean build-dir io.github.marmarart.QuickSnipp.yml
flatpak run io.github.marmarart.QuickSnipp
```

Verify: new snip works (portal capture), copy to clipboard, save to
~/Pictures.

**GNOME permission note:** the first capture inside the sandbox is rejected
by GNOME's portal until the user grants the screenshot permission once:
`flatpak permission-set screenshot screenshot io.github.marmarart.QuickSnipp yes`
(also available as a toggle in GNOME Settings → Apps → QuickSnipp).
QuickSnipp shows these instructions itself if a capture is denied. Expect a
reviewer question about this — link them to this note.

Then remove the build: `flatpak uninstall io.github.marmarart.QuickSnipp`.

## 5. Lint (what the Flathub reviewers run)

```bash
flatpak install -y flathub org.flatpak.Builder
flatpak run --command=flatpak-builder-lint org.flatpak.Builder manifest io.github.marmarart.QuickSnipp.yml
flatpak run --command=flatpak-builder-lint org.flatpak.Builder appstream packaging/io.github.marmarart.QuickSnipp.metainfo.xml
flatpak run --command=flatpak-builder-lint org.flatpak.Builder builddir build-dir
```

Fix anything reported before submitting.

## 6. Submit to Flathub

1. Fork https://github.com/flathub/flathub on GitHub.
2. Clone your fork, create a branch named `io.github.marmarart.QuickSnipp`.
3. Copy into it: `io.github.marmarart.QuickSnipp.yml`, `flathub.json`, and the
   `packaging/` directory (the manifest's `dir` source must be replaced
   with the git source shown commented in the manifest, using your tag and
   full commit SHA).
4. Push and open a pull request titled
   `Add io.github.marmarart.QuickSnipp`.
5. A test build runs automatically (`bot, build` if not). Reviewers usually
   respond within days; typical requests are screenshot tweaks or
   finish-args justification (xdg-pictures is for PNG export).

## After acceptance

Flathub creates the repo `github.com/flathub/io.github.marmarart.QuickSnipp`
and you get write access. The app appears on
https://flathub.org/apps/io.github.marmarart.QuickSnipp within hours, and in
GNOME Software / KDE Discover shortly after.

To ship an update: tag `v1.0.1` in your repo, bump `<release>` in the
metainfo, update `tag`/`commit` in the Flathub repo manifest, push — the
build and publish are automatic.
