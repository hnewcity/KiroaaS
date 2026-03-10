# KiroaaS

<p align="center">
  <img src="../public/icon.png" alt="KiroaaS Logo" width="128" height="128">
</p>

<h3 align="center">Kiro as a Service</h3>
<p align="center">Превратите Kiro в OpenAI-совместимый и Anthropic-совместимый API одним кликом</p>

<p align="center">
  <a href="../README.md">🇺🇸 English</a> • <a href="README_zh.md">🇨🇳 中文</a> • <a href="README_ja.md">🇯🇵 日本語</a> • <a href="README_ko.md">🇰🇷 한국어</a> • 🇷🇺 Русский • <a href="README_es.md">🇪🇸 Español</a> • <a href="README_pt.md">🇧🇷 Português</a> • <a href="README_id.md">🇮🇩 Indonesia</a>
</p>

<p align="center">
  <a href="https://opensource.org/licenses/AGPL-3.0"><img src="https://img.shields.io/badge/License-AGPL%203.0-blue.svg" alt="License: AGPL-3.0"></a>
  <img src="https://img.shields.io/badge/platform-macOS%20%7C%20Windows-brightgreen" alt="Platform">
  <a href="http://makeapullrequest.com"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome"></a>
</p>

<p align="center">
  <img src="../app-screenshot.webp" alt="Скриншот KiroaaS" width="800">
</p>

---

## ❤️ Спонсор

<table>
<tr>
<td width="180"><a href="https://ai18n.chat"><img src="../public/sponsors/ai18n.png" alt="ai18n" width="150"></a></td>
<td>Благодарим <a href="https://ai18n.chat">ai18n</a> за спонсорство проекта! ai18n — надёжный и эффективный провайдер API-ретрансляции, предоставляющий ретрансляцию моделей Claude для OpenClaw, Claude Code, Codex, Gemini и других инструментов.</td>
</tr>
</table>

---

> ~~**📢 Уведомление:** В следующей версии будет исправлена совместимость с Claude Code v2.1.69+, который отправляет блоки содержимого `tool_reference` внутри сообщений `tool_result` при использовании механизма отложенных инструментов ToolSearch.~~ ✅ Исправлено

KiroaaS (Kiro as a Service) — это десктопный шлюз, который предоставляет доступ к AI-моделям Kiro через локальный OpenAI-совместимый и Anthropic-совместимый API. Используйте ваши любимые AI-инструменты, библиотеки и приложения с Kiro без изменения кода.

## ✨ Возможности

