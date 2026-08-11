from pydantic import BaseModel, Field


class FileReplacement(BaseModel):
    file_path: str
    reason: str
    replacement_content: str


class WorkerResult(BaseModel):
    summary: str
    findings: list[str] = Field(default_factory=list)
    files_to_replace: list[FileReplacement] = Field(
        default_factory=list
    )