---
type: architecture
id: MEM-ARCH-AVCODEC-S130
title: "FFmpeg Adapter Common 通用工具链——ffmpeg_utils / ffmpeg_convert / ffmpeg_converter / stream_parser_manager 四组件"
scope: [AVCodec, FFmpeg, Adapter, Common, Utils, Resample, SwrContext, ColorSpace, ChannelLayout, NALU, StartCode, HEVC, StreamParser, dlopen]
status: draft
created_at: "2026-05-14T12:30:00+08:00"
created_by: builder-agent
关联主题: [S125(FFmpegDecoder基类), S8(FFmpeg音频插件总览), S50(AudioResample), S105(avc_parser_impl)]
---

# MEM-ARCH-AVCODEC-S130: FFmpeg Adapter Common 通用工具链

## 核心定位

`services/media_engine/plugins/ffmpeg_adapter/common/` 是 FFmpeg 适配层的**通用工具链目录**，包含四个相对独立但相互协作的组件：

| 组件 | 文件 | 行数 | 职责 |
|------|------|------|------|
| **ffmpeg_utils** | .cpp (505行) + .h (76行) | 581行 | MIME/CodecID 映射、色域/ transfer/矩阵转换、FLAC codec config、NALU 起始码查找、错误码转换 |
| **ffmpeg_convert** | .cpp (247行) + .h (98行) | 345行 | `Ffmpeg::Resample`（SwrContext 封装）+ `Ffmpeg::Scale`（SwsContext 封装） |
| **ffmpeg_converter** | .cpp (201行) + .h (53行) | 254行 | FFmpeg ↔ OHOS 通道布局映射（18种 AudioChannelLayout ↔ AV_CH_LAYOUT_*） |
| **stream_parser_manager** | .cpp (227行) + .h (73行) | 300行 | HEVC 流解析器 dlopen 插件管理器 |

这四个组件共同服务于 FFmpeg 软件编解码插件体系（S125/S8），提供格式转换、重采样、色彩空间转换等底层能力。

---

## 1. ffmpeg_utils 工具集（505行cpp + 76行h）

**源码路径**: `services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_utils.cpp/h`

### 1.1 常量定义（line 30-35）

```cpp
// line 30-34: AV_CODEC 时间基准常量（统一 FFmpeg 与 OHOS 时间单位）
#define AV_CODEC_TIME_BASE (static_cast<int64_t>(1))
#define AV_CODEC_NSECOND AV_CODEC_TIME_BASE
#define AV_CODEC_USECOND (static_cast<int64_t>(1000) * AV_CODEC_NSECOND)
#define AV_CODEC_MSECOND (static_cast<int64_t>(1000) * AV_CODEC_USECOND)
#define AV_CODEC_SECOND (static_cast<int64_t>(1000) * AV_CODEC_MSECOND)

// line 35: H.264/HEVC NALU 起始码 {0x00, 0x00, 0x01}
const uint8_t START_CODE[] = {0x00, 0x00, 0x01};
```

### 1.2 Mime2CodecId 映射表（line 41-68）

```cpp
// line 41-68: MIME → FFmpeg AVCodecID 倒排索引
bool Mime2CodecId(const std::string &mime, AVCodecID &codecId)
{
    static const std::unordered_map<std::string, AVCodecID> table = {
        {MimeType::AUDIO_MPEG, AV_CODEC_ID_MP3},        // line 45
        {MimeType::AUDIO_AAC, AV_CODEC_ID_AAC},
        {MimeType::AUDIO_AMR_NB, AV_CODEC_ID_AMR_NB},
        {MimeType::AUDIO_AMR_WB, AV_CODEC_ID_AMR_WB},
        {MimeType::AUDIO_RAW, AV_CODEC_ID_PCM_U8},
        {MimeType::AUDIO_G711MU, AV_CODEC_ID_PCM_MULAW},
        {MimeType::AUDIO_FLAC, AV_CODEC_ID_FLAC},
        {MimeType::AUDIO_OPUS, AV_CODEC_ID_OPUS},
        {MimeType::AUDIO_VORBIS, AV_CODEC_ID_VORBIS},
        {MimeType::AUDIO_AVS3DA, AV_CODEC_ID_AVS3DA},
        {MimeType::VIDEO_MPEG4, AV_CODEC_ID_MPEG4},
        {MimeType::VIDEO_AVC, AV_CODEC_ID_H264},        // line 56
        {MimeType::VIDEO_HEVC, AV_CODEC_ID_HEVC},
        {MimeType::IMAGE_JPG, AV_CODEC_ID_MJPEG},
        {MimeType::IMAGE_PNG, AV_CODEC_ID_PNG},
        {MimeType::IMAGE_BMP, AV_CODEC_ID_BMP},
        {MimeType::TIMED_METADATA, AV_CODEC_ID_FFMETADATA},
    };
    auto it = table.find(mime);
    if (it != table.end()) {
        codecId = it->second;
        return true;
    }
    return false;
}
```

