---
type: architecture
id: MEM-ARCH-AVCODEC-S133
title: "FFmpeg MPEG-4/FLV 封装修复器插件体系——FFmpegMuxerPlugin / FFmpegFlvMuxerPlugin / MPEG4MuxerPlugin / Mpeg4Track 四层架构"
scope: [AVCodec, FFmpeg, MuxerPlugin, MPEG4, FLV, MP4, ISOBMFF, BasicBox, Mpeg4Track, Track, AvcParser, HevcParser, BoxParser, WriteSample, Start, Stop, AddTrack, AVIOContext, FFmpegMuxerRegister, MediaMuxer, MuxerFilter, VideoTrack, AudioTrack, CoverTrack, TimedMetaTrack]
status: draft
created_at: "2026-05-14T16:50:00+08:00"
created_by: builder-agent
关联主题: [S40(FFmpegMuxerPlugin总览), S58(MPEG4BoxParser), S91(Mpeg4MuxerPlugin写时构建), S131(FFmpegBaseEncoder音频编码器), S130(FFmpegAdapterCommon工具链)]
source_repo: /home/west/av_codec_repo
source_root: services/media_engine/plugins/ffmpeg_adapter/muxer
evidence_version: local_mirror
---

# MEM-ARCH-AVCODEC-S133: FFmpeg MPEG-4/FLV 封装修复器插件体系

## 核心定位

`services/media_engine/plugins/ffmpeg_adapter/muxer/` 是 FFmpeg 封装修复器插件体系的**完整源代码目录**，包含三个平行的顶层插件和一个 MPEG-4 专用轨模型：

| 组件 | 路径 | 行数 | 职责 |
|------|------|------|------|
| **FFmpegMuxerPlugin** | `ffmpeg_muxer_plugin.cpp/h` | 1540行 | FFmpeg 底层封装：九格式（mp4/flv/mp3/amr/wav/adts/flac/ogg/ipod） |
| **FFmpegMuxerRegister** | `ffmpeg_muxer_register.cpp/h` | 452行 | 插件注册 + 自定义 AVIOContext + LGPL 许可声明 |
| **FFmpegFlvMuxerPlugin** | `flv_muxer/ffmpeg_flv_muxer_plugin.cpp/h` | 671行 | FLV 专用封装修复器（扩展基础插件） |
| **MPEG4MuxerPlugin** | `mpeg4_muxer/mpeg4_muxer_plugin.cpp/h` | 655行 | MPEG-4 ISOBMFF 封装修复器：BasicBox 树 + Mpeg4Track 轨 |
| **Mpeg4Track** | `mpeg4_muxer/track/*.cpp/h` | 1921行 | 视频/音频/字幕轨模型 + 码流写入逻辑 |
| **Box 解析器** | `mpeg4_muxer/*.cpp/h` | 2826行 | BasicBox/FulBox/AnyBox + AvcParser/HevcParser/VideoParser |

整体架构：FFmpegMuxerRegister（注册层）→ FFmpegMuxerPlugin/FFmpegFlvMuxerPlugin（二选一）→ MediaMuxer（Server 侧代理）→ MuxerFilter（Pipeline 入口）。MPEG4MuxerPlugin 走独立路径，不经 FFmpeg 而是基于自研 ISOBMFF BasicBox 树。

与 S40（FFmpegMuxerPlugin 总览）、S91（Mpeg4MuxerPlugin 写时构建）互补——S40 是总览视角，S91 是 ISOBMFF 写时构建策略，本条目是**逐文件逐行源码深度分析**。

---

## 一、FFmpegMuxerRegister 插件注册层

**源码路径**: `ffmpeg_muxer_register.cpp` (377行) + `ffmpeg_muxer_register.h` (75行)

### 1.1 PLUGIN_DEFINITION 与 LGPL 许可（ffmpeg_muxer_register.cpp:33-34）

```cpp
// ffmpeg_muxer_register.cpp:33-34: LGPL 许可声明 + 静态注册/反注册
PLUGIN_DEFINITION(FFmpegMuxer, LicenseType::LGPL,
    FFmpegMuxerRegister::RegisterMuxerPlugins, FFmpegMuxerRegister::UnregisterMuxerPlugins)
```

