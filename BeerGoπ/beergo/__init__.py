"""Backend modular do BeerGoπ; importar não inicializa GPIO nem servidor."""

from .application import Application

__all__ = ["Application"]
