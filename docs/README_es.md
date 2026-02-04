# KiroaaS

> 🚀 Convierte Kiro en una API compatible con OpenAI con un solo clic

[🇺🇸 English](../README.md) • [🇨🇳 中文](README_zh.md) • [🇯🇵 日本語](README_ja.md) • [🇰🇷 한국어](README_ko.md) • [🇷🇺 Русский](README_ru.md) • 🇪🇸 Español • [🇧🇷 Português](README_pt.md) • [🇮🇩 Indonesia](README_id.md)

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL%203.0-blue.svg)](https://opensource.org/licenses/AGPL-3.0)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows%20%7C%20Linux-lightgrey)]()
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](http://makeapullrequest.com)

KiroaaS (Kiro as a Service) es una pasarela de escritorio que expone los modelos de IA de Kiro a través de una API local compatible con OpenAI. Usa tus herramientas, bibliotecas y aplicaciones de IA favoritas con Kiro, sin necesidad de cambiar el código.

## ✨ Características

| Característica | Descripción |
|----------------|-------------|
| 🔌 API compatible con OpenAI | Funciona con cualquier herramienta compatible con OpenAI |
| 🔌 API compatible con Anthropic | Endpoint nativo `/v1/messages` |
| 🌐 Soporte VPN/Proxy | Proxy HTTP/SOCKS5 para redes restringidas |
| 🧠 Pensamiento extendido | Soporte de razonamiento exclusivo de nuestro proyecto |
| 👁️ Soporte de visión | Envía imágenes al modelo |
| 🛠️ Llamada de herramientas | Soporta llamadas a funciones |
| 💬 Historial completo de mensajes | Pasa el contexto completo de la conversación |
| 📡 Streaming | Soporte completo de streaming SSE |
| 🔄 Lógica de reintentos | Reintentos automáticos en errores (403, 429, 5xx) |
| 📋 Lista extendida de modelos | Incluyendo modelos versionados |
| 🔐 Gestión inteligente de tokens | Actualización automática antes de expirar |

## 📦 Instalación

### Descargar

Descarga la última versión:

| Plataforma | Descargar |
|------------|-----------|
| macOS | [KiroaaS.dmg](https://github.com/hnewcity/KiroaaS/releases) |

> Soporte para Windows y Linux próximamente.

### Compilar desde el código fuente

```bash
# Clonar el repositorio
git clone https://github.com/hnewcity/KiroaaS.git
cd kiro-gateway

# Instalar dependencias
npm install
cd python-backend && pip install -r requirements.txt && cd ..

# Ejecutar en modo desarrollo
npm run tauri:dev

# O compilar para producción
npm run tauri:build
```

## 🚀 Inicio rápido

1. **Inicia** KiroaaS
2. **Configura** tus credenciales de Kiro (se detectan automáticamente si están disponibles)
3. **Inicia** el servidor
4. **Usa** `http://localhost:8000` como tu endpoint de API de OpenAI

```bash
# Ejemplo: Chatear con Kiro usando curl
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "kiro",
    "messages": [{"role": "user", "content": "¡Hola!"}]
  }'
```

## 🔌 Compatible con

KiroaaS es compatible con herramientas y bibliotecas de IA populares:

- **Python**: OpenAI SDK, LangChain, LlamaIndex
- **JavaScript**: OpenAI Node.js SDK, Vercel AI SDK
- **Apps**: Cursor, Continue, ChatGPT-Next-Web y más

```python
# Ejemplo en Python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="not-needed"
)

response = client.chat.completions.create(
    model="kiro",
    messages=[{"role": "user", "content": "¡Hola!"}]
)
```

## ⚙️ Configuración

| Opción | Predeterminado | Descripción |
|--------|----------------|-------------|
| Host | `127.0.0.1` | Dirección de enlace del servidor |
| Puerto | `8000` | Puerto del servidor |
| Región | `us-east-1` | Región de Kiro |

Opciones avanzadas disponibles en el panel de Configuración.

## 🛠️ Stack tecnológico

- **Frontend**: React + TypeScript + Tailwind CSS
- **Escritorio**: Tauri (Rust)
- **Backend**: Python + FastAPI

## 🤝 Contribuir

¡Las contribuciones son bienvenidas!

- 🐛 Reportar errores
- 💡 Sugerir funcionalidades
- 🔧 Enviar pull requests

## 📄 Licencia

[AGPL-3.0](../LICENSE) © Contribuidores de KiroaaS
