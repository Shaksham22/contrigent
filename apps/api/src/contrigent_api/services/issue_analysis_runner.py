from agents import Runner
from contrigent_api.services.worker_discovery import discover_workers
from contrigent_api.agents.issue_analyzer.agent import issue_analyzer
from contrigent_api.agents.issue_analyzer.output_schema import (
    IssueAnalysis,
    WorkerAssignment,
)
from contrigent_api.services.sample_project_reader import (
    SampleProjectContext,
    load_sample_project,
)


def build_available_workers_section(
    workers: list[dict],
) -> str:
    enabled_workers = [
        worker
        for worker in workers
        if worker.get("enabled") is True
    ]

    if not enabled_workers:
        return "No worker agents are currently available."

    worker_sections = []

    for worker in enabled_workers:
        capabilities = ", ".join(
            worker.get("capabilities", [])
        )

        worker_sections.append(
            f"""Worker ID: {worker["id"]}
Name: {worker["name"]}
Description: {worker["description"]}
Capabilities: {capabilities or "None listed"}"""
        )

    return "\n\n".join(worker_sections)

def build_analysis_input(
    sample_project: SampleProjectContext,
    workers: list[dict],
) -> str:
    repository_files = "\n\n".join(
        f"--- FILE: {path} ---\n{content}"
        for path, content in sample_project.files.items()
    )

    available_workers = build_available_workers_section(
        workers
    )

    return f"""
=== AVAILABLE WORKERS ===
{available_workers}

=== GITHUB ISSUE ===
{sample_project.issue}

=== README ===
{sample_project.readme}

=== CONTRIBUTING INSTRUCTIONS ===
{sample_project.contributing}

=== REPOSITORY FILES ===
{repository_files}
""".strip()


async def analyze_sample_project(name: str):
    sample_project = load_sample_project(name)

    workers = discover_workers()

    agent_input = build_analysis_input(
        sample_project,
        workers,
    )

    result = await Runner.run(
        issue_analyzer,
        agent_input,
        max_turns=3,
    )

    if not isinstance(
        result.final_output,
        IssueAnalysis,
    ):
        raise TypeError(
            "Issue Analyzer returned an unexpected output type."
        )
    validate_worker_assignments(
    result.final_output.worker_assignments,
    workers,
)

    return (
        result.final_output,
        result.context_wrapper.usage,
    )

def validate_worker_assignments(
    worker_assignments: list[WorkerAssignment],
    available_workers: list[dict],
) -> None:
    available_worker_ids = {
        worker["id"]
        for worker in available_workers
        if worker.get("enabled") is True
    }

    selected_worker_ids = [
        assignment.worker_id
        for assignment in worker_assignments
    ]

    unknown_workers = (
        set(selected_worker_ids)
        - available_worker_ids
    )

    if unknown_workers:
        raise ValueError(
            "Issue Analyzer assigned unavailable workers: "
            + ", ".join(sorted(unknown_workers))
        )

    if len(selected_worker_ids) != len(
        set(selected_worker_ids)
    ):
        raise ValueError(
            "Issue Analyzer assigned the same worker more than once."
        )

    assignment_orders = [
        assignment.order
        for assignment in worker_assignments
    ]

    if len(assignment_orders) != len(
        set(assignment_orders)
    ):
        raise ValueError(
            "Worker assignment order values must be unique."
        )

    assignments_by_worker_id = {
        assignment.worker_id: assignment
        for assignment in worker_assignments
    }

    for assignment in worker_assignments:
        for dependency_id in assignment.depends_on:
            dependency = assignments_by_worker_id.get(
                dependency_id
            )

            if dependency is None:
                raise ValueError(
                    f"Worker '{assignment.worker_id}' depends on "
                    f"unassigned worker '{dependency_id}'."
                )

            if dependency.order >= assignment.order:
                raise ValueError(
                    f"Worker '{assignment.worker_id}' depends on "
                    f"'{dependency_id}', but dependencies must run earlier."
                )