### 1.2 支持格式列表（ffmpeg_muxer_register.cpp:42-44）

```cpp
// ffmpeg_muxer_register.cpp:42-44: 九种封装修复器支持格式
std::set<std::string> FFmpegMuxerRegister::supportedMuxer_ = {
    "mp4", "ipod", "amr", "mp3", "wav", "adts", "flac", "ogg", "flv"
};
```

### 1.3 CodecId → Capability 能力映射（ffmpeg_muxer_register.cpp:46-72）

```cpp
// ffmpeg_muxer_register.cpp:46-72: CodecID → OHOS MimeType 七映射
bool FFmpegMuxerRegister::CodecId2Cap(AVCodecID codecId, bool encoder, Capability &cap)
{
    switch (codecId) {
        case AV_CODEC_ID_MP3: cap.SetMime(MimeType::AUDIO_MPEG).AppendFixedKey<uint32_t>(Tag::AUDIO_MPEG_VERSION, 1); return true;
        case AV_CODEC_ID_AAC: cap.SetMime(MimeType::AUDIO_AAC); return true;
        case AV_CODEC_ID_MPEG4: cap.SetMime(MimeType::VIDEO_MPEG4); return true;
        case AV_CODEC_ID_H264: cap.SetMime(MimeType::VIDEO_AVC); return true;
        case AV_CODEC_ID_HEVC: cap.SetMime(MimeType::VIDEO_HEVC); return true;
        // ... AMR_NB / AMR_WB / PCM_S16LE / FLAC
    }
}
```

### 1.4 InitAvIoCtx 自定义 AVIOContext（ffmpeg_muxer_register.cpp:255-289）

```cpp
// ffmpeg_muxer_register.cpp:255-289: 用 DataSink 替换 FFmpeg 内部 I/O
AVIOContext* FFmpegMuxerRegister::InitAvIoCtx(const std::shared_ptr<DataSink> &dataSink, int writeFlags)
{
    auto *ptr = static_cast<AVIOContext*>(av_malloc(sizeof(AVIOContext)));
    ptr = avio_alloc_context(
        reinterpret_cast<unsigned char*>(av_malloc(4096)), // buffer
        4096,            // buffer size
        writeFlags,      // 1=write
        ptr->opaque,     // opaque → IoCtx
        IoRead,          // read callback (DataSink → Read)
        IoWrite,         // write callback (DataSink → Write)
        IoSeek);         // seek callback (DataSink → Seek)
    // line 287: 注册 IoOpen / IoClose
}
```

### 1.5 IoWrite / IoRead / IoSeek 回调桥接（ffmpeg_muxer_register.cpp:310-340）

```cpp
// ffmpeg_muxer_register.cpp:310-320: IoWrite → dataSink->Write
int32_t FFmpegMuxerRegister::IoWrite(void* opaque, const uint8_t* buf, int bufSize)
{
    auto* ioCtx = static_cast<AVIOContext*>(opaque);
    auto* io = static_cast<DataSink*>(ioCtx->opaque);
    return io->Write(buf, bufSize); // line 315: 转发到底层 DataSink
}

// ffmpeg_muxer_register.cpp:335-340: IoSeek → dataSink->Seek
int64_t FFmpegMuxerRegister::IoSeek(void* opaque, int64_t offset, int whence)
{
    auto* ioCtx = static_cast<AVIOContext*>(opaque);
    auto* io = static_cast<DataSink*>(ioCtx->opaque);
    return io->Seek(offset, whence); // line 338: 转发到底层 DataSink
}
```

---

## 二、FFmpegMuxerPlugin 底层 FFmpeg 封装

**源码路径**: `ffmpeg_muxer_plugin.cpp` (1414行) + `ffmpeg_muxer_plugin.h` (126行)

### 2.1 构造：AVFMT_FLAG_CUSTOM_IO（ffmpeg_muxer_plugin.cpp:81-92）

