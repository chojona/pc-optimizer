# CI and Windows source releases

**Windows CI** runs on pull requests, pushes to `main`, and manual Actions runs. It creates a fresh virtual environment for each of Python 3.12, 3.13 and 3.14, installs the pinned dependencies, checks dependency compatibility, compiles the code and runs the offline test suite. GUI tests use Qt's offscreen platform; system changes and bulk network traffic are mocked. Each job uploads a JUnit report for seven days.

After all three Python jobs pass, CI builds and verifies a Windows source ZIP and its SHA-256 checksum. Download the `windows-source` artifact from the Actions run; it is retained for fourteen days. The archive includes committed runtime code, UI assets, requirements, launcher, setup script and documentation. The user's database, logs, virtual environment and tests are excluded. Verification checks the checksum, archive paths, required runtime files and Python syntax.

## Publish a release

1. Update `__version__` in `optimizer/__init__.py`, then merge the version change and all release changes to `main` through a reviewed PR.
2. Fetch `main` and choose its intended release commit. Create an annotated tag matching the version, for example `git tag -a v1.0.1 <commit-sha> -m "PC Optimizer 1.0.1"`.
3. Push that tag with `git push origin v1.0.1`.
4. The **Windows release** workflow confirms the tagged commit belongs to `main`, repeats the full CI pipeline, requires the tag to match the application version, and then publishes a GitHub Release with the verified ZIP and checksum. A failed check prevents publication. Existing release assets are not overwritten by reruns.

The package is source with the existing Windows launcher; Python 3.12 or later remains required. Extract it, run `setup.ps1`, then open `Launch-PC-Optimizer.cmd`. To verify a downloaded ZIP, compare `Get-FileHash <archive> -Algorithm SHA256` with the `.sha256` file. Installation and system optimization remain user-initiated.

No deployment credentials need to be stored. Test/build jobs have read-only repository access; only the final tag-triggered publishing job has `contents: write`. Actions are pinned to commit SHAs, and Dependabot checks those pins monthly. Repository administrators can select the three `Windows / Python ...` jobs and the bundle job as required checks in a `main` ruleset. Branch protection is a separate repository setting; these workflows do not change it.

To build from a clean committed checkout locally, use `pwsh -File scripts/build-release.ps1`, followed by `python scripts/verify_release.py dist`. Supply `-Tag v1.0.0` to check a release tag before publishing. Packaging always reads `HEAD`, so commit intended runtime changes first.

Action references: [checkout](https://github.com/actions/checkout), [setup-python](https://github.com/actions/setup-python), [upload-artifact](https://github.com/actions/upload-artifact), [download-artifact](https://github.com/actions/download-artifact), [GitHub release CLI](https://cli.github.com/manual/gh_release_create).
