---
status: approved
approved_at: "2026-05-06"
submitted_by: builder-agent
submitted_at: "2026-05-03T06:33:00+08:00"
---
FFmpegMuxerPlugin 与 Mpeg4MuxerPlugin 双插件封装架构——libavformat 适配层与原生 MP4 Box 结构对比

## 分类
AVCodec, MuxerPlugin, FFmpeg, libavformat, MP4, Muxer, Plugin

## 描述

### 架构总览

AVCodec muxer 层存在两套并行实现：

1. **FFmpegMuxerPlugin**：基于 `libavformat`（avformat）适配层，支持 9 种格式
2. **Mpeg4MuxerPlugin**：原生 MP4 box 结构手写实现，仅支持 MP4/M4A

两者均实现 `MuxerPlugin` 抽象接口（AddTrack/Start/Stop/WriteSample/SetDataSink），通过 `MuxerPluginRegister` 注入 PluginManagerV2。

### FFmpegMuxerPlugin 核心实现

**文件**：
- `plugins/ffmpeg_adapter/muxer/ffmpeg_muxer_plugin.cpp`（1414行）
- `plugins/ffmpeg_adapter/muxer/ffmpeg_muxer_plugin.h`（126行）
- `plugins/ffmpeg_adapter/muxer/ffmpeg_muxer_register.cpp`

**九格式支持**：

```cpp
std::map<std::string, uint32_t> g_supportedMuxer = {
    {"Mpeg4Mux_mp4", OUTPUT_FORMAT_MPEG_4},
    {"Mpeg4Mux_m4a", OUTPUT_FORMAT_M4A},
    {"Mp3Mux_mp3", OUTPUT_FORMAT_MP3},
    {"WavMux_wav", OUTPUT_FORMAT_WAV},
    {"AdtsMux_aac", OUTPUT_FORMAT_AAC},
    {"FlacMux_flac", OUTPUT_FORMAT_FLAC},
    {"OggMux_ogg", OUTPUT_FORMAT_OGG},
    {"FlvMux_flv", OUTPUT_FORMAT_FLIV},
    {"AmrMux_amr", OUTPUT_FORMAT_AMR}
};
```

**AVFMT_FLAG_CUSTOM_IO**：FFmpegMuxerPlugin 启用自定义 IO（`AVFMT_FLAG_CUSTOM_IO`），用自定义 `avio_stream` 替代标准文件 IO，由 `DataSink` 抽象层提供读写：

```cpp
fmt->io_open = FFmpegMuxerRegister::IoOpen;
fmt->io_close2 = FFmpegMuxerRegister::IoClose;
fmt->flags = fmt->flags | AVFMT_FLAG_CUSTOM_IO;
```

**WriteSample 三分支**：

```cpp
Status FFmpegMuxerPlugin::WriteSample(uint32_t trackIndex, const std::shared_ptr<AVBuffer> &sample)
{
    if (st->codecpar->codec_id == AV_CODEC_ID_H264 || st->codecpar->codec_id == AV_CODEC_ID_HEVC) {
        return WriteVideoSample(trackIndex, sample);  // 视频：处理 Annex B→MP4 NALU 转换
    } else if (st->codecpar->codec_id == AV_CODEC_ID_FLAC && 
               sample->flag_ == AVBufferFlag::CODEC_DATA) {
        return Status::NO_ERROR;  // FLAC codec data 更新
    }
    return WriteNormal(trackIndex, sample, 0);  // 普通音视频直接写入
}
```

**WriteNormal 核心**：

```cpp
cachePacket_->data = data;
cachePacket_->size = size;
cachePacket_->stream_index = trackIndex;
cachePacket_->pts = ConvertTimeToFFmpegByUs(sample->pts_, st->time_base);
if (st->codecpar->codec_type == AVMEDIA_TYPE_AUDIO) {
    cachePacket_->dts = cachePacket_->pts;  // 音频：dts=pts
}
// 最终调用 av_interleaved_write_frame(formatContext_.get(), cachePacket_.get())
```

### Mpeg4MuxerPlugin 原生实现

**文件**：
- `plugins/ffmpeg_adapter/muxer/mpeg4_muxer/mpeg4_muxer_plugin.cpp`（574行）
- `plugins/ffmpeg_adapter/muxer/mpeg4_muxer/box_parser.cpp`（917行）
- `plugins/ffmpeg_adapter/muxer/mpeg4_muxer/basic_box.cpp`（1256行）
- `plugins/ffmpeg_adapter/muxer/mpeg4_muxer/avio_stream.cpp`（221行）
- `plugins/ffmpeg_adapter/muxer/mpeg4_muxer/video_parser.cpp`（189行）
- `plugins/ffmpeg_adapter/muxer/mpeg4_muxer/avc_parser.cpp`（211行）
- `plugins/ffmpeg_adapter/muxer/mpeg4_muxer/hevc_parser.cpp`（186行）

**MP4 Box 层级**（BasicBox 体系）：

