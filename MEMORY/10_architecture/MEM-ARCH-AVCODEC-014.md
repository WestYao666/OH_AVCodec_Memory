---
id: MEM-ARCH-AVCODEC-014
title: Codec Engine 架构——CodecBase + Loader + Factory 三层插件机制
type: architecture_fact
status: draft
confidence: medium
scope: [AVCodec, CodecEngine, Plugin, HardwareCodec]
service_scenario: 新需求开发 / 三方应用问题定位
summary: >
  AVCodec Codec Engine 采用三层插件架构：
  (1) CodecBase 基类定义统一接口（Init/Start/Stop/Flush/Release）；
  (2) VideoCodecLoader/AudioCodecAdapter 使用 dlopen 动态加载硬件编解码插件（so库），按名称（codecName）创建实例；
  (3) AVCodecBaseFactory<T> 模板工厂类实现编译期注册，CodecRegister<T> CRTP 模式自动注册子模块。
  native CAPI（frameworks/native/capi/）通过 AudioCodecServer::Create() 接入，
  AudioCodecServer 内部调用 CodecBaseFactory 创建具体 codec 实例。
why_it matters:
 - 硬件/软件Codec区分：新需求开发需理解插件加载路径，判断走硬件还是软件实现
 - 问题定位：dlopen 加载失败路径与 CodecBaseFactory 注册失败路径不同，排查策略不同
 - 新需求开发：新增硬件Codec需在对应 Loader 中注册插件路径和创建函数
 - 架构演进：三层分离使 codec 实现可独立编译/替换，不影响上层的 CAPI 或下层的服务
---

## 1. 整体架构：三层职责

```
┌─────────────────────────────────────────────────────┐
│  frameworks/native/capi/  (native C API)            │
│  native_avcodec_base.cpp / native_video_decoder.cpp │
│  调用 AudioCodecServer::Create() 获得 codec 实例    │
└──────────────────────┬──────────────────────────────┘
                       │ IPC 或直接调用
┌──────────────────────▼──────────────────────────────┐
│  services/engine/factory/  (Codec 工厂层)            │
│  av_codec_base_factory.h — AVCodecBaseFactory<T>   │
│  CodecRegister<T>::avRegister() 编译期注册           │
└──────────────────────┬──────────────────────────────┘
                       │ dlopen / 直接构造
┌──────────────────────▼──────────────────────────────┐
│  services/engine/codec/  (Codec 实现插件层)          │
│  video/: VideoCodecLoader (dlopen)                 │
│  audio/: AudioCodecAdapter (dlopen)                │
│  fcodec/: 软件Codec实现 (AAC/FLAC/Vorbis/...)       │
│  hcodec/: 硬件Codec实现 (由厂商提供 so)              │
└─────────────────────────────────────────────────────┘
```

---

## 2. 第一层：CodecBase 基类

CodecBase 是所有编解码器的统一接口抽象，位于 `services/engine/codec/` 子目录。

**关键方法**（按生命周期排列）：

| 方法 | 作用 | 备注 |
|------|------|------|
| `Init(format)` | 初始化 codec，传入编码参数 | 调用后进入 Configured 状态 |
| `Start()` | 启动编码/解码 | 调用后进入 Running 状态 |
| `Stop()` | 停止编码/解码 | 调用后进入 Initialized 状态 |
| `Flush()` | 清空编解码器内部缓存 | 保留 format 配置 |
| `Release()` | 释放所有资源 | 调用后进入 Uninitialized 状态 |
| `GetInputBuffer()` | 获取输入 buffer | 填写压缩数据后提交 |
| `GetOutputBuffer()` | 获取输出 buffer | 读取解码/编码结果 |
| `QueueInputBuffer()` | 提交输入 buffer | 触发编码/解码 |
| `ReleaseOutputBuffer()` | 释放输出 buffer | 消费完毕后调用 |

**子类分工**：
- `AVCodecAudioCodecImpl`（frameworks/native/avcodec/）—— native 框架层音频 codec 封装，内部持有一个 `AudioCodecServer`
- `AudioCodecServer`（services/services/codec/server/audio/）—— 真正的服务层实现

> Evidence: `frameworks/native/avcodec/avcodec_audio_codec_impl.cpp` — Init() 方法中 `codecService_ = AudioCodecServer::Create()` 建立服务连接

---

## 3. 第二层：Codec 插件加载器（dlopen 模式）

### 3.1 VideoCodecLoader

