#!/usr/bin/env python3
"""Ponto de entrada compatível: execute python3 beergo.py."""

from pathlib import Path
from beergo import Application


def main():
    Application(Path(__file__).resolve().parent).run()


if __name__ == "__main__":
    main()
