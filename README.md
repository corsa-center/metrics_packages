# metrics_packages
Contains the packages for which metrics are being collected

## Adding a package

Use the dashboard's [Add a Package](https://corsa-center.github.io/dashboard/about/add-package/) form, or add a `package_config/<owner>_<repo>.yaml` file by hand, and open a pull request. The [Check package config](.github/workflows/check-package-config.yml) workflow checks the file against the schema below, makes sure the name and repository aren't already listed, and checks that the repository exists and is public. To run the same checks locally:

```
python3 .github/scripts/check_package_config.py --online package_config/<owner>_<repo>.yaml
```

## Schema

```
schema: 1
published: true|false # optional
password_sha256: string # optional sha256 encoded password used if published is false
name: string # required, displayed on dashboard
description: string # optional, if provided will override repository description
repo_type: github|gitlab # required
repo_url: string # required
default_branch: string # optional
cdash: string # optional, url of cdash dashboard if available
documentation: string # optional, defaults to repo_url
homepage: string # optional
primary_language: string # optional, overrides repository metadata
spack_repo: string # optional, git URL of the Spack package repository holding this package's recipe, when it is not in Spack's builtin repository (a list is also accepted)

# Per-metric overrides for sub-metrics that are N/A or have known fixed values.
# Keys are the exact sub-metric labels from the CASS Sustainability Metrics Report v3.
# Supported values: "N/A", or any descriptive string.
overrides:
  metric:
    sub-metric: "N/A" | string
```
