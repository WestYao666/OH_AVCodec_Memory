---
mem_id: MEM-ARCH-AVCODEC-S94
title: "AVCodec Muxer/Demuxer/Source C API 三件套——OH_AVSource + OH_AVDemuxer + OH_AVMuxer 完整视图"
category: architecture
subcategory: native-api
tags:
  - AVCodec
  - Native API
  - C API
  - OH_AVSource
  - OH_AVDemuxer
  - OH_AVMuxer
  - OH_AVFormat
  - OH_AVBuffer
  - Muxer
  - Demuxer
  - Source
  - DRM
  - Spliter
  - Muxer
priority: P2
status: approved
approved_at: "2026-05-07T20:13:27+08:00"
submit_date: "2026-05-07T12:45:00+08:00"
submit_by: builder-agent
evidence_sources:
  - https://raw.gitcode.com/openharmony/multimedia_av_codec/raw/master/interfaces/kits/c/native_avsource.h
  - https://raw.gitcode.com/openharmony/multimedia_av_codec/raw/master/interfaces/kits/c/native_avdemuxer.h
  - https://raw.gitcode.com/openharmony/multimedia_av_codec/raw/master/interfaces/kits/c/native_avmuxer.h
  - https://raw.gitcode.com/openharmony/multimedia_av_codec/raw/master/interfaces/kits/c/native_avcodec_base.h
related_mems:
  - MEM-ARCH-AVCODEC-S83  # C API 总览
  - MEM-ARCH-AVCODEC-S84  # VideoEncoder C API
  - MEM-ARCH-AVCODEC-S88  # AudioDecoder C API
  - MEM-ARCH-AVCODEC-S65  # MediaMuxer 核心封装
  - MEM-ARCH-AVCODEC-S41  # DemuxerFilter
  - MEM-ARCH-AVCODEC-S87  # MediaSource 架构
notes: ""
---

# S94: AVCodec Muxer/Demuxer/Source C API 三件套——OH_AVSource + OH_AVDemuxer + OH_AVMuxer 完整视图

## 1. 概述

AVCodec Native C API 提供三个协同工作的核心组件，用于媒体的解封装（Demuxer）、封装（Muxer）和数据源（Source）操作。这三者构成完整的"读-转-写"媒体管线：

```
[OH_AVSource] ──创建数据源（URI/FD/DataSource）──> [OH_AVDemuxer] ──读取样本──> [解码/编码]
                                                                                          │
                                                                                          ▼
                                                                                   [OH_AVMuxer] ──写入文件（MP4/M4A...）
```

- **OH_AVSource**（`libnative_media_avsource.so`）：媒体资源对象构造，支持 URI / 文件描述符 / 自定义 DataSource 三种创建方式
- **OH_AVDemuxer**（`libnative_media_avdemuxer.so`）：音视频样本提取，支持 Track 选择 / 样本读取 / Seek 操作
- **OH_AVMuxer**（`libnative_media_avmuxer.so`）：媒体文件封装，支持 Track 添加 / 样本写入 / 格式设置

关联记忆：
- S83（C API 总览）定义了回调体系、OH_AVCodec 对象模型
- S84（VideoEncoder C API）和 S88（AudioDecoder C API）定义编解码器创建
- S65（MediaMuxer 核心）和 S74/91（MPEG4/FFmpeg MuxerPlugin）定义引擎层封装
- S41（DemuxerFilter）和 S87（MediaSource）定义 Filter 层的封装

## 2. OH_AVSource——媒体资源对象构造

**头文件**：`interfaces/kits/c/native_avsource.h`
**库**：`libnative_media_avsource.so`
**SysCap**：`SystemCapability.Multimedia.Media.Spliter`
**起始版本**：10

### 2.1 三种创建方式

