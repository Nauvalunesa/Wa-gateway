# Arsitektur backend Utusan

Backend berada pada package `gateway/`. `main.py` hanya menjadi entry point agar `python main.py`, `uvicorn main:app`, dan konfigurasi PM2 tetap dapat digunakan. Pemisahan ini mempertahankan URL, nama parameter, validasi payload, autentikasi, dan struktur respons yang sudah ada.

## Alur aplikasi

1. Entry point mengimpor `app` dari `gateway.application`.
2. `gateway.config` memuat `.env`; `create_app()` membuat direktori runtime dan mengambil signing key.
3. Factory memasang middleware CORS, pemeriksaan host, cookie sesi, router API, dan dashboard.
4. Lifespan menginisialisasi database lalu memulihkan perangkat dari `storage/<username>/sessions/*.sqlite3`.
5. Router memvalidasi request, mengambil klien milik pengguna, memanggil operasi WhatsApp, dan mencatat history.
6. Event pesan dari klien diterjemahkan melalui serializer dan diproses auto-reply bila sesuai aturan.
7. Shutdown menghentikan klien yang terdaftar.

Import model, builder, atau service tidak menjalankan factory aplikasi maupun membuat database. Koneksi WhatsApp dimulai pada lifespan atau permintaan pairing, bukan saat import modul.

## Pembagian direktori

| Modul | Tanggung jawab |
| --- | --- |
| `application.py` | Factory FastAPI, middleware, static mount, registrasi router |
| `config.py` | `.env`, lokasi source frontend, direktori runtime, signing key |
| `lifecycle.py` | Startup, pemulihan sesi, shutdown |
| `middleware.py` | Host yang dapat membuka endpoint internal |
| `security.py` | Password bcrypt, API key, sesi pengguna, origin autentikasi |
| `database.py` | SQLite akun, migrasi history, log pesan |
| `state.py` | Registry klien, status, pairing lock, task cleanup, cache auto-reply |
| `whatsapp/clients.py` | Event koneksi/pesan, QR-ready, PairPhone, retry dan cleanup |
| `whatsapp/runtime.py` | Thread native khusus agar koneksi tidak menghabiskan executor API |
| `whatsapp/addressing.py` | Normalisasi nomor, JID/channel URL, ekspansi mention |
| `whatsapp/serialization.py` | `Mess`, `QuotedMess`, metadata/media pesan |
| `messages/models.py` | Model request Pydantic untuk pesan, blok AI Rich, dan blast |
| `messages/cards.py` | Mapping jenis kartu Neonize |
| `messages/airich.py` | Builder blok/raw/HTML menjadi protobuf |
| `messages/interactive.py` | Normalisasi field native-flow dan validasi struktur |
| `messages/store.py` | Cache pesan yang dipakai quoted reply |
| `services/auto_reply.py` | Baca/simpan aturan, matching, deduplikasi dan cooldown |
| `services/blast.py` | Rotasi perangkat, personalisasi dan delay broadcast |

`routes/` berisi modul `devices`, `messages`, `interactive`, `airich`, `groups`, `newsletters`, `status`, `utilities`, `uploads`, `blast`, dan `dashboard`. Setiap router API mempunyai `router = APIRouter()`. Dashboard mendaftarkan endpoint cookie, middleware origin, dan halaman SPA melalui `register_dashboard(app)`.

## Aturan dependensi

- Entry point mengimpor aplikasi; aplikasi menyusun router dan lifecycle.
- Router mengimpor model, autentikasi, database, layanan, serta helper WhatsApp.
- Layanan memakai builder/model/database/state tanpa mengimpor router.
- Model/builder tidak mengimpor aplikasi atau router.
- Modul tidak mengimpor `main.py` dan tidak memakai wildcard import.
- Semua klien aktif berasal dari satu registry `gateway.state.clients`.

Registry dan cache berada dalam memori **per proses**. Factory membuat objek FastAPI baru tetapi tidak membuat registry WhatsApp terpisah. Deployment tetap menggunakan satu proses gateway. Beberapa worker dengan database sesi yang sama dapat saling berebut koneksi; pemisahan file bukan perubahan menjadi layanan terdistribusi.

## Contoh menambah endpoint

Tambahkan handler berikut pada router fitur yang sesuai, misalnya `gateway/routes/messages.py`. Contoh ini hanya memperlihatkan pola implementasi; endpoint `/api/send-example` belum didaftarkan dalam produk.

```python
from fastapi import Depends, HTTPException

from gateway.database import log_message
from gateway.security import verify_api_key
from gateway.whatsapp.addressing import get_actual_jid
from gateway.whatsapp.clients import get_client


@router.post("/api/send-example")
async def send_example(
    to: str,
    text: str,
    phone: str | None = None,
    username: str = Depends(verify_api_key),
):
    client, device = get_client(username, phone)
    if client is None:
        raise HTTPException(503, "Perangkat WhatsApp tidak terhubung")
    target = await get_actual_jid(client, to)
    await client.send_message(target, text)
    await log_message(username, f"DEVICE({device})", to, text, "OUTGOING")
    return {"success": True, "to": to}
```

Parameter contoh di atas berupa query, termasuk pada POST. Gunakan model Pydantic pada `messages/models.py` bila endpoint membutuhkan JSON body. `verify_api_key` menerima autentikasi cookie dashboard maupun API key eksternal seperti endpoint yang sudah ada.

Untuk fitur yang memiliki router baru, import modulnya di `gateway/application.py` dan tambahkan ke daftar `include_router`. Untuk path internal di luar `/api/web/`, periksa pula cakupan middleware origin di dashboard. Tambahkan pengujian autentikasi, validasi input, dan perilaku pengiriman sebelum menggunakannya di produksi.

## Pengujian dan mock

Patch nama dependency pada modul handler yang sedang diuji:

```python
from unittest.mock import AsyncMock, patch
from gateway.routes import airich

with patch.object(airich, "get_client", return_value=(client, "device")), \
     patch.object(airich, "log_message", AsyncMock()):
    response = await airich.api_send_airich_post(request, payload, username="tester")
```

Mock pada `main.get_client` tidak lagi tersedia karena entry point tidak memiliki logika layanan. Tes API tetap dapat menggunakan `main.app` atau factory `create_app()`. Jalankan tes dengan direktori runtime kosong agar startup tidak memulihkan sesi produksi. Jangan menjalankan dua server pada salinan sesi yang sama.

```bash
PYTHONPATH=. .venv312/bin/python -m unittest discover -s tests -v
```

Tes integrasi mencakup pengiriman melalui seluruh jenis composer, cookie/API key, pairing retry, callback klien lama, auto-reply, protobuf, factory aplikasi, dan import layanan tanpa side effect runtime. Pemisahan awal juga diperiksa dengan membandingkan seluruh OpenAPI sebelum/sesudah refactor.

## Lokasi data dan frontend

Path runtime `storage/` dan `static/uploads/` tetap relatif terhadap working directory proses. Jalankan dari akar repository; PM2 mengatur `cwd` lewat `ecosystem.config.cjs`.

Lokasi aset React dihitung dari `PROJECT_ROOT` pada `config.py`, bukan lokasi file router dashboard. Memindahkan handler ke `gateway/routes/` tidak mengubah lokasi `frontend/dist/`. Aset build tetap dibuat menggunakan `npm --prefix frontend run build`.

Database atau sesi tidak dipindahkan oleh refactor. Update tetap memakai prosedur backup, dependency install, build, dan restart dalam README.