```cpp
// ffmpeg_muxer_plugin.cpp:81-92: 构造 → 获取 AVOutputFormat + 分配 formatContext + 设置 AVFMT_FLAG_CUSTOM_IO
FFmpegMuxerPlugin::FFmpegMuxerPlugin(std::string name)
    : MuxerPlugin(std::move(name)), isWriteHeader_(false)
{
    outputFormat_ = FFmpegMuxerRegister::GetAVOutputFormat(pluginName_); // line 84
    formatContext_ = avformat_alloc_context();                           // line 85
    formatContext_->flags |= AVFMT_FLAG_CUSTOM_IO;                       // line 87: 禁用 FFmpeg 内部 I/O
    avformat_alloc_output_context2(&formatContext_, outputFormat_, pluginName_.c_str(), nullptr); // line 88-89
    // 注册 IoOpen/IoClose → formatContext_->pb
    FFmpegMuxerRegister::IoOpen(formatContext_, &formatContext_->pb,
        pluginName_.c_str(), AVIO_FLAG_WRITE, nullptr); // line 91-92
}
```

### 2.2 AddTrack 轨道添加（ffmpeg_muxer_plugin.cpp:963-966）

```cpp
// ffmpeg_muxer_plugin.cpp:963-966: AddTrack 前置校验
Status FFmpegMuxerPlugin::AddTrack(int32_t &trackIndex, const std::shared_ptr<Meta> &trackDesc)
{
    FALSE_RETURN_V_MSG_E(!isWriteHeader_, Status::ERROR_WRONG_STATE,
        "AddTrack failed! muxer has start!"); // line 964: Start 前才能 AddTrack
    FALSE_RETURN_V_MSG_E(outputFormat_ != nullptr, Status::ERROR_NULL_POINTER,
        "AVOutputFormat is nullptr");          // line 965: 格式有效性校验
    // ... 根据 codecType 分发到 AddVideoTrack / AddAudioTrack / AddTimedMetaTrack
}
```

### 2.3 Start：avformat_write_header（ffmpeg_muxer_plugin.cpp:1042-1073）

```cpp
// ffmpeg_muxer_plugin.cpp:1042-1073: Start → avformat_write_header 两阶段写入
Status FFmpegMuxerPlugin::Start()
{
    FALSE_RETURN_V_MSG_E(!isWriteHeader_, Status::ERROR_WRONG_STATE,
        "Start failed! muxer has start!");  // line 1043: 防止重复 Start
    avformat_alloc_output_context2(&formatContext_, outputFormat_,
        pluginName_.c_str(), nullptr);        // line 1048: 重新分配 context
    // ... 设置 metadata / rotation / location
    avformat_write_header(formatContext_, &options); // line 1069: 写入文件头
    isWriteHeader_ = true;                            // line 1070: 标记已写头
}
```

### 2.4 WriteSample：av_interleaved_write_frame（ffmpeg_muxer_plugin.cpp:1103-1110）

```cpp
// ffmpeg_muxer_plugin.cpp:1103-1110: WriteSample → avpacket → formatContext_->pb
Status FFmpegMuxerPlugin::WriteSample(uint32_t trackIndex,
    const std::shared_ptr<AVBuffer> &sample)
{
    FALSE_RETURN_V_MSG_E(isWriteHeader_, Status::ERROR_WRONG_STATE,
        "WriteSample failed! Did not write header!"); // line 1104
    // ... 填充 cachePacket_ (AVPacket) 并设置 pts/dts/flags/size
    av_interleaved_write_frame(formatContext_, cachePacket_.get()); // line 1109: 写入
}
```

### 2.5 Stop：av_interleaved_write_trailer（ffmpeg_muxer_plugin.cpp:1131-1138）

```cpp
// ffmpeg_muxer_plugin.cpp:1131-1138: Stop → 写入文件尾信息
Status FFmpegMuxerPlugin::Stop()
{
    FALSE_RETURN_V_MSG_E(isWriteHeader_, Status::ERROR_WRONG_STATE,
        "Stop failed! Did not write header!");
    av_interleaved_write_trailer(formatContext_); // line 1134: 写入 mp4 tailer (moov box)
    isWriteHeader_ = false;                       // line 1135: 重置状态
}
```

---

## 三、FFmpegFlvMuxerPlugin FLV 专用封装修复器

