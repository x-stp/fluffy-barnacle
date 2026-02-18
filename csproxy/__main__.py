#!/usr/bin/env python3
"""
Main entry point for running csproxy as a module.

Usage:
    python -m csproxy
"""

import sys
from .cli import main_proxy

if __name__ == '__main__':
    sys.exit(main_proxy())
