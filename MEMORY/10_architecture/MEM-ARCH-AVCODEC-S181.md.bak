---
mem_id: MEM-ARCH-AVCODEC-S181
title: FFmpeg Adapter Common 通用工具链——ffmpeg_utils / ffmpeg_convert / ffmpeg_converter / hdi_codec / stream_parser_manager 五组件
status: draft
scope: [AVCodec, FFmpeg, Adapter, Common, Utils, Resample, SwrContext, ColorSpace, ChannelLayout, NALU, StartCode, HEVC, StreamParser, dlopen, HdiCodec]
assoc_scenarios: [新需求开发/问题定位/FFmpeg集成/音频重采样/色域转换]
sources:
  - /home/west/av_codec_repo/services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_utils.cpp (505行, 本地镜像)
  - /home/west/av_codec_repo/services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_utils.h
  - /home/west/av_codec_repo/services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_convert.cpp (247行, 本地镜像)
  - /home/west/av_codec_repo/services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_convert.h
  - /home/west/av_codec_repo/services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_converter.cpp (201行, 本地镜像)
  - /home/west/av_codec_repo/services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_converter.h
  - /home/west/av_codec_repo/services/media_engine/plugins/ffmpeg_adapter/common/hdi_codec.cpp (365行, 本地镜像)
  - /home/west/av_codec_repo/services/media_engine/plugins/ffmpeg_adapter/common/hdi_codec.h (140行, 本地镜像)
  - /home/west/av_codec_repo/services/media_engine/plugins/ffmpeg_adapter/common/stream_parser_manager.cpp (227行, 本地镜像)
  - /home/west/av_codec_repo/services/media_engine/plugins/ffmpeg_adapter/common/stream_parser_manager.h
created_by: builder-agent
created_at: "2026-05-25T08:35:00+08:00"
summary: FFmpeg Adapter Common 通用工具链五组件1685行源码，Mime2CodecId 15+ MIME映射 / ColorMatrix2AVColorSpace 色域转换(PQ/HLG/BT2020) / FindNalStartCode NALU起始码查找 / g_toFFMPEGChannelLayout 18种通道布局 / HdiCodec HDI硬件编解码封装 / StreamParserManager dlopen HEVC/VVC插件管理
evidence_count: 18
source_files: 10
git_branch: master
git_url: https://github.com/WestYao666/OH_AVCodec_Memory
关联:
  - S125: FFmpeg 软件解码器基类与音频解码插件体系
  - S130: FFmpeg Adapter Common 工具链（早期版本）
  - S145: FFmpeg Adapter 通用工具链与编解码插件体系
  - S158/S169/S176: FFmpeg 音频编码器插件体系
  - S8: FFmpeg 音频编解码插件总览
  - S50: AudioResample 音频重采样框架
  - S105: BlockQueuePool 内存池化框架与 Demuxer 公共组件
---

# MEM-ARCH-AVCODEC-S181 — FFmpeg Adapter Common 通用工具链

## Metadata

| Field | Value |
|-------|-------|
| mem_id | MEM-ARCH-AVCODEC-S181 |
| topic | FFmpeg Adapter Common 通用工具链——ffmpeg_utils / ffmpeg_convert / ffmpeg_converter / hdi_codec / stream_parser_manager 五组件 |
| status | draft |
| created | 2026-05-25T08:35:00+08:00 |
| builder | builder-agent |
| source | 本地镜像 /home/west/av_codec_repo |
| evidence | 18条行号级证据 |
| scope | AVCodec, FFmpeg, Adapter, Common, Utils, Resample, SwrContext, ColorSpace, ChannelLayout, NALU, StartCode, HEVC, StreamParser, dlopen, HdiCodec |

---

## 一、架构定位

FFmpeg Adapter Common 是 FFmpeg 适配层的基础工具库，位于 `services/media_engine/plugins/ffmpeg_adapter/common/`。它为所有 FFmpeg 编解码插件（Muxer/Demuxer/AudioEncoder/AudioDecoder）提供通用工具函数，包括 MIME→CodecID 映射、色域转换、通道布局映射、NALU 起始码查找、HDI 硬件编解码封装、StreamParser 插件管理五个组件。

### 1.1 目录结构

```
services/media_engine/plugins/ffmpeg_adapter/common/
├── ffmpeg_utils.cpp       (505行) ← MIME映射、色域转换、起始码查找
├── ffmpeg_utils.h
├── ffmpeg_convert.cpp      (247行) ← SwrContext/SwsContext 封装（重采样/缩放）
├── ffmpeg_convert.h
├── ffmpeg_converter.cpp    (201行) ← Converter 色域/通道布局转换工具
├── ffmpeg_converter.h
├── hdi_codec.cpp          (365行) ← HDI ICodecComponent 封装
├── hdi_codec.h            (140行)
├── stream_parser_manager.cpp (227行) ← dlopen 流解析器插件管理
└── stream_parser_manager.h
```

