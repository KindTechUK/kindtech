# kindtech

`kindtech` is the old name of
[uk-open-data](https://pypi.org/project/uk-open-data/), a Python package of UK
open data for charities. Up to version 0.1 the package was published under
this name.

Installing `kindtech` installs the same version of `uk-open-data` and keeps
code that imports `kindtech` working:

```python
from kindtech.geo import load_geodata  # the same function as uk_open_data.geo.load_geodata
```

Importing `kindtech` gives a `DeprecationWarning`. For new code:

```bash
uv add uk-open-data
```

```python
from uk_open_data.geo import load_geodata
```

Docs: <https://kindtechuk.github.io/uk-open-data/>
