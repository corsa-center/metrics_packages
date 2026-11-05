# metrics_packages
Contains the packages for which metrics are being collected

## Schema

```
schema: 1
published: true|false # optional
name: string # required, displayed on dashboard
description: string # optional, if provided will override repository description
repo_type: github|gitlab # required
repo_url: string # required
default_branch: string # optional
cdash: string # optional, url of cdash dashboard if available
documentation: string # optional, defaults to repo_url
homepage: string # optional
primary_language: string # optional, overrides repository metadata

# Per-metric overrides for sub-metrics that are N/A or have known fixed values.
# Keys are the exact sub-metric labels from the CASS Sustainability Metrics Report v3.
# Supported values: "N/A", or any descriptive string.
overrides:
  metric:
    sub-metric: "N/A" | string
```
