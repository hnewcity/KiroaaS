# Tauri 自动更新实现指南

本文档详细说明了 KiroaaS 项目中 Tauri 自动更新功能的完整实现。

## 📋 目录

1. [概述](#概述)
2. [初始设置](#初始设置)
3. [发布新版本](#发布新版本)
4. [前端集成](#前端集成)
5. [故障排查](#故障排查)

---

## 概述

KiroaaS 使用 Tauri 内置的更新器功能,通过 GitHub Releases 分发更新。更新流程:

1. 用户打开应用时自动检查更新
2. 发现新版本时显示更新提示
3. 用户确认后下载并验证签名
4. 安装更新并重启应用

### 安全机制

- 所有更新包使用 Ed25519 签名
- 客户端验证签名后才安装
- 使用 HTTPS 下载更新包

---

## 初始设置

### 1. 生成签名密钥对

**⚠️ 只需执行一次,密钥需要妥善保管!**

```bash
npm run tauri signer generate -w ~/.tauri/kiroaas.key
```

输入密码后会生成:

- **私钥**: `~/.tauri/kiroaas.key` (保密!)
- **公钥**: 终端输出,类似 `dW50cnVzdGVkIGNvbW1lbnQ6...`

### 2. 配置公钥

将生成的公钥复制到 `src-tauri/tauri.conf.json`:

```json
{
  "tauri": {
    "updater": {
      "active": true,
      "endpoints": [
        "https://github.com/hnewcity/KiroaaS/releases/latest/download/latest.json"
      ],
      "dialog": true,
      "pubkey": "你的公钥内容"
    }
  }
}
```

### 3. 保护私钥

**重要**: 私钥文件 `~/.tauri/kiroaas.key` 必须:

- ✅ 备份到安全位置
- ✅ 添加到 `.gitignore`
- ❌ 永远不要提交到 Git
- ❌ 永远不要分享给他人

---

## 发布新版本

### 步骤 1: 更新版本号

在以下三个文件中同步更新版本号:

**package.json**:

```json
{
  "version": "1.0.1"
}
```

**src-tauri/Cargo.toml**:

```toml
[package]
version = "1.0.1"
```

**src-tauri/tauri.conf.json**:

```json
{
  "package": {
    "version": "1.0.1"
  }
}
```

### 步骤 2: 构建应用

```bash
npm run tauri build
```

构建产物位于 `src-tauri/target/release/bundle/`:

- **macOS**: `macos/KiroaaS.app.tar.gz`
- **Windows**: `msi/KiroaaS_1.0.1_x64_en-US.msi`
- **Linux**: `appimage/kiroaas_1.0.1_amd64.AppImage`

### 步骤 3: 签名更新包

为每个平台的安装包生成签名:

```bash
# macOS (Intel)
npm run tauri signer sign \
  src-tauri/target/release/bundle/macos/KiroaaS.app.tar.gz \
  -k ~/.tauri/kiroaas.key

# macOS (Apple Silicon) - 如果有单独构建
npm run tauri signer sign \
  src-tauri/target/aarch64-apple-darwin/release/bundle/macos/KiroaaS.app.tar.gz \
  -k ~/.tauri/kiroaas.key

# Windows
npm run tauri signer sign \
  src-tauri/target/release/bundle/msi/KiroaaS_1.0.1_x64_en-US.msi \
  -k ~/.tauri/kiroaas.key

# Linux
npm run tauri signer sign \
  src-tauri/target/release/bundle/appimage/kiroaas_1.0.1_amd64.AppImage \
  -k ~/.tauri/kiroaas.key
```

每个命令会生成对应的 `.sig` 文件。

### 步骤 4: 创建更新清单

创建 `latest.json` 文件:

```json
{
  "version": "1.0.1",
  "notes": "更新说明:\n- 修复了登录问题\n- 优化了性能\n- 添加了新功能",
  "pub_date": "2026-02-04T12:00:00Z",
  "platforms": {
    "darwin-x86_64": {
      "signature": "从 KiroaaS.app.tar.gz.sig 文件复制的内容",
      "url": "https://github.com/hnewcity/KiroaaS/releases/download/v1.0.1/KiroaaS.app.tar.gz"
    },
    "darwin-aarch64": {
      "signature": "从 KiroaaS.app.tar.gz.sig 文件复制的内容",
      "url": "https://github.com/hnewcity/KiroaaS/releases/download/v1.0.1/KiroaaS-aarch64.app.tar.gz"
    },
    "linux-x86_64": {
      "signature": "从 .AppImage.sig 文件复制的内容",
      "url": "https://github.com/hnewcity/KiroaaS/releases/download/v1.0.1/kiroaas_1.0.1_amd64.AppImage.tar.gz"
    },
    "windows-x86_64": {
      "signature": "从 .msi.sig 文件复制的内容",
      "url": "https://github.com/hnewcity/KiroaaS/releases/download/v1.0.1/KiroaaS_1.0.1_x64_en-US.msi.zip"
    }
  }
}
```

**注意**:

- `signature` 字段的内容从对应的 `.sig` 文件中复制
- `url` 必须指向实际的下载地址
- `pub_date` 使用 ISO 8601 格式

### 步骤 5: 发布到 GitHub

1. 创建新的 Git tag:

```bash
git tag v1.0.1
git push origin v1.0.1
```

1. 在 GitHub 上创建 Release:
   - 进入 <https://github.com/hnewcity/KiroaaS/releases/new>
   - 选择刚创建的 tag `v1.0.1`
   - 填写 Release 标题和说明
   - 上传以下文件:
     - `latest.json`
     - `KiroaaS.app.tar.gz` (macOS)
     - `KiroaaS_1.0.1_x64_en-US.msi.zip` (Windows)
     - `kiroaas_1.0.1_amd64.AppImage.tar.gz` (Linux)
   - 发布 Release

### 步骤 6: 验证更新

1. 打开旧版本的应用
2. 应用会自动检查更新
3. 确认显示更新提示
4. 点击更新按钮
5. 验证更新成功并重启

---

## 前端集成

### 使用更新 API

在 TypeScript/React 中使用更新功能:

```typescript
import { checkForUpdates, installUpdate } from './lib/tauri';

// 检查更新
async function checkUpdate() {
  try {
    const hasUpdate = await checkForUpdates();
    if (hasUpdate) {
      console.log('发现新版本!');
      // 显示更新提示
    }
  } catch (error) {
    console.error('检查更新失败:', error);
  }
}

// 安装更新
async function installUpdateNow() {
  try {
    await installUpdate();
    // 应用会自动重启
  } catch (error) {
    console.error('安装更新失败:', error);
  }
}
```

### 更新检查组件

参考 `src/components/UpdateChecker.tsx.example` 文件,其中包含:

- 启动时自动检查更新
- 显示更新提示 UI
- 处理更新安装
- 错误处理

---

## 故障排查

### 问题 1: 签名验证失败

**症状**: 更新下载后提示签名验证失败

**解决方案**:

1. 确认 `tauri.conf.json` 中的公钥正确
2. 确认使用正确的私钥签名
3. 确认 `.sig` 文件内容完整复制到 `latest.json`

### 问题 2: 无法检查更新

**症状**: `checkForUpdates()` 返回错误

**解决方案**:

1. 确认 `latest.json` 文件可访问
2. 检查网络连接
3. 确认 URL 格式正确
4. 查看浏览器控制台错误信息

### 问题 3: 更新下载失败

**症状**: 下载更新包时失败

**解决方案**:

1. 确认安装包文件已上传到 GitHub Release
2. 确认 URL 指向正确的文件
3. 确认文件格式正确 (tar.gz 或 zip)
4. 检查文件大小是否正常

### 问题 4: 更新后应用无法启动

**症状**: 安装更新后应用崩溃或无法启动

**解决方案**:

1. 检查新版本是否正确构建
2. 在本地测试新版本
3. 回滚到旧版本
4. 检查应用日志

---

## 最佳实践

### 版本管理

- 使用语义化版本 (Semantic Versioning)
- 主版本号: 不兼容的 API 变更
- 次版本号: 向后兼容的功能新增
- 修订号: 向后兼容的问题修正

### 发布流程

1. 在开发分支完成功能
2. 合并到主分支
3. 更新版本号
4. 创建 tag
5. 构建和签名
6. 发布 Release
7. 验证更新功能

### 安全建议

- 定期备份私钥
- 使用强密码保护私钥
- 只在安全环境中签名
- 验证每次发布的签名
- 监控更新服务器日志

---

## 自动化发布 (可选)

可以使用 GitHub Actions 自动化发布流程。创建 `.github/workflows/release.yml`:

```yaml
name: Release

on:
  push:
    tags:
      - 'v*'

jobs:
  release:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]

    steps:
      - uses: actions/checkout@v3

      - name: Setup Node.js
        uses: actions/setup-node@v3
        with:
          node-version: 18

      - name: Install dependencies
        run: npm install

      - name: Build app
        run: npm run tauri build

      - name: Sign and upload
        env:
          TAURI_PRIVATE_KEY: ${{ secrets.TAURI_PRIVATE_KEY }}
        run: |
          # 签名和上传逻辑
```

**注意**: 需要将私钥添加到 GitHub Secrets。

---

## 参考资料

- [Tauri Updater 官方文档](https://tauri.app/v1/guides/distribution/updater)
- [语义化版本规范](https://semver.org/lang/zh-CN/)
- [GitHub Releases 文档](https://docs.github.com/en/repositories/releasing-projects-on-github)

---

**最后更新**: 2026-02-04
