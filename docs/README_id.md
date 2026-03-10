# KiroaaS

<p align="center">
  <img src="../public/icon.png" alt="KiroaaS Logo" width="128" height="128">
</p>

<h3 align="center">Kiro as a Service</h3>
<p align="center">Ubah Kiro menjadi API yang kompatibel dengan OpenAI dan Anthropic dengan satu klik</p>

<p align="center">
  <a href="../README.md">🇺🇸 English</a> • <a href="README_zh.md">🇨🇳 中文</a> • <a href="README_ja.md">🇯🇵 日本語</a> • <a href="README_ko.md">🇰🇷 한국어</a> • <a href="README_ru.md">🇷🇺 Русский</a> • <a href="README_es.md">🇪🇸 Español</a> • <a href="README_pt.md">🇧🇷 Português</a> • 🇮🇩 Indonesia
</p>

<p align="center">
  <a href="https://opensource.org/licenses/AGPL-3.0"><img src="https://img.shields.io/badge/License-AGPL%203.0-blue.svg" alt="License: AGPL-3.0"></a>
  <img src="https://img.shields.io/badge/platform-macOS%20%7C%20Windows-brightgreen" alt="Platform">
  <a href="http://makeapullrequest.com"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome"></a>
</p>

<p align="center">
  <img src="../app-screenshot.webp" alt="Screenshot KiroaaS" width="800">
</p>

---

## ❤️ Sponsor

<table>
<tr>
<td width="180"><a href="https://ai18n.chat"><img src="../public/sponsors/ai18n.png" alt="ai18n" width="150"></a></td>
<td>Terima kasih kepada <a href="https://ai18n.chat">ai18n</a> atas sponsornya! ai18n adalah penyedia layanan relay API yang andal dan efisien, menawarkan relay model Claude untuk OpenClaw, Claude Code, Codex, Gemini, dan lainnya.</td>
</tr>
</table>

---

> ~~**📢 Pemberitahuan:** Versi berikutnya akan memperbaiki kompatibilitas dengan Claude Code v2.1.69+, yang mengirimkan blok konten `tool_reference` di dalam pesan `tool_result` saat menggunakan mekanisme alat tertunda ToolSearch.~~ ✅ Diperbaiki

KiroaaS (Kiro as a Service) adalah gateway desktop yang mengekspos model AI Kiro melalui API lokal yang kompatibel dengan OpenAI dan Anthropic. Gunakan alat, pustaka, dan aplikasi AI favorit Anda dengan Kiro - tanpa perlu mengubah kode.

## ✨ Fitur

