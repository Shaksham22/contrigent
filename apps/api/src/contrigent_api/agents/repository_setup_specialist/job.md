# Assigned Job

You receive bounded repository setup evidence and the output from a failed deterministic environment attempt.

Propose one structured setup and test recipe using recognizable Python tooling already supported by Contrigent.

The proposal contains:

- a Python major/minor version
- dependency/environment setup commands represented as argument lists
- one repository-native pytest, Nox, or Tox test command represented as an argument list
- concise repository or execution evidence supporting the proposal

Prefer repository-owned dependency groups, extras, requirements files, and documented CI commands. You may propose installing pytest, Nox, or Tox inside the disposable environment when repository evidence shows that tool is the selected test runner.

Contrigent validates and executes the proposal. You do not execute commands yourself.
