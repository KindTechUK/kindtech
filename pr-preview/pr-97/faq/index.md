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

The package was called `kindtech` up to version 0.1. Code that imports
`kindtech` still works and gives a deprecation warning: `kindtech.geo` is the
same module as `uk_open_data.geo`.

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

## Does KindTech still need to be registered on PyPI?

**Short answer:** No. [KindTech 0.1.0 is published on PyPI](https://pypi.org/project/kindtech/0.1.0/).
Its first successful Trusted Publishing run created the project.

Future releases use the existing GitHub workflow and PyPI publisher. Update the
package version, complete the release checks, and push the corresponding `v*`
tag when the release is approved. The workflow checks that the tag and package
version match before publishing the wheel and source distribution.

### Sources

- [Successful first release](https://github.com/KindTechUK/uk-open-data/actions/runs/35527839991): the build and Trusted Publishing run.
- [Release workflow](https://github.com/KindTechUK/uk-open-data/blob/v0.1.0/.github/workflows/release.yml): tag/version checks and publication steps.

Recheck the PyPI project and workflow configuration before a future release.

_Created: 2026-09-20 · Updated: 2026-09-20 · Verified: 2026-09-20 · Scope/version: 0.1.0_
