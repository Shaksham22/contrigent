# Contrigent - A Multi-Agent Open Source Contributor

> **Work in Progress**

Contrigent is an experimental multi-agent system designed to work on open-source software issues.

The goal is to build a system that can take a GitHub issue and its repository, understand the problem, inspect the relevant code, propose a solution, modify the required files, test the changes, review its own work, and eventually prepare a pull request for human approval.

## Current Idea

The intended workflow is:

```text
GitHub Issue + Repository
          ↓
    Issue Analyzer
          ↓
 Understands the problem
 and creates a plan
          ↓
     Human Approval
          ↓
      Code Editor
          ↓
 Produces edited files
          ↓
      Test Runner
          ↓
     Code Reviewer
          ↓
     Human Approval
          ↓
   Draft Pull Request