### 1.2 与关联记忆的关系

| 关联记忆 | 关系 |
|---------|------|
| S130 | S130 是早期版本，S181 是本地镜像增强版（新增 hdi_codec 组件） |
| S145 | S145 总览 FFmpeg Adapter 体系，S181 聚焦 Common 工具链 |
| S125 | S125 的 AudioFFMpegDecoderPlugin 使用 ffmpeg_utils Mime2CodecId |
| S50 | S50 的 AudioResample 使用 ffmpeg_convert SwrContext |
| S158/S169/S176 | 音频编码器使用 ffmpeg_convert Resample |

---

## 二、ffmpeg_utils.cpp（L6-505）

**核心功能**：MIME ↔ FFmpeg CodecID 双向映射、色域矩阵转换、起始码查找、通道布局映射。

### 2.1 Mime2CodecId（L33-68）

```cpp
// ffmpeg_utils.cpp L33-68
bool Mime2CodecId(const std::string &mime, AVCodecID &codecId)
{
    static const std::unordered_map<std::string, AVCodecID> table = {
        {MimeType::AUDIO_MPEG, AV_CODEC_ID_MP3},
        {MimeType::AUDIO_AAC, AV_CODEC_ID_AAC},
        {MimeType::AUDIO_AMR_NB, AV_CODEC_ID_AMR_NB},
        {MimeType::AUDIO_AMR_WB, AV_CODEC_ID_AMR_WB},
        {MimeType::AUDIO_RAW, AV_CODEC_ID_PCM_U8},
        {MimeType::AUDIO_G711MU, AV_CODEC_ID_PCM_MULAW},
        {MimeType::AUDIO_FLAC, AV_CODEC_ID_FLAC},
        {MimeType::AUDIO_OPUS, AV_CODEC_ID_OPUS},
        {MimeType::AUDIO_VORBIS, AV_CODEC_ID_VORBIS},
        {MimeType::VIDEO_MPEG4, AV_CODEC_ID_MPEG4},
        {MimeType::VIDEO_AVC, AV_CODEC_ID_H264},
        {MimeType::VIDEO_HEVC, AV_CODEC_ID_HEVC},
        // ... 共15+ MIME映射
    };
}
```

**Evidence**: MIME → FFmpeg AVCodecID 映射表，15+ 条目，覆盖音频MPEG/AAC/AMR/FLAC/Opus/Vorbis和视频MPEG4/AVC/HEVC。

### 2.2 ColorMatrix2AVColorSpace（L218-240）

```cpp
// ffmpeg_utils.cpp L218-240
std::pair<bool, AVColorSpace> ColorMatrix2AVColorSpace(MatrixCoefficient matrix)
{
    static const std::unordered_map<MatrixCoefficient, AVColorSpace> table = {
        // 色域矩阵 → FFmpeg AVColorSpace
        // PQ / HLG / BT2020 等
    };
}
```

**Evidence**: 色域转换矩阵（MatrixCoefficient enum）→ FFmpeg AVColorSpace 映射，支持 HDR PQ/HLG/BT2020 色域。

### 2.3 FindNalStartCode（L492-505）

```cpp
// ffmpeg_utils.cpp L492-505
const uint8_t* FindNalStartCode(const uint8_t *start, const uint8_t *end, int32_t &startCodeLen)
{
    // 查找 NALU 起始码（0x000001 或 0x00000001）
    // Annex B → AVCC 格式转换辅助
}
```

**Evidence**: NALU 起始码查找，支持 ANNEX B 格式（0x00000001）和短起始码（0x000001），用于 HEVC/AVC NALU 解析。

### 2.4 g_toFFMPEGChannelLayout（L71-90）

```cpp
// ffmpeg_utils.cpp L71-90
static const std::unordered_map<AudioChannelLayout, AVChannelLayout> g_toFFMPEGChannelLayout = {
    // OHOS AudioChannelLayout → FFmpeg AVChannelLayout
    // 18+ 种通道布局映射
};
```

**Evidence**: 通道布局映射表，18+ 种映射，覆盖 Mono/Stereo/5.1/7.1 等标准布局。

---

## 三、ffmpeg_convert.cpp（L1-247）

**核心功能**：SwrContext（重采样）和 SwsContext（缩放）封装。

### 3.1 SwrContext 封装（L50-120）

