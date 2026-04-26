# MEM-ARCH-AVCODEC-S57: HDecoder / HEncoder 硬件视频编解码器——OMX组件架构与HDI四层调用链

> **状态**: draft
> **生成时间**: 2026-04-26T20:51
> **scope**: AVCodec, HardwareCodec, HDI, OMX, HDecoder, HEncoder, CodecBase, StateMachine, MsgHandleLoop, DMA-BUF, SuspendResume
> **关联场景**: 新需求开发/问题定位
> **memory_id**: MEM-ARCH-AVCODEC-S57

---

## 1. 背景

Hcodec 是 OpenHarmony AVCodec 模块中对接硬件 OMX (OpenMAX IL) 组件的核心子系统。它通过 HDI (Hardware Device Interface) V4.0 接口与厂商提供的硬件编解码器通信，实现了视频硬件加速。

**与 S39/S51/S53/S54 的关系**:
- S39 (VideoDecoder): 视频解码器 Filter 层封装，包含 VideoDecoderAdapter
- S51 (Av1Decoder): 基于 dav1d 库的软件 AV1 解码器
- S53 (FCodec): 基于 FFmpeg libavcodec 的软件 H.264/AVC 解码器
- S54 (HevcDecoder/VpxDecoder): 基于 libhevcdec_ohos 和 libvpx 的软件解码器
- **S57**: 上述均为软件解码器；S57 覆盖的是**硬件编解码器**，通过 OMX/HDI 路径

**代码路径**:
```
services/engine/codec/video/hcodec/
```

---

## 2. 架构概览

### 2.1 类继承层次

```
CodecBase (codecbase.h)
    └── HCodec (hcodec.h, line 35)  [核心基类, 继承 StateMachine]
            ├── HDecoder (hdecoder.h)  [硬件视频解码器]
            └── HEncoder (hencoder.h)  [硬件视频编码器]
```

**证据**:
- `class HCodec : public CodecBase, protected StateMachine` — hcodec.h:35
- `class HDecoder : public HCodec` — hdecoder.h:28
- `class HEncoder : public HCodec` — hencoder.h:24

### 2.2 三层调用链

```
AVCodecVideoEncoder/VideoDecoder (Filter适配层)
    ↓ SurfaceEncoderAdapter / VideoDecoderAdapter
HDecoder / HEncoder (HCodec子类, OMX逻辑)
    ↓ ICodecComponent (HDI调用)
厂商硬件CodecComponent (OMX组件)
```

### 2.3 核心组件文件清单

| 文件 | 行数 | 职责 |
|------|------|------|
| hcodec.h | 683行 | HCodec基类声明 |
| hcodec.cpp | 1615行 | HCodec主体实现 |
| hcodec_state.cpp | 1091行 | 8个State类实现 |
| hcodec_bg.cpp | 441行 | DMA-BUF Swap / SuspendResume |
| hdecoder.cpp | 1927行 | HDecoder硬件解码器 |
| hencoder.cpp | 1872行 | HEncoder硬件编码器 |
| hcodec_list.cpp | 405行 | 硬件Codec能力查询 |
| hcodec_dfx.cpp | 513行 | DFX统计与日志 |
| state_machine.cpp | 40行 | StateMachine基类 |
| msg_handle_loop.cpp | 157行 | 消息队列线程 |
| type_converter.cpp | 480行 | HDI↔OMX类型转换 |
| codec_hdi.h | — | HDI类型引入 (ICodecComponent/V4_0) |

---

## 3. HCodec 基类架构

### 3.1 消息驱动状态机 (StateMachine)

HCodec 内部使用 `MsgHandleLoop` 作为消息队列线程，派生类 (HDecoder/HEncoder) 各自包含 8 个 State 子类，所有状态切换通过消息驱动。

**MsgHandleLoop 消息队列**:
- `SendAsyncMsg(MsgType type, const ParamSP &msg, uint32_t delayUs = 0)` — 异步消息
- `SendSyncMsg(MsgType type, const ParamSP &msg, ParamSP &reply, uint32_t waitMs = 0)` — 同步消息 (阻塞等待回复)
- `MsgToken` 结构包含 `std::map<TimeUs, MsgInfo>` 按时间排序的消息队列 + `std::condition_variable` 线程同步

