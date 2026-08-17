from contrigent_api.models.run_record import Run


def repository_tests_succeeded(
    run: Run,
) -> bool:
    result = run.repository_test_result

    return (
        run.repository_tests_completed
        and run.repository_tests_passed is True
        and result is not None
        and result.passed
        and result.stage == "tests"
    )


def build_issue_comment(
    *,
    pull_request_number: int,
    pull_request_url: str,
    repository_tests_passed: bool,
) -> str:
    activity_sentence = (
        (
            "The system was used to investigate the issue, prepare the "
            "proposed change, run the repository tests, and create the "
            "draft pull request."
        )
        if repository_tests_passed
        else (
            "The system was used to investigate the issue, prepare the "
            "proposed change, and create the draft pull request."
        )
    )

    return (
        "Hi — I opened draft PR "
        f"#{pull_request_number} for this issue:\n\n"
        f"{pull_request_url}\n\n"
        "This comment was posted automatically by **Contrigent**, a "
        "multi-agent open-source contribution system I’m currently "
        "developing and testing. "
        f"{activity_sentence}\n\n"
        "Feedback on the proposed change is welcome. I’d also appreciate "
        "feedback on whether AI-assisted contributions like this are "
        "appropriate for this project."
    )