### 1.3 Raw2BitPerSample 位深映射（line 88-108）

```cpp
// line 88-108: AudioSampleFormat → 位深映射（用于 FLAC 等需要明确位深的格式）
bool Raw2BitPerSample(AudioSampleFormat sampleFormat, uint8_t &bitPerSample)
{
    static const std::unordered_map<AudioSampleFormat, uint8_t> table = {
        {AudioSampleFormat::SAMPLE_U8, 8},
        {AudioSampleFormat::SAMPLE_S16LE, 16},
        {AudioSampleFormat::SAMPLE_S24LE, 24},
        {AudioSampleFormat::SAMPLE_S32LE, 32},
        {AudioSampleFormat::SAMPLE_F32LE, 32},
        // ... planar 版本（U8P/S16P/S24P/S32P/F32P）
    };
}
```

### 1.4 色彩空间转换三函数（line 168-290）

```cpp
// line 168-189: ColorPrimary → AVColorPrimaries 映射
std::pair<bool, AVColorPrimaries> ColorPrimary2AVColorPrimaries(ColorPrimary primary) {
    static const std::unordered_map<ColorPrimary, AVColorPrimaries> table = {
        {ColorPrimary::BT709, AVCOL_PRI_BT709},
        {ColorPrimary::BT2020, AVCOL_PRI_BT2020},
        {ColorPrimary::P3DCI, AVCOL_PRI_SMPTE431},  // Dolby Cinema
        {ColorPrimary::P3D65, AVCOL_PRI_SMPTE432},
        // ... 11 种 primaries 映射
    };
}

// line 190-216: TransferCharacteristic → AVColorTransferCharacteristic 映射
std::pair<bool, AVColorTransferCharacteristic> ColorTransfer2AVColorTransfer(TransferCharacteristic transfer) {
    static const std::unordered_map<TransferCharacteristic, AVColorTransferCharacteristic> table = {
        {TransferCharacteristic::BT709, AVCOL_TRC_BT709},
        {TransferCharacteristic::PQ, AVCOL_TRC_SMPTE2084},   // HDR PQ
        {TransferCharacteristic::HLG, AVCOL_TRC_ARIB_STD_B67}, // HLG
        // ... 16 种 transfer 映射
    };
}

// line 218-293: MatrixCoefficient → AVColorSpace 映射
std::pair<bool, AVColorSpace> ColorMatrix2AVColorSpace(MatrixCoefficient matrix);
```

### 1.5 FlacCodecConfig FLAC 编解码配置生成器（line 295-480）

```cpp
// line 295-325: GenerateCodecConfig - 从 Meta 生成 FLAC codec config（34字节）
bool FlacCodecConfig::GenerateCodecConfig(const std::shared_ptr<Meta> &trackDesc)
{
    // 包含 sampleRate/channels/bitPerSample 等元数据写入
}

// line 327+: Update / UpdateNewConfig / UpdateBitPerSample / UpdatePerFrame
// FlacCodecConfig 类负责 FLAC 流元数据（STREAMINFO block）的动态更新
```

### 1.6 FindNalStartCode NALU 起始码查找（line 492-505）

