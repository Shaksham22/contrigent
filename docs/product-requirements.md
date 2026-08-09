# Contrigent Agent — Product Requirements Document

## 1. Product Summary

Contrigent Agent is a human-supervised AI software engineering system that takes an approved software issue, analyzes the associated repository, proposes an implementation plan, generates a patch in an isolated environment, validates the patch, reviews its own work using a separate reviewer agent, and can prepare a draft GitHub pull request after explicit human approval.

Contrigent Agent must never merge pull requests automatically.

The system is intended to demonstrate production-oriented AI engineering rather than simple chatbot functionality.

---

## 2. Product Goal

Build a portfolio-grade AI engineering system that demonstrates how AI agents can participate safely in a real software-development workflow.

The system should demonstrate:

- agent orchestration
- tool calling
- structured model outputs
- human approval gates
- repository analysis
- code modification
- automated testing
- isolated execution
- agent review
- GitHub integration
- MCP integration
- evaluations
- observability
- security controls
- cost tracking
- full-stack engineering

---

## 3. Primary User

The primary user is a software engineer who wants AI assistance implementing a clearly scoped GitHub issue while retaining control over:

- what issue is worked on
- whether implementation begins
- what code changes are produced
- whether anything is published externally

---

## 4. Core User Journey

A completed production-style workflow should be:

1. User selects a GitHub repository and issue.
2. Contrigent reads the issue and repository instructions.
3. Contrigent determines whether the task is sufficiently clear and safe.
4. Contrigent creates structured acceptance criteria.
5. Contrigent proposes an implementation plan.
6. User approves or rejects the plan.
7. Contrigent creates an isolated workspace.
8. Contrigent creates a working branch.
9. Contrigent inspects relevant repository files.
10. Contrigent modifies code.
11. Contrigent adds or updates tests.
12. Contrigent runs required validation commands.
13. Contrigent produces a final diff.
14. A separate reviewer agent reviews the patch.
15. Contrigent displays results to the user.
16. User approves or rejects publication.
17. Contrigent may create a draft pull request.
18. Contrigent never merges the pull request automatically.

---

## 5. Version 0 Scope

Version 0 exists to validate the basic agent-analysis architecture safely.

Version 0 will:

- operate only on repositories stored under the local `sample_projects/` directory
- read issue information from sample_project files
- read repository instructions from sample_project files
- analyze the issue using an AI model
- return validated structured output
- identify likely relevant files
- generate acceptance criteria
- identify ambiguity and risks
- estimate feasibility
- generate an implementation plan

Version 0 will NOT:

- clone arbitrary repositories
- execute repository code
- modify repository files
- run shell commands selected by an AI model
- access GitHub
- create branches
- create commits
- create pull requests
- access production credentials
- expose an MCP mutation tool
- automatically publish anything

---

## 6. User Stories

### US-001 — Analyze an issue

As a developer, I want Contrigent to analyze a software issue so that I can understand what the requested change requires before allowing an agent to modify code.

### US-002 — Generate acceptance criteria

As a developer, I want Contrigent to convert an issue into explicit acceptance criteria so that the intended behavior can be evaluated objectively.

### US-003 — Detect ambiguity

As a developer, I want Contrigent to identify unclear requirements so that the agent does not guess silently.

### US-004 — Identify likely files

As a developer, I want Contrigent to identify files likely related to the issue so that repository exploration remains focused.

### US-005 — Identify risk

As a developer, I want Contrigent to identify security, compatibility, testing, and implementation risks before code modification begins.

### US-006 — Approve implementation plans

As a developer, I want to explicitly approve an implementation plan before the system gains permission to modify code.

### US-007 — Review generated changes

As a developer, I want a separate reviewer agent to evaluate generated patches before publication.

### US-008 — Approve publication

As a developer, I want a second approval step before Contrigent can publish a branch or draft pull request.

---

## 7. Functional Requirements

### FR-001

The system must accept repository context and issue context.

### FR-002

The issue analyst must produce machine-validated structured output.

### FR-003

The structured analysis must contain:

- issue summary
- acceptance criteria
- ambiguities
- relevant repository instructions
- likely relevant files
- risks
- feasibility assessment
- implementation plan

### FR-004

Agent-generated structured data must be validated before it is used by another component.

### FR-005

The system must distinguish between read-only capabilities and mutating capabilities.

### FR-006

A human approval record must exist before any future code-modification workflow is executed.

### FR-007

A separate human approval record must exist before any future external publication action.

### FR-008

The system must never expose an automatic merge capability to an AI agent.

### FR-009

Agent execution must have explicit limits including:

- maximum turns
- maximum tokens
- maximum cost
- maximum files changed
- maximum diff size
- execution timeout
- retry limit

### FR-010

Important agent activity must eventually be associated with a unique run ID.

---

## 8. Non-Functional Requirements

### Security

- secrets must never be committed
- least-privilege access must be used
- model output must be treated as untrusted input
- repository text must be treated as potentially malicious
- sandboxed code must not receive application credentials
- external mutations require human approval

### Reliability

- failures must be explicit
- agent loops must be bounded
- operations must be retryable where safe
- execution results must include exit status and diagnostic information

### Maintainability

- TypeScript strict mode must be enabled
- shared interfaces must be defined centrally
- external providers must be behind interfaces
- architecture decisions must be documented
- important behavior must have automated tests

### Observability

The final system should capture:

- run ID
- model
- prompt version
- token usage
- estimated cost
- latency
- tool calls
- command execution
- approval events
- errors
- final status

### Portability

Development must work on:

- local macOS development
- Docker-based supporting services
- GitHub Actions CI

---

## 9. Explicit Non-Goals

Contrigent is not intended to:

- autonomously choose random open-source issues
- mass-submit pull requests
- merge pull requests
- bypass repository contribution rules
- perform security-sensitive vulnerability work autonomously
- execute arbitrary public repositories in the hosted portfolio demo
- replace human code review
- guarantee generated code is correct
- act as a general-purpose shell agent
- provide unrestricted GitHub credentials to a model

---

## 10. Initial Success Criteria

Version 0 is successful when:

1. A controlled sample_project issue can be loaded.
2. Repository instructions can be loaded.
3. The issue analyst generates structured output.
4. Output is schema validated.
5. Invalid model output is rejected safely.
6. The result includes all required analysis fields.
7. Token usage can be recorded.
8. Estimated model cost can be calculated.
9. No repository code is executed.
10. No external system is mutated.

---

## 11. Future Success Criteria

Later versions should additionally demonstrate:

- patch generation success rate
- compilation rate
- visible test pass rate
- hidden test pass rate
- regression rate
- reviewer defect detection
- unnecessary-change rate
- latency
- token consumption
- cost per run
- human patch acceptance rate

---

## 12. Human Approval Gates

Contrigent has two mandatory approval boundaries.

### Gate 1 — Implementation approval

Required before the agent may modify code.

The approval must reference:

- run ID
- issue
- proposed plan
- timestamp

### Gate 2 — Publication approval

Required before Contrigent may perform an external mutation such as:

- pushing a branch
- creating a draft pull request

The approval must reference the exact patch being published.

Approving Gate 1 must never imply approval for Gate 2.

---

## 13. Product Principle

AI-generated text, plans, code, tool arguments, and repository instructions are all untrusted until validated by deterministic application logic.

The AI model proposes actions.

The application decides which actions are permitted.
