# Release Process

## 1. Freeze scope

Before a public release, stop adding unrelated features. Fix release-blocking bugs first.

## 2. Update version

Keep these in sync:

- `extension/blender_manifest.toml` → `version`;
- `extension/__init__.py` → `bl_info["version"]`;
- `CHANGELOG.md`;
- README compatibility/status text when needed.

## 3. Static check

```bash
python -m py_compile extension/__init__.py
```

## 4. Build

```bash
python scripts/build_extension.py
```

Open the generated ZIP and verify its root contains:

```text
__init__.py
blender_manifest.toml
```

## 5. Clean install test

Test the generated ZIP, not only a development symlink.

At minimum:

- install;
- enable;
- restart Blender;
- create a fresh animated cube;
- edit key;
- edit handle;
- Alt-click;
- Alt-drag;
- Undo/Redo;
- disable/re-enable extension;
- uninstall/reinstall.

## 6. Run QA matrix

Run [Testing](TESTING.md) on the platforms available to you. Record PASS/FAIL and open issues for failures.

## 7. Tag and release on GitHub

Recommended tag format:

```text
v0.9.4
```

Attach the installable ZIP as a GitHub Release asset. Do not tell users to install GitHub's automatically generated repository source ZIP.

## 8. Release notes

Include:

- one-sentence value proposition;
- what's new;
- compatibility;
- known limitations;
- installation link;
- feedback link;
- short demo GIF/video.

## 9. Post-release

For the first days after release:

- triage reproducible crashes first;
- label platform-specific bugs;
- ask for minimal `.blend` files;
- avoid changing multiple interaction rules in one hotfix unless necessary.
