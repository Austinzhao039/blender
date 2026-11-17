# 环境监测 iOS 客户端 · 未签名 IPA 构建

`https://iot.austin666.top` 的原生 iOS 版（SwiftUI），以及一个在 GitHub 的 macOS runner 上
编出**未签名 IPA** 的 workflow。装到 iPhone/iPad 上不需要开发者账号、不需要越狱，
用自己的 Apple ID 自签即可（7 天有效，可续签）。

这是 Linux 上唯一能编 iOS 的办法 —— `xcodebuild` 只有 macOS 才有。

## 怎么出包

1. Actions 页 → **iOS 未签名 IPA** → `Run workflow`
2. 等 2~3 分钟（macos-14 runner 启动 + 编译）
3. 两种取包方式：
   - 运行页底部 **Artifacts** → `IoMonitor-unsigned-ipa`
   - 或者 **Releases** 里直接下 `IoMonitor-unsigned.ipa`（每次构建自动发一个 tag）

## 怎么装到设备上

用 **Sideloadly**（Win/Mac 都有）或 **AltStore**：

1. 下载 `IoMonitor-unsigned.ipa`
2. Sideloadly 里填自己的 Apple ID，选「Start」
3. 手机上「设置 → 通用 → VPN与设备管理」信任一下开发者证书
4. 首次打开若提示不受信任，按提示再进一次设置

免费 Apple ID 的限制：**7 天到期**（到期重装即可）、最多 3 个 App 同时装着。
付费开发者账号（$99/年）是 1 年有效期。

> 这个 workflow 用的是 `CODE_SIGNING_ALLOWED=NO`，产物**完全没有签名**、也没有 `_CodeSignature`。
> 这是正常的 —— 侧载工具会用自己的证书重新签一遍。别指望它能在未改动的设备上直接双击安装。

## 前提条件（重要）

- **Bundle ID 必须和你的 Apple ID 下已占用的不冲突**：默认 `top.austin666.iotmonitor`。
  如果 Sideloadly 报 "app identifier cannot be registered"，改 `IoMonitor.xcodeproj` 里的
  `PRODUCT_BUNDLE_IDENTIFIER` 再推一次即可。
- **iOS 版本**：最低 16.0（用到 `NavigationStack`）。iPad 上的 iPadOS 16+ 也支持。

## 仓库里有什么

```
IoMonitor.xcodeproj/     工程（由 tools/gen_xcodeproj.py 生成，UUID 确定性，重跑无 diff）
IoMonitor/               11 个 .swift + Info.plist + Assets.xcassets
tools/gen_xcodeproj.py   工程生成器；加源文件后重跑，或直接 --check 自检
.github/workflows/ios-app.yml
```

## 忘了改什么的时候

```bash
python3 tools/gen_xcodeproj.py --check   # 括号/ID 引用/文件存在/Sources 阶段
xcodebuild -version                      # 本机 Xcode（有 Mac 时）
```
