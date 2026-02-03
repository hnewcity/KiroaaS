# KiroaaS

> 🚀 Transforme o Kiro em uma API compatível com OpenAI com um clique

[🇺🇸 English](../README.md) • [🇨🇳 中文](README_zh.md) • [🇯🇵 日本語](README_ja.md) • [🇰🇷 한국어](README_ko.md) • [🇷🇺 Русский](README_ru.md) • [🇪🇸 Español](README_es.md) • 🇧🇷 Português • [🇮🇩 Indonesia](README_id.md)

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL%203.0-blue.svg)](https://opensource.org/licenses/AGPL-3.0)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows%20%7C%20Linux-lightgrey)]()
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](http://makeapullrequest.com)

KiroaaS (Kiro as a Service) é um gateway desktop que expõe os modelos de IA do Kiro através de uma API local compatível com OpenAI. Use suas ferramentas, bibliotecas e aplicações de IA favoritas com o Kiro - sem necessidade de alterar código.

## ✨ Funcionalidades

| Funcionalidade | Descrição |
|----------------|-----------|
| 🔌 API compatível com OpenAI | Funciona com qualquer ferramenta compatível com OpenAI |
| 🔌 API compatível com Anthropic | Endpoint nativo `/v1/messages` |
| 🌐 Suporte VPN/Proxy | Proxy HTTP/SOCKS5 para redes restritas |
| 🧠 Pensamento estendido | Suporte a raciocínio exclusivo do nosso projeto |
| 👁️ Suporte a visão | Envie imagens para o modelo |
| 🛠️ Chamada de ferramentas | Suporta chamadas de função |
| 💬 Histórico completo de mensagens | Passa o contexto completo da conversa |
| 📡 Streaming | Suporte completo a streaming SSE |
| 🔄 Lógica de retry | Retentativas automáticas em erros (403, 429, 5xx) |
| 📋 Lista estendida de modelos | Incluindo modelos versionados |
| 🔐 Gerenciamento inteligente de tokens | Atualização automática antes da expiração |

## 📦 Instalação

### Download

Baixe a versão mais recente:

| Plataforma | Download |
|------------|----------|
| macOS | [KiroaaS.dmg](https://github.com/Jwadow/kiro-gateway/releases) |

> Suporte para Windows e Linux em breve.

### Compilar do código fonte

```bash
# Clonar o repositório
git clone https://github.com/Jwadow/kiro-gateway.git
cd kiro-gateway

# Instalar dependências
npm install
cd python-backend && pip install -r requirements.txt && cd ..

# Executar em modo de desenvolvimento
npm run tauri:dev

# Ou compilar para produção
npm run tauri:build
```

## 🚀 Início rápido

1. **Inicie** o KiroaaS
2. **Configure** suas credenciais do Kiro (detectadas automaticamente se disponíveis)
3. **Inicie** o servidor
4. **Use** `http://localhost:8000` como seu endpoint da API OpenAI

```bash
# Exemplo: Conversar com o Kiro usando curl
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "kiro",
    "messages": [{"role": "user", "content": "Olá!"}]
  }'
```

## 🔌 Compatível com

KiroaaS é compatível com ferramentas e bibliotecas de IA populares:

- **Python**: OpenAI SDK, LangChain, LlamaIndex
- **JavaScript**: OpenAI Node.js SDK, Vercel AI SDK
- **Apps**: Cursor, Continue, ChatGPT-Next-Web e mais

```python
# Exemplo em Python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="not-needed"
)

response = client.chat.completions.create(
    model="kiro",
    messages=[{"role": "user", "content": "Olá!"}]
)
```

## ⚙️ Configuração

| Opção | Padrão | Descrição |
|-------|--------|-----------|
| Host | `127.0.0.1` | Endereço de bind do servidor |
| Porta | `8000` | Porta do servidor |
| Região | `us-east-1` | Região do Kiro |

Opções avançadas disponíveis no painel de Configurações.

## 🛠️ Stack tecnológica

- **Frontend**: React + TypeScript + Tailwind CSS
- **Desktop**: Tauri (Rust)
- **Backend**: Python + FastAPI

## 🤝 Contribuir

Contribuições são bem-vindas!

- 🐛 Reportar bugs
- 💡 Sugerir funcionalidades
- 🔧 Enviar pull requests

## 📄 Licença

[AGPL-3.0](../LICENSE) © Contribuidores do KiroaaS