**源码路径**: `flv_muxer/ffmpeg_flv_muxer_plugin.cpp` (586行) + `flv_muxer/ffmpeg_flv_muxer_plugin.h` (85行)

### 3.1 继承关系与 FLV 标记（ffmpeg_flv_muxer_plugin.h:40 + ffmpeg_flv_muxer_plugin.cpp:46-70）

```cpp
// ffmpeg_flv_muxer_plugin.h:40: FLV 插件继承 MuxerPlugin（Mpeg4MuxerPlugin 同级）
class FFmpegFlvMuxerPlugin : public MuxerPlugin { ... };

// ffmpeg_flv_muxer_plugin.cpp:46-70: 构造复用 FFmpegMuxerRegister 的 GetAVOutputFormat
FFmpegFlvMuxerPlugin::FFmpegFlvMuxerPlugin(std::string name)
    : MuxerPlugin(std::move(name)), isWriteHeader_(false)
{
    outputFormat_ = FFmpegMuxerRegister::GetAVOutputFormat(pluginName_); // line 56
    formatContext_ = avformat_alloc_context();
    // line 88-89: Stop 时重新初始化 AVIOContext（FLV 的 Seek 需求）
    FFmpegMuxerRegister::DeInitAvIoCtx(ptr->pb);
    formatContext_->pb = FFmpegMuxerRegister::InitAvIoCtx(dataSink, 1); // line 92-93
}
```

### 3.2 Start：flvflags add_keyframe_index（ffmpeg_flv_muxer_plugin.cpp:467-484）

```cpp
// ffmpeg_flv_muxer_plugin.cpp:467-484: FLV 专用写入选项
Status FFmpegFlvMuxerPlugin::Start()
{
    FALSE_RETURN_V_MSG_E(!isWriteHeader_, Status::ERROR_WRONG_STATE,
        "Start failed! muxer has start!");
    av_dict_set(&options, "flvflags", "add_keyframe_index+no_duration_filesize", 0); // line 478
    avformat_write_header(formatContext_, &options);  // line 480
    isWriteHeader_ = true;                           // line 484
}
```

### 3.3 WriteNormal：FLV 元数据标签（ffmpeg_flv_muxer_plugin.cpp:539-580）

```cpp
// ffmpeg_flv_muxer_plugin.cpp:539-580: WriteNormal → 写 FLV tag + metadata
// line 550-558: 处理 video/audio script data tag
// line 565-572: 写入 flv header + previousTagSize
```

---

## 四、MPEG4MuxerPlugin MPEG-4 ISOBMFF 封装修复器

**源码路径**: `mpeg4_muxer/mpeg4_muxer_plugin.cpp` (574行) + `mpeg4_muxer_plugin.h` (81行)

### 4.1 自定义 AVIOStream 而非 FFmpeg AVIOContext（mpeg4_muxer_plugin.h:41-48）

```cpp
// mpeg4_muxer_plugin.h:41-48: MPEG4 不走 FFmpeg AVIOContext，走自研 AVIOStream
class MPEG4MuxerPlugin : public MuxerPlugin {
    std::shared_ptr<AVIOStream> io_{nullptr};          // 自研 I/O 流
    std::shared_ptr<BasicBox> moovBox_{nullptr};        // moov 根 box
    std::vector<std::shared_ptr<Mpeg4Track>> tracks_;  // 轨列表
    Status AddTrack(int32_t &trackIndex, const std::shared_ptr<Meta> &trackDesc) override;
    Status Start() override;
    Status WriteSample(uint32_t trackIndex, const std::shared_ptr<AVBuffer> &sample) override;
    Status Stop() override;
};
```

### 4.2 Start：写入 moov header + 遍历 Track（mpeg4_muxer_plugin.cpp:420-470）

```cpp
// mpeg4_muxer_plugin.cpp:420-470: Start → 写入 moov header → Track::WriteSample → 遍历 tracks_
Status MPEG4MuxerPlugin::Start()
{
    FALSE_RETURN_V_MSG_E(io_ != nullptr, Status::ERROR_NULL_POINTER, "AVIOStream is nullptr");
    for (auto& track : tracks_) {
        track->WriteHeader(io_);  // line 444: 每条 Track 写入自己的 header
    }
    moovBox_->Write(io_);         // line 448: 写入 moov box 到 AVIOStream
}
```

