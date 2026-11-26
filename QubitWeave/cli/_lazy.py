"""Deferred construction, so importing the CLI does not start the engines."""

from collections.abc import Callable
from typing import Any


class Lazy:
    """
    Stands in for an object and builds it on first use.

    Importing QuTiP and loading a session takes seconds, which `QubitWeave --help`
    has no reason to pay.
    """

    def __init__(self, factory: Callable[[], Any]):
        self.__dict__["_factory"] = factory
        self.__dict__["_object"] = None

    def _resolve(self) -> Any:
        if self.__dict__["_object"] is None:
            self.__dict__["_object"] = self.__dict__["_factory"]()
        return self.__dict__["_object"]

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolve(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._resolve(), name, value)
