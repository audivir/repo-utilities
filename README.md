# repo-utilities

Build and sign package repositories for `apt`, `brew`, `chocolatey`, and `conda`. Provides both
a library and standalone CLIs for building `apt` and `brew` repositories.

# Prerequisites

- Python 3.10 or newer
- `git`
- GnuPG (`gpg`) for signing `apt` repositories
- A `conda`-based environment with `mono` and `chocolatey` installed under `$CONDA_PREFIX` for
  Chocolatey packaging
- Playwright browsers (`playwright install`) for downloads that require a headless browser

# Installation

```bash
pip install git+https://github.com/audivir/repo-utilities
```

# Usage

As a library:

```python
import repo_utilities
```

As standalone CLIs:

```bash
build-apt-deb --help
build-apt-repo --help
build-apt-meta --help
build-brew-tap --help
```

# License

MIT, see `LICENSE`.
