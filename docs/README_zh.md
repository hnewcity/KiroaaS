# KiroaaS

> 🚀 一键将 Kiro 转换为 OpenAI 兼容 API

[🇺🇸 English](../README.md) • 🇨🇳 中文 • [🇯🇵 日本語](README_ja.md) • [🇰🇷 한국어](README_ko.md) • [🇷🇺 Русский](README_ru.md) • [🇪🇸 Español](README_es.md) • [🇧🇷 Português](README_pt.md) • [🇮🇩 Indonesia](README_id.md)

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL%203.0-blue.svg)](https://opensource.org/licenses/AGPL-3.0)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows%20%7C%20Linux-lightgrey)]()
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](http://makeapullrequest.com)

KiroaaS（Kiro 即服务）是一个桌面网关应用，通过本地 OpenAI 兼容 API 暴露 Kiro 的 AI 模型。无需修改代码，即可使用您喜爱的 AI 工具、库和应用程序与 Kiro 交互。

## ✨ 功能特性

| 功能 | 描述 |
|------|------|
| 🔌 OpenAI 兼容 API | 兼容任何 OpenAI 兼容工具 |
| 🔌 Anthropic 兼容 API | 原生 `/v1/messages` 端点 |
| 🌐 VPN/代理支持 | 支持 HTTP/SOCKS5 代理 |
| 🧠 扩展思维 | 本项目独有的推理支持 |
| 👁️ 视觉支持 | 向模型发送图片 |
| 🛠️ 工具调用 | 支持函数调用 |
| 💬 完整消息历史 | 传递完整对话上下文 |
| 📡 流式传输 | 完整 SSE 流式支持 |
| 🔄 重试逻辑 | 自动重试错误 (403, 429, 5xx) |
| 📋 扩展模型列表 | 包含版本化模型 |
| 🔐 智能令牌管理 | 过期前自动刷新 |

## 📦 安装

### 下载

下载最新版本：

| 平台 | 下载 |
|------|------|
| macOS | [KiroaaS.dmg](https://github.com/Jwadow/kiro-gateway/releases) |

> Windows 和 Linux 支持即将推出。

### 从源码构建

```bash
# 克隆仓库
git clone https://github.com/Jwadow/kiro-gateway.git
cd kiro-gateway

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
2. **配置** 您的 Kiro 凭证（如果可用会自动检测）
3. **启动** 服务器
4. **使用** `http://localhost:8000` 作为您的 OpenAI API 端点

```bash
# 示例：使用 curl 与 Kiro 对话
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "kiro",
    "messages": [{"role": "user", "content": "你好！"}]
  }'
```

## 🔌 兼容工具

KiroaaS 兼容流行的 AI 工具和库：

- **Python**: OpenAI SDK、LangChain、LlamaIndex
- **JavaScript**: OpenAI Node.js SDK、Vercel AI SDK
- **应用**: Cursor、Continue、ChatGPT-Next-Web 等

```python
# Python 示例
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="not-needed"
)

response = client.chat.completions.create(
    model="kiro",
    messages=[{"role": "user", "content": "你好！"}]
)
```

## ⚙️ 配置

| 选项 | 默认值 | 描述 |
|------|--------|------|
| 主机 | `127.0.0.1` | 服务器绑定地址 |
| 端口 | `8000` | 服务器端口 |
| 区域 | `us-east-1` | Kiro 区域 |

更多高级选项请查看设置面板。

## 🛠️ 技术栈

- **前端**: React + TypeScript + Tailwind CSS
- **桌面**: Tauri (Rust)
- **后端**: Python + FastAPI

## 🤝 贡献

欢迎贡献！您可以：

- 🐛 报告 Bug
- 💡 建议新功能
- 🔧 提交 Pull Request

## 📄 许可证

[AGPL-3.0](../LICENSE) © KiroaaS 贡献者