```c
// 方式1：通过 URI 创建（网络/本地资源）
OH_AVSource *OH_AVSource_CreateWithURI(char *uri);

// 方式2：通过文件描述符创建（支持部分文件读取）
OH_AVSource *OH_AVSource_CreateWithFD(int32_t fd, int64_t offset, int64_t size);
// 参数：fd 文件描述符，offset 文件内起始偏移，size 文件大小

// 方式3：通过自定义数据源创建（since 12）
OH_AVSource *OH_AVSource_CreateWithDataSource(OH_AVDataSource *dataSource);
// 自定义回调：OH_AVDataSourceReadAt(data, length, pos) → 实际读取字节数

// 方式4：通过 DataSource + userData 创建（since 20）
OH_AVSource *OH_AVSource_CreateWithDataSourceExt(OH_AVDataSourceExt *dataSource, void* userData);
// 支持用户自定义上下文指针传递
```

### 2.2 OH_AVDataSource 结构

```c
typedef int32_t (*OH_AVDataSourceReadAt)(OH_AVBuffer *data, int32_t length, int64_t pos);

typedef struct OH_AVDataSource {
    int64_t size;                    // 数据源总大小
    OH_AVDataSourceReadAt readAt;    // 数据读取回调
} OH_AVDataSource;
```

### 2.3 格式查询接口

```c
// 获取整个媒体的格式信息（包含时长、比特率等）
OH_AVFormat *OH_AVSource_GetSourceFormat(OH_AVSource *source);

// 获取指定轨道的格式信息（包含 MIME、分辨率、采样率等）
OH_AVFormat *OH_AVSource_GetTrackFormat(OH_AVSource *source, uint32_t trackIndex);

// 获取自定义元数据格式（since 18）
OH_AVFormat *OH_AVSource_GetCustomMetadataFormat(OH_AVSource *source);

// 销毁 Source 实例
OH_AVErrCode OH_AVSource_Destroy(OH_AVSource *source);
```

### 2.4 Source → Demuxer 关系

Source 扮演"资源句柄"角色，AVDemuxer 依赖 Source 实例创建：

```c
OH_AVDemuxer *OH_AVDemuxer_CreateWithSource(OH_AVSource *source);
```

Source 销毁时，所有关联的 Demuxer 自动失效。

## 3. OH_AVDemuxer——音视频样本提取

**头文件**：`interfaces/kits/c/native_avdemuxer.h`
**库**：`libnative_media_avdemuxer.so`
**SysCap**：`SystemCapability.Multimedia.Media.Spliter`
**起始版本**：10

### 3.1 创建与销毁

```c
OH_AVDemuxer *OH_AVDemuxer_CreateWithSource(OH_AVSource *source);
OH_AVErrCode OH_AVDemuxer_Destroy(OH_AVDemuxer *demuxer);
```

### 3.2 Track 选择

```c
// 选择轨道（可多次调用选择多轨）
OH_AVErrCode OH_AVDemuxer_SelectTrackByID(OH_AVDemuxer *demuxer, uint32_t trackIndex);

// 取消选择轨道
OH_AVErrCode OH_AVDemuxer_UnselectTrackByID(OH_AVDemuxer *demuxer, uint32_t trackIndex);
```

### 3.3 样本读取（两种模式）

```c
// 旧版：基于 OH_AVMemory + OH_AVCodecBufferAttr（deprecated since 11）
OH_AVErrCode OH_AVDemuxer_ReadSample(OH_AVDemuxer *demuxer, uint32_t trackIndex,
    OH_AVMemory *sample, OH_AVCodecBufferAttr *info);

// 新版：基于 OH_AVBuffer（since 11，推荐）
OH_AVErrCode OH_AVDemuxer_ReadSampleBuffer(OH_AVDemuxer *demuxer, uint32_t trackIndex,
    OH_AVBuffer *sample);
```

ReadSampleBuffer 返回的 `OH_AVBuffer` 包含：
- 编码后样本数据
- 时间戳（PTS/DTS）
- 是否为关键帧
- 是否为 EOS

### 3.4 Seek 操作

