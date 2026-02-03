# KiroaaS

> 🚀 Ubah Kiro menjadi API yang kompatibel dengan OpenAI dengan satu klik

[🇺🇸 English](../README.md) • [🇨🇳 中文](README_zh.md) • [🇯🇵 日本語](README_ja.md) • [🇰🇷 한국어](README_ko.md) • [🇷🇺 Русский](README_ru.md) • [🇪🇸 Español](README_es.md) • [🇧🇷 Português](README_pt.md) • 🇮🇩 Indonesia

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL%203.0-blue.svg)](https://opensource.org/licenses/AGPL-3.0)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows%20%7C%20Linux-lightgrey)]()
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](http://makeapullrequest.com)

KiroaaS (Kiro as a Service) adalah gateway desktop yang mengekspos model AI Kiro melalui API lokal yang kompatibel dengan OpenAI. Gunakan alat, pustaka, dan aplikasi AI favorit Anda dengan Kiro - tanpa perlu mengubah kode.

## ✨ Fitur

| Fitur | Deskripsi |
|-------|-----------|
| 🔌 API kompatibel OpenAI | Bekerja dengan alat apa pun yang kompatibel dengan OpenAI |
| 🔌 API kompatibel Anthropic | Endpoint native `/v1/messages` |
| 🌐 Dukungan VPN/Proxy | Proxy HTTP/SOCKS5 untuk jaringan terbatas |
| 🧠 Extended Thinking | Dukungan penalaran eksklusif untuk proyek kami |
| 👁️ Dukungan Vision | Kirim gambar ke model |
| 🛠️ Tool Calling | Mendukung pemanggilan fungsi |
| 💬 Riwayat pesan lengkap | Meneruskan konteks percakapan lengkap |
| 📡 Streaming | Dukungan streaming SSE penuh |
| 🔄 Logika Retry | Retry otomatis saat error (403, 429, 5xx) |
| 📋 Daftar model diperluas | Termasuk model berversi |
| 🔐 Manajemen token cerdas | Refresh otomatis sebelum kedaluwarsa |

## 📦 Instalasi

### Unduh

Unduh rilis terbaru:

| Platform | Unduh |
|----------|-------|
| macOS | [KiroaaS.dmg](https://github.com/Jwadow/kiro-gateway/releases) |

> Dukungan Windows dan Linux segera hadir.

### Build dari sumber

```bash
# Clone repositori
git clone https://github.com/Jwadow/kiro-gateway.git
cd kiro-gateway

# Instal dependensi
npm install
cd python-backend && pip install -r requirements.txt && cd ..

# Jalankan dalam mode pengembangan
npm run tauri:dev

# Atau build untuk produksi
npm run tauri:build
```

## 🚀 Mulai cepat

1. **Jalankan** KiroaaS
2. **Konfigurasi** kredensial Kiro Anda (terdeteksi otomatis jika tersedia)
3. **Mulai** server
4. **Gunakan** `http://localhost:8000` sebagai endpoint API OpenAI Anda

```bash
# Contoh: Chat dengan Kiro menggunakan curl
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "kiro",
    "messages": [{"role": "user", "content": "Halo!"}]
  }'
```

## 🔌 Kompatibel dengan

KiroaaS kompatibel dengan alat dan pustaka AI populer:

- **Python**: OpenAI SDK, LangChain, LlamaIndex
- **JavaScript**: OpenAI Node.js SDK, Vercel AI SDK
- **Aplikasi**: Cursor, Continue, ChatGPT-Next-Web, dan lainnya

```python
# Contoh Python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="not-needed"
)

response = client.chat.completions.create(
    model="kiro",
    messages=[{"role": "user", "content": "Halo!"}]
)
```

## ⚙️ Konfigurasi

| Opsi | Default | Deskripsi |
|------|---------|-----------|
| Host | `127.0.0.1` | Alamat bind server |
| Port | `8000` | Port server |
| Region | `us-east-1` | Region Kiro |

Opsi lanjutan tersedia di panel Pengaturan.

## 🛠️ Tech Stack

- **Frontend**: React + TypeScript + Tailwind CSS
- **Desktop**: Tauri (Rust)
- **Backend**: Python + FastAPI

## 🤝 Kontribusi

Kontribusi sangat diterima!

- 🐛 Laporkan bug
- 💡 Sarankan fitur
- 🔧 Kirim pull request

## 📄 Lisensi

[AGPL-3.0](../LICENSE) © Kontributor KiroaaS
