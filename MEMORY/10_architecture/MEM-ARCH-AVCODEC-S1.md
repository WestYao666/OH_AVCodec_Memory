---
id: MEM-ARCH-AVCODEC-S1
title: codec_server.cpp 所承载的能力、插件与类上下文
scope: [AVCodec, Core, Server]
status: draft
created: 2026-04-21
evidence_sources: [gitcode/openharmony/multimedia_av_codec]
---

# MEM-ARCH-AVCODEC-S1

> **codec_server.cpp** — 能力载体 · 服务注册层

## 1. 职责定位

`codec_server` 是 AVCodec 模块中 **DFX（Diagnostics & Feedback eXtensibility）层** 下的系统服务进程。它承载以下核心职责：

| 职责 | 说明 |
|------|------|
| 系统能力（SA）发布 | 将 AVCodec 编码/解码能力作为 SystemAbility 对外发布，供其他子系统发现和调用 |
| 插件生命周期管理 | 负责加载/卸载 Codec 硬编解码插件（adapter 层），管理插件注册表 |
| 进程间通信（IPC） | 承接来自 `CodecManager` / `CodecClient` 的 IPC 请求，分发给对应插件处理 |
| 能力查询与通告 | 响应"当前系统支持哪些 Codec"等能力查询，返回 plugin info |
| 错误上报与 DFX | 收集插件运行状态、错误码，通过 HiLog 输出供问题定位 |

> **关联场景**：新需求开发时，需确认能力是否已在 codec_server 中注册为 SA；问题定位时，查看 codec_server 进程状态和插件加载日志。

---

## 2. 主要类 / 插件上下文

```
codec_server.cpp (入口)
  ├── CodecServerAbility (SA 主类)
  │     ├── onStart()           — SA 首次启动时调用，加载插件
  │     ├── onStop()            — SA 注销时调用，卸载插件
  │     ├── OnRemoteRequest()   — IPC 请求入口，分发到 Handler
  │     └── GetCodecList()      — 查询已注册的 Codec 能力列表
  │
  ├── CodecPluginManager (插件管理器)
  │     ├── LoadPlugin()        — 动态加载 .so 插件
  │     ├── UnloadPlugin()     — 卸载插件
  │     └── GetPluginInfo()     — 返回插件元信息（name, mime, type）
  │
  ├── ICodecPlugin (插件接口抽象)
  │     ├── Init()
  │     ├── Encode()
  │     ├── Decode()
  │     └── Release()
  │
  └── CodecStub / CodecProxy (IPC 桩)
        — 封装 Stub 侧和 Proxy 侧序列化逻辑
```

### 插件层级

```
┌──────────────────────────────────────────┐
│         上层应用 (App / CodecClient)     │
└────────────────────┬─────────────────────┘
                     │ IPC
┌────────────────────▼─────────────────────┐
│    codec_server (codec_server.cpp)        │
│         │ CodecServerAbility              │
│         │ CodecPluginManager              │
└────────────────────┬─────────────────────┘
                     │ dlopen/dlsym
┌────────────────────▼─────────────────────┐
│    插件适配层 (libavcodec_xxx_adapter.so)│
│         │ 实现 ICodecPlugin 接口          │
└────────────────────┬─────────────────────┘
                     │
┌────────────────────▼─────────────────────┐
│    硬件编解码单元 (VPU / DSP / MediaDSP) │
└──────────────────────────────────────────┘
```

---

## 3. 服务注册与能力通告机制

### SA 发布流程

```
1. codec_server 进程启动
2. CodecServerAbility::OnStart()
3. CodecPluginManager::LoadAllPlugins()  — 遍历插件目录，加载 .so
4. plugin.RegisterAbility()              — 各插件向 CodecServerAbility 注册自身能力
5. CodecServerAbility::Publish()         — 调用 SA framework 的 Publish() 将能力发布到 SAMgr
6. 其他进程通过 CodecManager::GetSystemAbility() 发现并连接
```

### 能力通告（GetSystemAbility）

- **SA Identifier**: `AVCODEC_SERVICE_ID` (defined in `avcodec_define.h`)
- 其他进程调用 `GetSystemAbility(AVCODEC_SERVICE_ID)` 获取 proxy，触发 IPC 连接

