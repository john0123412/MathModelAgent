from pydantic import BaseModel
from typing import Any


class CoordinatorToModeler(BaseModel):
    questions: dict
    ques_count: int


class ModelerToCoder(BaseModel):
    questions_solution: dict[str, str]


class CoderToWriter(BaseModel):
    code_response: str
    code_output: str
    created_images: list[str]


class WriterResponse(BaseModel):
    response_content: Any
    footnotes: list[str] | None = None
