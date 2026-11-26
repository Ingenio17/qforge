"""Core simulation engines for QubitWeave."""


def __getattr__(name):
    # `import QubitWeave; QubitWeave.core.gate_engine` without importing every engine.
    import importlib

    try:
        return importlib.import_module(f"QubitWeave.core.{name}")
    except ModuleNotFoundError as missing:
        if missing.name != f"QubitWeave.core.{name}":
            raise
        raise AttributeError(f"module 'QubitWeave.core' has no attribute {name!r}") from None
