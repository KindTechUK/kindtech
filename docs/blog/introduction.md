# Introduction to KindTech

## Posted on June 28, 2025

Welcome to KindTech, a Python package designed to simplify working with geographic and Office for National Statistics (ONS) data.

## What is KindTech?

KindTech is a Python library that provides easy-to-use functions for loading and processing geographic data and ONS statistics. Whether you're a data scientist, researcher, or developer, KindTech aims to make your data workflows more efficient.

## Key Features

- **Simple API**: Clean, intuitive functions that are easy to use
- **Geographic Data**: Load and process geographic data from various sources
- **ONS Integration**: Direct access to Office for National Statistics datasets
- **Flexible**: Works with your existing data pipelines

## Getting Started

Installation is simple:

```bash
# Using pip
pip install kindtech

# Using uv (recommended)
uv add kindtech
```

Then you can import and use the package:

```python
from kindtech import load_geodata, load_ons

# Load geographic data
geo_data = load_geodata(source="uk_boundaries")

# Load ONS data
ons_data = load_ons(dataset="population", period="2023")
```

## Next Steps

Check out our [API documentation](/api/) to learn more about the available functions and how to use them effectively.

Stay tuned for more blog posts and tutorials on how to make the most of KindTech!
