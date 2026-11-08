from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, min_length=1, max_length=100)
    top_k: int | None = Field(default=None, ge=1, le=10)

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message must not be blank.")
        return value.strip()


class Source(BaseModel):
    question: str
    source: str
    similarity: float


class ChatResponse(BaseModel):
    answer: str
    session_id: str
    sources: list[Source]

