# KiroaaS

<p align="center">
  <img src="../public/icon.png" alt="KiroaaS Logo" width="128" height="128">
</p>

<h3 align="center">Kiro as a Service</h3>
<p align="center">ワンクリックで Kiro を OpenAI 互換・Anthropic 互換 API に変換</p>

<p align="center">
  <a href="../README.md">🇺🇸 English</a> • <a href="README_zh.md">🇨🇳 中文</a> • 🇯🇵 日本語 • <a href="README_ko.md">🇰🇷 한국어</a> • <a href="README_ru.md">🇷🇺 Русский</a> • <a href="README_es.md">🇪🇸 Español</a> • <a href="README_pt.md">🇧🇷 Português</a> • <a href="README_id.md">🇮🇩 Indonesia</a>
</p>

<p align="center">
  <a href="https://opensource.org/licenses/AGPL-3.0"><img src="https://img.shields.io/badge/License-AGPL%203.0-blue.svg" alt="License: AGPL-3.0"></a>
  <img src="https://img.shields.io/badge/platform-macOS%20%7C%20Windows-brightgreen" alt="Platform">
  <a href="http://makeapullrequest.com"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome"></a>
</p>

<p align="center">
  <img src="../app-screenshot.webp" alt="KiroaaS スクリーンショット" width="800">
</p>

---

KiroaaS（Kiro as a Service）は、ローカルの OpenAI 互換・Anthropic 互換 API を通じて Kiro の AI モデルを公開するデスクトップゲートウェイです。コードを変更することなく、お気に入りの AI ツール、ライブラリ、アプリケーションで Kiro を使用できます。

## ✨ 機能

| 機能 | 説明 |
|------|------|
| 🔌 **OpenAI 互換 API** | OpenAI SDK 用の `/v1/chat/completions` エンドポイント |
| 🔌 **Anthropic 互換 API** | Anthropic SDK 用の `/v1/messages` エンドポイント |
| 🌐 **VPN/プロキシ対応** | 制限されたネットワーク用の HTTP/SOCKS5 プロキシ |
| 🧠 **拡張思考** | 本プロジェクト独自の推論サポート |
| 👁️ **ビジョン対応** | モデルに画像を送信 |
| 🛠️ **ツール呼び出し** | 関数呼び出しをサポート |
| 💬 **内蔵チャット** | 統合チャットインターフェースで設定をテスト |
| 📡 **ストリーミング** | 完全な SSE ストリーミングサポート |
| 🔄 **リトライロジック** | エラー時の自動リトライ (403, 429, 5xx) |
| 🔐 **スマートトークン管理** | 有効期限前に自動更新 |
| 🌍 **多言語 UI** | English, 中文, 日本語, 한국어, Русский, Español, Português, Indonesia |
| 🔗 **CC Switch 連携** | [CC Switch](https://github.com/farion1231/cc-switch) へワンクリックインポート（Claude Code 用） |
| 🔄 **自動アップデート** | 内蔵アップデートチェッカーで最新版を維持 |

## 📦 インストール

### ダウンロード

[GitHub Releases](https://github.com/hnewcity/KiroaaS/releases) から最新リリースをダウンロード：

| プラットフォーム | アーキテクチャ | ダウンロード |
|------------------|----------------|--------------|
| macOS | Apple Silicon (M1/M2/M3) | [KiroaaS_aarch64.dmg](https://github.com/hnewcity/KiroaaS/releases) |
| macOS | Intel | [KiroaaS_x64.dmg](https://github.com/hnewcity/KiroaaS/releases) |
| Windows | x64 | [KiroaaS_x64-setup.exe](https://github.com/hnewcity/KiroaaS/releases) |

> Linux のサポートは近日公開予定。

### ソースからビルド

```bash
# リポジトリをクローン
git clone https://github.com/hnewcity/KiroaaS.git
cd KiroaaS

# 依存関係をインストール
npm install
cd python-backend && pip install -r requirements.txt && cd ..

# 開発モードで実行
npm run tauri:dev

# または本番用にビルド
npm run tauri:build
```

## 🚀 クイックスタート

1. KiroaaS を**起動**
2. Kiro 認証情報を**設定**（Kiro CLI がインストールされていれば自動検出）
3. プロキシ API キーを**生成**（または管理者から提供されたキーを使用）
4. サーバーを**開始**
5. `http://localhost:8000` を OpenAI/Anthropic API エンドポイントとして**使用**

### 例：cURL

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_PROXY_API_KEY" \
  -d '{
    "model": "claude-sonnet-4-5",
    "messages": [{"role": "user", "content": "こんにちは！"}]
  }'
```

### 例：Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="YOUR_PROXY_API_KEY"
)

response = client.chat.completions.create(
    model="claude-sonnet-4-5",
    messages=[{"role": "user", "content": "こんにちは！"}]
)
print(response.choices[0].message.content)
```

### 例：JavaScript (OpenAI SDK)

```javascript
import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: 'http://localhost:8000/v1',
  apiKey: 'YOUR_PROXY_API_KEY',
});

const response = await client.chat.completions.create({
  model: 'claude-sonnet-4-5',
  messages: [{ role: 'user', content: 'こんにちは！' }],
});
console.log(response.choices[0].message.content);
```

## 🔌 対応ツール

KiroaaS は人気の AI ツールやライブラリと互換性があります：

| カテゴリ | ツール |
|----------|--------|
| **Python** | OpenAI SDK, Anthropic SDK, LangChain, LlamaIndex |
| **JavaScript** | OpenAI Node.js SDK, Anthropic SDK, Vercel AI SDK |
| **IDE 拡張機能** | Cursor, Continue, Cline, Claude Code |
| **チャットアプリ** | ChatGPT-Next-Web, LobeChat, Open WebUI |

## ⚙️ 設定

### 認証方式

KiroaaS は複数の認証方式をサポート：

| 方式 | 説明 |
|------|------|
| **Kiro CLI データベース** | Kiro CLI から認証情報を自動検出（推奨） |
| **認証情報ファイル** | JSON 認証情報ファイルを使用 |
| **リフレッシュトークン** | リフレッシュトークンを手動入力 |

### サーバー設定

| オプション | デフォルト | 説明 |
|------------|------------|------|
| ホスト | `127.0.0.1` | サーバーバインドアドレス |
| ポート | `8000` | サーバーポート |
| プロキシ API キー | - | API 認証に必要なキー |

### 詳細設定

| オプション | 説明 |
|------------|------|
| VPN/プロキシ URL | ネットワーク制限用の HTTP/SOCKS5 プロキシ |
| 最初のトークンタイムアウト | 初期応答のタイムアウト（秒） |
| ストリーミング読み取りタイムアウト | ストリーミング応答のタイムアウト（秒） |

## 🛠️ 技術スタック

| レイヤー | 技術 |
|----------|------|
| **フロントエンド** | React + TypeScript + Tailwind CSS |
| **デスクトップ** | Tauri (Rust) |
| **バックエンド** | Python + FastAPI |

## 🤝 コントリビュート

コントリビュートを歓迎します！

- 🐛 [GitHub Issues](https://github.com/hnewcity/KiroaaS/issues) でバグを報告
- 💡 機能を提案
- 🔧 プルリクエストを送信
- 🌍 翻訳を手伝う

## 📄 ライセンス

[AGPL-3.0](../LICENSE) © KiroaaS コントリビューター
