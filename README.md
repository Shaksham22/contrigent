# Contrigent

**Contrigent is an experimental multi-agent AI developer for open-source project contributions.**

Give it a GitHub repository and an issue. Contrigent investigates the problem, plans a solution, delegates work to specialist agents, tests the proposed changes in Docker, reviews the result, asks for human approval, and can create a draft pull request from your fork.

The project is an experiment in using multiple specialized AI agents as a small software-engineering team instead of relying on one coding agent to do everything.

---

## What Contrigent Does

The intended workflow is:

```text
GitHub Repository + Issue
          ↓
Repository Setup / Test Environment
          ↓
Manager analyzes the issue
          ↓
Human approves the plan
          ↓
Specialist agents implement the solution
          ↓
Testing specialist designs regression / edge-case tests
          ↓
Docker executes the verified test suite
          ↓
Failure → Manager replans with full failure context
          ↓
Passing candidate
          ↓
Independent Reviewer
          ↓
Human final approval
          ↓
Final tests
          ↓
Commit → Push to Fork → Draft Pull Request
```

Contrigent keeps the **reasoning work** and the **verification work** separate: AI agents can decide what should be changed, but actual pass/fail results come from running the repository's tests.

---

## Multi-Agent Structure

Contrigent currently includes agents for different responsibilities, including:

- **Issue Analyzer / Manager** — understands the issue, creates the implementation plan, assigns work, and replans after failures.
- **Python Solver** — handles Python implementation work.
- **Frontend Solver** — handles frontend / JavaScript-related work.
- **Database Solver** — handles database-related changes.
- **Configuration Specialist** — handles project and environment configuration.
- **Documentation Specialist** — handles documentation changes.
- **Testing Specialist** — creates or updates regression and edge-case tests.
- **Advanced Solver** — handles more difficult implementation work when needed.
- **Repository Setup Specialist** — determines how an unfamiliar repository should be installed, configured, and tested.
- **Independent Reviewer** — reviews the final passing candidate separately from the implementation agents.
- **Pull Request Documentation Agent** — prepares the draft PR title and description.

Model selection is centralized in `agent_models.toml`, and agents can use model escalation when repeated attempts require stronger reasoning.

---

## Human-in-the-Loop

Contrigent has two important approval points:

1. **Plan approval** — before implementation begins.
2. **Final approval** — before approved changes are applied and published.

Contrigent does not automatically merge pull requests.

The user remains in control of whether the proposed solution is implemented and whether it is published.

---

## Testing and Repository Environments

Contrigent tests repositories inside disposable Docker environments.

The environment layer is designed to discover how the repository itself expects to be run rather than assuming every project uses the same commands.

A verified environment can include:

- project / subproject root,
- runtime and ecosystem,
- dependency installation,
- repository-owned setup scripts,
- build commands,
- background processes,
- pre-test commands,
- test commands,
- environment variables,
- local service containers,
- network requirements.

The sandbox is intentionally allowed to install dependencies, generate temporary files, build the project, create caches or lockfiles, and run repository tooling.

The strict boundary is outside the sandbox: repository code does not receive GitHub credentials, SSH credentials, the host Docker socket, privileged host access, or permission to commit/push changes.

Only explicitly approved candidate files are allowed to leave the sandbox and become part of the contribution.

---

## Failure and Remediation

Contrigent is designed around the expectation that the first solution may fail.

When tests fail, the Manager can receive:

- the original issue,
- the current implementation plan,
- files changed by the workers,
- the current candidate,
- newly created tests,
- exact Docker test output,
- successful work completed so far,
- and the failed work.

The Manager then creates a revised plan and reassigns the necessary work.

Reviewer feedback follows the same pattern: findings go back to the Manager, which decides how the implementation should be revised.

---

## GitHub Contribution Flow

Contrigent uses a fork-based contribution workflow:

```text
Original Repository
      ↓
User Fork
      ↓
Contrigent Branch
      ↓
Implementation + Tests + Review
      ↓
Final Human Approval
      ↓
Commit
      ↓
Push to User Fork
      ↓
Draft Pull Request to Upstream
```

After a successful draft PR, the CLI can also prepare an issue comment that clearly discloses that Contrigent was used to create the contribution.

---

## Current Scope of Improvements

The next major work is focused on making Contrigent more general across unfamiliar repositories:

- **Repository-wide analysis** using specialized analyzers for Python, JavaScript/TypeScript, documentation, configuration, databases, and other file types.
- **Better relevance detection** so the Manager receives the right implementation, test, and configuration files before planning.
- **Stronger monorepo support** so Contrigent can identify and test the correct subproject instead of treating every repository as one project.
- **Broader ecosystem support** beyond the current Python-first foundation, including Node.js and later Go, Rust, Ruby, Java, and others.
- **More flexible environment setup** for repositories that require local servers, databases, background processes, or non-standard test commands.
- **Incremental implementation/testing** so dependency-complete groups of worker changes can be verified before moving forward.
- **More systematic evaluation** across a larger set of real software-engineering tasks.

---

## Running Contrigent

The main CLI entry point is:

```bash
contrigent
```

It asks for:

```text
GitHub repository URL
GitHub issue URL
maximum testing rounds
maximum review rounds
```

The CLI then walks through analysis, approval, implementation, testing, review, and publication.

---

## Project Status

Contrigent is an **experimental research / portfolio project**, not a production-ready autonomous developer.

The core multi-agent workflow works end-to-end, including repository analysis, specialist implementation, Docker testing, remediation, independent review, Git operations, and draft PR creation. The main challenge now is making repository understanding and environment setup general enough to work reliably across a much wider range of open-source projects.

---

## Development Note

I wanted to continue refining the system and evaluate it more systematically on **SWE-bench / software-engineering benchmark tasks**, but I ran out of money for API usage before I could continue tuning and testing it at that scale.

So the project is being published in its current experimental state.

Contrigent is not meant to prove that AI can replace software engineers. It is an exploration of how multiple specialized AI agents can be coordinated around a real software-development workflow: **understand, plan, implement, test, review, and contribute.**
