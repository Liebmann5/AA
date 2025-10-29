"""
Makes the 'auto_apply' package executable.

This file serves as the entry point when the package is run directly
using the '-m' flag, for example: python -m auto_apply
"""
from .main import main

if __name__ == "__main__":
    main()