```cpp
// line 492-505: 在字节流中搜索 NALU 起始码 {0x00 0x00 0x01}
const uint8_t* FindNalStartCode(const uint8_t *start, const uint8_t *end, int32_t &startCodeLen)
{
    startCodeLen = sizeof(START_CODE); // 3 字节
    auto *iter = std::search(start, end, START_CODE, START_CODE + startCodeLen);
    // 返回找到的起始码位置（未找到返回 end）
}
```

---

## 2. ffmpeg_convert 工具集（247行cpp + 98行h）

**源码路径**: `services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_convert.cpp/h`

### 2.1 ResamplePara 结构体（ffmpeg_convert.h:42-51）

```cpp
// ffmpeg_convert.h:42-51: Resample 参数结构体
struct ResamplePara {
    uint32_t channels{2};                   // 默认立体声
    uint32_t sampleRate{0};
    uint32_t bitsPerSample{0};
    AVChannelLayout channelLayout;          // FFmpeg 通道布局
    AVSampleFormat srcFfFmt{AV_SAMPLE_FMT_NONE};  // 源 FFmpeg 采样格式
    uint32_t destSamplesPerFrame{0};
    AVSampleFormat destFmt{AV_SAMPLE_FMT_S16};   // 目标默认 S16
};
```

### 2.2 Resample 类——SwrContext 封装（ffmpeg_convert.cpp:28-152）

```cpp
// ffmpeg_convert.cpp:28-61: Resample::Init - 初始化重采样器
Status Resample::Init(const ResamplePara &resamplePara)
{
    auto swrContext = swr_alloc();  // line 42
    swr_alloc_set_opts2(&swrContext,
        &resamplePara_.channelLayout,
        resamplePara_.destFmt,
        resamplePara_.sampleRate,
        ...);  // line 44-47
    swr_init(swrContext);  // line 48
}

// ffmpeg_convert.cpp:123-165: Resample::Convert - 缓冲区级别重采样
// ffmpeg_convert.cpp:165-192: Resample::ConvertFrame - AVFrame 级别重采样
Status Resample::ConvertFrame(AVFrame *outputFrame, const AVFrame *inputFrame)
{
    auto ret = swr_convert_frame(swrCtx_.get(), outputFrame, inputFrame); // line 187
}

// ffmpeg_convert.cpp:237: ~Resample 析构
```

### 2.3 Scale 类——SwsContext 封装（ffmpeg_convert.h:75-98, ffmpeg_convert.cpp:228-237）

```cpp
// ffmpeg_convert.h:75-98: Scale 结构体（VIDEO_SUPPORT 条件编译）
struct ScalePara {
    int32_t srcWidth{0}, srcHeight{0};
    AVPixelFormat srcFfFmt{AV_PIX_FMT_NONE};
    int32_t dstWidth{0}, dstHeight{0};
    AVPixelFormat dstFfFmt{AV_PIX_FMT_RGBA};  // 默认 RGBA 输出
    int32_t align{16};
};

struct Scale {
    Status Init(const ScalePara &scalePara, uint8_t **dstData, int32_t *dstLineSize);
    Status Convert(uint8_t **srcData, const int32_t *srcLineSize,
                   uint8_t **dstData, int32_t *dstLineSize); // line 228-237
private:
    std::shared_ptr<SwsContext> swsCtx_{nullptr};
};
```

---

## 3. ffmpeg_converter 通道布局映射（201行cpp + 53行h）

**源码路径**: `services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_converter.cpp/h`

### 3.1 g_toFFMPEGChannelLayout 映射表（ffmpeg_converter.cpp:28-201）

