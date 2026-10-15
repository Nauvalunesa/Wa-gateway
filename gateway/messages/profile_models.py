"""Input validation for per-device WhatsApp profile changes."""
from pydantic import BaseModel, Field, field_validator
from typing import Literal

PRIVACY_OPTIONS = {
    "read_receipts": ("all", "none"),
    "last_seen": ("all", "contacts", "none"),
    "online": ("all", "match_last_seen"),
    "profile_photo": ("all", "contacts", "none"),
    "group_add": ("all", "contacts", "none"),
    "calls": ("all", "known"),
}


class ProfileNamePayload(BaseModel):
    phone: str
    name: str = Field(min_length=1, max_length=25)

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value):
        if not value.strip():
            raise ValueError("Nama profil tidak boleh kosong")
        return value.strip()


class ProfileAboutPayload(BaseModel):
    phone: str
    about: str = Field(max_length=139)


class ProfilePreferences(BaseModel):
    auto_read: bool = False
    auto_read_scope: Literal["private", "all"] = "private"


class ProfilePreferencesPayload(ProfilePreferences):
    phone: str


class ProfilePrivacyPayload(BaseModel):
    phone: str
    setting: Literal["read_receipts", "last_seen", "online", "profile_photo", "group_add", "calls"]
    value: str

    @field_validator("value")
    @classmethod
    def supported_value(cls, value, info):
        if value not in PRIVACY_OPTIONS.get(info.data.get("setting"), ()):
            raise ValueError("Nilai privasi tidak didukung untuk pengaturan ini")
        return value
