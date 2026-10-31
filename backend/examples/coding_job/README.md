# Small coding-job trial

Copy `helper.py` and `test_helper.py` into a small folder under Documents (or another root configured in
`MITRAA_ALLOWED_ROOTS`). Create a responsibility in Mitraa and open Coding jobs.

- Workspace: that folder.
- Objective: Change value() to return 2 instead of 1.
- Acceptance criteria: The function remains named value, takes no arguments, and returns integer 2.
- Input files (one per line): helper.py, test_helper.py
- Allowed output files: helper.py

Prepare the contract, inspect the selected text/provider/limits, and explicitly
start. This consumes a model request. Inspect the proposed file and diff. Python
syntax is checked locally. Then open **Run checks**, choose **Python unit tests
(unittest)**, select `test_helper.py`, and click **Run approved check**. Read the
execution warning and approve only code you trust. The test imports the proposed
helper in a temporary copy and checks that `value()` returns 2. Inspect the saved
report, accept review, then **Apply to original folder**. The original `helper.py`
still returns 1; the saved working copy is `helper_byMitraa.py` and returns 2.
Optional checks do not use an additional AI call. Execution has Windows resource
limits but is not a filesystem/network security sandbox.