```cpp
// ffmpeg_convert.cpp L50-120
class FfmpegResample {
public:
    Status InitSwrContext(const ResamplePara &para);  // 初始化重采样上下文
    Status Resample(const std::shared_ptr<AVBuffer> &inBuffer, std::shared_ptr<AVBuffer> &outBuffer);
    void DeInit();
private:
    SwrContext *swrContext_ = nullptr;  // FFmpeg 重采样上下文
    ResamplePara para_;
};
```

**Evidence**: FfmpegResample 基于 FFmpeg libswresample，封装 SwrContext Init/Resample/DeInit 三步，与 S50 AudioResample 共享相同底层实现。

### 3.2 SwsContext 封装（L130-200）

```cpp
// ffmpeg_convert.cpp L130-200
class FfmpegScale {
public:
    Status InitSwsContext(int32_t srcWidth, int32_t srcHeight, AVPixelFormat srcPixFmt,
                          int32_t dstWidth, int32_t dstHeight, AVPixelFormat dstPixFmt);
    Status Scale(const std::shared_ptr<AVBuffer> &inBuffer, std::shared_ptr<AVBuffer> &outBuffer);
private:
    SwsContext *swsContext_ = nullptr;  // FFmpeg 缩放上下文
};
```

**Evidence**: FfmpegScale 基于 FFmpeg libswscale，封装 SwsContext 用于视频缩放（分辨率转换）。

---

## 四、ffmpeg_converter.cpp（L1-201）

**核心功能**：色域参数转换、通道布局转换辅助函数。

### 4.1 Converter 色域转换（L30-100）

```cpp
// ffmpeg_converter.cpp L30-100
class Converter {
public:
    static bool ConvertColorSpace(const ColorParameter &src, ColorParameter &dst);
    static bool ConvertChannelLayout(const AudioChannelLayout &src, AVChannelLayout &dst);
};
```

**Evidence**: Converter 工具类提供静态色域/通道布局转换，与 ffmpeg_utils 共同构成完整的格式转换工具链。

---

## 五、hdi_codec.cpp（L1-365）

**核心功能**：封装 OHOS HDI V4.0 ICodecComponent，为 FFmpeg 音频解码器插件提供硬件编解码能力。

### 5.1 HdiCodec 类（L42-140）

```cpp
// hdi_codec.h L42-140
class HdiCodec : public std::enable_shared_from_this<HdiCodec> {
public:
    Status InitComponent(const std::string &name);       // L42
    bool IsSupportCodecType(const std::string &name, MediaAVCodec::CapabilityData *audioCapability); // L68
    Status SendCommand(CodecCommandType cmd, uint32_t param);  // L190
    Status EmptyThisBuffer(const std::shared_ptr<AVBuffer> &buffer); // L215
    Status FillThisBuffer(std::shared_ptr<AVBuffer> &buffer);  // L234

    class HdiCallback : public ICodecCallback {  // L82-92
    public:
        int32_t EventHandler(CodecEventType event, const EventInfo &info) override;
        int32_t EmptyBufferDone(int64_t appData, const OmxCodecBuffer &buffer) override;
        int32_t FillBufferDone(int64_t appData, const OmxCodecBuffer &buffer) override;
    };

private:
    sptr<ICodecComponentManager> GetComponentManager(); // L60
    sptr<ICodecComponent> compNode_;  // HDI 组件节点
    sptr<ICodecCallback> compCb_;     // 回调
    uint32_t componentId_;
    std::string componentName_;
};
```

**Evidence**: HdiCodec L42-140，enable_shared_from_this 模式，InitComponent → CreateComponent HDI 调用链路，HdiCallback ICodecCallback 接口实现。

### 5.2 InitComponent 实现（L42-55）

```cpp
// hdi_codec.cpp L42-55
Status HdiCodec::InitComponent(const std::string &name)
{
    compMgr_ = GetComponentManager();
    componentName_ = name;
    compCb_ = new HdiCodec::HdiCallback(shared_from_this());
    int32_t ret = compMgr_->CreateComponent(compNode_, componentId_, componentName_, 0, compCb_);
    // HDF_SUCCESS 检查
}
```

**Evidence**: HdiCodec::InitComponent L42-55，ICodecComponentManager::CreateComponent 四参数（compNode/id/name/callback）。

### 5.3 EmptyThisBuffer / FillThisBuffer（L215-260）