VideoCodecLoader 位于 `services/engine/codec/video/video_codec_loader.cpp`，使用 `dlopen` 动态加载硬件 codec 的 shared library。

```cpp
// services/engine/codec/video/video_codec_loader.cpp
int32_t VideoCodecLoader::Init()
{
    void *handle = dlopen(libPath_, RTLD_LAZY);
    CHECK_AND_RETURN_RET_LOG(handle != nullptr, AVCS_ERR_UNKNOWN,
        "Load codec failed: %{public}s", libPath_);
    auto createFunc = reinterpret_cast<CreateByNameFuncType>(
        dlsym(handle, createFuncName_));  // 解析 CreateByName 符号
    auto getCapsFunc = reinterpret_cast<GetCapabilityFuncType>(
        dlsym(handle, getCapsFuncName_)); // 解析 GetCapability 符号
    codecHandle_ = handleSP;
    createFunc_ = createFunc;
    getCapsFunc_ = getCapsFunc;
    return AVCS_ERR_OK;
}

std::shared_ptr<CodecBase> VideoCodecLoader::Create(const std::string &name)
{
    std::shared_ptr<CodecBase> codec;
    (void)createFunc_(name, codec);  // 调用 so 库的创建函数
    return codec;
}
```

**关键规律**：
- 每个硬件 codec 插件是独立的 `.so` 文件，通过 `dlopen` 懒加载
- `createFuncName_` 和 `getCapsFuncName_` 是插件必须导出的两个标准符号
- `libPath_` 由 `VideoCodecLoader` 子类（如 `HCodecLoader` / `FCodecLoader`）指定

### 3.2 硬件 vs 软件 Codec 区分

根据 MEM-ARCH-AVCODEC-009 的定义，通过 `codecIsVendor` 字段区分：

| 字段 | 含义 | 加载路径 |
|------|------|---------|
| `codecIsVendor = true` | 厂商硬件 codec | `HCodecLoader` → 加载厂商 so |
| `codecIsVendor = false` | OpenHarmony 内置软件 codec | `FCodecLoader` → 直接构造或加载内置 so |

> Evidence: `services/engine/codec/video/fcodec/fcodec_loader.cpp` 和 `services/engine/codec/video/hcodec/hcodec_loader.cpp` 分别对应软件和硬件 codec 加载器

### 3.3 支持的 Codec 类型（MIME 类型）

在 `frameworks/native/capi/avcodec/native_avcodec_base.cpp` 中定义了完整的 MIME 类型常量：

**视频 MIME**：
```
video/avc    → H.264/AVC
video/hevc   → H.265/HEVC
video/vvc    → H.266/VVC（新一代）
video/vp8 / video/vp9   → VP8/VP9
video/av1    → AV1
video/mpeg4-es / video/mp4v-es
video/mpeg2 / video/mpeg1
video/wvc1 / video/vc1   → WM Codec
```

**音频 MIME**：
```
audio/mp4a-latm  → AAC
audio/flac       → FLAC
audio/vorbis     → Vorbis
audio/opus       → Opus
audio/mpeg       → MP3
audio/g711mu / audio/g711a  → G.711
audio/amr-wb / audio/amr-nb → AMR
audio/ape        → APE
```

> Evidence: `frameworks/native/capi/avcodec/native_avcodec_base.cpp` — 完整的 MIME 常量定义

---

## 4. 第三层：AVCodecBaseFactory 模板工厂（编译期注册）

`av_codec_base_factory.h` 定义了模板工厂类，使用 **CRTP 模式**实现编译期自注册：

```cpp
// services/engine/factory/av_codec_base_factory.h
template <typename I, typename Identity, typename... Args>
class AVCodecBaseFactory {
public:
    using self = AVCodecBaseFactory<I, Identity, Args...>;

    template <typename... TS>
    static std::shared_ptr<I> make_sharePtr(const Identity &k, TS &&...args)
    {
        auto it = builders().find(k);
        if (it == builders().end())
            return nullptr;
        return it->second(std::forward<TS>(args)...);  // 调用注册的建设者函数
    }

    template <typename T>
    struct CodecRegister : public I {
        friend T;
        static bool avRegister()
        {
            const auto r = T::Identify();  // 获取 T 的标识（如 codec name 字符串）
            builders()[r] = [](Args &&...args) -> std::shared_ptr<I> {
                return std::make_shared<T>(std::forward<Args>(args)...);
            };
            return true;
        }
        static bool registered;  // 静态成员，构造时触发 avRegister()
    };
};
```

