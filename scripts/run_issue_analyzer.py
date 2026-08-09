import asyncio
import json

from dotenv import load_dotenv

from contrigent_api.services.issue_analysis_runner import analyze_sample_project


async def main() -> None:
    load_dotenv()

    analysis, usage = await analyze_sample_project("python-missing-display-name")

    print("\n=== ISSUE ANALYSIS ===\n")
    print(
        json.dumps(
            analysis.model_dump(mode="json"),
            indent=2,
        )
    )

    print("\n=== TOKEN USAGE ===\n")
    print(f"API requests: {usage.requests}")
    print(f"Input tokens: {usage.input_tokens}")
    print(f"Output tokens: {usage.output_tokens}")
    print(f"Total tokens: {usage.total_tokens}")


if __name__ == "__main__":
    asyncio.run(main())