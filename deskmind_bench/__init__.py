"""DeskMind Bench: sandbox desktop tasks, their graders, and the scorer of record.

Everything in this package is pure Python (PyYAML is the only dependency). It never imports a desktop driver:
scoring reads a finished run's workspace and trace from disk. Executing runs is deskmind-hands' job
(``pip install 'deskmind-bench[run]'``).
"""

__version__ = "0.1.0"
