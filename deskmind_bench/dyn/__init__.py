"""The dynamic-task set (deskmind#62): tasks in which something changes mid-run -- a file moves, a dialog opens, an
app quits, the user changes their mind, a result decides the next step -- and the reaction is graded.

events.py is the record format the orchestrator and the bench runner write; graders.py the checks that read it.
Importing this package registers the checks.
"""

from . import graders  # noqa: F401  -- registers the dynamic-task checks