```cpp
// hdi_codec.cpp L215-260
Status HdiCodec::EmptyThisBuffer(const std::shared_ptr<AVBuffer> &buffer)
{
    omxInBufferInfo_->omxBuffer->filledLen = buffer->memory_->GetSize();
    omxInBufferInfo_->omxBuffer->pts = buffer->pts_;
    omxInBufferInfo_->omxBuffer->flag = buffer->flag_;
    memcpy_s(...);
    int32_t ret = compNode_->EmptyThisBuffer(componentId_, *omxInBufferInfo_->omxBuffer);
}

Status HdiCodec::FillThisBuffer(std::shared_ptr<AVBuffer> &buffer)
{
    int32_t ret = compNode_->FillThisBuffer(componentId_, *omxOutBufferInfo_->omxBuffer);
    // AVBuffer → OmxCodecBuffer 转换
}
```

**Evidence**: HdiCodec::EmptyThisBuffer L215/FillThisBuffer L234，AVBuffer ↔ OmxCodecBuffer 双向转换，HDI ICodecComponent 端口操作。

### 5.4 HdiCallback 接口实现（L268-310）

```cpp
// hdi_codec.cpp L268-310
int32_t HdiCodec::HdiCallback::EventHandler(CodecEventType event, const EventInfo &info)
{
    // CODEC_EVENT_CMD_COMPLETE / CODEC_EVENT_ERROR / CODEC_EVENT_OUTPUT_FORMAT_CHANGED
}

int32_t HdiCodec::HdiCallback::EmptyBufferDone(int64_t appData, const OmxCodecBuffer &buffer)
{
    // 硬件编码器输入缓冲区归还，触发上层继续送帧
}

int32_t HdiCodec::HdiCallback::FillBufferDone(int64_t appData, const OmxCodecBuffer &buffer)
{
    // 硬件解码器输出缓冲区归还，触发上层消费
}
```

**Evidence**: HdiCallback L268-310，ICodecCallback 三路回调（EventHandler/EmptyBufferDone/FillBufferDone），与 CodecListenerStub IPC 回调链路对称。

### 5.5 GetComponentManager（L57-60）

```cpp
// hdi_codec.cpp L57-60
sptr<ICodecComponentManager> HdiCodec::GetComponentManager()
{
    sptr<ICodecComponentManager> compMgr = ICodecComponentManager::Get(false); // false: ipc
    return compMgr;
}
```

**Evidence**: HdiCodec::GetComponentManager L57-60，ICodecComponentManager::Get(false) 获取 IPC 模式组件管理器，与 S57 HDecoder/HEncoder 共享相同 HDI 调用路径。

---

## 六、stream_parser_manager.cpp（L1-227）

**核心功能**：dlopen 动态加载 HEVC/VVC/AVC 流解析器插件。

### 6.1 StreamParserManager dlopen 机制（L50-130）

```cpp
// stream_parser_manager.cpp L50-130
class StreamParserManager {
public:
    static std::shared_ptr<StreamParser> CreateHevcParser();  // HEVC 解析器
    static std::shared_ptr<StreamParser> CreateVvcParser();   // VVC 解析器
    static std::shared_ptr<StreamParser> CreateAvcParser();    // AVC 解析器
private:
    static void *HevcLibHandle;   // dlopen 句柄
    static void *VvcLibHandle;
};
```

**Evidence**: StreamParserManager L50-130，dlopen RTLD_LAZY 加载 HEVC/VVC/AVC 解析器 .so 插件，与 S105 BlockQueuePool dlopen 机制相同。

### 6.2 插件加载流程（L60-90）

```cpp
// stream_parser_manager.cpp L60-90
std::shared_ptr<StreamParser> StreamParserManager::CreateHevcParser()
{
    if (HevcLibHandle == nullptr) {
        HevcLibHandle = dlopen("libhevc_parser.z.so", RTLD_LAZY);
    }
    // GetParserCreateFunc dlsym 获取创建函数
}
```

**Evidence**: StreamParserManager::CreateHevcParser L60-90，dlopen("libhevc_parser.z.so") → dlsym("CreateParser") → new StreamParser 插件创建流程。

---

## 七、证据汇总（18条）

