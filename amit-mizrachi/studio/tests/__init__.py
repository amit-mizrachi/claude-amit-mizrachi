"""Project Studio tests. stdlib unittest; run by CI as
`python3 -m unittest discover -s amit-mizrachi/studio/tests -t .` from the repo root.

Importing this package puts `studio/` on sys.path, so tests import the SDK as `sdk`, the same
way the adapters do.
"""

import os
import sys

STUDIO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.dirname(STUDIO)
if STUDIO not in sys.path:
    sys.path.insert(0, STUDIO)