**证据**: msg_handle_loop.h (完整消息队列类定义)

### 3.2 八状态状态机

hcodec_state.cpp 定义了 8 个 State 类:

| State | 职责 | OnMsgReceived行号 |
|-------|------|-------------------|
| UninitializedState | 初始/释放后状态 | 240 |
| InitializedState | Configure完成后 | 307 |
| StartingState | Start→Running过渡, 分配Buffer | 439 |
| RunningState | 正常工作状态 | 538 |
| OutputPortChangedState | 输出端口参数变化 | 691 |
| FlushingState | Flush时双向暂停OMX端口 | 875 |
| StoppingState | Stop→Idle→Loaded过渡 | 1012 |
| FrozenState | Suspend时冻结Buffer | hcodec_bg.cpp:337 |

**关键消息类型** (hcodec.h:70-99):
```cpp
enum MsgWhat : MsgType {
    INIT, SET_CALLBACK, CONFIGURE, START, STOP, FLUSH, RELEASE,
    SUSPEND, RESUME,          // 电源管理
    CODEC_EVENT,              // OMX事件回调
    OMX_EMPTY_BUFFER_DONE,    // 输入Buffer消耗完
    OMX_FILL_BUFFER_DONE,     // 输出Buffer填充完
    BUFFER_RECYCLE,           // Buffer回收
    ...
};
```

**StateMachine基类** (state_machine.h):
```cpp
class StateMachine : public MsgHandleLoop {
protected:
    std::shared_ptr<State> currState_;
    void ChangeStateTo(const std::shared_ptr<State> &targetState);
};
```

### 3.3 HDI回调 (HdiCallback)

HCodec 在 OMX 组件上注册 `CodecHDI::ICodecCallback` 回调，将 OMX 事件转换为内部消息:

```cpp
class HCodec::HdiCallback : public CodecHDI::ICodecCallback {  // hcodec.h:623
    int32_t EventHandler(CodecEventType event, const EventInfo& info);  // line 627
    int32_t EmptyBufferDone(int64_t appData, const OmxCodecBuffer& buffer);  // line 629
    int32_t FillBufferDone(int64_t appData, const OmxCodecBuffer& buffer);  // line 630
};
```

### 3.4 核心OMX成员

```cpp
CodecHDI::CodecCompCapability caps_;  // 硬件能力
sptr<CodecHDI::ICodecCallback> compCb_;   // 本地回调Stub
sptr<CodecHDI::ICodecComponent> compNode_; // OMX组件实例
sptr<CodecHDI::ICodecComponentManager> compMgr_;  // OMX组件管理器
```

**证据**: hcodec.h:455-457

### 3.5 生命周期方法

```cpp
int32_t Init(Media::Meta &callerInfo)                           // hcodec.cpp:82
int32_t Configure(const Format &format)                         // hcodec.cpp:192
int32_t Start()                                                  // hcodec.cpp:219
int32_t Stop()                                                   // hcodec.cpp:227
int32_t Flush()                                                  // hcodec.cpp:234
int32_t Reset()                                                  // hcodec.cpp:241
int32_t Release()                                                // hcodec.cpp:252
int32_t NotifySuspend()                                          // hcodec_bg.cpp:126
int32_t NotifyResume()                                           // hcodec_bg.cpp:134
```

---

## 4. HDecoder 硬件视频解码器

### 4.1 XperfConnector 性能回调

HDecoder 包含内嵌类 `XperfConnector`，继承自 `VideoStateCallbackStub` (HiSysEvent DFX):

```cpp
class HDecoder::XperfConnector : public OHOS::HiviewDFX::VideoStateCallbackStub {  // hdecoder.h:32
    static std::shared_ptr<MsgToken> FindSuitableDecoder(uint64_t surfaceId, const std::string& bundleName);
    static std::shared_ptr<MsgToken> FindSuitableDecoder(const std::string& msg);
    ErrCode OnVideoJankEvent(const std::string& msg) override;
    ErrCode OnVideoResumed(const std::string& msg) override;
    ErrCode OnVideoPaused(const std::string& msg) override;
};
```

**证据**: hdecoder.h:32-42

### 4.2 DecoderInst 实例追踪

每个 HDecoder 实例对应一个 `DecoderInst`，记录 surfaceId 和进程名:

