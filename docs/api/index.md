# API Reference

Welcome to the KindTech API reference documentation. This section provides detailed information about the available modules and functions in the KindTech package.

## Available Modules

KindTech provides the following modules:

- **Geographic Data**: Functions for loading and processing geographic data
- **ONS Data**: Functions for accessing Office for National Statistics data

## Quick Start

```python
# Import functions directly
from kindtech import load_geodata, load_ons

# Load geographic data
geo_data = load_geodata(source="uk_boundaries")

# Load ONS data
ons_data = load_ons(dataset="population", period="2023", geography="E12000007")
```