---

## 五、BasicBox ISOBMFF 原子层级

**源码路径**: `mpeg4_muxer/basic_box.cpp` (1256行) + `basic_box.h` (575行)

### 5.1 BasicBox / FullBox 类层级（basic_box.h:98-160）

```cpp
// basic_box.h:98-130: BasicBox — 原子节点基类
class BasicBox {
    uint32_t size_;                                            // box size (4B)
    std::string type_;                                         // fourcc type (4B)
    std::unordered_map<std::string, std::shared_ptr<BasicBox>> childBoxes_;  // 子 box
    std::vector<std::string> childTypes_;                      // 子类型顺序
    bool needWrite_ = true;                                   // 跳过标记
    int64_t Write(std::shared_ptr<AVIOStream> io) override;    // line 103: 写入自身
    void WriteChild(std::shared_ptr<AVIOStream> io);           // line 117: 递归写子 box
};

// basic_box.h:131-160: FullBox — 扩展 version+flags (用于 mvhd/trak 等)
class FullBox : public BasicBox {
    uint8_t version_;
    uint8_t flags_[3];  // 3-byte flags
    int64_t Write(std::shared_ptr<AVIOStream> io) override;   // line 146: 先写 version+flags
};

// basic_box.h:169+: AnyBox — 纯数据容器（无子节点）
class AnyBox : public BasicBox { ... };
```

### 5.2 Write 递归写入（basic_box.cpp:103-120）

```cpp
// basic_box.cpp:103-120: BasicBox::Write — 递归写入自身+所有子 box
int64_t BasicBox::Write(std::shared_ptr<AVIOStream> io)
{
    if (!needWrite_) { return 0; }        // line 105: 跳过标记
    io->Write(size_);                     // line 110: 写入 size
    io->Write(type_.data(), BOX_TYPE_LEN); // line 111: 写入 type (4B)
    WriteChild(io);                        // line 112: 递归写子 box
    AppendChildSize();                     // line 113: 更新 size (子 box 大小汇总)
}
```

### 5.3 常用 Box 子类（basic_box.h:175-575）

```cpp
// basic_box.h:175+: 关键 Box 子类
class MvhdBox : public FullBox { ... };   // movie header (duration/timeScale/rate/volume/matrix)
class TrakBox : public FullBox { ... };   // track container
class MdiaBox : public BasicBox { ... };  // media container
class MinfBox : public BasicBox { ... };  // media information
class StblBox : public BasicBox { ... };   // sample table
class AvccBox : public BasicBox { ... };  // AVC decoder config record (SPS/PPS)
class HvccBox : public BasicBox { ... };  // HEVC decoder config record (VPS/SPS/PPS)
class EsdsBox : public FullBox { ... };   // ESDS audio config
class CttsBox : public FullBox { ... };   // composition time offset (B-frame 补偿)
class StssBox : public FullBox { ... };   // sync sample (I-frame 标记)
class SttsBox : public FullBox { ... };   // time-to-sample (PTS 增量)
class StscBox : public FullBox { ... };   // sample-to-chunk (chunk 映射)
class StszBox : public FullBox { ... };   // sample size
class StcoBox : public FullBox { ... };   // chunk offset
class Co64Box : public FullBox { ... };  // 64-bit chunk offset
```

---

## 六、Mpeg4Track 轨模型

**源码路径**: `mpeg4_muxer/track/`

### 6.1 BasicTrack 基类（basic_track.cpp:282行 + basic_track.h:111行）

