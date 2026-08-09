from pydantic import BaseModel


class FileReplacement(BaseModel):
    file_path: str
    reason: str
    replacement_content: str


class CodeEditResult(BaseModel):
    summary: str
    files_to_replace: list[FileReplacement]