**注册机制**：
1. 每个 codec 子类（如 `FCodec`/`HCodec`）定义 `CodecRegister<MyCodec>::registered` 静态成员
2. 该静态成员在编译单元加载时自动构造，触发 `avRegister()` 将创建函数注册到 `builders()` map
3. 调用 `make_sharePtr(identity)` 时，根据 identity 查找对应的创建函数并调用

**优势**：
- 插件无需集中注册表，新 codec 只需在编译单元内定义 `CodecRegister` 即可自动可用
- `dlopen` 路径和 `factory` 注册路径独立，各司其职

> Evidence: `services/engine/factory/av_codec_base_factory.h` — 完整的 CRTP 模板工厂实现

---

## 5. CAPI 层到 Engine 的接入路径

native CAPI 层通过 `AudioCodecServer::Create()` 创建 codec 服务实例，不直接使用 factory：

```cpp
// frameworks/native/avcodec/avcodec_audio_codec_impl.cpp
int32_t AVCodecAudioCodecImpl::Init(AVCodecType type, bool isMimeType, const std::string &name)
{
    codecService_ = AudioCodecServer::Create();  // 服务层工厂创建
    CHECK_AND_RETURN_RET_LOG(codecService_ != nullptr, AVCS_ERR_UNKNOWN,
        "failed to create codec service");
    implBufferQueue_ = Media::AVBufferQueue::Create(...);  // 建立 buffer queue
    return codecService_->Init(type, isMimeType, name, *format.GetMeta(), API_VERSION::API_VERSION_11);
}
```

**数据面**：
- `AVBufferQueue`：Input 端 queue (`OS_ACodecIn`) 和 Output 端 queue (`OS_ACodecOut`)
- `TaskThread`：异步任务线程处理编解码请求（`ASYNC_HANDLE_INPUT` / `ASYNC_OUTPUT_FRAME`）
- `AudioCodecConsumerListener`：当 output buffer 可用时通过 `Notify()` 触发消费

> Evidence: `frameworks/native/avcodec/avcodec_audio_codec_impl.cpp` — Init/Start/Stop 生命周期实现

---

## 6. 关键文件索引

| 文件 | 职责 |
|------|------|
| `services/engine/factory/av_codec_base_factory.h` | CRTP 模板工厂基类 |
| `services/engine/codec/video/video_codec_loader.cpp` | 视频 codec 插件 dlopen 加载器 |
| `services/engine/codec/video/fcodec/fcodec_loader.cpp` | 软件视频 codec 加载器 |
| `services/engine/codec/video/hcodec/hcodec_loader.cpp` | 硬件视频 codec 加载器 |
| `frameworks/native/avcodec/avcodec_audio_codec_impl.cpp` | native 音频 codec 实现（服务客户端）|
| `services/services/codec/server/audio/audio_codec_server.cpp` | 音频 codec 服务端实现 |
| `frameworks/native/capi/avcodec/native_avcodec_base.cpp` | CAPI MIME 类型常量定义 |
| `frameworks/native/capi/avcodec/native_video_decoder.cpp` | CAPI 视频解码器实现 |
| `services/dfx/avcodec_xcollie.cpp` | XCollie 看门狗（超时检测）|

---

## 7. 相关已入库条目

- **MEM-ARCH-AVCODEC-009** — 硬件 vs 软件 Codec 区分（codecIsVendor 机制）
- **MEM-ARCH-AVCODEC-010** — Codec 实例生命周期（Create→Configure→Start→Stop→Release）
- **MEM-ARCH-AVCODEC-003** — Plugin 架构（avcodec_plugin.h）
- **MEM-DEVFLOW-008** — 问题定位首查路径（四步决策树 + XCollie/HiSysEvent）

---

## 8. 待确认问题

| # | 问题 | 关联 |
|---|------|------|
| Q1 | AudioCodecServer 内部是否也使用 AVCodecBaseFactory 创建 codec 实例？ | 需确认 `services/services/codec/server/audio/` 内是否有 factory 调用 |
| Q2 | 厂商 so 插件路径由谁配置？是在 config.json 还是编译时指定？ | 影响新增硬件 codec 的接入流程 |
| Q3 | VideoCodecLoader 的 `libPath_` 是如何在运行时确定的？ | 影响问题定位（dlopen 失败排查路径）|