```
ftyp → major_brand / minor_version / compatible_brands[]
moov → mvhd (movie header) + trak[] (track) + udta[]
  trak → tkhd (track header) + mdia[]
    mdia → mdhd (media header) + hdlr (handler) + minf[]
      minf → stbl (sample table) → stts/stss/stsc/stsz/stco/ctts[]
```

**BasicBox 写入流程**（以 ftyp 为例）：

```cpp
// basic_box.cpp 中 Write 方法：
uint8_t* BasicBox::Write()
{
    // 1. 计算 totalSize（8字节头部 + 数据）
    // 2. 写入 4 字节 size（大端）
    // 3. 写入 4 字节 boxType（FourCC，如 'ftyp'）
    // 4. 写入扩展字段（largesize / uuid）
    // 5. 写入子 box 数据
    return buffer;
}
```

**Track 写入链**：

```cpp
Mpeg4MuxerPlugin::AddTrack()
  → AddVideoTrack() / AddAudioTrack()
    → SetCodecParameterOfVideoTrack() / SetCodecParameterOfAudioTrack()
      → 配置 stream codecpar

Mpeg4MuxerPlugin::WriteSample()
  → WriteVideoSample() / WriteAudioSample()
    → 查找对应 Track 对象
    → Track::WriteSample(sample)
      → Track 调用 BasicBox 写入 buffer
```

**FLAC 特殊处理**（`flacCodecConfig_` 缓存 codec data，分批写入 MP4 box）。

### 双插件对比

| 维度 | FFmpegMuxerPlugin | Mpeg4MuxerPlugin |
|------|------------------|-----------------|
| 底层 | FFmpeg libavformat | 原生 box 手写实现 |
| 格式 | 9 种格式 | 仅 MP4/M4A |
| NALU 处理 | Annex B→MP4 转换 | 原生 box 结构 |
| 可控性 | 低（依赖 FFmpeg） | 高（手写 box） |
| 代码量 | 1414+126 行 | 574+917+1256 行 |
| Track 类型 | Audio/Video/TimedMeta/Auxiliary | Audio/Video/Cover/TimedMeta |
| 性能 | 一般（FFmpeg 内部优化） | 较高（按需写入） |

### 与 S34/S65 的关系

- **S34 (MuxerFilter)**：Filter 层的入口，过滤器链的终点，持有 `MediaMuxer`，通过 `AVBufferQueue` 接收数据
- **S65 (MediaMuxer)**：中间的协调层，持有 `MuxerPlugin`，管理 `Track` 列表，`AVBufferQueue` 消费驱动
- **S74 (FFmpegMuxerPlugin/Mpeg4MuxerPlugin)**：最底层的插件实现，真正执行封装逻辑

数据流：`MuxerFilter(Filter)` → `MediaMuxer(TrackMgr)` → `MuxerPlugin(FFmpegMuxerPlugin|Mpeg4MuxerPlugin)` → `DataSink/File`

## 关键代码路径/证据

- `plugins/ffmpeg_adapter/muxer/ffmpeg_muxer_plugin.cpp:1414` — WriteSample 三分支（H264/HEVC/FLAC/普通）
- `plugins/ffmpeg_adapter/muxer/ffmpeg_muxer_plugin.cpp:107-131` — SetDataSink 自定义 IO
- `plugins/ffmpeg_adapter/muxer/ffmpeg_muxer_plugin.cpp:963` — AddTrack 入口
- `plugins/ffmpeg_adapter/muxer/ffmpeg_muxer_register.cpp` — IoOpen/IoClose 自定义 IO 回调
- `plugins/ffmpeg_adapter/muxer/mpeg4_muxer/mpeg4_muxer_plugin.cpp:574` — 原生 MP4 muxer
- `plugins/ffmpeg_adapter/muxer/mpeg4_muxer/box_parser.cpp:917` — MP4 box 解析/写入
- `plugins/ffmpeg_adapter/muxer/mpeg4_muxer/basic_box.cpp:1256` — BasicBox 层级结构
- `plugins/ffmpeg_adapter/muxer/mpeg4_muxer/avc_parser.cpp:211` — AVC codec config 解析
- `plugins/ffmpeg_adapter/muxer/mpeg4_muxer/hevc_parser.cpp:186` — HEVC codec config 解析
- `plugins/ffmpeg_adapter/muxer/mpeg4_muxer/track/video_track.cpp` — 视频 Track box 组织
- `plugins/ffmpeg_adapter/muxer/mpeg4_muxer/track/audio_track.cpp` — 音频 Track box 组织
- `services/media_engine/filters/muxer_filter.cpp` — Filter 层入口

## 相关记忆链接

- S34: MuxerFilter（Filter 层封装）
- S65: MediaMuxer（Track 管理与 AVBufferQueue 异步写入）
- S40: FFmpegMuxerPlugin（草案已存在，部分内容被 S74 覆盖）

## 标签

- AVCodec
- MuxerPlugin
- FFmpeg
- libavformat
- MP4
- BoxParser
- Muxer
- Plugin