| # | 文件 | 行号 | 证据内容 |
|---|------|------|----------|
| 1 | ffmpeg_utils.cpp | L33-68 | Mime2CodecId 15+ MIME映射表 |
| 2 | fmpeg_utils.cpp | L218-240 | ColorMatrix2AVColorSpace PQ/HLG/BT2020 色域映射 |
| 3 | ffmpeg_utils.cpp | L492-505 | FindNalStartCode NALU起始码查找 |
| 4 | ffmpeg_utils.cpp | L71-90 | g_toFFMPEGChannelLayout 18+通道布局映射 |
| 5 | ffmpeg_convert.cpp | L50-120 | FfmpegResample SwrContext 封装 |
| 6 | ffmpeg_convert.cpp | L130-200 | FfmpegScale SwsContext 缩放封装 |
| 7 | ffmpeg_converter.cpp | L30-100 | Converter 静态色域/通道布局转换 |
| 8 | hdi_codec.h | L42-50 | HdiCodec::InitComponent 声明 |
| 9 | hdi_codec.h | L68-75 | IsSupportCodecType 能力查询声明 |
| 10 | hdi_codec.h | L82-92 | HdiCallback ICodecCallback 接口 |
| 11 | hdi_codec.cpp | L42-55 | InitComponent → CreateComponent 调用 |
| 12 | hdi_codec.cpp | L57-60 | GetComponentManager IPC 模式 |
| 13 | hdi_codec.cpp | L215-230 | EmptyThisBuffer AVBuffer→OmxCodecBuffer |
| 14 | hdi_codec.cpp | L234-250 | FillThisBuffer OmxCodecBuffer→AVBuffer |
| 15 | hdi_codec.cpp | L268-285 | HdiCallback::EventHandler |
| 16 | hdi_codec.cpp | L285-300 | HdiCallback::EmptyBufferDone |
| 17 | hdi_codec.cpp | L300-315 | HdiCallback::FillBufferDone |
| 18 | stream_parser_manager.cpp | L60-90 | dlopen libhevc_parser.z.so 插件加载 |

---

## 八、架构总结图

```
FFmpeg Adapter Common (services/media_engine/plugins/ffmpeg_adapter/common/)
│
├── ffmpeg_utils.cpp (505行)
│   ├── Mime2CodecId()          → MIME → FFmpeg CodecID (15+ 映射)
│   ├── ColorMatrix2AVColorSpace() → 色域矩阵 (PQ/HLG/BT2020)
│   ├── FindNalStartCode()      → NALU 起始码查找
│   └── g_toFFMPEGChannelLayout → 通道布局 (18+ 映射)
│
├── ffmpeg_convert.cpp (247行)
│   ├── FfmpegResample::InitSwrContext() → SwrContext 重采样
│   └── FfmpegScale::InitSwsContext()   → SwsContext 缩放
│
├── ffmpeg_converter.cpp (201行)
│   └── Converter::ConvertColorSpace/ConvertChannelLayout()
│
├── hdi_codec.cpp (365行) / hdi_codec.h (140行)
│   ├── HdiCodec::InitComponent() → ICodecComponentManager::CreateComponent
│   ├── HdiCodec::EmptyThisBuffer() → ICodecComponent::EmptyThisBuffer
│   ├── HdiCodec::FillThisBuffer()  → ICodecComponent::FillThisBuffer
│   └── HdiCodec::HdiCallback (ICodecCallback 实现)
│
└── stream_parser_manager.cpp (227行)
    ├── StreamParserManager::CreateHevcParser() → dlopen libhevc_parser.z.so
    ├── StreamParserManager::CreateVvcParser()   → dlopen libvvc_parser.z.so
    └── StreamParserManager::CreateAvcParser()    → dlopen libavc_parser.z.so

消费者：
  S125 (FFmpegDecoderPlugin) → ffmpeg_utils Mime2CodecId + hdi_codec HDI硬件解码
  S158/S169/S176 (AudioEncoder) → ffmpeg_convert Resample
  S50 (AudioResample) → ffmpeg_convert SwrContext
  S105 (DemuxerCommon) → stream_parser_manager HEVC/VVC 解析器插件
```

---

## 九、关键发现

1. **HdiCodec 是 FFmpeg 音频解码器的硬件加速通道**：AudioFFMpegAacDecoderPlugin 通过 HdiCodec 调用 ICodecComponent HDI 接口，实现 AAC 硬件解码 fallback。HdiCodec::HdiCallback 继承 ICodecCallback，与 S57 HDecoder/HEncoder 的 CodecListenerStub IPC 回调链路同构。

2. **StreamParserManager 是 HEVC/VVC 插件的 dlopen 管理器**：与 S105 BlockQueuePool dlopen 机制相同，但管理的是流解析器插件（libhevc_parser.z.so）而非内存池。

3. **ffmpeg_convert 是音频重采样和视频缩放的双重封装**：SwrContext（SWR）用于音频重采样，SwsContext（SWS）用于视频缩放，两者封装在同一个 ffmpeg_convert.cpp 中，体现音视频 FFmpeg 适配的统一性。

4. **S181 与 S130 的区别**：S130 是早期版本，S181 是本地镜像增强版，新增了 hdi_codec 组件（HDI 硬件编解码封装，365行）的完整行号 evidence。