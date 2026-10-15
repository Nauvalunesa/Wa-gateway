"""Validated request models for messages and broadcasts."""
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from gateway.messages.cards import AIRICH_CARDS


class BlastRequest(BaseModel):
    phone_data: list # [{'phone': '628...', 'name': 'John'}, ...]
    message: str
    delay_min: int = 5
    delay_max: int = 15
    devices: list # ['628...', ...]


class LocationSendPayload(BaseModel):
    to: str
    phone: Optional[str] = None
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    name: Optional[str] = None
    address: Optional[str] = None


class PollSendPayload(BaseModel):
    to: str
    phone: Optional[str] = None
    question: str = Field(min_length=1, max_length=255)
    options: List[str] = Field(min_length=2, max_length=12)
    allow_multiple: bool = False

    @field_validator("question")
    @classmethod
    def nonempty_question(cls, value):
        if not value.strip():
            raise ValueError("Pertanyaan polling tidak boleh kosong.")
        return value.strip()


class ReactionSendPayload(BaseModel):
    to: str
    phone: Optional[str] = None
    message_id: str = Field(min_length=1)
    reaction: str = Field(min_length=1, max_length=8)
    sender: Optional[str] = None


class InteractivePayload(BaseModel):
    to: str
    payload: dict
    phone: Optional[str] = None
    media_url: Optional[str] = None
    media_type: Optional[str] = "image" # image or video
    mentions: Optional[str] = None
    hd: bool = False


class ButtonV2ItemPayload(BaseModel):
    display_text: str = Field(min_length=1, max_length=25)
    button_id: Optional[str] = None


class ButtonV2Payload(BaseModel):
    to: str
    phone: Optional[str] = None
    title: Optional[str] = None
    subtitle: Optional[str] = None
    body: str = Field(min_length=1)
    footer: Optional[str] = None
    thumbnail_url: Optional[str] = None
    buttons: List[ButtonV2ItemPayload] = Field(min_length=1, max_length=3)
    mentions: Optional[str] = None


class AIRichBlock(BaseModel):
    type: Literal["text", "code", "table", "image", "video", "source", "product", "reels", "post", "tip", "suggest", "html"]
    text: Optional[str] = None
    latex: bool = True
    hyperlink: bool = True
    citation: bool = True
    language: Optional[str] = None
    html: Optional[str] = Field(default=None, max_length=500000)
    trusted_sources: List[str] = Field(default_factory=list)
    code: Optional[str] = None
    table: Optional[List[List[str]]] = None
    url: Optional[Union[str, List[str]]] = None
    duration: int = Field(default=0, ge=0)
    source: Optional[Union[Dict, List[Dict]]] = None
    product: Optional[Union[Dict, List[Dict]]] = None
    reel: Optional[Union[Dict, List[Dict]]] = None
    post: Optional[Union[Dict, List[Dict]]] = None
    suggestions: Optional[Union[str, List[str]]] = None

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, value):
        return value.lower() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_content(self):
        field = {"text": "text", "tip": "text", "code": "code", "table": "table",
                 "image": "url", "video": "url", "source": "source", "product": "product",
                 "reels": "reel", "post": "post", "suggest": "suggestions", "html": "html"}[self.type]
        value = getattr(self, field)
        if not value or isinstance(value, list) and any(not item for item in value):
            raise ValueError(f"{self.type} requires a nonempty {field}")
        if self.type == "code" and not self.language:
            raise ValueError("code requires language; use language=html to display HTML source")
        if self.type == "table" and any(len(row) != len(value[0]) for row in value):
            raise ValueError("table rows must have the same number of columns")
        if self.type in AIRICH_CARDS:
            for item in value if isinstance(value, list) else [value]:
                try:
                    AIRICH_CARDS[self.type](**item)
                except TypeError as exc:
                    raise ValueError(str(exc)) from exc
        return self


class AIRichPayload(BaseModel):
    to: str = Field(min_length=1)
    phone: Optional[str] = None
    title: Optional[str] = None
    footer: Optional[str] = None
    mentions: Optional[str] = None
    blocks: List[AIRichBlock] = Field(default_factory=list)
    submessages: Optional[List[Dict[str, Any]]] = None
    unified: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def validate_mode(self):
        if (self.submessages is None) != (self.unified is None):
            raise ValueError("raw mode requires both submessages and unified")
        if self.submessages is not None and self.blocks:
            raise ValueError("choose blocks or raw mode")
        if self.submessages is None and not self.blocks:
            raise ValueError("provide at least one AI Rich block")
        return self
