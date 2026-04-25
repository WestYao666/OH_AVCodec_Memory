---
type: architecture
id: MEM-ARCH-AVCODEC-S20
status: pending_approval
topic: PostProcessing 后处理框架——DynamicController+DynamicInterface+LockFreeQueue三组件与VPE插件热加载
created_at: "2026-04-24T10:50:00+08:00"
evidence: |
  - source: /home/west/av_codec_repo/services/services/codec/server/video/post_processing/post_processing.h
    anchor: "PostProcessing<T>::Create / SetOutputSurface / Prepare / Start / Stop / Flush / Reset / Release — CRTP模板类完整生命周期"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/post_processing/post_processing.h
    anchor: "PostProcessing<T>::Init() — HDR Vivid三元组校验（colorSpaceType/pixelFormat/metadataType），AVCS_ERR_UNSUPPORT无能力时返回"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/post_processing/post_processing.h
    anchor: "PostProcessing<T>::CreateConfiguration() — MD_KEY_VIDEO_DECODER_OUTPUT_COLOR_SPACE默认值BT709_Limit / 像素格式默认NV12"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/post_processing/post_processing.h
    anchor: "PostProcessing<T>::SetDecoderInputSurface() — controller_->CreateInputSurface→surface->SetSurfaceSourceType→codec_->SetOutputSurface 三步级联"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/post_processing/post_processing.h
    anchor: "PostProcessing<T>::ConfigureController() — primaries/transFunc/matrix/range四元组ColorSpace配置写入"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/post_processing/post_processing.h
    anchor: "PostProcessing<T>::SetOutputSurfaceTransform() — rotation映射（0→NONE/90→270/180→180/270→90），scalingMode透传"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/post_processing/controller.h
    anchor: "Controller<T>::LoadInterfaces / UnloadInterfaces / Create / Destroy / Configure / Prepare / Start / Stop / Flush / Reset / Release — CRTP派遣模式"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/post_processing/dynamic_controller.h
    anchor: "DynamicController::LoadInterfacesImpl() — ready_标志 + dlopen libvideoprocessingengine.z.so"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/post_processing/dynamic_controller.cpp
    anchor: "DynamicController::SetOutputSurfaceImpl() — surface->RegisterReleaseListener(OnProducerBufferReleased)"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/post_processing/dynamic_controller.cpp
    anchor: "DynamicController::CreateInputSurfaceImpl() — 返回sptr<Surface>给decoder，decoder调用SetOutputSurface(surface)"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/post_processing/dynamic_interface.h
    anchor: "DynamicInterface::Invoke<E>() — 函数指针数组interfaces_[I]通过dlsym解析，RTLD_LAZY延迟解析"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/post_processing/dynamic_interface.cpp
    anchor: "DynamicInterface::OpenLibrary() — dlopen('libvideoprocessingengine.z.so', RTLD_LAZY)，VPE（VideoProcessingEngine）动态库"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/post_processing/dynamic_interface.cpp
    anchor: "DynamicInterface::ReadSymbols() — 17个符号循环解析DYNAMIC_INTERFACE_SYMBOLS[]"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/post_processing/dynamic_interface_types.h
    anchor: "DYNAMIC_INTERFACE_SYMBOLS[] — ColorSpaceConvertVideo[Create/Destroy/SetCallback/SetOutputSurface/Configure/Start/Stop/Flush/...] 17个VPE接口"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/post_processing/dynamic_interface_types.h
    anchor: "DynamicInterfaceName enum — 17项（IS_COLORSPACE_CONVERSION_SUPPORTED/CREATE/DESTROY/SET_CALLBACK/SET_OUTPUT_SURFACE/CONFIGURE/PREPARE/START/STOP/FLUSH/RESET/RELEASE/RELEASE_OUTPUT_BUFFER/GET_OUTPUT_FORMAT/ON_PRODUCER_BUFFER_RELEASED/NOTIFY_EOS）"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/post_processing/state_machine.h
    anchor: "State enum — DISABLED/CONFIGURED/PREPARED/RUNNING/FLUSHED/STOPPED六状态，std::atomic<State> state_"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/post_processing/state_machine.cpp
    anchor: "STATE_NAMES[] — 'Disabled'/'Configured'/'Prepared'/'Running'/'Flushed'/'Stopped'/'Unknown'"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/post_processing/post_processing_callback.h
    anchor: "Callback struct — OnErrorCallback / OnOutputBufferAvailableCallback / OnOutputFormatChangedCallback 三路回调"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/post_processing/post_processing_utils.h
    anchor: "TypeArray<Types...> — std::tuple实现编译期函数指针类型列表，Get<I>通过tuple_element_t取第I个类型"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/post_processing/post_processing_utils.h
    anchor: "EnumerationValue<T, V> — 编译期枚举值到整型映射，value=static_cast<UnderlyingType>(V)"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/post_processing/lock_free_queue.h
    anchor: "LockFreeQueue<T, N> — 单生产者单消费者无锁环形队列，PushWait/PopWait接口，QueueResult::OK/FULL/EMPTY/INACTIVE/NO_MEMORY"
  - source: /home/west/av_codec_repo/services/services/codec/server/video/post_processing/post_processing.h
    anchor: "DynamicPostProcessing = PostProcessing<DynamicController> — 类型别名"