```c
// 定位到指定时间（所有选中轨道同步 Seek）
OH_AVErrCode OH_AVDemuxer_SeekToTime(OH_AVDemuxer *demuxer, int64_t millisecond, OH_AVSeekMode mode);

// Seek 模式枚举：
// SEEK_MODE_SET     = 0   // 精确到指定时间
// SEEK_MODE_CLOSEST = 1   // 最近关键帧
// SEEK_MODE_CLOSEST_SYNC = 2  // 最近同步帧（since 11）
```

### 3.5 DRM 信息处理

```c
// DRM 密钥信息回调（旧版，deprecated since 14）
typedef void (*DRM_MediaKeySystemInfoCallback)(DRM_MediaKeySystemInfo* mediaKeySystemInfo);
OH_AVErrCode OH_AVDemuxer_SetMediaKeySystemInfoCallback(OH_AVDemuxer *demuxer,
    DRM_MediaKeySystemInfoCallback callback);

// DRM 密钥信息回调（新版，since 12）
typedef void (*Demuxer_MediaKeySystemInfoCallback)(OH_AVDemuxer *demuxer,
    DRM_MediaKeySystemInfo *mediaKeySystemInfo);
OH_AVErrCode OH_AVDemuxer_SetDemuxerMediaKeySystemInfoCallback(OH_AVDemuxer *demuxer,
    Demuxer_MediaKeySystemInfoCallback callback);

// 获取 DRM 信息（在回调成功后调用）
OH_AVErrCode OH_AVDemuxer_GetMediaKeySystemInfo(OH_AVDemuxer *demuxer,
    DRM_MediaKeySystemInfo *mediaKeySystemInfo);
```

## 4. OH_AVMuxer——音视频文件封装

**头文件**：`interfaces/kits/c/native_avmuxer.h`
**库**：`libnative_media_avmuxer.so`
**SysCap**：`SystemCapability.Multimedia.Media.Muxer`
**起始版本**：10

### 4.1 创建与销毁

```c
// 通过文件描述符和输出格式创建
OH_AVMuxer *OH_AVMuxer_Create(int32_t fd, OH_AVOutputFormat format);

// 销毁
OH_AVErrCode OH_AVMuxer_Destroy(OH_AVMuxer *muxer);
```

### 4.2 输出格式（OH_AVOutputFormat）

```c
enum OH_AVOutputFormat {
    OH_AVOutputFormat_AAC = 0,    // ADTS AAC (M4A container)
    OH_AVOutputFormat_MPEG_4 = 2, // MP4 container
    OH_AVOutputFormat_WAV = 6,    // WAV container
    OH_AVOutputFormat_AMR = 9,    // AMR-NB/WB container
    OH_AVOutputFormat_FLAC = 14,  // FLAC container
    // more...
};
```

### 4.3 Track 管理

```c
// 添加轨道（只能在 Start 之前调用）
OH_AVErrCode OH_AVMuxer_AddTrack(OH_AVMuxer *muxer, int32_t *trackIndex,
    OH_AVFormat *trackFormat);

// 设置轨道格式参数（since 14）
OH_AVErrCode OH_AVMuxer_SetFormat(OH_AVMuxer *muxer, OH_AVFormat *format);
```

TrackFormat 中需要包含 MIME 类型、分辨率/采样率、码率等参数。

### 4.4 视频旋转

```c
// 设置输出视频旋转角度（只能在 Start 之前调用）
OH_AVErrCode OH_AVMuxer_SetRotation(OH_AVMuxer *muxer, int32_t rotation);
// 支持 0, 90, 180, 270 度
```

### 4.5 样本写入（两种模式）

```c
// 旧版：基于 OH_AVMemory + OH_AVCodecBufferAttr（deprecated since 11）
OH_AVErrCode OH_AVMuxer_WriteSample(OH_AVMuxer *muxer, uint32_t trackIndex,
    OH_AVMemory *sample, OH_AVCodecBufferAttr info);

// 新版：基于 OH_AVBuffer（since 11，推荐）
OH_AVErrCode OH_AVMuxer_WriteSampleBuffer(OH_AVMuxer *muxer, uint32_t trackIndex,
    const OH_AVBuffer *sample);
```

