============
Installation
============

Stable Release
--------------
To install **qforge** via PyPI, run the following command in your terminal:

.. code-block:: bash

   $ pip install qforge

This is the preferred method to install qforge, as it will always fetch the most recent stable release along with its core dependencies.

From Source
-----------
If you want to contribute to development or run the absolute latest features, you can clone the repository and install it in editable mode.

First, clone the official GitHub repository:

.. code-block:: bash

   $ git clone https://github.com/Ingenio17/qforge.git
   $ cd qforge

Then, install the package locally:

.. code-block:: bash

   $ pip install -e .

.. note::
   Because **qforge** relies heavily on ``QuTiP`` and ``scqubits`` for physical hardware simulation, installing from source requires a working C/C++ compiler environment on your machine to build underlying native extensions successfully.