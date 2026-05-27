"""
Process-wide startup compatibility settings.

Python imports this module automatically when it is present on sys.path. Keeping
the protobuf setting here ensures it is applied before transitive Google/Gemini
imports can load protobuf's C extension on Python 3.14.
"""
import os

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")
