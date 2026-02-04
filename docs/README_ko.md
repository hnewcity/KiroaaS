# KiroaaS

> 🚀 원클릭으로 Kiro를 OpenAI 호환 API로 변환

[🇺🇸 English](../README.md) • [🇨🇳 中文](README_zh.md) • [🇯🇵 日本語](README_ja.md) • 🇰🇷 한국어 • [🇷🇺 Русский](README_ru.md) • [🇪🇸 Español](README_es.md) • [🇧🇷 Português](README_pt.md) • [🇮🇩 Indonesia](README_id.md)

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL%203.0-blue.svg)](https://opensource.org/licenses/AGPL-3.0)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows%20%7C%20Linux-lightgrey)]()
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](http://makeapullrequest.com)

KiroaaS(Kiro as a Service)는 로컬 OpenAI 호환 API를 통해 Kiro의 AI 모델을 제공하는 데스크톱 게이트웨이입니다. 코드 변경 없이 좋아하는 AI 도구, 라이브러리, 애플리케이션에서 Kiro를 사용하세요.

## ✨ 기능

| 기능 | 설명 |
|------|------|
| 🔌 OpenAI 호환 API | 모든 OpenAI 호환 도구와 작동 |
| 🔌 Anthropic 호환 API | 네이티브 `/v1/messages` 엔드포인트 |
| 🌐 VPN/프록시 지원 | HTTP/SOCKS5 프록시 지원 |
| 🧠 확장 사고 | 본 프로젝트 전용 추론 지원 |
| 👁️ 비전 지원 | 모델에 이미지 전송 |
| 🛠️ 도구 호출 | 함수 호출 지원 |
| 💬 전체 메시지 기록 | 완전한 대화 컨텍스트 전달 |
| 📡 스트리밍 | 완전한 SSE 스트리밍 지원 |
| 🔄 재시도 로직 | 오류 시 자동 재시도 (403, 429, 5xx) |
| 📋 확장 모델 목록 | 버전 지정 모델 포함 |
| 🔐 스마트 토큰 관리 | 만료 전 자동 갱신 |

## 📦 설치

### 다운로드

최신 릴리스 다운로드:

| 플랫폼 | 다운로드 |
|--------|----------|
| macOS | [KiroaaS.dmg](https://github.com/hnewcity/KiroaaS/releases) |

> Windows 및 Linux 지원 예정.

### 소스에서 빌드

```bash
# 저장소 클론
git clone https://github.com/hnewcity/KiroaaS.git
cd kiro-gateway

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
2. Kiro 자격 증명 **설정** (가능한 경우 자동 감지)
3. 서버 **시작**
4. `http://localhost:8000`을 OpenAI API 엔드포인트로 **사용**

```bash
# 예시: curl로 Kiro와 대화
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "kiro",
    "messages": [{"role": "user", "content": "안녕하세요!"}]
  }'
```

## 🔌 호환 도구

KiroaaS는 인기 있는 AI 도구 및 라이브러리와 호환됩니다:

- **Python**: OpenAI SDK, LangChain, LlamaIndex
- **JavaScript**: OpenAI Node.js SDK, Vercel AI SDK
- **앱**: Cursor, Continue, ChatGPT-Next-Web 등

```python
# Python 예시
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="not-needed"
)

response = client.chat.completions.create(
    model="kiro",
    messages=[{"role": "user", "content": "안녕하세요!"}]
)
```

## ⚙️ 설정

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| 호스트 | `127.0.0.1` | 서버 바인드 주소 |
| 포트 | `8000` | 서버 포트 |
| 리전 | `us-east-1` | Kiro 리전 |

고급 옵션은 설정 패널에서 사용할 수 있습니다.

## 🛠️ 기술 스택

- **프론트엔드**: React + TypeScript + Tailwind CSS
- **데스크톱**: Tauri (Rust)
- **백엔드**: Python + FastAPI

## 🤝 기여

기여를 환영합니다!

- 🐛 버그 신고
- 💡 기능 제안
- 🔧 풀 리퀘스트 제출

## 📄 라이선스

[AGPL-3.0](../LICENSE) © KiroaaS 기여자