```cpp
// ffmpeg_converter.cpp:28-201: OHOS AudioChannelLayout ↔ FFmpeg AV_CH_LAYOUT_* 映射
const std::vector<std::pair<AudioChannelLayout, uint64_t>> g_toFFMPEGChannelLayout = {
    {AudioChannelLayout::MONO, AV_CH_LAYOUT_MONO},
    {AudioChannelLayout::STEREO, AV_CH_LAYOUT_STEREO},
    {AudioChannelLayout::CH_2POINT1, AV_CH_LAYOUT_2POINT1},
    {AudioChannelLayout::CH_2_1, AV_CH_LAYOUT_2_1},
    {AudioChannelLayout::SURROUND, AV_CH_LAYOUT_SURROUND},
    {AudioChannelLayout::CH_3POINT1, AV_CH_LAYOUT_3POINT1},
    {AudioChannelLayout::CH_4POINT0, AV_CH_LAYOUT_4POINT0},
    {AudioChannelLayout::CH_4POINT1, AV_CH_LAYOUT_4POINT1},
    {AudioChannelLayout::CH_2_2, AV_CH_LAYOUT_2_2},
    {AudioChannelLayout::QUAD, AV_CH_LAYOUT_QUAD},
    {AudioChannelLayout::CH_5POINT0, AV_CH_LAYOUT_5POINT0},
    {AudioChannelLayout::CH_5POINT1, AV_CH_LAYOUT_5POINT1},
    {AudioChannelLayout::CH_5POINT0_BACK, AV_CH_LAYOUT_5POINT0_BACK},
    {AudioChannelLayout::CH_5POINT1_BACK, AV_CH_LAYOUT_5POINT1_BACK},
    {AudioChannelLayout::CH_6POINT0, AV_CH_LAYOUT_6POINT0},
    {AudioChannelLayout::CH_6POINT0_FRONT, AV_CH_LAYOUT_6POINT0_FRONT},
    {AudioChannelLayout::HEXAGONAL, AV_CH_LAYOUT_HEXAGONAL},
    {AudioChannelLayout::CH_6POINT1, AV_CH_LAYOUT_6POINT1},
    {AudioChannelLayout::CH_6POINT1_BACK, AV_CH_LAYOUT_6POINT1_BACK},
    {AudioChannelLayout::CH_6POINT1_FRONT, AV_CH_LAYOUT_6POINT1_FRONT},
    {AudioChannelLayout::CH_7POINT0, AV_CH_LAYOUT_7POINT0},
    {AudioChannelLayout::CH_7POINT1, AV_CH_LAYOUT_7POINT1},
    {AudioChannelLayout::CH_7POINT1_WIDE, AV_CH_LAYOUT_7POINT1_WIDE},
    {AudioChannelLayout::CH_7POINT1_WIDE_BACK, AV_CH_LAYOUT_7POINT1_WIDE_BACK},
    // 18 种通道布局完整覆盖
};
```

---

## 4. stream_parser_manager HEVC 流解析器管理器（227行cpp + 73行h）

**源码路径**: `services/media_engine/plugins/ffmpeg_adapter/common/stream_parser_manager.cpp/h`

### 4.1 dlopen 插件加载机制（stream_parser_manager.cpp:26-73）

```cpp
// stream_parser_manager.cpp:26: dlopen 库路径常量
const std::string HEVC_LIB_PATH = "libav_codec_hevc_parser.z.so";

// stream_parser_manager.cpp:32-35: 静态成员（类级别共享）
std::mutex StreamParserManager::mtx_;
std::map<VideoStreamType, void *> StreamParserManager::handlerMap_ {};
std::map<VideoStreamType, CreateFunc> StreamParserManager::createFuncMap_ {};
std::map<VideoStreamType, DestroyFunc> StreamParserManager::destroyFuncMap_ {};

// stream_parser_manager.cpp:43-64: Init - dlopen 加载 HEVC 解析器插件
bool StreamParserManager::Init(VideoStreamType videoStreamType)
{
    std::lock_guard<std::mutex> lock(mtx_);
    void *handler = dlopen(HEVC_LIB_PATH.c_str(), RTLD_LAZY); // line 46
    CreateFunc createFunc = dlsym(handler, "CreateStreamParser"); // line 50
    DestroyFunc destroyFunc = dlsym(handler, "DestroyStreamParser"); // line 51
    // 注册到 createFuncMap_ / destroyFuncMap_ / handlerMap_
}
```

### 4.2 VideoStreamType 枚举与插件管理（stream_parser_manager.h:36-73）

