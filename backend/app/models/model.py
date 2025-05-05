from pydantic import BaseModel


class CoderToWriter(BaseModel):
    code_response: str
    code_execution_result: str
    created_images: list[str]