---

# MEM-ARCH-AVCODEC-S20: PostProcessing 后处理框架——DynamicController+DynamicInterface+LockFreeQueue三组件与VPE插件热加载

## Metadata

| 字段 | 值 |
|------|-----|
| id | MEM-ARCH-AVCODEC-S20 |
| title | PostProcessing 后处理框架——DynamicController+DynamicInterface+LockFreeQueue三组件与VPE插件热加载 |
| scope | [AVCodec, PostProcessing, VPE, DynamicController, DynamicInterface, ColorSpace, LockFreeQueue] |
| status | draft |
| created_by | builder-agent |
| created_at | 2026-04-24 |
| type | architecture_fact |
| confidence | high |
| related_scenes | [新需求开发, 问题定位, 后处理, 色域转换, VPE插件, 无锁队列] |
| why_it_matters: |
  - 问题定位：视频解码输出色彩异常（偏色/色域错误），需排查 PostProcessing 的 ColorSpace 转换配置
  - 新需求开发：视频Pipeline中插入后处理（旋转/缩放/色域转换）需理解 PostProcessing 的状态机与Controller派遣机制
  - 性能分析：VPE（libvideoprocessingengine.z.so）通过 dlopen/RTLD_LAZY 动态加载，失败时降级无后处理
  - CodecServer 集成：PostProcessing 是 CodecServer 的成员（codec_），通过 SetDecoderInputSurface 与 Decoder 级联

## 1. 概述

PostProcessing（后处理框架）是 AVCodec 视频解码 Pipeline 中的一个**可选插件化处理阶段**，位于解码器（Decoder）与输出 Surface 之间，职责包括：

- **色域转换**：BT709 Limited ↔ P3 Full 等色彩空间转换
- **旋转/缩放**：视频解码后输出方向的修正
- **HDR Vivid 支持**：元数据透传与色彩参数配置

其核心设计为 **CRTP 模板方法模式** + **动态接口 dlopen 插件**：
- `PostProcessing<T>`：模板基类，定义标准生命周期（Create→Configure→Prepare→Start→Stop→Flush→Release）
- `DynamicController`：通过 `DynamicInterface` 调用 VPE（VideoProcessingEngine）动态库
- `DynamicInterface`：dlopen/RTLD_LAZY 加载 `libvideoprocessingengine.z.so`，通过 dlsym 解析 17 个符号

> 对应 `DynamicPostProcessing = PostProcessing<DynamicController>`

---

## 2. 核心数据结构

### 2.1 PostProcessing 模板类

**文件**: `post_processing.h`

```cpp
template<typename T, typename = IsDerivedController<T>>
class PostProcessing {
    // CRTP派遣：controller_ = std::make_unique<T>()  // T=DynamicController
    // 生命周期: DISABLED → CONFIGURED → PREPARED → RUNNING
    //                   ↓ FLUSHED / STOPPED（可跳转回RUNNING）
};
```

**成员变量**:
- `state_`: `StateMachine` — 六状态机
- `controller_`: `std::unique_ptr<Controller<T>>` — 实际执行者
- `codec_`: `std::shared_ptr<CodecBase>` — 绑定的解码器实例
- `config_`: `Configuration` — 配置结构（宽/高/色空间/像素格式/旋转/缩放）
- `callback_`: `Callback` — 三路回调（onError/onOutputBuffer/onFormatChanged）