```cpp
struct HDecoder::DecoderInst {  // hdecoder.h:52
    std::weak_ptr<MsgToken> token;
    std::optional<uint64_t> surfaceId;
    std::string processName;
};
```

### 4.3 SurfaceBufferItem 缓冲区管理

```cpp
struct HDecoder::SurfaceBufferItem {  // hdecoder.h:58
    sptr<SyncFence> fence;         // 同步栅栏
    uint32_t seqnum = 0;            // 序列号(释放用)
    sptr<SurfaceBuffer> buffer;     // Surface缓冲区
    int32_t generation = 0;         // 代际(检测过期)
};
```

### 4.4 配置与端口

```cpp
int32_t HDecoder::OnConfigure(const Format &format)        // hdecoder.cpp (覆盖HCodec)
int32_t HDecoder::SetupPort(const Format &format)
int32_t HDecoder::UpdateInPortFormat() override
int32_t HDecoder::UpdateOutPortFormat() override
void HDecoder::UpdateColorAspects() override
int32_t HDecoder::RegisterListenerToSurface(const sptr<Surface> &surface)
void HDecoder::OnSetOutputSurface(const MsgInfo &msg, BufferOperationMode mode) override
```

---

## 5. HEncoder 硬件视频编码器

### 5.1 Buffer与水印管理

```cpp
struct HEncoder::BufferItem {  // hencoder.h:42
    uint64_t generation = 0;
    sptr<SurfaceBuffer> buffer;
    sptr<SyncFence> fence;
    OHOS::Rect damage;
    sptr<Surface> surface;
};

struct HEncoder::WaterMarkInfo {  // hencoder.h:63
    bool enableWaterMark = false;
    int32_t x = 0, y = 0, w = 0, h = 0;
};
```

### 5.2 关键方法

```cpp
int32_t HEncoder::OnConfigure(const Format &format) override
int32_t HEncoder::ConfigureBufferType()
int32_t HEncoder::ConfigureOutputBitrate(const Format &format)
static std::optional<uint32_t> GetBitRateFromUser(const Format &format)
static std::optional<VideoEncodeBitrateMode> GetBitRateModeFromUser(const Format &format)
```

**证据**: hencoder.h:35-80 (OnConfigure 相关私有方法)

---

## 6. HDI V4.0 抽象层

### 6.1 引入的头文件

```cpp
#include "v4_0/codec_types.h"
#include "v4_0/icodec_callback.h"
#include "v4_0/icodec_component.h"
#include "v4_0/icodec_component_manager.h"
```
**证据**: codec_hdi.h (完整HDI层引入)

### 6.2 ICodecComponentManager 组件工厂

`ICodecComponentManager` 是 OMX 组件管理器，用于创建/获取组件:
- `GetCodecComponentManager()` 获取单例Manager
- `CreateComponent()` 创建指定codec组件
- `DestroyComponent()` 销毁组件

### 6.3 ICodecComponent OMX组件接口

每个 `ICodecComponent` 实例对应一个 OMX 组件，提供:
- `SendCommand()` — 发送OMX命令 (StateSet/EmptyBuffer/FillBuffer等)
- `EmptyThisBuffer()` / `FillThisBuffer()` — Buffer数据交互
- `GetParameter()` / `SetParameter()` — OMX参数查询/设置
- `Configure()` — 组件配置

---

## 7. HCodecLoader 工厂与能力发现

### 7.1 HCodecLoader

```cpp
class HCodecLoader : public VideoCodecLoader {  // hcodec_loader.h
    static std::shared_ptr<CodecBase> CreateByName(const std::string &name);
    static int32_t GetCapabilityList(std::vector<CapabilityData> &caps);
};
```

**证据**: hcodec_loader.h

### 7.2 HCodecList 能力查询

```cpp
class HCodecList : public CodecListBase {  // hcodec_list.h
    int32_t GetCapabilityList(std::vector<CapabilityData>& caps) override;
    static VideoFeature FindFeature(const vector<VideoFeature> &features, const VideoFeatureKey &key);
};
```

`GetCapabilityList` (hcodec_list.cpp:162) 通过 `CodecHDI::ICodecComponentManager::GetCodecCapability()` 获取硬件能力，然后调用 `FindFeature` (line 174) 解析每项能力:

