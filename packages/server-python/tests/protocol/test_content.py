import pytest
from pydantic import ValidationError
from rfnry_chat_protocol import (
    AudioPart,
    ContentPart,
    DocumentPart,
    FormPart,
    ImagePart,
    TextPart,
    parse_content_part,
)


def test_text_part() -> None:
    p = TextPart(text="hello")
    assert p.type == "text"


def test_image_part_requires_url_and_mime() -> None:
    p = ImagePart(url="https://cdn.example.com/x.png", mime="image/png")
    assert p.type == "image"
    with pytest.raises(ValidationError):
        ImagePart(url="https://x", mime="")


def test_audio_with_duration() -> None:
    p = AudioPart(url="https://x/a.mp3", mime="audio/mpeg", duration_ms=42000)
    assert p.duration_ms == 42000


def test_document_part() -> None:
    p = DocumentPart(url="https://x/d.pdf", mime="application/pdf", name="r.pdf")
    assert p.name == "r.pdf"


def test_form_part_pending() -> None:
    p = FormPart(form_id="f1", json_schema={"type": "object"}, status="pending")
    assert p.values is None
    assert p.answers_event_id is None


def test_form_part_submitted() -> None:
    p = FormPart(
        form_id="f1",
        json_schema={"type": "object"},
        status="submitted",
        values={"name": "Alice"},
        answers_event_id="evt_orig",
    )
    assert p.status == "submitted"
    assert p.values == {"name": "Alice"}


def test_parse_dispatches_on_type() -> None:
    raw = {"type": "text", "text": "hi"}
    parsed: ContentPart = parse_content_part(raw)
    assert isinstance(parsed, TextPart)


def test_parse_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        parse_content_part({"type": "video", "url": "https://x"})
