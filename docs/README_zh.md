# KiroaaS

<p align="center">
  <img src="../public/icon.png" alt="KiroaaS Logo" width="128" height="128">
</p>

<h3 align="center">Kiro 即服务</h3>
<p align="center">一键将 Kiro 转换为 OpenAI 兼容和 Anthropic 兼容的 API</p>

<p align="center">
  <a href="../README.md">🇺🇸 English</a> • 🇨🇳 中文 • <a href="README_ja.md">🇯🇵 日本語</a> • <a href="README_ko.md">🇰🇷 한국어</a> • <a href="README_ru.md">🇷🇺 Русский</a> • <a href="README_es.md">🇪🇸 Español</a> • <a href="README_pt.md">🇧🇷 Português</a> • <a href="README_id.md">🇮🇩 Indonesia</a>
</p>

<p align="center">
  <a href="https://opensource.org/licenses/AGPL-3.0"><img src="https://img.shields.io/badge/License-AGPL%203.0-blue.svg" alt="License: AGPL-3.0"></a>
  <img src="https://img.shields.io/badge/platform-macOS%20%7C%20Windows-brightgreen" alt="Platform">
  <a href="http://makeapullrequest.com"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome"></a>
</p>

<p align="center">
  <img src="../app-screenshot.webp" alt="KiroaaS 截图" width="800">
</p>

---

KiroaaS（Kiro 即服务）是一个桌面网关应用，通过本地 OpenAI 兼容和 Anthropic 兼容的 API 暴露 Kiro 的 AI 模型。无需修改代码，即可使用您喜爱的 AI 工具、库和应用程序与 Kiro 交互。

## ✨ 功能特性

| 功能 | 描述 |
|------|------|
| 🔌 **OpenAI 兼容 API** | `/v1/chat/completions` 端点，支持 OpenAI SDK |
| 🔌 **Anthropic 兼容 API** | `/v1/messages` 端点，支持 Anthropic SDK |
| 🌐 **VPN/代理支持** | 支持 HTTP/SOCKS5 代理，适用于受限网络 |
| 🧠 **扩展思维** | 本项目独有的推理支持 |
| 👁️ **视觉支持** | 向模型发送图片 |
| 🛠️ **工具调用** | 支持函数调用 |
| 💬 **内置聊天** | 使用集成的聊天界面测试您的配置 |
| 📡 **流式传输** | 完整 SSE 流式支持 |
| 🔄 **重试逻辑** | 自动重试错误 (403, 429, 5xx) |
| 🔐 **智能令牌管理** | 过期前自动刷新 |
| 🌍 **多语言界面** | English, 中文, 日本語, 한국어, Русский, Español, Português, Indonesia |
| 🔗 **CC Switch 集成** | 一键导入到 [CC Switch](https://github.com/farion1231/cc-switch)，用于 Claude Code |
| 🔄 **自动更新** | 内置更新检查器，保持最新版本 |

## 📦 安装

### 下载

从 [GitHub Releases](https://github.com/hnewcity/KiroaaS/releases) 下载最新版本：

| 平台 | 架构 | 下载 |
|------|------|------|
| macOS | Apple Silicon (M1/M2/M3) | [KiroaaS_aarch64.dmg](https://github.com/hnewcity/KiroaaS/releases) |
| macOS | Intel | [KiroaaS_x64.dmg](https://github.com/hnewcity/KiroaaS/releases) |
| Windows | x64 | [KiroaaS_x64-setup.exe](https://github.com/hnewcity/KiroaaS/releases) |

> Linux 支持即将推出。

### 从源码构建

```bash
# 克隆仓库
git clone https://github.com/hnewcity/KiroaaS.git
cd KiroaaS

# 安装依赖
npm install
cd python-backend && pip install -r requirements.txt && cd ..

# 开发模式运行
npm run tauri:dev

# 或构建生产版本
npm run tauri:build
```

## 🚀 快速开始

1. **启动** KiroaaS
2. **配置** 您的 Kiro 凭证（如果已安装 Kiro CLI 会自动检测）
3. **生成** 代理 API 密钥（或使用管理员提供的密钥）
4. **启动** 服务器
5. **使用** `http://localhost:8000` 作为您的 OpenAI/Anthropic API 端点

### 示例：cURL

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_PROXY_API_KEY" \
  -d '{
    "model": "claude-sonnet-4-5",
    "messages": [{"role": "user", "content": "你好！"}]
  }'
```

### 示例：Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="YOUR_PROXY_API_KEY"
)

response = client.chat.completions.create(
    model="claude-sonnet-4-5",
    messages=[{"role": "user", "content": "你好！"}]
)
print(response.choices[0].message.content)
```

### 示例：JavaScript (OpenAI SDK)

```javascript
import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: 'http://localhost:8000/v1',
  apiKey: 'YOUR_PROXY_API_KEY',
});

const response = await client.chat.completions.create({
  model: 'claude-sonnet-4-5',
  messages: [{ role: 'user', content: '你好！' }],
});
console.log(response.choices[0].message.content);
```

## 🔌 兼容工具

KiroaaS 兼容流行的 AI 工具和库：

| 类别 | 工具 |
|------|------|
| **Python** | OpenAI SDK, Anthropic SDK, LangChain, LlamaIndex |
| **JavaScript** | OpenAI Node.js SDK, Anthropic SDK, Vercel AI SDK |
| **IDE 扩展** | Cursor, Continue, Cline, Claude Code |
| **聊天应用** | ChatGPT-Next-Web, LobeChat, Open WebUI |

## ⚙️ 配置

### 认证方式

KiroaaS 支持多种认证方式：

| 方式 | 描述 |
|------|------|
| **Kiro CLI 数据库** | 从 Kiro CLI 自动检测凭证（推荐） |
| **凭证文件** | 使用 JSON 凭证文件 |
| **刷新令牌** | 手动输入刷新令牌 |

### 服务器设置

| 选项 | 默认值 | 描述 |
|------|--------|------|
| 主机 | `127.0.0.1` | 服务器绑定地址 |
| 端口 | `8000` | 服务器端口 |
| 代理 API 密钥 | - | API 认证所需的密钥 |

### 高级设置

| 选项 | 描述 |
|------|------|
| VPN/代理 URL | 用于网络限制的 HTTP/SOCKS5 代理 |
| 首个令牌超时 | 初始响应超时（秒） |
| 流式读取超时 | 流式响应超时（秒） |

## 🛠️ 技术栈

| 层级 | 技术 |
|------|------|
| **前端** | React + TypeScript + Tailwind CSS |
| **桌面** | Tauri (Rust) |
| **后端** | Python + FastAPI |

## 🤝 贡献

欢迎贡献！您可以：

- 🐛 通过 [GitHub Issues](https://github.com/hnewcity/KiroaaS/issues) 报告 Bug
- 💡 建议新功能
- 🔧 提交 Pull Request
- 🌍 帮助翻译

## 📄 许可证

[AGPL-3.0](../LICENSE) © KiroaaS 贡献者
