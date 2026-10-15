"""Validated customer-service menus and conversation settings."""
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class CSOption(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    label: str = Field(min_length=1, max_length=25)
    target: str

    @field_validator("label")
    @classmethod
    def nonempty_label(cls, value):
        if not value.strip():
            raise ValueError("Label tombol tidak boleh kosong")
        return value.strip()


class CSNode(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    title: str = Field(min_length=1, max_length=60)
    text: str = Field(min_length=1, max_length=4000)
    handoff: bool = False
    options: list[CSOption] = Field(default_factory=list, max_length=10)

    @field_validator("title", "text")
    @classmethod
    def nonempty_content(cls, value):
        if not value.strip():
            raise ValueError("Judul dan pesan tidak boleh kosong")
        return value.strip()


class CSConfig(BaseModel):
    enabled: bool = False
    business_name: str = Field(default="Layanan Pelanggan", min_length=1, max_length=80)
    admin_phone: str = ""
    devices: list[str] = Field(default_factory=list, max_length=20)
    reply_mode: Literal["buttons", "list", "legacy", "text"] = "buttons"
    start_on_first_message: bool = True
    keywords: list[str] = Field(default_factory=lambda: ["menu", "halo", "mulai"], min_length=1, max_length=20)
    cooldown_seconds: int = Field(default=2, ge=0, le=60)
    session_ttl_minutes: int = Field(default=30, ge=1, le=1440)
    inactivity_minutes: int = Field(default=3, ge=1, le=1440)
    closing_message: str = Field(default="Percakapan diakhiri karena tidak ada respons. Terima kasih telah menghubungi kami. Ketik menu untuk memulai kembali.", min_length=1, max_length=2000)
    handoff_minutes: int = Field(default=60, ge=1, le=1440)
    root_node: str = "menu"
    nodes: list[CSNode] = Field(min_length=1, max_length=30)

    @field_validator("admin_phone")
    @classmethod
    def validate_admin(cls, value):
        value = value.strip()
        if value and not re.fullmatch(r"[1-9][0-9]{6,14}", value):
            raise ValueError("Nomor admin harus 7–15 digit dengan kode negara, tanpa +")
        return value

    @field_validator("devices")
    @classmethod
    def validate_devices(cls, values):
        if any(not re.fullmatch(r"[1-9][0-9]{6,14}", value) for value in values):
            raise ValueError("Nomor perangkat harus menggunakan kode negara")
        return list(dict.fromkeys(values))

    @field_validator("business_name", "closing_message")
    @classmethod
    def validate_name(cls, value):
        if not value.strip():
            raise ValueError("Nama layanan tidak boleh kosong")
        return value.strip()

    @field_validator("keywords")
    @classmethod
    def validate_keywords(cls, values):
        if any(not value.strip() or len(value) > 50 for value in values):
            raise ValueError("Kata pemicu harus 1–50 karakter")
        return list(dict.fromkeys(value.strip().casefold() for value in values))

    @model_validator(mode="after")
    def validate_flow(self):
        ids = {node.id for node in self.nodes}
        if len(ids) != len(self.nodes) or self.root_node not in ids:
            raise ValueError("ID halaman harus unik dan menu awal harus tersedia")
        if self.enabled and any(node.handoff for node in self.nodes) and not self.admin_phone:
            raise ValueError("Isi nomor admin sebelum mengaktifkan alur Hubungi Admin")
        for node in self.nodes:
            if len({option.id for option in node.options}) != len(node.options):
                raise ValueError(f"ID tombol pada {node.id} harus unik")
            if any(option.target not in ids for option in node.options):
                raise ValueError(f"Tujuan tombol pada {node.id} tidak ditemukan")
            if self.reply_mode == "legacy" and len(node.options) > 3:
                raise ValueError("Tombol legacy maksimal 3 pilihan per halaman")
        return self


class CSPreviewPayload(BaseModel):
    config: CSConfig
    text: str = Field(default="menu", max_length=500)
    current_node: str | None = None
    name: str = Field(default="Pelanggan", max_length=80)


def default_cs_config() -> CSConfig:
    back = [{"id": "menu", "label": "Menu utama", "target": "menu"}]
    return CSConfig(nodes=[
        CSNode(id="menu", title="Selamat datang", text="Halo {name}! Selamat datang di {business}. Pilih layanan di bawah atau ketik nomor pilihan.", options=[
            CSOption(id="produk", label="Produk & layanan", target="produk"),
            CSOption(id="faq", label="Bantuan / FAQ", target="faq"),
            CSOption(id="admin", label="Hubungi admin", target="admin"),
        ]),
        CSNode(id="produk", title="Produk & layanan", text="Silakan tulis daftar produk, harga, atau tautan katalog Anda di halaman ini.", options=back),
        CSNode(id="faq", title="Pusat bantuan", text="Informasi apa yang Anda butuhkan?", options=[
            CSOption(id="jam", label="Jam operasional", target="jam"),
            CSOption(id="alamat", label="Alamat & kontak", target="alamat"),
            CSOption(id="menu", label="Menu utama", target="menu"),
        ]),
        CSNode(id="jam", title="Jam operasional", text="Isi jam layanan dan hari operasional bisnis Anda di sini.", options=back),
        CSNode(id="alamat", title="Alamat & kontak", text="Isi alamat, website, dan kontak bisnis Anda di sini.", options=back),
        CSNode(id="admin", title="Hubungi admin", text="Silakan hubungi admin melalui kontak di bawah. Bot dijeda sementara untuk percakapan ini. Ketik menu untuk kembali ke layanan otomatis.", handoff=True, options=back),
    ])