```cpp
// stream_parser_manager.h:36-73: StreamParserManager 类定义
enum class VideoStreamType : int32_t { HEVC = 0, ... };

class StreamParserManager {
public:
    static std::mutex mtx_;
    static std::map<VideoStreamType, void *> handlerMap_;
    static std::map<VideoStreamType, CreateFunc> createFuncMap_;
    static std::map<VideoStreamType, DestroyFunc> destroyFuncMap_;
    bool Init(VideoStreamType videoStreamType);
    bool Create(VideoStreamType videoStreamType);
    void Destroy();
    bool Parse(const uint8_t *buffer, size_t size, std::vector<AnalysisResult> &results);
private:
    VideoStreamType videoStreamType_ = VideoStreamType::HEVC;
    void *streamParser_ = nullptr;
};
```

---

## 5. 四组件协作关系

```
FfmpegBaseDecoder (S125)
├── resample_: Ffmpeg::Resample (ffmpeg_convert.h)
│   ├── InitResample() → swr_alloc() / swr_init()
│   └── ConvertFrame() → swr_convert_frame()
├── color conversion → ffmpeg_utils.h
│   ├── ColorPrimary2AVColorPrimaries()
│   ├── ColorTransfer2AVColorTransfer()
│   └── ColorMatrix2AVColorSpace()
└── channel layout → ffmpeg_converter.cpp
    └── g_toFFMPEGChannelLayout 18种映射

StreamParserManager
└── dlopen "libav_codec_hevc_parser.z.so"
    └── Parse() → HEVC NALU 流解析（供 S105 使用）

ffmpeg_utils.h
├── Mime2CodecId() → ffmpeg_utils.cpp:41 (15+ MIME类型映射)
├── FindNalStartCode() → ffmpeg_utils.cpp:492 (AVC/HEVC NALU 切分)
└── FlacCodecConfig::GenerateCodecConfig() → ffmpeg_utils.cpp:295 (34字节 FLAC header)
```

---

## 关键证据汇总

| 证据 | 文件:行号 | 说明 |
|------|-----------|------|
| E1 | ffmpeg_utils.cpp:30-35 | AV_CODEC_TIME_BASE/USECOND/MSECOND 常量 + START_CODE |
| E2 | ffmpeg_utils.cpp:41-68 | Mime2CodecId 15+ MIME→AVCodecID 映射表 |
| E3 | ffmpeg_utils.cpp:88-108 | Raw2BitPerSample 位深映射（8/16/24/32bit） |
| E4 | ffmpeg_utils.cpp:168-189 | ColorPrimary2AVColorPrimaries 11种色域映射 |
| E5 | ffmpeg_utils.cpp:190-216 | ColorTransfer2AVColorTransfer 16种 transfer 映射（含PQ/HLG） |
| E6 | ffmpeg_utils.cpp:218-293 | ColorMatrix2AVColorSpace 色彩矩阵映射 |
| E7 | ffmpeg_utils.cpp:295-325 | FlacCodecConfig::GenerateCodecConfig FLAC元数据生成 |
| E8 | ffmpeg_utils.cpp:492-505 | FindNalStartCode NALU起始码查找 {0x00,0x00,0x01} |
| E9 | ffmpeg_convert.h:42-51 | ResamplePara 结构体（6成员） |
| E10 | ffmpeg_convert.cpp:28-61 | Resample::Init → swr_alloc_set_opts2 / swr_init |
| E11 | ffmpeg_convert.cpp:165-192 | Resample::ConvertFrame → swr_convert_frame |
| E12 | ffmpeg_convert.h:75-98 | ScalePara/Scale SwsContext 封装（VIDEO_SUPPORT） |
| E13 | ffmpeg_converter.cpp:28-201 | g_toFFMPEGChannelLayout 18种通道布局映射表 |
| E14 | stream_parser_manager.cpp:26 | HEVC_LIB_PATH="libav_codec_hevc_parser.z.so" |
| E15 | stream_parser_manager.cpp:32-35 | 静态成员 handlerMap_/createFuncMap_/destroyFuncMap_ |
| E16 | stream_parser_manager.cpp:43-64 | Init → dlopen RTLD_LAZY + dlsym Create/Destroy |
| E17 | stream_parser_manager.h:36-73 | StreamParserManager 类定义（VideoStreamType 枚举） |