```cpp
// basic_track.h:28-60: BasicTrack — Mpeg4Track 基类
class BasicTrack {
    std::string mimeType_;
    std::shared_ptr<BasicBox> moov_;               // 父 moov box
    std::vector<std::shared_ptr<BasicTrack>>& tracks_; // 兄弟 track 引用
    std::shared_ptr<Meta> trackDesc_;
    int32_t timeScale_{0};
    virtual Status Init(const std::shared_ptr<Meta> &trackDesc) = 0;
    virtual void SetRotation(uint32_t rotation) = 0;
    virtual Status WriteSample(std::shared_ptr<AVIOStream> io, const std::shared_ptr<AVBuffer> &sample) = 0;
    virtual Status WriteTailer() = 0;
};

// basic_track.cpp:28-40: TREF_TAG_MAP — track reference type 表
const std::map<std::string, uint32_t> TREF_TAG_MAP = {
    {"hint", 'hint'}, {"cdsc", 'cdsc'}, {"subt", 'subt'},
    {"thmb", 'thmb'}, {"auxl", 'auxl'}, ...
};
```

### 6.2 VideoTrack（video_track.cpp:753行 + video_track.h:95行）

```cpp
// video_track.h:24-36: VideoTrack 公开接口
class VideoTrack : public BasicTrack {
    Status Init(const std::shared_ptr<Meta> &trackDesc) override;
    void SetRotation(uint32_t rotation) override;
    Status WriteSample(std::shared_ptr<AVIOStream> io, const std::shared_ptr<AVBuffer> &sample) override;
    void UpdateUserMeta(const std::shared_ptr<Meta> &userMeta) override;
    int32_t GetWidth() const; int32_t GetHeight() const;
    bool IsColor() const; bool IsCuvaHDR() const;
    void SetCttsBox(std::shared_ptr<SttsBox> ctts);
    void SetStssBox(std::shared_ptr<StssBox> stss);
};

// video_track.cpp:127-145: CreateParser — 动态创建 AVC/H265 解析器
int32_t VideoTrack::CreateParser()
{
    if (videoParser_ == nullptr) {
        if (mimeType_ == MimeType::VIDEO_AVC) {
            videoParser_ = std::make_shared<AvcParser>();  // line 130: AVC 解析器
        } else if (mimeType_ == MimeType::VIDEO_HEVC) {
            videoParser_ = std::make_shared<HevcParser>();  // line 132: HEVC 解析器
        }
        videoParser_->Init(); // line 136
    }
}

// video_track.cpp:266-323: WriteSample — 解析 NALU + 写入视频帧
Status VideoTrack::WriteSample(std::shared_ptr<AVIOStream> io, const std::shared_ptr<AVBuffer> &sample)
{
    // line 285: ParserSetConfig() 在首帧设置 SPS/PPS/HVCC
    // line 291: DisposeCtts(pts) 写入 CTTS box (B-frame 补偿)
    // line 317-319: DisposeCttsAndStts / DisposeSttsOnly 写入 stts/stss
}

// video_track.cpp:398-432: InitColor — 初始化色彩元数据
bool VideoTrack::InitColor(const std::shared_ptr<Meta> &trackDesc)
{
    // 从 trackDesc 提取 ColorPrimary/Transfer/Matrix/Range
    // 创建 ColrBox/MdtaBox
}

// video_track.cpp:442-462: DisposeCtts — CTTS B帧补偿计算
void VideoTrack::DisposeCtts(int64_t pts)
{
    // 将 PTS 转为 MPEG-4 时间单位，计算 DTS-PTS 差值写入 ctts box
    // line 462: DisposeCttsByFrameRate 按帧率估算 CTS 偏移
}
```

### 6.3 AudioTrack（audio_track.cpp:263行 + audio_track.h:50行）

```cpp
// audio_track.h:25-38: AudioTrack 公开接口
class AudioTrack : public BasicTrack {
    Status Init(const std::shared_ptr<Meta> &trackDesc) override;
    Status WriteSample(std::shared_ptr<AVIOStream> io, const std::shared_ptr<AVBuffer> &sample) override;
    Status WriteTailer() override;
    Any GetPointer() override { return Any(this); }
    void UpdateUserMeta(const std::shared_ptr<Meta> &userMeta) override;
};

// audio_track.cpp:52-100: AudioTrack::Init — 提取 audio 采样参数
Status AudioTrack::Init(const std::shared_ptr<Meta> &trackDesc)
{
    // 从 trackDesc 提取 sampleRate/channels/bitPerSample/codecConfig
    // 创建 EsdsBox 设置 AAC decoder config
}
```

