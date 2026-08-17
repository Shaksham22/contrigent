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
2. Contrigent creates a working branch without exposing publication credentials to repository code.
3. The Manager reads the issue and repository instructions, creates acceptance criteria, and assigns affected files.
4. Contrigent determines whether repository execution is required and selects the issue-relevant project root.
5. For source, configuration, or test work, Contrigent verifies a repository-native setup and test recipe in disposable Docker isolation.
6. For documentation-only work, Contrigent skips Docker and repository tests.
7. User approves or rejects the implementation plan.
8. Assigned workers create a candidate patch without writing to the real checkout.
9. Contrigent replays the verified recipe against the candidate when repository execution is required.
10. A separate reviewer agent reviews the patch.
11. Contrigent displays the candidate and truthful validation evidence to the user.
12. User approves or rejects publication.
13. The host application applies only approved candidate files.
14. Contrigent replays the same verified recipe as final validation when required.
15. The host application may commit, push, and create a draft pull request.
16. Contrigent never merges the pull request automatically.

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
- repository execution must occur only in disposable Docker isolation
- sandboxed code must not receive application, GitHub, SSH, or host credentials
- the real repository checkout must be mounted read-only during setup and testing
- repository code must not receive the host Docker socket, privileged mode, host networking, host PID/IPC namespaces, host devices, or arbitrary host mounts
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

---

## 14. Repository Environment Verification and Execution

### 14.1 Trust zones

Repository code and repository-selected commands are untrusted. Contrigent separates them into two trust zones.

The disposable repository execution sandbox is intentionally permissive. Inside its writable copy of the repository, setup and test commands may install dependencies and development tools, create virtual environments and caches, generate or update lockfiles and configuration, compile or build the project, run package-manager and repository-owned scripts, start local processes, and communicate with approved disposable services. These changes are destroyed with the sandbox and are not changes to the user's checkout.

The host and publication boundary remains strict. Repository code cannot write to the real checkout, receive GitHub or SSH credentials, access the Docker socket, request privileged or host-namespace execution, mount arbitrary host directories, commit, push, create pull requests, or comment on issues. Only the host-side application may apply explicitly approved files and perform publication after human approval.

Generated sandbox artifacts are never copied into a candidate patch automatically. Tool-generated lockfiles returned by an LLM worker as replacement content remain prohibited; this worker-output rule is separate from normal package-manager generation inside the disposable sandbox.

### 14.2 Analysis and documentation-only work

Manager analysis runs after branch creation and before repository environment verification. Its worker assignments and affected paths determine whether execution is needed and which project root is relevant. No implementation worker runs before required environment verification completes, and the existing plan-approval gate remains in place.

A run skips environment verification only when its final feasible Manager analysis contains one or more assignments and every assignment targets `documentation_specialist`. The documentation worker and Independent Reviewer still run, final human approval is still required, and publication follows the normal host-side workflow. Contrigent does not start Docker, invoke the Repository Setup Specialist, store a fake recipe, or claim repository tests passed for this path. Any non-documentation assignment requires environment verification.

### 14.3 Verified execution strategy

A verified repository execution strategy records:

- ecosystem
- optional runtime version
- repository-relative project root
- pinned Docker image
- structured setup commands
- structured background commands and foreground pre-test commands
- one or more structured test commands
- non-secret environment variables
- test network mode
- structured disposable services and readiness checks
- repository evidence supporting the choices

The verified strategy and passing untouched baseline are stored once. Candidate testing starts from a clean repository copy, overlays only current proposed files, and replays that strategy. Final testing replays the same strategy after approved files are applied. Environment, dependency, and service failures remain distinct from candidate test failures and do not consume candidate remediation rounds.

### 14.4 Ecosystems and project roots

The ecosystem registry currently supports Python and Node. Python uses the pinned Astral `uv` Bookworm image matching the selected runtime, defaulting to Python 3.12. Node uses the official `node:22-bookworm-slim` image by default. Runtime selection, evidence files, and default images are ecosystem metadata rather than language-specific fields on the execution contract.

Python discovery retains support for repository-native pytest, Nox, Tox, Makefile, task, and script workflows. Node discovery uses `package.json`, lockfiles, runtime-version files, and package scripts; lockfile evidence selects npm, pnpm, or Yarn setup. The Repository Setup Specialist may propose other repository-native structured commands supported by the current ecosystem evidence. Go, Rust, and Ruby are not implemented by this milestone.

For monorepos, Contrigent gathers Manager-assigned file paths, finds their nearest ancestor directories containing registered ecosystem evidence, and selects the deepest common relevant project. The repository root is used only when it is the actual project root or assignments span components without one valid subproject. Setup and tests run from the verified project root, and candidate/final replay preserves it.

### 14.5 Networks, services, and local processes

Test network mode is explicit:

- `none` disables test-container networking.
- `services_only` joins the test container and disposable services to a unique internal Docker network with no public internet route.
- `internet` permits outbound test access only when repository evidence requires it; no credentials are supplied.

Setup may use network access for dependency installation. Repository-native background commands start persistent processes inside the test container and terminate with that container. Foreground pre-test commands run sequentially and must complete successfully before the repository's test commands begin.

Disposable service definitions contain a name, pinned image, optional command, non-secret environment variables, network alias, optional readiness command, and bounded startup timeout. Service containers use disposable writable container layers, resource limits, no-new-privileges, no host ports, no host mounts, and no privileged or host-network mode. This permits normal database/search-service initialization without exposing host storage. Contrigent confirms each service remains running, executes any bounded readiness command, classifies startup/readiness failures as environment failures, and removes service containers and their network on success, failure, or timeout.
