# Publishing claudown to PyPI

This guide is for maintainers. It explains how to build the package and upload it to [PyPI](https://pypi.org), so users can run `pip install claudown`.

## How the package is laid out

[`pyproject.toml`](pyproject.toml) ships the `scripts/` folder as the importable package `claudown` (`package-dir = { claudown = "scripts" }`). The same files therefore work in three ways: as plain scripts (`python scripts/x.py`), as Claude Code hooks copied to `~/.claude/claudown/`, and as an installed package. Each module tries a package-relative import first and falls back to a plain import.

Console commands created by `pip install`:

| Command | Entry point |
|---|---|
| `claudown` | `claudown.shutdown_orchestrator:main` |
| `claudown-gate` | `claudown.pretooluse_gate:main` |
| `claudown-setup` | `claudown.claudown_setup:main` |
| `claudown-sensor` | `claudown.statusline_sensor:main` |
| `claudown-vscode-sensor` | `claudown.vscode_transcript_sensor:main` |
| `claudown-web-watcher` | `claudown.web_limit_watcher:main` |
| `claudown-listener` | `claudown.local_webhook_listener:main` |

The package has no runtime dependencies; it uses the standard library only.

## One-time setup

1. Create accounts on [PyPI](https://pypi.org/account/register/) and [TestPyPI](https://test.pypi.org/account/register/), and enable two-factor authentication. PyPI requires it for uploads.
2. Create an **API token** on each site (*Account settings → API tokens*). The first upload needs an account-wide token. After the project exists, replace it with a token scoped to `claudown` only.
3. Install the tools:
   ```bash
   python -m pip install --upgrade build twine
   ```
4. Optionally, save the tokens in `~/.pypirc` so you don't paste them each time. **Never commit this file.**
   ```ini
   [pypi]
   username = __token__
   password = pypi-AgEIcHlwaS5vcmc...

   [testpypi]
   repository = https://test.pypi.org/legacy/
   username = __token__
   password = pypi-AgENdGVzdC5weXBp...
   ```
   Without the file, twine prompts you: enter `__token__` as the username and the token as the password. On Windows, don't paste the token with Ctrl+V at that prompt. Set it for the current terminal window instead:
   ```powershell
   $env:TWINE_USERNAME = "__token__"
   $env:TWINE_PASSWORD = "pypi-AgEIcHlwaS5vcmc..."     # PowerShell
   ```
   ```bat
   rem Command Prompt (cmd)
   set TWINE_USERNAME=__token__
   set TWINE_PASSWORD=pypi-AgEIcHlwaS5vcmc...
   ```

## Release checklist

1. **Run the tests.** Everything must pass:
   ```bash
   python -m pytest -q
   ```
2. **Bump the version** in **both** places, which must match:
   - `version` in `pyproject.toml`
   - `VERSION` in `scripts/claudown_common.py` (also `__version__` in `scripts/__init__.py` and `version` in `vscode_bridge_extension/package.json`)

   PyPI never accepts the same version twice, even after you delete a release.
3. **Clean old builds** so you don't upload stale files:
   ```bash
   rm -rf dist build *.egg-info          # Windows PowerShell: Remove-Item -Recurse -Force dist, build
   ```
4. **Build** the source archive and the wheel:
   ```bash
   python -m build
   ```
   This creates `dist/claudown-X.Y.Z.tar.gz` and `dist/claudown-X.Y.Z-py3-none-any.whl`.
5. **Check** the metadata and that the README renders:
   ```bash
   python -m twine check dist/*
   ```
6. **Rehearse on TestPyPI:**
   ```bash
   python -m twine upload --repository testpypi dist/*
   python -m venv /tmp/cd-test && /tmp/cd-test/bin/pip install -i https://test.pypi.org/simple/ claudown
   /tmp/cd-test/bin/claudown --version
   ```
   On Windows, use `\tmp\cd-test\Scripts\pip` and `\tmp\cd-test\Scripts\claudown`.
7. **Upload to the real PyPI:**
   ```bash
   python -m twine upload dist/*
   ```
8. **Tag the release** in git so the code and the package match:
   ```bash
   git tag v0.1.0 && git push origin v0.1.0
   ```

## After publishing

Users install and set up claudown with:

```bash
pip install claudown
claudown-setup            # copies the hooks to ~/.claude/claudown and merges settings.json (DRY RUN)
```

`claudown-setup` writes hook commands that point to the Python that ran it, so the hooks keep working even if pip's scripts folder isn't on PATH.

## Troubleshooting uploads

| Error | Cause |
|---|---|
| `403 Forbidden` / `Invalid or non-existent authentication` | Wrong token, or username isn't `__token__`. |
| `Your password contains control characters`, then `403` | Windows: **Ctrl+V** at twine's hidden password prompt inserts a control character. Use the `TWINE_USERNAME` / `TWINE_PASSWORD` environment variables shown below instead, or paste with a right-click. |
| `400 File already exists` | That version was uploaded before. Bump the version and rebuild. |
| `400 The name 'claudown' is too similar to an existing project` | Someone registered a similar name. Pick another name in `pyproject.toml`. |
| `twine check` fails on the long description | A Markdown construct PyPI can't render. Fix it in `README.md`. |
| `license-files` / `license` errors during build | The build backend needs `setuptools>=77`. `python -m build` installs it automatically in an isolated environment. |