### 6.4 CoverTrack / TimedMetaTrack（cover_track.cpp:93行 + timed_meta_track.cpp:198行）

```cpp
// cover_track.h:24-34: CoverTrack — 封面图轨
class CoverTrack : public BasicTrack {
    Status Init(const std::shared_ptr<Meta> &trackDesc) override;
    Status WriteSample(std::shared_ptr<AVIOStream> io, const std::shared_ptr<AVBuffer> &sample) override;
};

// timed_meta_track.h:26-37: TimedMetaTrack — 时间元数据轨
class TimedMetaTrack : public BasicTrack {
    Status Init(const std::shared_ptr<Meta> &trackDesc) override;
    Status WriteSample(std::shared_ptr<AVIOStream> io, const std::shared_ptr<AVBuffer> &sample) override;
    Status WriteTailer() override;
    Any GetPointer() override { return Any(this); }
};
```

---

## 七、AvcParser / HevcParser 视频码流解析

**源码路径**: `mpeg4_muxer/avc_parser.cpp` (211行) + `mpeg4_muxer/hevc_parser.cpp` (186行)

### 7.1 AvcParser（avc_parser.h:30-58）

```cpp
// avc_parser.h:30-58: AvcParser — AVC NALU → ISOBMFF 转换
enum AvcNalType : uint8_t {
    AVC_SPS_NAL_UNIT = 7,
    AVC_PPS_NAL_UNIT = 8,
    AVC_SPS_EXT_NAL_UNIT = 13,
};

class AvcParser : public VideoParser {
    int32_t WriteFrame(const std::shared_ptr<AVIOStream> &io,
        const std::shared_ptr<AVBuffer> &sample) override;      // 帧写入
    int32_t SetConfig(const std::shared_ptr<BasicBox> &box,
        std::vector<uint8_t> &codecConfig) override;            // 设置 codec config
    int32_t ParseSps(const uint8_t* sample, int32_t size);      // 解析 SPS
    int32_t ParsePps(const uint8_t* sample, int32_t size);       // 解析 PPS
    std::shared_ptr<BasicBox> avccBasicBox_;                    // AVCC box (SPS/PPS)
    AvccBox* avccBox_ = nullptr;
    std::unordered_map<AvcNalType, std::pair<bool, ParserFunc>> needParse_ = {
        {AVC_SPS_NAL_UNIT, {true, &AvcParser::ParseSps}},    // line 47
        {AVC_PPS_NAL_UNIT, {true, &AvcParser::ParsePps}},    // line 48
        {AVC_SPS_EXT_NAL_UNIT, {true, &AvcParser::ParseSpsExt}} // line 49
    };
};
```

### 7.2 SetConfig 首帧配置（avc_parser.cpp:110-170）

```cpp
// avc_parser.cpp:110-170: SetConfig — 从首帧提取 SPS/PPS → 写入 AVCC box
int32_t AvcParser::SetConfig(const std::shared_ptr<BasicBox> &box,
    std::vector<uint8_t> &codecConfig)
{
    // line 120-135: ParseAnnexBFrame 提取 SPS/PPS
    // line 140-145: 创建 AvccBox 并写入 avcC codec config
    // line 150-165: ParseSps 提取 width/height/chroma_format/profile_level
}
```

---

## 八、四组件协作关系

```
MuxerFilter (Pipeline 入口)
└── MediaMuxer (Server 侧代理)
    ├── FFmpegMuxerPlugin (ffmpeg_muxer_plugin.cpp:1414行)
    │   ├── AddTrack → avformat_new_stream / avcodec_parameters_copy
    │   ├── Start → avformat_write_header (写入 header)
    │   ├── WriteSample → av_interleaved_write_frame (写入样本)
    │   └── Stop → av_interleaved_write_trailer (写入 tailer)
    │
    ├── FFmpegFlvMuxerPlugin (flv_muxer/ffmpeg_flv_muxer_plugin.cpp:586行)
    │   └── 继承 FFmpegMuxerPlugin，覆写 Start() 加 flvflags
    │
    └── MPEG4MuxerPlugin (mpeg4_muxer/mpeg4_muxer_plugin.cpp:574行)
        ├── 自研 AVIOStream (不依赖 FFmpeg)
        ├── moovBox_ (BasicBox 树根节点)
        ├── VideoTrack::WriteSample → VideoTrack → BasicBox
        ├── AudioTrack::WriteSample → AudioTrack → BasicBox
        └── WriteSample → AvcParser → AvccBox (NALU → ISOBMFF 转换)
```

