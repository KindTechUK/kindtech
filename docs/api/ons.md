# ONS Data

The `kindtech.ons` module provides functions for accessing and working with Office for National Statistics (ONS) data.

## Functions

### `load_ons()`

```python
from kindtech import load_ons

# Load ONS population data for London
data = load_ons(dataset="population", period="2023", geography="E12000007")
```

#### Parameters

- **dataset** (*str*): The ONS dataset identifier.
- **period** (*str, optional*): Time period for the data (e.g., '2023', 'Q1-2023').
- **geography** (*str, optional*): Geographic area code or name.

#### Returns

- **dict**: Loaded ONS data.

#### Raises

- **ValueError**: If dataset identifier is not provided.

## Examples

```python
# Load population data for London
london_pop = load_ons(dataset="population", geography="E12000007")

# Load quarterly economic data
quarterly_data = load_ons(dataset="gdp", period="Q1-2023")
```
