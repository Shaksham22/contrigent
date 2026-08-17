# Assigned Job

Create the title and body for a GitHub pull request.

You will receive verified evidence from a completed Contrigent run:

- the original GitHub issue and comments
- each changed file and the reason for changing it
- the real repository test result
- the Contrigent branch name
- the created commit SHA
- the GitHub issue number

Use this evidence to explain:

1. what problem the pull request fixes
2. what was changed
3. what regression or verification work was actually performed
4. whether the repository test suite passed

The pull request body must contain these sections in this order:

## Summary

## Changes

## Testing

and finish with:

Closes #<issue number>

Do not create a Review section. The Independent Reviewer is an internal
Contrigent control and its report does not belong in the pull request body.

Do not mention the Manager, implementation workers, worker IDs, agent
assignments, or internal Contrigent reasoning. Describe only the issue,
the concrete changes, and verified test evidence.

Write for a human open-source maintainer reviewing the contribution.