---

## 关键证据汇总

| 证据 | 文件:行号 | 说明 |
|------|-----------|------|
| E1 | ffmpeg_muxer_register.cpp:33-34 | PLUGIN_DEFINITION(FFmpegMuxer, LicenseType::LGPL) |
| E2 | ffmpeg_muxer_register.cpp:42-44 | supportedMuxer_ 九格式列表 |
| E3 | ffmpeg_muxer_register.cpp:46-72 | CodecId2Cap 七映射 (MP3/AAC/MPEG4/AVC/HEVC/AMR/FLAC) |
| E4 | ffmpeg_muxer_register.cpp:255-289 | InitAvIoCtx 自定义 AVIOContext |
| E5 | ffmpeg_muxer_register.cpp:310-320 | IoWrite → dataSink->Write |
| E6 | ffmpeg_muxer_register.cpp:335-340 | IoSeek → dataSink->Seek |
| E7 | ffmpeg_muxer_plugin.cpp:81-92 | 构造 → AVFMT_FLAG_CUSTOM_IO + IoOpen |
| E8 | ffmpeg_muxer_plugin.cpp:963-966 | AddTrack 前置校验 (isWriteHeader_/outputFormat_) |
| E9 | ffmpeg_muxer_plugin.cpp:1042-1073 | Start → avformat_write_header + isWriteHeader_=true |
| E10 | ffmpeg_muxer_plugin.cpp:1103-1110 | WriteSample → av_interleaved_write_frame |
| E11 | ffmpeg_muxer_plugin.cpp:1131-1138 | Stop → av_interleaved_write_trailer |
| E12 | ffmpeg_flv_muxer_plugin.cpp:46-70 | 构造复用 FFmpegMuxerRegister::GetAVOutputFormat |
| E13 | ffmpeg_flv_muxer_plugin.cpp:467-484 | Start → flvflags=add_keyframe_index |
| E14 | ffmpeg_flv_muxer_plugin.cpp:539-580 | WriteNormal → FLV tag + metadata |
| E15 | mpeg4_muxer_plugin.h:41-48 | MPEG4MuxerPlugin 自研 AVIOStream 而非 FFmpeg AVIO |
| E16 | mpeg4_muxer_plugin.cpp:420-470 | Start → moovBox_->Write(io) 递归写入 |
| E17 | basic_box.h:98-130 | BasicBox 类定义 (size/type/childBoxes/needWrite_) |
| E18 | basic_box.h:131-160 | FullBox 类定义 (version/flags 三字节) |
| E19 | basic_box.cpp:103-120 | BasicBox::Write 递归写入自身+子 box |
| E20 | basic_box.h:175+ | AvccBox/HvccBox/EsdsBox/CttsBox/StssBox/SttsBox/StscBox/StszBox/StcoBox |
| E21 | basic_track.h:28-60 | BasicTrack 抽象基类 (mimeType/moov/tracks_) |
| E22 | basic_track.cpp:28-40 | TREF_TAG_MAP track reference type 表 |
| E23 | video_track.cpp:127-145 | CreateParser 动态创建 AVC/H265 解析器 |
| E24 | video_track.cpp:266-323 | WriteSample → ParserSetConfig + DisposeCtts + DisposeCttsAndStts |
| E25 | video_track.cpp:398-432 | InitColor 初始化 ColrBox 色彩元数据 |
| E26 | video_track.cpp:442-462 | DisposeCtts B帧补偿时间戳写入 CTTS box |
| E27 | audio_track.h:25-38 | AudioTrack 公开接口 (Init/WriteSample/WriteTailer) |
| E28 | avc_parser.h:30-58 | AvcParser::AvcNalType 枚举 + needParse_ 三映射表 |
| E29 | avc_parser.cpp:110-170 | SetConfig 首帧解析 SPS/PPS → 写入 AVCC box |