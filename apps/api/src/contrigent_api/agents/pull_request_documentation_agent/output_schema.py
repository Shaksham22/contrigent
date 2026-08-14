from pydantic import BaseModel, Field


class PullRequestDocumentationResult(BaseModel):
    title: str = Field(
        min_length=1,
        max_length=120,
    )

    body: str = Field(
        min_length=1,
    )