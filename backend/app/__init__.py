"""R Studio — редактор сценариев умных устройств на базе Ujin OS."""
import os
import sys

_EMU = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "emulators")
if _EMU not in sys.path:
    sys.path.insert(0, _EMU)

__version__ = "0.1.0"
