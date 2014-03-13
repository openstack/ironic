"""
 wrapper for pyflakes to ignore gettext based warning:
     "undefined name '_'"

 Synced in from openstack-common
"""

__all__ = ['main']

import sys
import six.moves.builtins as builtins
import pyflakes.api
from pyflakes import checker


def main():
    checker.Checker.builtIns = (set(dir(builtins)) |
                                set(['_']) |
                                set(checker._MAGIC_GLOBALS))
    sys.exit(pyflakes.api.main())

if __name__ == "__main__":
    main()
