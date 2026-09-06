# Configuration file for the Sphinx documentation builder.

import os
import sys

sys.path.insert(0, os.path.abspath(".."))

project = "qforge"
copyright = "2026, Saumya Shah"
author = "Saumya Shah"
release = "0.2.0"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.githubpages",
    "sphinx.ext.mathjax",
    "sphinx.ext.intersphinx",
    "nbsphinx",
    "sphinx_copybutton",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store", "**.ipynb_checkpoints"]

copybutton_prompt_text = "$ "
html_theme = "furo"
html_static_path = ["_static"]
html_title = "qforge"

nbsphinx_execute = "never"
html_logo = "_static/icon.png"
html_favicon = "_static/fav.ico"

# Keep the order a reader would expect rather than alphabetical: methods on an
# engine read better in the order they are meant to be called.
autodoc_member_order = "bysource"
autodoc_typehints = "description"

# Heavy numerical dependencies are mocked so the API pages build even where the
# full simulation stack is not installed. Read the Docs does install the package,
# so these only matter for lightweight local doc builds.
autodoc_mock_imports = ["qiskit_metal"]

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable/", None),
    "scipy": ("https://docs.scipy.org/doc/scipy/", None),
    "qutip": ("https://qutip.readthedocs.io/en/stable/", None),
    "scqubits": ("https://scqubits.readthedocs.io/en/latest/", None),
}
