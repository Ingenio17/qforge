# Configuration file for the Sphinx documentation builder.

import os
import sys
sys.path.insert(0, os.path.abspath('..'))

project = 'qforge'
copyright = '2026, Saumya Shah'
author = 'Saumya Shah'
release = '0.2.0'

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.viewcode',
    'sphinx.ext.githubpages',
    'sphinx.ext.mathjax',
    'nbsphinx', 
    "sphinx_copybutton",
]

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store', '**.ipynb_checkpoints']

copybutton_prompt_text = "$ "
html_theme = 'furo'
html_static_path = ['_static']

nbsphinx_execute = 'never'
html_logo = "_static/icon.png"
html_favicon = "_static/fav.ico"
