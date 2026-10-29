# Small coding-job trial

Copy `helper.py` into a small folder under Documents (or another root configured in
`MITRAA_ALLOWED_ROOTS`). Create a responsibility in Mitraa and open Coding jobs.

- Workspace: that folder.
- Objective: Change value() to return 2 instead of 1.
- Acceptance criteria: The function remains named value, takes no arguments, and returns integer 2.
- Input files: helper.py
- Allowed output files: helper.py

Prepare the contract, inspect the selected text/provider/limits, and explicitly
start. This consumes a model request. Inspect the proposed file and diff. Python
syntax is checked locally; behavior is not executed or proven. The original file
must still return 1; the isolated proposed copy should return 2. Review manually
before accepting or copying any output into the original folder.