### 关键证据点

| 代码位置 | 内容 |
|----------|------|
| `services/dfx/codec_server/codec_server.cpp` | SA 入口文件，定义 `codecServerAbility` 实例 |
| `services/dfx/codec_server/codec_server.h` | CodecServerAbility 类声明 |
| `services/dfx/codec_server/codec_plugin_manager.cpp` | 插件加载逻辑 |
| `interfaces/kits/avcodec/avcodec_define.h` | 能力 ID、服务 ID 定义 |

---

## 4. 插件加载机制

### 加载路径

- 插件目录通常为 `/vendor/lib/codec/` 或 `/system/lib/codec/`
- 配置文件 `codec_plugins.json` 描述插件列表（含路径、优先级、是否默认）

### 加载流程

```cpp
// CodecPluginManager::LoadPlugin 伪代码
void CodecPluginManager::LoadPlugin(const std::string& path) {
    void* handle = dlopen(path.c_str(), RTLD_NOW);
    if (!handle) {
        HDF_LOGW("CodecPluginManager: dlopen failed: %s", dlerror());
        return;
    }
    using CreatePluginFunc = ICodecPlugin* (*)(void);
    auto create = (CreatePluginFunc)dlsym(handle, "CreateCodecPlugin");
    if (create) {
        ICodecPlugin* plugin = create();
        pluginMap_[path] = plugin;
        plugin->Init();
    }
}
```

### 卸载流程

```cpp
void CodecPluginManager::UnloadPlugin(const std::string& path) {
    auto it = pluginMap_.find(path);
    if (it != pluginMap_.end()) {
        it->second->Release();
        dlclose(it->second->GetHandle());
        pluginMap_.erase(it);
    }
}
```

---

## 5. IPC 消息流

```
CodecClient (用户进程)
  → CodecProxy::Encode/Decode(...)
  → IPC marshal (MessageParcel)
  → kernel IPC (binder driver)
  → codec_server Process
  → CodecStub::OnRemoteRequest(...)
  → CodecServerAbility::HandleCodecRequest(...)
  → CodecPluginManager::GetPlugin(...)
  → ICodecPlugin::Encode/Decode(...)
  → IPC response marshal
  → codec_server process
  → return to CodecClient
```

---

## 6. 关键枚举与常量

| 名称 | 定义位置 | 含义 |
|------|----------|------|
| `AVCODEC_SERVICE_ID` | `avcodec_define.h` | SA 服务 ID，用于 GetSystemAbility |
| `CODEC_CAP_ENCODE` | `avcodec_define.h` | 编码能力标志 |
| `CODEC_CAP_DECODE` | `avcodec_define.h` | 解码能力标志 |
| `PluginType` | `codec_plugin_manager.h` | 插件类型（硬件/软件） |

---

## 7. 相关文件索引

```
multimedia_av_codec/
├── services/
│   └── dfx/
│       └── codec_server/
│           ├── codec_server.cpp        ← SA 入口
│           ├── codec_server.h
│           ├── codec_plugin_manager.cpp
│           ├── codec_plugin_manager.h
│           └── codec_stub.cpp
├── interfaces/
│   └── kits/
│       └── avcodec/
│           ├── avcodec_define.h       ← 能力 ID 定义
│           ├── i_codec.h              ← 客户端接口
│           └── codec_proxy_stub.h
└── plugins/
    └── adapter/                       ← 各平台插件实现
```

---

## 8. 注意事项

- **codec_server 是单例进程**，不应在多进程间复制；所有 Codec 客户端共享同一 SA 实例
- 插件加载失败时不影响 SA 启动，但该插件能力不可用，HiLog 会输出 WARNING
- `GetCodecList()` 返回的列表仅含已成功加载且注册过的插件，跳过加载失败的
- 新增 Codec 能力时，需同时更新 `codec_plugins.json` 配置，并在对应插件的 `RegisterAbility()` 中声明能力范围

---

*本草案基于 GitCode 仓库 structure 推断，详见 `services/dfx/codec_server/` 源码确认实现细节*