**Configuration 结构**:
```cpp
struct Configuration {
    int32_t width{0}, height{0};
    int32_t inputColorSpaceType{0}, inputMetadataType{0}, inputPixelFormat{0};
    sptr<Surface> inputSurface{nullptr};   // decoder的输出Surface（VPE创建）
    int32_t outputColorSpaceType{0}, outputMetadataType{0}, outputPixelFormat{0};
    sptr<Surface> outputSurface{nullptr};  // 用户的输出Surface
    int32_t rotation{0};    // 0/90/180/270
    int32_t scalingMode{0};  // 0=NoScaling, 1=ScaleToWindow, 2=ScaleCrop
};
```

### 2.2 DynamicInterface 动态接口

**文件**: `dynamic_interface.h` / `dynamic_interface.cpp`

通过 `dlopen("libvideoprocessingengine.z.so", RTLD_LAZY)` 加载 VPE 动态库，解析 17 个函数符号：

```cpp
constexpr const char* DYNAMIC_INTERFACE_SYMBOLS[]{
    "ColorSpaceConvertVideoIsColorSpaceConversionSupported",
    "ColorSpaceConvertVideoCreate",
    "ColorSpaceConvertVideoDestroy",
    "ColorSpaceConvertVideoSetCallback",
    "ColorSpaceConvertVideoSetOutputSurface",
    "ColorSpaceConvertVideoCreateInputSurface",
    "ColorSpaceConvertVideoConfigure",
    "ColorSpaceConvertVideoPrepare",
    "ColorSpaceConvertVideoStart",
    "ColorSpaceConvertVideoStop",
    "ColorSpaceConvertVideoFlush",
    "ColorSpaceConvertVideoReset",
    "ColorSpaceConvertVideoRelease",
    "ColorSpaceConvertVideoReleaseOutputBuffer",
    "ColorSpaceConvertVideoGetOutputFormat",
    "ColorSpaceConvertVideoOnProducerBufferReleased",
    "ColorSpaceConvertVideoNotifyEos"
};
```

**调用方式**: `interface_.Invoke<DynamicInterfaceName::CREATE>()` — 编译期索引 + 函数指针数组

### 2.3 StateMachine 状态机

**文件**: `state_machine.h` / `state_machine.cpp`

```
DISABLED → CONFIGURED → PREPARED → RUNNING
                              ↑         ↓
                          FLUSHED ←←← STOPPED
```

| 状态 | 触发条件 |
|------|---------|
| DISABLED | 初始 / Reset() 完成后 |
| CONFIGURED | Init() 成功（HDR Vivid 能力校验通过） |
| PREPARED | Prepare() 成功（VPE 创建+Surface绑定完成） |
| RUNNING | Start() 成功 |
| FLUSHED | Flush() 成功 |
| STOPPED | Stop() 成功 |

---

## 3. 生命周期详解

### 3.1 正常路径（Create → Start）

```
1. PostProcessing::Create(codec, format, ret)
   └─ new PostProcessing(codec)
   └─ Init(format)
      └─ std::make_unique<T>()        // new DynamicController()
      └─ controller_->LoadInterfaces() // dlopen VPE
      └─ CreateConfiguration(format)   // 解析宽高/色空间/像素格式/旋转/缩放
      └─ HDR Vivid能力校验（三元组遍历）
      └─ state_ = CONFIGURED

2. SetOutputSurface(surface)
   └─ state_ == CONFIGURED: 仅保存到config_.outputSurface
   └─ state_ >= PREPARED: 透传给controller_->SetOutputSurface()

3. Prepare()
   └─ controller_->Create()                    // VPE实例创建
   └─ SetOutputSurfaceTransform()              // rotation/scalingMode写入Surface
   └─ controller_->SetOutputSurface(surface)   // VPE绑定输出Surface
   └─ SetDecoderInputSurface()                 // 创建VPE输入Surface，decoder.SetOutputSurface(输入Surface)
   └─ controller_->SetCallback()               // 注册三路回调
   └─ ConfigureController()                    // 四元组色彩参数写入VPE
   └─ controller_->Prepare()
   └─ state_ = PREPARED

4. Start()
   └─ controller_->Start()
   └─ state_ = RUNNING
```

### 3.2 SetDecoderInputSurface 关键链路

