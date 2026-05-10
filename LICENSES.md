# Third-party licenses

Snapshot of all packages installed in the resolved dependency tree (runtime + dev), with their declared SPDX license and homepage.

Regenerate with:

```bash
uv run pip-licenses --format=markdown --with-urls --order=license > LICENSES.md
```

Generated 2026-05-10.

| Name                    | Version     | License                                            | URL                                                                   |
|-------------------------|-------------|----------------------------------------------------|-----------------------------------------------------------------------|
| keras                   | 3.14.1      | Apache License 2.0                                 | https://github.com/keras-team/keras                                   |
| gingado                 | 0.2.7       | Apache Software License                            | https://github.com/bis-med-it/gingado                                 |
| pyarrow                 | 22.0.0      | Apache Software License                            | https://arrow.apache.org/                                             |
| pysdmx                  | 1.15.1      | Apache Software License                            | https://sdmx.io/tools/pysdmx                                          |
| requests                | 2.33.1      | Apache Software License                            | https://github.com/psf/requests                                       |
| sdmx1                   | 2.26.0      | Apache Software License                            | https://github.com/khaeru/sdmx                                        |
| stevedore               | 5.7.0       | Apache Software License                            | https://docs.openstack.org/stevedore                                  |
| python-dateutil         | 2.9.0.post0 | Apache Software License; BSD License               | https://github.com/dateutil/dateutil                                  |
| absl-py                 | 2.4.0       | Apache-2.0                                         | https://github.com/abseil/abseil-py                                   |
| bandit                  | 1.9.4       | Apache-2.0                                         | https://bandit.readthedocs.io/                                        |
| coverage                | 7.13.5      | Apache-2.0                                         | https://github.com/coveragepy/coveragepy                              |
| ml_dtypes               | 0.5.4       | Apache-2.0                                         | https://github.com/jax-ml/ml_dtypes                                   |
| optree                  | 0.19.1      | Apache-2.0                                         | https://github.com/metaopt/optree                                     |
| tzdata                  | 2026.2      | Apache-2.0                                         | https://github.com/python/tzdata                                      |
| packaging               | 26.2        | Apache-2.0 OR BSD-2-Clause                         | https://github.com/pypa/packaging                                     |
| contourpy               | 1.3.3       | BSD License                                        | https://github.com/contourpy/contourpy                                |
| cycler                  | 0.12.1      | BSD License                                        | https://matplotlib.org/cycler/                                        |
| httpx                   | 0.28.1      | BSD License                                        | https://github.com/encode/httpx                                       |
| kiwisolver              | 1.5.0       | BSD License                                        | https://github.com/nucleic/kiwi                                       |
| nodeenv                 | 1.10.0      | BSD License                                        | https://github.com/ekalinin/nodeenv                                   |
| pandas                  | 2.3.3       | BSD License                                        | https://pandas.pydata.org                                             |
| scipy                   | 1.17.1      | BSD License                                        | https://scipy.org/                                                    |
| threadpoolctl           | 3.6.0       | BSD License                                        | https://github.com/joblib/threadpoolctl                               |
| Pygments                | 2.20.0      | BSD-2-Clause                                       | https://pygments.org                                                  |
| requests-cache          | 1.3.1       | BSD-2-Clause                                       | https://github.com/requests-cache/requests-cache                      |
| h5py                    | 3.16.0      | BSD-3-Clause                                       | https://www.h5py.org/                                                 |
| httpcore                | 1.0.9       | BSD-3-Clause                                       | https://www.encode.io/httpcore/                                       |
| idna                    | 3.13        | BSD-3-Clause                                       | https://github.com/kjd/idna                                           |
| joblib                  | 1.5.3       | BSD-3-Clause                                       | https://joblib.readthedocs.io                                         |
| lxml                    | 6.1.0       | BSD-3-Clause                                       | https://lxml.de/                                                      |
| msgspec                 | 0.21.1      | BSD-3-Clause                                       | https://jcristharif.com/msgspec/                                      |
| scikit-learn            | 1.8.0       | BSD-3-Clause                                       | https://scikit-learn.org                                              |
| numpy                   | 2.4.4       | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | https://numpy.org                                                     |
| anyio                   | 4.13.0      | MIT                                                | https://anyio.readthedocs.io/en/stable/versionhistory.html            |
| ast_serialize           | 0.3.0       | MIT                                                | https://github.com/mypyc/ast_serialize                                |
| attrs                   | 26.1.0      | MIT                                                | https://www.attrs.org/en/stable/changelog.html                        |
| cfgv                    | 3.5.0       | MIT                                                | https://github.com/asottile/cfgv                                      |
| charset-normalizer      | 3.4.7       | MIT                                                | https://github.com/jawah/charset_normalizer/blob/master/CHANGELOG.md  |
| filelock                | 3.29.0      | MIT                                                | https://github.com/tox-dev/py-filelock                                |
| fonttools               | 4.62.1      | MIT                                                | http://github.com/fonttools/fonttools                                 |
| identify                | 2.6.19      | MIT                                                | https://github.com/pre-commit/identify                                |
| iniconfig               | 2.3.0       | MIT                                                | https://github.com/pytest-dev/iniconfig                               |
| librt                   | 0.10.0      | MIT                                                | https://github.com/mypyc/librt                                        |
| mypy                    | 2.0.0       | MIT                                                | https://www.mypy-lang.org/                                            |
| mypy_extensions         | 1.1.0       | MIT                                                | https://github.com/python/mypy_extensions                             |
| platformdirs            | 4.9.6       | MIT                                                | https://github.com/tox-dev/platformdirs                               |
| pre_commit              | 4.6.0       | MIT                                                | https://github.com/pre-commit/pre-commit                              |
| pyparsing               | 3.3.2       | MIT                                                | https://github.com/pyparsing/pyparsing/                               |
| pytest                  | 9.0.3       | MIT                                                | https://docs.pytest.org/en/latest/                                    |
| pytest-cov              | 7.1.0       | MIT                                                | https://pytest-cov.readthedocs.io/en/latest/changelog.html            |
| ruff                    | 0.15.12     | MIT                                                | https://docs.astral.sh/ruff                                           |
| url-normalize           | 3.0.0       | MIT                                                | https://github.com/niksite/url-normalize                              |
| urllib3                 | 2.7.0       | MIT                                                | https://github.com/urllib3/urllib3/blob/main/CHANGES.rst              |
| virtualenv              | 21.3.1      | MIT                                                | https://github.com/pypa/virtualenv                                    |
| PyYAML                  | 6.0.3       | MIT License                                        | https://pyyaml.org/                                                   |
| cattrs                  | 26.1.0      | MIT License                                        | https://catt.rs                                                       |
| h11                     | 0.16.0      | MIT License                                        | https://github.com/python-hyper/h11                                   |
| h2                      | 4.3.0       | MIT License                                        | https://github.com/python-hyper/h2/                                   |
| hpack                   | 4.1.0       | MIT License                                        | https://github.com/python-hyper/hpack/                                |
| hyperframe              | 6.1.0       | MIT License                                        | https://github.com/python-hyper/hyperframe/                           |
| markdown-it-py          | 4.2.0       | MIT License                                        | https://github.com/executablebooks/markdown-it-py                     |
| mdurl                   | 0.1.2       | MIT License                                        | https://github.com/executablebooks/mdurl                              |
| parsy                   | 2.2         | MIT License                                        | https://github.com/python-parsy/parsy                                 |
| pluggy                  | 1.6.0       | MIT License                                        | UNKNOWN                                                               |
| python-discovery        | 1.3.0       | MIT License                                        | https://github.com/tox-dev/python-discovery                           |
| pytz                    | 2026.2      | MIT License                                        | http://pythonhosted.org/pytz                                          |
| rich                    | 15.0.0      | MIT License                                        | https://github.com/Textualize/rich                                    |
| six                     | 1.17.0      | MIT License                                        | https://github.com/benjaminp/six                                      |
| pillow                  | 12.2.0      | MIT-CMU                                            | https://python-pillow.github.io                                       |
| certifi                 | 2026.4.22   | Mozilla Public License 2.0 (MPL 2.0)               | https://github.com/certifi/python-certifi                             |
| pathspec                | 1.1.1       | Mozilla Public License 2.0 (MPL 2.0)               | https://python-path-specification.readthedocs.io/en/latest/index.html |
| typing_extensions       | 4.15.0      | PSF-2.0                                            | https://github.com/python/typing_extensions                           |
| distlib                 | 0.4.0       | Python Software Foundation License                 | https://github.com/pypa/distlib                                       |
| matplotlib              | 3.10.9      | Python Software Foundation License                 | https://matplotlib.org                                                |
| bis-policy-rate-monitor | 0.1.0       | UNKNOWN                                            | UNKNOWN                                                               |
| bis-policy-rate-monitor | 0.1.0       | UNKNOWN                                            | UNKNOWN                                                               |
| namex                   | 0.1.0       | UNKNOWN                                            | UNKNOWN                                                               |
