# Installation

## Requirements

- Blender 5.2.0 or newer.
- Current prototype target: object Location animation.

## Install a release ZIP

1. Download the latest `editable_motion_paths_*.zip` from GitHub Releases.
2. Open Blender.
3. Go to **Edit → Preferences → Get Extensions**.
4. Open the top-right menu and choose **Install from Disk**.
5. Choose the ZIP.
6. Enable **Editable Motion Paths** if necessary.
7. In the 3D View press `N`, then open the **Motion Path** tab.

The installable ZIP must contain `blender_manifest.toml` and `__init__.py` at its root.

## Upgrade

For prototype builds, prefer a clean upgrade:

1. Save your `.blend`.
2. Open Preferences.
3. Disable/remove the previous Editable Motion Paths version.
4. Install the new release ZIP.
5. Restart Blender if you observe stale UI state after a development build.

## Development install

The repository keeps source under `extension/`.

You can either rebuild and reinstall:

```bash
python scripts/build_extension.py
```

or create a local Blender extension repository and symlink the `extension/` directory into it.

### macOS/Linux symlink example

```bash
ln -s /absolute/path/to/editable-motion-paths/extension /absolute/path/to/local-extension-repo/editable_motion_paths
```

### Windows

Use a directory symbolic link (`mklink /d`) from your local Blender extension repository to the repository's `extension` directory.

Keep your development checkout outside Blender-managed directories so uninstall/repository operations cannot accidentally remove source files.

## Troubleshooting

### The add-on installs but I cannot find it

- Check **Preferences → Add-ons** and search `Editable Motion Paths`.
- In the 3D View press `N` and look for the **Motion Path** tab.
- Confirm the installed ZIP is a release asset, not GitHub's automatically generated “Source code” ZIP.

### The path does not appear

- Select an object.
- Insert at least two Location keyframes.
- Confirm **Trajectory** is enabled in the panel.
- Confirm the selected display mode includes the active object.

### Keys are hard to see

Open **Appearance** and increase:

- Key Size;
- Handle Size;
- Key Outline thickness.

The prototype uses screen-space disk rendering to reduce PC/macOS differences.

### A crash occurs

Please attach the Blender crash log to a GitHub Bug Report and include exact reproduction steps. If possible, provide a minimal `.blend` file that reproduces the crash.