`OH_AVCodecBufferAttr` 包含：
```c
struct OH_AVCodecBufferAttr {
    int64_t pts;        // 展示时间戳（微秒）
    int64_t dts;        // 解码时间戳（微秒）
    int32_t duration;    // 样本时长（微秒）
    uint32_t size;      // 数据大小
    int32_t offset;     // 数据偏移
    uint32_t flags;     // 标志（BUFFER_EOS / BUFFER_SYNC 等）
};
```

### 4.6 生命周期

```
创建(Create) ──> 添加轨道(AddTrack) ──> 启动(Start)
                                              │
                                              ▼
                                    写入样本(WriteSampleBuffer)
                                              │
                                              ▼
                                          停止(Stop) ──> 销毁(Destroy)
```

注意：`OH_AVMuxer_Stop` 后不可重启（Once stopped, cannot be restarted）。

## 5. OH_AVCodecBufferAttr——编解码缓冲区属性

**定义位置**：`native_avcodec_base.h`

```c
struct OH_AVCodecBufferAttr {
    int64_t pts;        // Presentation Time Stamp (μs)
    int64_t dts;        // Decode Time Stamp (μs)
    int32_t duration;   // 样本时长 (μs)
    uint32_t size;      // 数据大小 (bytes)
    int32_t offset;     // 缓冲区数据偏移
    uint32_t flags;     // 标志位
};

// flags 常用值
#define OH_AVCodecBufferFlag_EOS      0x1   // End of Stream
#define OH_AVCodecBufferFlag_SYNC     0x2   // 关键帧/同步帧
#define OH_AVCodecBufferFlag_CODEC_CONFIG  0x4  // 编解码器配置数据
```

## 6. 三组件协作模式

### 6.1 解封装流程（Source → Demuxer）

```
1. OH_AVSource_CreateWithURI/fd/dataSource    // 创建数据源
2. OH_AVSource_GetTrackFormat(source, i)       // 查询各轨道格式
3. OH_AVDemuxer_CreateWithSource(source)        // 创建解封装器
4. OH_AVDemuxer_SelectTrackByID(demuxer, idx)  // 选择音频/视频轨
5. LOOP:
     OH_AVDemuxer_ReadSampleBuffer(...)         // 读取编码样本
     → 送至解码器 → 送至渲染/编码
6. OH_AVDemuxer_SeekToTime(demuxer, ts, mode)  // 随机定位
7. OH_AVDemuxer_Destroy(demuxer)
8. OH_AVSource_Destroy(source)
```

### 6.2 封装流程（Source → Demuxer → Muxer）

```
1. OH_AVDemuxer_ReadSampleBuffer(...)  // 从源提取编码样本
2. 送至解码器解码
3. 送至编码器重新编码（或直接原样封装）
4. OH_AVMuxer_Create(fd, format)      // 创建封装器
5. OH_AVMuxer_AddTrack(muxer, &idx, trackFormat)  // 添加音视频轨
6. OH_AVMuxer_SetRotation(muxer, 90)   // 设置视频旋转
7. OH_AVMuxer_Start(muxer)
8. LOOP:
     OH_AVMuxer_WriteSampleBuffer(muxer, trackIdx, buffer)  // 写入样本
9. OH_AVMuxer_Stop(muxer)
10. OH_AVMuxer_Destroy(muxer)
```

## 7. MIME 类型体系（来自 native_avcodec_base.h）

AVCodec C API 支持的 MIME 类型覆盖：