```cpp
int32_t SetDecoderInputSurface()
{
    sptr<Surface> surface = nullptr;
    ret = controller_->CreateInputSurface(surface);  // VPE创建输入Surface
    surface->SetSurfaceSourceType(OH_SURFACE_SOURCE_VIDEO);  // 标记来源
    ret = codec_->SetOutputSurface(surface);          // Decoder输出绑定到VPE输入Surface
    config_.inputSurface = surface;
}
```

这条链路使 VPE 能拦截 Decoder 的输出 buffer，进行色彩转换后再输出到用户 Surface。

### 3.3 VPE 插件降级

当 VPE 库加载失败时（dlopen 返回 nullptr），`LoadInterfacesImpl()` 返回 `false`，
但 `Init()` 中若所有 HDR Vivid 三元组都不支持，则返回 `AVCS_ERR_UNSUPPORT`，
此时 **PostProcessing 不会被创建**，CodecServer 直接输出解码帧（无后处理）。

### 3.4 Surface Release 监听

```cpp
// DynamicController::SetOutputSurfaceImpl
surface->RegisterReleaseListener([this](sptr<SurfaceBuffer> &buffer) -> GSError {
    return OnProducerBufferReleased(buffer);  // 回调VPE ON_PRODUCER_BUFFER_RELEASED
});
```

当用户 Surface 释放 buffer 时，触发 VPE 的资源清理回调。

---

## 4. LockFreeQueue 无锁队列

**文件**: `lock_free_queue.h`

```cpp
template<typename T, std::size_t N>
class LockFreeQueue {
    // 单生产者 + 单消费者无锁环形队列
    // PushWait / PopWait 阻塞接口
    // QueueResult: OK / FULL / EMPTY / INACTIVE / NO_MEMORY
};
```

用于 PostProcessing 内部 buffer 传递，保证生产端（VPE）和消费端（用户回调）无锁并发。

---

## 5. ColorSpace 配置参数

**四元组色彩系统**:

| 参数 | BT709 Limited | P3 Full |
|------|--------------|---------|
| primaries | 1 | 6 |
| transFunc | 1 | 2 |
| matrix | 1 | 3 |
| range | 2 | 1 |

**HDR Vivid 判定**（Init 时校验）:
- 色彩空间：BT2020 HLG Limit(0x440504) / BT2020 PQ Limit(0x440404) / BT2020 HLG Full(0x240504)
- 元数据类型：3（HDR Vivid Video）
- 像素格式：35(NV12) / 36(NV21)

---

## 6. 关联主题

| 主题 | 关联点 |
|------|--------|
| S16: SurfaceCodec与Surface绑定 | PostProcessing 是 CodecServer 的成员，SetDecoderInputSurface 依赖 Decoder 的 SetOutputSurface |
| S12: VideoResizeFilter | VideoResizeFilter 是 FilterChain 的一环，与 PostProcessing 同属视频处理组件，但位于不同层级 |
| S15: SuperResolutionPostProcessor | 超分后处理与 PostProcessing 并列，通过 Plugin 注册到 FilterChain |
| S3: CodecServer Pipeline | CodecServer 管理 PostProcessing 的创建、配置与销毁 |
| P1f: Codec Engine 架构 | PostProcessing 通过 CodecBase 调用解码器，属于服务层编排 |

---

## 7. 关键常量汇总

| 常量 | 值 | 含义 |
|------|----|------|
| libvideoprocessingengine.z.so | VPE动态库 | dlopen加载的VideoProcessingEngine插件 |
| RTLD_LAZY | dlopen标志 | 延迟解析符号 |
| DYNAMIC_INTERFACE_NUM | 17 | VPE接口函数数量 |
| ConfigurationParameters::pixelFormatNV12 | 24 | NATIVEBUFFER_PIXEL_FMT_YCBCR_420_SP |
| ConfigurationParameters::pixelFormatNV21 | 25 | NATIVEBUFFER_PIXEL_FMT_YCRCB_420_SP |
| ConfigurationParameters::colorSpaceBT709Limited | 0x410101 | OH_COLORSPACE_BT709_LIMIT |
| ConfigurationParameters::colorSpaceP3Full | 0x230206 | OH_COLORSPACE_P3_FULL |
| hdrVividVideoMetadataType | 3 | HDR Vivid Video 元数据类型 |
| OH_SURFACE_SOURCE_VIDEO | Surface来源标记 | SetDecoderInputSurface中设置 |