| Функция | Описание |
|---------|----------|
| 🔌 **OpenAI-совместимый API** | Эндпоинт `/v1/chat/completions` для OpenAI SDK |
| 🔌 **Anthropic-совместимый API** | Эндпоинт `/v1/messages` для Anthropic SDK |
| 🌐 **Поддержка VPN/Прокси** | HTTP/SOCKS5 прокси для ограниченных сетей |
| 🧠 **Расширенное мышление** | Поддержка рассуждений, эксклюзивная для нашего проекта |
| 👁️ **Поддержка изображений** | Отправка изображений модели |
| 🛠️ **Вызов инструментов** | Поддержка вызова функций |
| 💬 **Встроенный чат** | Тестируйте настройки через интегрированный чат |
| 📡 **Стриминг** | Полная поддержка SSE стриминга |
| 🔄 **Логика повторов** | Автоматические повторы при ошибках (403, 429, 5xx) |
| 🔐 **Умное управление токенами** | Автоматическое обновление до истечения срока |
| 🌍 **Многоязычный интерфейс** | English, 中文, 日本語, 한국어, Русский, Español, Português, Indonesia |
| 🔗 **Интеграция с CC Switch** | Импорт в [CC Switch](https://github.com/farion1231/cc-switch) одним кликом (для Claude Code) |
| 🔄 **Автообновление** | Встроенная проверка обновлений |

## 📦 Установка

### Скачать

Скачайте последний релиз с [GitHub Releases](https://github.com/hnewcity/KiroaaS/releases):

| Платформа | Архитектура | Скачать |
|-----------|-------------|---------|
| macOS | Apple Silicon (M1/M2/M3) | [KiroaaS_aarch64.dmg](https://github.com/hnewcity/KiroaaS/releases) |
| macOS | Intel | [KiroaaS_x64.dmg](https://github.com/hnewcity/KiroaaS/releases) |
| Windows | x64 | [KiroaaS_x64-setup.exe](https://github.com/hnewcity/KiroaaS/releases) |

> Поддержка Linux скоро появится.

### Сборка из исходников

```bash
# Клонировать репозиторий
git clone https://github.com/hnewcity/KiroaaS.git
cd KiroaaS

# Установить зависимости
npm install
cd python-backend && pip install -r requirements.txt && cd ..

# Запустить в режиме разработки
npm run tauri:dev

# Или собрать для продакшена
npm run tauri:build
```

## 🚀 Быстрый старт

1. **Запустите** KiroaaS
2. **Настройте** учётные данные Kiro (автоматически обнаруживаются, если установлен Kiro CLI)
3. **Сгенерируйте** прокси API-ключ (или используйте ключ от администратора)
4. **Запустите** сервер
5. **Используйте** `http://localhost:8000` как эндпоинт OpenAI/Anthropic API

### Пример: cURL

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_PROXY_API_KEY" \
  -d '{
    "model": "claude-sonnet-4-6",
    "messages": [{"role": "user", "content": "Привет!"}]
  }'
```

### Пример: Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="YOUR_PROXY_API_KEY"
)

response = client.chat.completions.create(
    model="claude-sonnet-4-6",
    messages=[{"role": "user", "content": "Привет!"}]
)
print(response.choices[0].message.content)
```

### Пример: JavaScript (OpenAI SDK)

```javascript
import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: 'http://localhost:8000/v1',
  apiKey: 'YOUR_PROXY_API_KEY',
});

const response = await client.chat.completions.create({
  model: 'claude-sonnet-4-6',
  messages: [{ role: 'user', content: 'Привет!' }],
});
console.log(response.choices[0].message.content);
```

## 🔌 Совместимость

KiroaaS совместим с популярными AI-инструментами и библиотеками:

| Категория | Инструменты |
|-----------|-------------|
| **Python** | OpenAI SDK, Anthropic SDK, LangChain, LlamaIndex |
| **JavaScript** | OpenAI Node.js SDK, Anthropic SDK, Vercel AI SDK |
| **Расширения IDE** | Cursor, Continue, Cline, Claude Code |
| **Чат-приложения** | ChatGPT-Next-Web, LobeChat, Open WebUI |

## ⚙️ Конфигурация

### Методы аутентификации

KiroaaS поддерживает несколько методов аутентификации:

| Метод | Описание |
|-------|----------|
| **База данных Kiro CLI** | Автоматическое обнаружение учётных данных из Kiro CLI (рекомендуется) |
| **Файл учётных данных** | Использование JSON-файла с учётными данными |
| **Refresh-токен** | Ручной ввод refresh-токена |

### Настройки сервера

| Опция | По умолчанию | Описание |
|-------|--------------|----------|
| Хост | `127.0.0.1` | Адрес привязки сервера |
| Порт | `8000` | Порт сервера |
| Прокси API-ключ | - | Ключ для аутентификации API |

### Расширенные настройки

| Опция | Описание |
|-------|----------|
| URL VPN/Прокси | HTTP/SOCKS5 прокси для сетевых ограничений |
| Таймаут первого токена | Таймаут начального ответа (секунды) |
| Таймаут чтения стрима | Таймаут потоковых ответов (секунды) |

## 🛠️ Технологический стек

| Слой | Технология |
|------|------------|
| **Фронтенд** | React + TypeScript + Tailwind CSS |
| **Десктоп** | Tauri (Rust) |
| **Бэкенд** | Python + FastAPI |

## 🤝 Вклад в проект

Мы приветствуем вклад в проект!

- 🐛 Сообщайте об ошибках через [GitHub Issues](https://github.com/hnewcity/KiroaaS/issues)
- 💡 Предлагайте функции
- 🔧 Отправляйте pull request'ы
- 🌍 Помогайте с переводами

## 📄 Лицензия

[AGPL-3.0](../LICENSE) © Участники KiroaaS
