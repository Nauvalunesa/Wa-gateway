# Utusan — WhatsApp Workspace

Dashboard WhatsApp multi-session dengan **React, TypeScript, Tailwind CSS, FastAPI, dan Neonize 0.5.2**.

Domain produksi: **https://utusan.chat**. Frontend React dibangun menjadi aset statis dan dilayani langsung oleh FastAPI; tidak membutuhkan server Node saat produksi.

## Fitur

- Login dan register berbasis cookie sesi, konfirmasi password, API key per akun.
- Dashboard dengan statistik nyata, grafik 7 hari, dan aktivitas terbaru.
- Pairing kode WhatsApp, status koneksi otomatis, unduh sesi, dan hapus perangkat.
- Composer teks, gambar, video, audio, dokumen, stiker, kontak, interactive, tombol, dan status.
- AI Rich Studio dengan 12 jenis blok, urutkan blok, edit konten, validasi, dan pratinjau struktur pesan.
- Pengelolaan channel WhatsApp, broadcast CSV dengan personalisasi, pencarian riwayat, dan ekspor CSV.
- Tampilan responsif untuk desktop dan ponsel; font dan aset dilayani dari server sendiri.

## Menjalankan

Gunakan Python 3.12+ dan Node 22.12+ untuk membangun frontend. FFmpeg dan libmagic dibutuhkan untuk media.

```bash
python3.12 -m venv .venv312
.venv312/bin/python -m pip install -r requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build
.venv312/bin/python main.py
```

Untuk pengembangan frontend: `npm --prefix frontend run dev`. Vite meneruskan `/api` dan `/static` ke FastAPI pada port 8880.

Konfigurasi `.env`:

```dotenv
GATEWAY_ALLOWED_HOSTS=utusan.chat,localhost:8880,127.0.0.1:8880,localhost:5173,127.0.0.1:5173
GATEWAY_SECURE_COOKIE=true
```

Gunakan `GATEWAY_SECURE_COOKIE=false` untuk pengembangan melalui HTTP lokal. Cookie signing key otomatis disimpan pada `storage/.session-secret`; `GATEWAY_SESSION_SECRET` dapat digunakan untuk menentukan key sendiri. Tidak ada akun admin bawaan: daftar melalui `/register`.

Konfigurasi PM2 tersedia di `ecosystem.config.cjs`. Setelah build frontend, jalankan `pm2 startOrReload ecosystem.config.cjs --update-env`.

## API

Dokumentasi interaktif: **https://utusan.chat/docs**. API eksternal memakai header `x-api-key`. Dashboard memakai endpoint `/api/web/*` dengan cookie sesi.

```bash
curl 'https://utusan.chat/api/send-message?to=62812xxxxxxxx&text=Halo' \
  -H 'x-api-key: YOUR_API_KEY'
```

AI Rich: `POST /api/send-airich`. Validasi tanpa mengirim: `POST /api/airich/preview` dengan payload dan header yang sama. GET `/api/send-airich` menerima `to` dan query `payload` berisi JSON.

```json
{
  "to": "62812xxxxxxxx",
  "blocks": [
    {"type": "text", "text": "**Halo!** [Dokumentasi](https://github.com/krypton-byte/neonize)"},
    {"type": "code", "language": "html", "code": "<h1>Halo</h1>"},
    {"type": "table", "table": [["Produk", "Harga"], ["Paket A", "Rp50.000"]]},
    {"type": "suggest", "suggestions": ["Lihat detail", "Info harga"]}
  ]
}
```

Jenis blok: `text`, `code`, `table`, `image`, `video`, `source`, `product`, `reels`, `post`, `tip`, `suggest`, `html`. Blok `code` menampilkan sumber; blok `html` membungkus HTML interaktif eksperimental. Tampilan akhir bergantung pada aplikasi WhatsApp penerima. Payload tidak valid menghasilkan HTTP 422. API passkey khusus dari engine lama tidak tersedia pada Neonize resmi; gunakan pairing kode.

## Pengujian

```bash
.venv312/bin/python -m unittest discover -s tests -v
npm --prefix frontend run build
```

Tes browser pada `frontend/e2e` menggunakan server uji terpisah pada `http://127.0.0.1:18880`; gunakan `TEST_BASE_URL` untuk mengganti alamat. Tes pairing dan broadcast memakai mock agar tidak menghubungi atau mengirim pesan WhatsApp.

```bash
npm --prefix frontend test
```

## Struktur

- `main.py`: API dan integrasi WhatsApp.
- `neonize_runtime.py`: adapter Neonize yang memisahkan thread koneksi jangka panjang dari pool API; `Stop`/`Disconnect` tetap bisa berjalan saat pool sibuk. Setiap worker memakai UUID berbeda agar cleanup lama tidak menghentikan penggantinya.
- `dashboard_api.py`: autentikasi, statistik, riwayat, perangkat, dan serving frontend.
- `frontend/src/`: seluruh UI React.
- `serialize.py`, `msg_store.py`: pemrosesan pesan WhatsApp.
- `storage/`: akun, riwayat, dan sesi; tidak disertakan dalam Git.
- `static/uploads/`: unggahan media.

MIT License.

### HTML interaktif (eksperimental)

AI Rich Studio menyediakan blok HTML dengan editor HTML/CSS/JavaScript, contoh Sound Test dan Dino Runner, serta pratinjau browser terisolasi. Dukungan render di WhatsApp penerima belum terverifikasi. Python membungkus HTML; JavaScript tetap berjalan di renderer penerima bila didukung.

Contoh Python: `examples/send_html.py`. Jalankan tanpa `--send` untuk menghasilkan JSON lokal. Gunakan `--send --to NOMOR --phone DEVICE` dan environment `UTUSAN_API_KEY` untuk mengirim. File contoh berada di `frontend/src/rich-examples/`. Data unifiedResponse disimpan sebagai bytes JSON UTF-8 di protobuf; serializer protobuf menghasilkan base64, jadi jangan melakukan base64 dua kali. Signature/certificate dari contoh tidak dibuat atau dianggap sah oleh gateway.
