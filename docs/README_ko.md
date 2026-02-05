# KiroaaS

<p align="center">
  <img src="../public/icon.png" alt="KiroaaS Logo" width="128" height="128">
</p>

<h3 align="center">Kiro as a Service</h3>
<p align="center">원클릭으로 Kiro를 OpenAI 호환 및 Anthropic 호환 API로 변환</p>

<p align="center">
  <a href="../README.md">🇺🇸 English</a> • <a href="README_zh.md">🇨🇳 中文</a> • <a href="README_ja.md">🇯🇵 日本語</a> • 🇰🇷 한국어 • <a href="README_ru.md">🇷🇺 Русский</a> • <a href="README_es.md">🇪🇸 Español</a> • <a href="README_pt.md">🇧🇷 Português</a> • <a href="README_id.md">🇮🇩 Indonesia</a>
</p>

<p align="center">
  <a href="https://opensource.org/licenses/AGPL-3.0"><img src="https://img.shields.io/badge/License-AGPL%203.0-blue.svg" alt="License: AGPL-3.0"></a>
  <img src="https://img.shields.io/badge/platform-macOS-brightgreen" alt="Platform">
  <a href="http://makeapullrequest.com"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome"></a>
</p>

<p align="center">
  <img src="../app-screenshot.webp" alt="KiroaaS 스크린샷" width="800">
</p>

---

KiroaaS(Kiro as a Service)는 로컬 OpenAI 호환 및 Anthropic 호환 API를 통해 Kiro의 AI 모델을 제공하는 데스크톱 게이트웨이입니다. 코드 변경 없이 좋아하는 AI 도구, 라이브러리, 애플리케이션에서 Kiro를 사용하세요.

## ✨ 기능

| 기능 | 설명 |
|------|------|
| 🔌 **OpenAI 호환 API** | OpenAI SDK용 `/v1/chat/completions` 엔드포인트 |
| 🔌 **Anthropic 호환 API** | Anthropic SDK용 `/v1/messages` 엔드포인트 |
| 🌐 **VPN/프록시 지원** | 제한된 네트워크를 위한 HTTP/SOCKS5 프록시 |
| 🧠 **확장 사고** | 본 프로젝트 전용 추론 지원 |
| 👁️ **비전 지원** | 모델에 이미지 전송 |
| 🛠️ **도구 호출** | 함수 호출 지원 |
| 💬 **내장 채팅** | 통합 채팅 인터페이스로 설정 테스트 |
| 📡 **스트리밍** | 완전한 SSE 스트리밍 지원 |
| 🔄 **재시도 로직** | 오류 시 자동 재시도 (403, 429, 5xx) |
| 🔐 **스마트 토큰 관리** | 만료 전 자동 갱신 |
| 🌍 **다국어 UI** | English, 中文, 日本語, 한국어, Русский, Español, Português, Indonesia |
| 🔗 **CC Switch 연동** | [CC Switch](https://github.com/yiGmMk/cc-switch)로 원클릭 가져오기 (Claude Code용) |
| 🔄 **자동 업데이트** | 내장 업데이트 체커로 최신 버전 유지 |

## 📦 설치

### 다운로드

[GitHub Releases](https://github.com/hnewcity/KiroaaS/releases)에서 최신 릴리스 다운로드:

| 플랫폼 | 아키텍처 | 다운로드 |
|--------|----------|----------|
| macOS | Apple Silicon (M1/M2/M3) | [KiroaaS_aarch64.dmg](https://github.com/hnewcity/KiroaaS/releases) |
| macOS | Intel | [KiroaaS_x64.dmg](https://github.com/hnewcity/KiroaaS/releases) |

> Windows 및 Linux 지원 예정.

### 소스에서 빌드

```bash
# 저장소 클론
git clone https://github.com/hnewcity/KiroaaS.git
cd KiroaaS

# 의존성 설치
npm install
cd python-backend && pip install -r requirements.txt && cd ..

# 개발 모드로 실행
npm run tauri:dev

# 또는 프로덕션 빌드
npm run tauri:build
```

## 🚀 빠른 시작

1. KiroaaS **실행**
2. Kiro 자격 증명 **설정** (Kiro CLI가 설치되어 있으면 자동 감지)
3. 프록시 API 키 **생성** (또는 관리자가 제공한 키 사용)
4. 서버 **시작**
5. `http://localhost:8000`을 OpenAI/Anthropic API 엔드포인트로 **사용**

### 예시: cURL

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_PROXY_API_KEY" \
  -d '{
    "model": "claude-sonnet-4-5",
    "messages": [{"role": "user", "content": "안녕하세요!"}]
  }'
```

### 예시: Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="YOUR_PROXY_API_KEY"
)

response = client.chat.completions.create(
    model="claude-sonnet-4-5",
    messages=[{"role": "user", "content": "안녕하세요!"}]
)
print(response.choices[0].message.content)
```

### 예시: JavaScript (OpenAI SDK)

```javascript
import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: 'http://localhost:8000/v1',
  apiKey: 'YOUR_PROXY_API_KEY',
});

const response = await client.chat.completions.create({
  model: 'claude-sonnet-4-5',
  messages: [{ role: 'user', content: '안녕하세요!' }],
});
console.log(response.choices[0].message.content);
```

## 🔌 호환 도구

KiroaaS는 인기 있는 AI 도구 및 라이브러리와 호환됩니다:

| 카테고리 | 도구 |
|----------|------|
| **Python** | OpenAI SDK, Anthropic SDK, LangChain, LlamaIndex |
| **JavaScript** | OpenAI Node.js SDK, Anthropic SDK, Vercel AI SDK |
| **IDE 확장** | Cursor, Continue, Cline, Claude Code |
| **채팅 앱** | ChatGPT-Next-Web, LobeChat, Open WebUI |

## ⚙️ 설정

### 인증 방식

KiroaaS는 여러 인증 방식을 지원합니다:

| 방식 | 설명 |
|------|------|
| **Kiro CLI 데이터베이스** | Kiro CLI에서 자격 증명 자동 감지 (권장) |
| **자격 증명 파일** | JSON 자격 증명 파일 사용 |
| **리프레시 토큰** | 리프레시 토큰 수동 입력 |

### 서버 설정

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| 호스트 | `127.0.0.1` | 서버 바인드 주소 |
| 포트 | `8000` | 서버 포트 |
| 프록시 API 키 | - | API 인증에 필요한 키 |

### 고급 설정

| 옵션 | 설명 |
|------|------|
| VPN/프록시 URL | 네트워크 제한을 위한 HTTP/SOCKS5 프록시 |
| 첫 토큰 타임아웃 | 초기 응답 타임아웃 (초) |
| 스트리밍 읽기 타임아웃 | 스트리밍 응답 타임아웃 (초) |

## 🛠️ 기술 스택

| 레이어 | 기술 |
|--------|------|
| **프론트엔드** | React + TypeScript + Tailwind CSS |
| **데스크톱** | Tauri (Rust) |
| **백엔드** | Python + FastAPI |

## 🤝 기여

기여를 환영합니다!

- 🐛 [GitHub Issues](https://github.com/hnewcity/KiroaaS/issues)에서 버그 신고
- 💡 기능 제안
- 🔧 풀 리퀘스트 제출
- 🌍 번역 도움

## 📄 라이선스

[AGPL-3.0](../LICENSE) © KiroaaS 기여자
