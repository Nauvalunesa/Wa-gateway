"""Owner-only raw-message tools; CRM payloads are protobuf JSON, never code."""
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from google.protobuf.json_format import ParseDict, ParseError
from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import Message

MAX_RAW_BYTES = 256 * 1024


def validate_raw(payload: dict) -> Message:
    if len(json.dumps(payload, ensure_ascii=False).encode()) > MAX_RAW_BYTES:
        raise ValueError('Raw message maksimal 256 KiB')
    try:
        message = ParseDict(payload, Message())
    except (ParseError, ValueError, TypeError, RecursionError) as exc:
        raise ValueError(f'Raw message tidak valid: {exc}') from exc
    if not message.ListFields():
        raise ValueError('Raw message tidak boleh kosong')
    return message


class RawItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=100)
    kind: Literal['saved', 'action'] = 'saved'
    payload: dict

    @field_validator('name')
    @classmethod
    def name_not_empty(cls, value):
        if not value.strip(): raise ValueError('Nama tidak boleh kosong')
        return value.strip()

    @field_validator('payload')
    @classmethod
    def raw_payload(cls, value):
        validate_raw(value)
        return value


class RawRun(BaseModel):
    model_config = ConfigDict(extra='forbid')
    phone: str
    to: str = Field(min_length=7, max_length=60)
    request_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{8,64}$')


class CRMOwners(BaseModel):
    model_config = ConfigDict(extra='forbid')
    owners: list[str] = Field(default_factory=list, max_length=20)

    @field_validator('owners')
    @classmethod
    def valid_phones(cls,values):
        import re
        normalized=[value.strip().lstrip('+') for value in values]
        if any(not re.fullmatch(r'[1-9][0-9]{6,19}',value) for value in normalized):
            raise ValueError('Owner harus nomor WhatsApp dengan kode negara, tanpa spasi')
        return list(dict.fromkeys(normalized))


class JIDConversion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    phone: str
    jid: str = Field(min_length=7,max_length=60)
