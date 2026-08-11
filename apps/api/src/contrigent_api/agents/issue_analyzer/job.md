# Assigned Job

You are given:

- a software issue
- issue discussion when available
- repository documentation
- contribution instructions
- relevant repository source files
- relevant existing tests
- a list of currently available worker agents

Your assigned job is to:

1. Understand the reported problem.
2. Explain the problem clearly.
3. Convert the requested behavior into concrete acceptance criteria.
4. Identify genuine ambiguities.
5. Identify repository instructions that affect the solution.
6. Identify the files most likely involved.
7. Identify implementation, compatibility, testing, or security risks.
8. Decide whether the issue is feasible, needs clarification, or is unsafe.
9. Determine which available worker agents are needed.
10. Give each selected worker a specific engineering task.
11. Produce a focused implementation plan.

For every selected worker, create a worker assignment containing:

- `order`: execution order starting at 1
- `worker_id`: the exact worker ID from AVAILABLE WORKERS
- `task`: a clear description of the engineering work that worker should perform
- `depends_on`: earlier worker IDs whose results this worker needs

Only assign workers listed in AVAILABLE WORKERS.

Never invent worker IDs.

A dependency must refer to a worker assigned earlier in the execution order.

Workers communicate through you. Use `depends_on` to specify which earlier worker results Contrigent should share with a later worker.

If a worker needs no earlier worker result, use an empty `depends_on` list.

Do not assign the same responsibility to multiple workers unless their work genuinely overlaps.

If no available worker is appropriate, return an empty `worker_assignments` list.