# KiroaaS

**Kiro as a Service** - Turn Kiro into an OpenAI-compatible and Anthropic-compatible API with one click

🇺🇸 English • [🇨🇳 中文](docs/README_zh.md) • [🇯🇵 日本語](docs/README_ja.md) • [🇰🇷 한국어](docs/README_ko.md) • [🇷🇺 Русский](docs/README_ru.md) • [🇪🇸 Español](docs/README_es.md) • [🇧🇷 Português](docs/README_pt.md) • [🇮🇩 Indonesia](docs/README_id.md)

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL%203.0-blue.svg)](https://opensource.org/licenses/AGPL-3.0)
[![Platform](https://img.shields.io/badge/platform-macOS-brightgreen)]()
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](http://makeapullrequest.com)

KiroaaS (Kiro as a Service) is a desktop gateway that exposes Kiro's AI models through a local OpenAI-compatible and Anthropic-compatible API. Use your favorite AI tools, libraries, and applications with Kiro - no code changes required.

<!--
## Screenshots

![KiroaaS Screenshot](docs/screenshot.png)
-->

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🔌 OpenAI-compatible API | `/v1/chat/completions` endpoint for OpenAI SDK |
| 🔌 Anthropic-compatible API | `/v1/messages` endpoint for Anthropic SDK |
| 🌐 VPN/Proxy Support | HTTP/SOCKS5 proxy for restricted networks |
| 🧠 Extended Thinking | Reasoning support exclusive to our project |
| 👁️ Vision Support | Send images to model |
| 🛠️ Tool Calling | Supports function calling |
| 💬 Full Message History | Passes complete conversation context |
| 📡 Streaming | Full SSE streaming support |
| 🔄 Retry Logic | Automatic retries on errors (403, 429, 5xx) |
| 📋 Extended Model List | Including versioned models |
| 🔐 Smart Token Management | Automatic refresh before expiration |

## 📦 Installation

### Download

Download the latest release:

| Platform | Download |
|----------|----------|
| macOS | [KiroaaS.dmg](https://github.com/hnewcity/KiroaaS/releases) |

> Windows and Linux support coming soon.

### Build from Source

```bash
# Clone the repo
git clone https://github.com/hnewcity/KiroaaS.git
cd kiro-gateway

# Install dependencies
npm install
cd python-backend && pip install -r requirements.txt && cd ..

# Run in dev mode
npm run tauri:dev

# Or build for production
npm run tauri:build
```

## 🚀 Quick Start

1. **Launch** KiroaaS
2. **Configure** your Kiro credentials (auto-detected if available)
3. **Start** the server
4. **Use** `http://localhost:8000` as your OpenAI API endpoint

```bash
# Example: Chat with Kiro using curl
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "kiro",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

## 🔌 Works With

KiroaaS is compatible with popular AI tools and libraries:

- **Python**: OpenAI SDK, LangChain, LlamaIndex
- **JavaScript**: OpenAI Node.js SDK, Vercel AI SDK
- **Apps**: Cursor, Continue, ChatGPT-Next-Web, and more

```python
# Python example
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="not-needed"
)

response = client.chat.completions.create(
    model="kiro",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

## ⚙️ Configuration

| Option | Default | Description |
|--------|---------|-------------|
| Host | `127.0.0.1` | Server bind address |
| Port | `8000` | Server port |
| Region | `us-east-1` | Kiro region |

Advanced options available in the Settings panel.

## 🛠️ Tech Stack

- **Frontend**: React + TypeScript + Tailwind CSS
- **Desktop**: Tauri (Rust)
- **Backend**: Python + FastAPI

## 🤝 Contributing

Contributions are welcome! Feel free to:

- 🐛 Report bugs
- 💡 Suggest features
- 🔧 Submit pull requests

## 📄 License

[AGPL-3.0](LICENSE) © KiroaaS Contributors