```cpp
map<CodecHDI::VideoFeatureKey, pair<AVCapabilityFeature, string>> featureConvertMap = {  // line 341
    { VIDEO_FEATURE_PASS_THROUGH, {AVCapabilityFeature::FEATURE_PASSTHROUGH, "passthrough"} },
    { VIDEO_FEATURE_LTR, {AVCapabilityFeature::FEATURE_LTR, "ltr"} },
    { VIDEO_FEATURE_ENCODE_B_FRAME, {AVCapabilityFeature::FEATURE_B_FRAME, "b_frame"} },
    ...
};
```

**证据**: hcodec_list.cpp:162-400 (完整能力映射)

---

## 8. TypeConverter 类型转换

HDI↔OMX 类型转换引擎，处理:

```cpp
class TypeConverter {  // type_converter.h
    static std::optional<AVCodecType> HdiCodecTypeToInnerCodecType(CodecHDI::CodecType type);
    static std::optional<OMX_VIDEO_CODINGTYPE> HdiRoleToOmxCodingType(CodecHDI::AvCodecRole role);
    static std::string HdiRoleToMime(CodecHDI::AvCodecRole role);
    static std::optional<PixelFmt> GraphicFmtToFmt(GraphicPixelFormat format);
    static std::optional<PixelFmt> InnerFmtToFmt(VideoPixelFormat format);
};
```

**证据**: type_converter.h

---

## 9. DMA-BUF Swap / Suspend-Resume 机制

hcodec_bg.cpp 实现了 Codec 级别的内存回收与恢复:

### 9.1 DmaSwaper DMA缓冲区交换

```cpp
class DmaSwaper {  // hcodec_bg.cpp:50
    int32_t SwapOutDma(pid_t pid, int bufFd);  // line 52
    int32_t SwapInDma(pid_t pid, int bufFd);    // line 65
};
```

### 9.2 Suspend/Resume 流程

```
NotifySuspend()  → FreezeBuffers() → DecreaseFreq() → SwapOutBufferByPortIndex()
NotifyResume()   → SwapInBufferByPortIndex() → ActiveBuffers() → RecoverFreq()
```

**证据**: hcodec_bg.cpp:112-265
- `NotifyMemoryRecycle()` — line 112
- `NotifyMemoryWriteBack()` — line 119
- `NotifySuspend()` — line 126
- `NotifyResume()` — line 134
- `SwapOutBufferByPortIndex()` — line 151
- `SwapInBufferByPortIndex()` — line 171
- `FreezeBuffers()` — line 208
- `ActiveBuffers()` — line 243

### 9.3 FrozenState 冻结状态

`HCodec::FrozenState` (hcodec_bg.cpp:337) 处理暂停期间的 Buffer 状态，收到 Buffer 事件时记录在 `inputBufIdQueueToOmx_` / `outputBufIdQueueToOmx_` 中等待 Resume。

### 9.4 BufferOwner 追踪

```cpp
void HCodec::RecordBufferStatus(OMX_DIRTYPE portIndex, uint32_t bufferId, BufferOwner nextOwner);  // hcodec_bg.cpp:142
```
BufferOwner 枚举跟踪 Buffer 当前所有者 (Codec/OMX/APP/NEXT_OWNER)，用于 Swap 判断。

---

## 10. DFX 追踪体系

### 10.1 追踪宏

```cpp
#define SCOPED_TRACE() \
    HITRACE_METER_FMT(HITRACE_TAG_ZMEDIA, "[hcodec][%s]%s", compUniqueStr_.c_str(), __func__)

#define SCOPED_TRACE_FMT(fmt, ...) \
    HITRACE_METER_FMT(HITRACE_TAG_ZMEDIA, "[hcodec][%s]%s " fmt, \
        compUniqueStr_.c_str(), __func__, ##__VA_ARGS__)

struct FuncTracker {  // hcodec_dfx.h:26
    explicit FuncTracker(std::string value);
    ~FuncTracker();
};
#define FUNC_TRACKER() FuncTracker tracker("[" + compUniqueStr_ + " " + __func__ + "]")
```

**证据**: hcodec_dfx.h:21-29

### 10.2 OnGetHidumperInfo / OnQueryJankReason