| Fitur | Deskripsi |
|-------|-----------|
| 🔌 **API kompatibel OpenAI** | Endpoint `/v1/chat/completions` untuk OpenAI SDK |
| 🔌 **API kompatibel Anthropic** | Endpoint `/v1/messages` untuk Anthropic SDK |
| 🌐 **Dukungan VPN/Proxy** | Proxy HTTP/SOCKS5 untuk jaringan terbatas |
| 🧠 **Extended Thinking** | Dukungan penalaran eksklusif untuk proyek kami |
| 👁️ **Dukungan Vision** | Kirim gambar ke model |
| 🛠️ **Tool Calling** | Mendukung pemanggilan fungsi |
| 💬 **Chat bawaan** | Uji pengaturan Anda dengan antarmuka chat terintegrasi |
| 📡 **Streaming** | Dukungan streaming SSE penuh |
| 🔄 **Logika Retry** | Retry otomatis saat error (403, 429, 5xx) |
| 🔐 **Manajemen token cerdas** | Refresh otomatis sebelum kedaluwarsa |
| 🌍 **UI multibahasa** | English, 中文, 日本語, 한국어, Русский, Español, Português, Indonesia |
| 🔗 **Integrasi CC Switch** | Impor satu klik ke [CC Switch](https://github.com/farion1231/cc-switch) untuk Claude Code |
| 🔄 **Pembaruan otomatis** | Pemeriksa pembaruan bawaan |

## 📦 Instalasi

### Unduh

Unduh rilis terbaru dari [GitHub Releases](https://github.com/hnewcity/KiroaaS/releases):

| Platform | Arsitektur | Unduh |
|----------|------------|-------|
| macOS | Apple Silicon (M1/M2/M3) | [KiroaaS_aarch64.dmg](https://github.com/hnewcity/KiroaaS/releases) |
| macOS | Intel | [KiroaaS_x64.dmg](https://github.com/hnewcity/KiroaaS/releases) |
| Windows | x64 | [KiroaaS_x64-setup.exe](https://github.com/hnewcity/KiroaaS/releases) |

> Dukungan Linux segera hadir.

### Build dari sumber

```bash
# Clone repositori
git clone https://github.com/hnewcity/KiroaaS.git
cd KiroaaS

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
2. **Konfigurasi** kredensial Kiro Anda (terdeteksi otomatis jika Kiro CLI terinstal)
3. **Buat** kunci API proxy (atau gunakan yang diberikan administrator)
4. **Mulai** server
5. **Gunakan** `http://localhost:8000` sebagai endpoint API OpenAI/Anthropic Anda

### Contoh: cURL

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_PROXY_API_KEY" \
  -d '{
    "model": "claude-sonnet-4-6",
    "messages": [{"role": "user", "content": "Halo!"}]
  }'
```

### Contoh: Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="YOUR_PROXY_API_KEY"
)

response = client.chat.completions.create(
    model="claude-sonnet-4-6",
    messages=[{"role": "user", "content": "Halo!"}]
)
print(response.choices[0].message.content)
```

### Contoh: JavaScript (OpenAI SDK)

```javascript
import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: 'http://localhost:8000/v1',
  apiKey: 'YOUR_PROXY_API_KEY',
});

const response = await client.chat.completions.create({
  model: 'claude-sonnet-4-6',
  messages: [{ role: 'user', content: 'Halo!' }],
});
console.log(response.choices[0].message.content);
```

## 🔌 Kompatibel dengan

KiroaaS kompatibel dengan alat dan pustaka AI populer:

| Kategori | Alat |
|----------|------|
| **Python** | OpenAI SDK, Anthropic SDK, LangChain, LlamaIndex |
| **JavaScript** | OpenAI Node.js SDK, Anthropic SDK, Vercel AI SDK |
| **Ekstensi IDE** | Cursor, Continue, Cline, Claude Code |
| **Aplikasi Chat** | ChatGPT-Next-Web, LobeChat, Open WebUI |

## ⚙️ Konfigurasi

### Metode autentikasi

KiroaaS mendukung beberapa metode autentikasi:

| Metode | Deskripsi |
|--------|-----------|
| **Database Kiro CLI** | Deteksi otomatis kredensial dari Kiro CLI (direkomendasikan) |
| **File kredensial** | Gunakan file JSON kredensial |
| **Refresh token** | Masukkan refresh token secara manual |

### Pengaturan server

| Opsi | Default | Deskripsi |
|------|---------|-----------|
| Host | `127.0.0.1` | Alamat bind server |
| Port | `8000` | Port server |
| Kunci API proxy | - | Kunci yang diperlukan untuk autentikasi API |

### Pengaturan lanjutan

| Opsi | Deskripsi |
|------|-----------|
| URL VPN/Proxy | Proxy HTTP/SOCKS5 untuk pembatasan jaringan |
| Timeout token pertama | Timeout untuk respons awal (detik) |
| Timeout baca streaming | Timeout untuk respons streaming (detik) |

## 🛠️ Tech Stack

| Layer | Teknologi |
|-------|-----------|
| **Frontend** | React + TypeScript + Tailwind CSS |
| **Desktop** | Tauri (Rust) |
| **Backend** | Python + FastAPI |

## 🤝 Kontribusi

Kontribusi sangat diterima!

- 🐛 Laporkan bug di [GitHub Issues](https://github.com/hnewcity/KiroaaS/issues)
- 💡 Sarankan fitur
- 🔧 Kirim pull request
- 🌍 Bantu dengan terjemahan

## 📄 Lisensi

[AGPL-3.0](../LICENSE) © Kontributor KiroaaS