| 类别 | MIME 类型 | 起始版本 |
|------|----------|---------|
| 视频 | VIDEO_AVC (H.264) | 9 |
| 视频 | VIDEO_HEVC (H.265) | 10 |
| 视频 | VIDEO_MPEG4 | 10 (deprecated 11) |
| 视频 | VIDEO_MPEG2 | 17 |
| 视频 | VIDEO_VVC (H.266) | 12 |
| 视频 | VIDEO_AV1 | 23 |
| 视频 | VIDEO_VP8/VP9 | 23 |
| 视频 | VIDEO_MPEG1 | 23 |
| 视频 | VIDEO_H263 | 17 |
| 视频 | VIDEO_MPEG4_PART2 | 17 |
| 视频 | VIDEO_VC1/WVC1/WMV3 | 22 |
| 视频 | VIDEO_MSVIDEO1 | 22 |
| 视频 | VIDEO_MJPEG | 22 |
| 视频 | VIDEO_DVVIDEO | 23 |
| 视频 | VIDEO_RV30/RV40 | 23 |
| 视频 | VIDEO_CINEPAK | 23 |
| 视频 | VIDEO_RAWVIDEO | 23 |
| 音频 | AUDIO_AAC | 9 |
| 音频 | AUDIO_AAC | 9 |
| 音频 | AUDIO_FLAC | 10 |
| 音频 | AUDIO_VORBIS | 10 |
| 音频 | AUDIO_MPEG | 10 |
| 音频 | AUDIO_AMR_NB/WB | 11 |
| 音频 | AUDIO_OPUS | 11 |
| 音频 | AUDIO_G711MU | 11 |
| 音频 | AUDIO_VIVID | 11 |
| 音频 | AUDIO_LBVC | 12 |
| 音频 | AUDIO_APE | 12 |
| 音频 | AUDIO_G711A | 20 |
| 音频 | AUDIO_EAC3/AC3 | 22 |
| 音频 | AUDIO_ALAC | 22 |
| 音频 | AUDIO_GSM/GSM_MS | 22 |
| 音频 | AUDIO_WMAV1/WMAV2/WMAPRO | 22 |
| 音频 | AUDIO_ILBC/TRUEHD/TWINVQ/DTS/COOK | 23 |
| 音频 | AUDIO_RAW | 18 |
| 字幕 | SUBTITLE_SRT | 12 |
| 字幕 | SUBTITLE_WEBVTT | 12 |

## 8. 与 Filter 层 / 引擎层的关系

```
应用层（Native C API）
├── OH_AVSource + OH_AVDemuxer  ──对应──>  [S87] MediaSource + [S41] DemuxerFilter
│                                       （SourcePlugin/FFmpegDemuxerPlugin/MPEG4DemuxerPlugin）
└── OH_AVMuxer            ──对应──>  [S65] MediaMuxer / [S74] FFmpegMuxerPlugin / [S91] MPEG4MuxerPlugin
                                （BasicBox树 + BoxParser）
```

关键区别：
- **C API 层**（S94）：面向应用开发者，提供 fd/URI/DataSource 输入、AVBuffer 输出
- **Filter 层**（S41/S89）：面向流水线编排，支持 FilterGraph 中的 Filter 间直接传递 AVBuffer
- **Plugin 层**（S68/S74/S76/S79）：面向格式编解码，提供具体格式的解析/封装实现

## 9. 核心发现

1. **Source-Demuxer 分离设计**：Source 专注资源定位，Demuxer 专注样本读取，允许多个 Demuxer 实例共享同一 Source
2. **Buffer API 演进**：从 `OH_AVMemory + OH_AVCodecBufferAttr`（deprecated）迁移到 `OH_AVBuffer` 一体化设计（since 11）
3. **DRM 全链路支持**：Demuxer 提供 DRM_MediaKeySystemInfo 回调机制，支持加密内容解密
4. **Muxer 状态机约束**：AddTrack/SetRotation 必须在 Start 之前；Stop 后不可重启
5. **DataSource 扩展性**：OH_AVDataSource 支持用户自定义数据读取回调，实现内存数据/网络流等非标准源
6. **多轨同步 Seek**：SeekToTime 同时作用于所有已选中的 Track，保证音视频同步
7. **自定义元数据支持**：OH_AVSource_GetCustomMetadataFormat（since 18）支持提取媒体自定义元数据
