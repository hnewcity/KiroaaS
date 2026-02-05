# KiroaaS

<p align="center">
  <img src="../public/icon.png" alt="KiroaaS Logo" width="128" height="128">
</p>

<h3 align="center">Kiro as a Service</h3>
<p align="center">Transforme o Kiro em uma API compatível com OpenAI e Anthropic com um clique</p>

<p align="center">
  <a href="../README.md">🇺🇸 English</a> • <a href="README_zh.md">🇨🇳 中文</a> • <a href="README_ja.md">🇯🇵 日本語</a> • <a href="README_ko.md">🇰🇷 한국어</a> • <a href="README_ru.md">🇷🇺 Русский</a> • <a href="README_es.md">🇪🇸 Español</a> • 🇧🇷 Português • <a href="README_id.md">🇮🇩 Indonesia</a>
</p>

<p align="center">
  <a href="https://opensource.org/licenses/AGPL-3.0"><img src="https://img.shields.io/badge/License-AGPL%203.0-blue.svg" alt="License: AGPL-3.0"></a>
  <img src="https://img.shields.io/badge/platform-macOS-brightgreen" alt="Platform">
  <a href="http://makeapullrequest.com"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome"></a>
</p>

<p align="center">
  <img src="../app-screenshot.webp" alt="Captura de tela do KiroaaS" width="800">
</p>

---

KiroaaS (Kiro as a Service) é um gateway desktop que expõe os modelos de IA do Kiro através de uma API local compatível com OpenAI e Anthropic. Use suas ferramentas, bibliotecas e aplicações de IA favoritas com o Kiro - sem necessidade de alterar código.

## ✨ Funcionalidades

| Funcionalidade | Descrição |
|----------------|-----------|
| 🔌 **API compatível com OpenAI** | Endpoint `/v1/chat/completions` para OpenAI SDK |
| 🔌 **API compatível com Anthropic** | Endpoint `/v1/messages` para Anthropic SDK |
| 🌐 **Suporte VPN/Proxy** | Proxy HTTP/SOCKS5 para redes restritas |
| 🧠 **Pensamento estendido** | Suporte a raciocínio exclusivo do nosso projeto |
| 👁️ **Suporte a visão** | Envie imagens para o modelo |
| 🛠️ **Chamada de ferramentas** | Suporta chamadas de função |
| 💬 **Chat integrado** | Teste sua configuração com a interface de chat integrada |
| 📡 **Streaming** | Suporte completo a streaming SSE |
| 🔄 **Lógica de retry** | Retentativas automáticas em erros (403, 429, 5xx) |
| 🔐 **Gerenciamento inteligente de tokens** | Atualização automática antes da expiração |
| 🌍 **Interface multilíngue** | English, 中文, 日本語, 한국어, Русский, Español, Português, Indonesia |
| 🔗 **Integração com CC Switch** | Importação com um clique para [CC Switch](https://github.com/yiGmMk/cc-switch) para Claude Code |
| 🔄 **Atualização automática** | Verificador de atualizações integrado |

## 📦 Instalação

### Download

Baixe a versão mais recente do [GitHub Releases](https://github.com/hnewcity/KiroaaS/releases):

| Plataforma | Arquitetura | Download |
|------------|-------------|----------|
| macOS | Apple Silicon (M1/M2/M3) | [KiroaaS_aarch64.dmg](https://github.com/hnewcity/KiroaaS/releases) |
| macOS | Intel | [KiroaaS_x64.dmg](https://github.com/hnewcity/KiroaaS/releases) |

> Suporte para Windows e Linux em breve.

### Compilar do código fonte

```bash
# Clonar o repositório
git clone https://github.com/hnewcity/KiroaaS.git
cd KiroaaS

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
2. **Configure** suas credenciais do Kiro (detectadas automaticamente se o Kiro CLI estiver instalado)
3. **Gere** uma chave API de proxy (ou use uma fornecida pelo seu administrador)
4. **Inicie** o servidor
5. **Use** `http://localhost:8000` como seu endpoint da API OpenAI/Anthropic

### Exemplo: cURL

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_PROXY_API_KEY" \
  -d '{
    "model": "claude-sonnet-4-5",
    "messages": [{"role": "user", "content": "Olá!"}]
  }'
```

### Exemplo: Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="YOUR_PROXY_API_KEY"
)

response = client.chat.completions.create(
    model="claude-sonnet-4-5",
    messages=[{"role": "user", "content": "Olá!"}]
)
print(response.choices[0].message.content)
```

### Exemplo: JavaScript (OpenAI SDK)

```javascript
import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: 'http://localhost:8000/v1',
  apiKey: 'YOUR_PROXY_API_KEY',
});

const response = await client.chat.completions.create({
  model: 'claude-sonnet-4-5',
  messages: [{ role: 'user', content: 'Olá!' }],
});
console.log(response.choices[0].message.content);
```

## 🔌 Compatível com

KiroaaS é compatível com ferramentas e bibliotecas de IA populares:

| Categoria | Ferramentas |
|-----------|-------------|
| **Python** | OpenAI SDK, Anthropic SDK, LangChain, LlamaIndex |
| **JavaScript** | OpenAI Node.js SDK, Anthropic SDK, Vercel AI SDK |
| **Extensões IDE** | Cursor, Continue, Cline, Claude Code |
| **Apps de chat** | ChatGPT-Next-Web, LobeChat, Open WebUI |

## ⚙️ Configuração

### Métodos de autenticação

KiroaaS suporta múltiplos métodos de autenticação:

| Método | Descrição |
|--------|-----------|
| **Banco de dados Kiro CLI** | Detecção automática de credenciais do Kiro CLI (recomendado) |
| **Arquivo de credenciais** | Usar um arquivo JSON de credenciais |
| **Token de atualização** | Inserir manualmente o token de atualização |

### Configurações do servidor

| Opção | Padrão | Descrição |
|-------|--------|-----------|
| Host | `127.0.0.1` | Endereço de bind do servidor |
| Porta | `8000` | Porta do servidor |
| Chave API de proxy | - | Chave necessária para autenticação da API |

### Configurações avançadas

| Opção | Descrição |
|-------|-----------|
| URL VPN/Proxy | Proxy HTTP/SOCKS5 para restrições de rede |
| Timeout do primeiro token | Timeout para resposta inicial (segundos) |
| Timeout de leitura streaming | Timeout para respostas streaming (segundos) |

## 🛠️ Stack tecnológica

| Camada | Tecnologia |
|--------|------------|
| **Frontend** | React + TypeScript + Tailwind CSS |
| **Desktop** | Tauri (Rust) |
| **Backend** | Python + FastAPI |

## 🤝 Contribuir

Contribuições são bem-vindas!

- 🐛 Reportar bugs em [GitHub Issues](https://github.com/hnewcity/KiroaaS/issues)
- 💡 Sugerir funcionalidades
- 🔧 Enviar pull requests
- 🌍 Ajudar com traduções

## 📄 Licença

[AGPL-3.0](../LICENSE) © Contribuidores do KiroaaS
