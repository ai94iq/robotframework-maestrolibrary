# Releasing MaestroLibrary

MIT licensed. Source and issues: https://github.com/ai94iq/robotframework-maestrolibrary. Package: https://pypi.org/project/robotframework-maestrolibrary/

## How a release is published
`.github/workflows/ci.yml` runs the device-free checks on every push and pull request (unit tests
with a coverage gate, bandit, pip-audit, a Robot dry run of `atest`, libdoc, build and
`twine check --strict`). A `vX.Y.Z` tag runs them, then checks that the tag equals `__version__`
and publishes the wheel and sdist to PyPI.

## Turning on publishing (once)
PyPI trusted publishing, no token stored anywhere:
1. On pypi.org, project `robotframework-maestrolibrary` > Settings > Publishing > add a GitHub
   publisher: owner `ai94iq`, repository `robotframework-maestrolibrary`, workflow `ci.yml`,
   environment `pypi`.
2. On GitHub, Settings > Environments > create `pypi` (optionally require a reviewer), and protect
   `v*` tags so only maintainers can push them.

## Releasing
1. Bump `__version__` in `src/MaestroLibrary/__init__.py` and move CHANGELOG's Unreleased entries
   under the new version.
2. Merge to `main`, then `git tag -a vX.Y.Z -m "MaestroLibrary X.Y.Z" && git push origin vX.Y.Z`.

PyPI never accepts the same version twice: a failed or wrong upload needs a new version.
