from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class _PartBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TextPart(_PartBase):
    type: Literal["text"] = "text"
    text: str


class ImagePart(_PartBase):
    type: Literal["image"] = "image"
    url: str = Field(min_length=1)
    mime: str = Field(min_length=1)
    name: str | None = None
    size: int | None = None


class AudioPart(_PartBase):
    type: Literal["audio"] = "audio"
    url: str = Field(min_length=1)
    mime: str = Field(min_length=1)
    name: str | None = None
    size: int | None = None
    duration_ms: int | None = None


class DocumentPart(_PartBase):
    type: Literal["document"] = "document"
    url: str = Field(min_length=1)
    mime: str = Field(min_length=1)
    name: str | None = None
    size: int | None = None


FormStatus = Literal["pending", "submitted", "cancelled"]


class FormPart(_PartBase):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    type: Literal["form"] = "form"
    form_id: str
    json_schema: dict[str, Any] = Field(alias="schema", serialization_alias="schema")
    status: FormStatus
    values: dict[str, Any] | None = None
    answers_event_id: str | None = None
    title: str | None = None
    description: str | None = None


ContentPart = TextPart | ImagePart | AudioPart | DocumentPart | FormPart

_content_adapter: TypeAdapter[ContentPart] = TypeAdapter(
    TextPart | ImagePart | AudioPart | DocumentPart | FormPart,
)


def parse_content_part(raw: dict[str, Any]) -> ContentPart:
    return _content_adapter.validate_python(raw)
