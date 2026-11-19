# Package FAQ

## Is this `uk_open_data.geo`, and can we keep developing more subpackages?

**Short answer:** `uk-open-data` is the package installed from PyPI, and
`uk_open_data` is the name it is imported by. It includes `uk_open_data.geo`,
`uk_open_data.ons`, `uk_open_data.postcodes`, and `uk_open_data.imd`. Each
subpackage has its own Python import path, but all share one package version
and release.

```bash
uv add uk-open-data
```

```python
from uk_open_data.geo import load_geodata
from uk_open_data.ons import load_ons
```

The package was called `kindtech` up to version 0.1. The `kindtech` project on
PyPI is kept for that name: installing or upgrading it installs the same
version of `uk-open-data`, and code that imports `kindtech` still works and
gives a deprecation warning. `kindtech.geo` is the same module as
`uk_open_data.geo`. Installing `uk-open-data` alone does not add the old import
name.

New modules can be added under `src/uk_open_data/<name>/` and included in future
`uk-open-data` releases. Because they remain inside the same distribution, they do
not need separate PyPI registrations. Add tests and API documentation alongside
each new module, and include any bundled data in the package configuration.

### Sources

- [API reference](../api/index.md): available modules and their imports.
- [Package configuration](https://github.com/KindTechUK/uk-open-data/blob/v0.1.0/pyproject.toml): one distribution name and version.
- [Released package tree](https://github.com/KindTechUK/uk-open-data/tree/v0.1.0/src/kindtech): subpackages included in 0.1.0.

Check the package configuration and tagged source tree when the package layout
changes or a new release adds modules.

_Created: 2026-09-20 · Updated: 2026-09-20 · Verified: 2026-09-20 · Scope/version: 0.1.0_

## Which projects on PyPI does a release publish?

**Short answer:** Two, from one tag. `uk-open-data` is the package.
[`kindtech`](https://pypi.org/project/kindtech/) is its old name: a small
distribution that depends on the same version of `uk-open-data` and holds the
`kindtech` import name.

Both use Trusted Publishing from the release workflow, so each project on PyPI
needs its own trusted publisher that names this repository, the workflow file
`release.yml` and the environment `pypi`. For `uk-open-data`, a pending
publisher creates the project on the first release. `kindtech` was created by
the 0.1.0 release and needs a publisher that names the repository as it is
called now.

To release, set the same version in `pyproject.toml` and in
`packaging/kindtech/pyproject.toml` (twice there: its own version and the
version of `uk-open-data` it depends on), complete the release checks, and push
the matching `v*` tag when the release is approved. The workflow checks that
the tag and both versions match, publishes `uk-open-data`, then `kindtech`.

### Sources

- [Release workflow](https://github.com/KindTechUK/uk-open-data/blob/main/.github/workflows/release.yml): the checks and the two publishing jobs.
- [The old name's package](https://github.com/KindTechUK/uk-open-data/tree/main/packaging/kindtech): what the `kindtech` distribution holds.
- [First release, 0.1.0](https://pypi.org/project/kindtech/0.1.0/): published as `kindtech`.

Recheck the two PyPI projects and their publishers before a release.

_Created: 2026-09-20 · Updated: 2026-11-19 · Verified: 2026-11-19 (builds and installs; no release has run yet) · Scope/version: 0.2_