`BaseState::OnMsgReceived` (hcodec_state.cpp:28) 处理:
- `MsgWhat::GET_HIDUMPER_INFO` → 返回codec各状态/buffer/dump信息
- `MsgWhat::QUERY_JANK_REASON` → 查询卡顿原因
- `MsgWhat::XPERF_RESUME_EVENT` / `XPERF_PAUSE_EVENT` → 启停Jank检测

---

## 11. 与其他模块的关系

```
CodecServer (S48)
    ├── AVCodecVideoEncoder (S42)
    │       └── SurfaceEncoderAdapter → HEncoder → HCodec → ICodecComponent → HDI V4.0
    └── AVCodecVideoDecoder (S39)
            └── VideoDecoderAdapter → HDecoder → HCodec → ICodecComponent → HDI V4.0

HCodecLoader (本S57)
    └── CreateByName("h264.dec") → HDecoder
    └── CreateByName("h264.enc") → HEncoder

CodecList (S27)
    └── HCodecList::GetCapabilityList → ICodecComponentManager::GetCodecCapability
```

---

## 12. AvcEncoder 硬件H.264编码器 (AVCEncoder)

除了 HEncoder (OMX路径) 外，services/engine/codec/video/avcencoder/ 还有独立的 `AvcEncoder` 类，基于原生 AVC_ENC_HANDLE API (非OMX):

```cpp
class AvcEncoder : public CodecBase, public RefBase {  // avc_encoder.h
    explicit AvcEncoder(const std::string &name);
    int32_t Configure(const Format &format) override;
    int32_t Start() override;
    sptr<Surface> CreateInputSurface() override;
    int32_t SetCallback(const std::shared_ptr<MediaCodecCallback> &callback) override;
    int32_t RenderOutputBuffer(uint32_t index) override;
    int32_t SignalRequestIDRFrame() override;
    static int32_t GetCodecCapability(std::vector<CapabilityData> &capaArray);
    
    // FFmpeg式函数指针
    using CreateAvcEncoderFuncType = uint32_t (*)(AVC_ENC_HANDLE*, AVC_ENC_INIT_PARAM*);
    using EncodeFuncType = uint32_t (*)(AVC_ENC_HANDLE, AVC_ENC_INARGS*, AVC_ENC_OUTARGS*);
    using DeleteFuncType = uint32_t (*)(AVC_ENC_HANDLE);
};
```

**证据**: avc_encoder.h (完整类定义)
**代码路径**: services/engine/codec/video/avcencoder/

AvcEncoder 通过 `avc_encoder_loader.cpp` 加载厂商提供的编码库。

---

## 附录: 关键证据索引

| 证据 | 文件 | 行号 |
|------|------|------|
| HCodec类定义 | hcodec.h | 35 |
| HCodec构造函数 | hcodec.h | 229 |
| HdiCallback类 | hcodec.h | 623 |
| OMX回调方法 | hcodec.h | 627-630 |
| ICodecComponent成员 | hcodec.h | 455-457 |
| HDecoder类定义 | hdecoder.h | 28 |
| XperfConnector类 | hdecoder.h | 32 |
| DecoderInst结构 | hdecoder.h | 52 |
| SurfaceBufferItem | hdecoder.h | 58 |
| HEncoder类定义 | hencoder.h | 24 |
| BufferItem/WaterMarkInfo | hencoder.h | 42, 63 |
| MsgHandleLoop类 | msg_handle_loop.h | — |
| StateMachine类 | state_machine.h | — |
| 8个State类 | hcodec_state.cpp | 225-1091 |
| FrozenState | hcodec_bg.cpp | 337 |
| DmaSwaper | hcodec_bg.cpp | 50 |
| HCodecList::GetCapabilityList | hcodec_list.cpp | 162 |
| TypeConverter | type_converter.h | — |
| SCOPED_TRACE宏 | hcodec_dfx.h | 21 |
| FuncTracker | hcodec_dfx.h | 26 |
| HCodecLoader | hcodec_loader.h | — |
| CodecHDI引入 | codec_hdi.h | — |
| AvcEncoder | avc_encoder.h | — |
| AvcEncoder Create/Encode/Delete函数指针 | avc_encoder.h | 38-40 |
