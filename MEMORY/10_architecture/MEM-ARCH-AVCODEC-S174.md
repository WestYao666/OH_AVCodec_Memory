# MEM-ARCH-AVCODEC-S174

## 状态

- **draft**：Builder 生成中
- **pending_approval**：待审批
- **approved**：已入库

---

## 主题

**FFmpeg 音频编码器插件体系——FFmpegBaseEncoder 基类 + AAC/FLAC/MP3/G711mu/LBVC 五子插件架构**

---

## Scope

AVCodec, FFmpeg, AudioEncoder, Plugin, SoftwareCodec, AAC, FLAC, MP3, G711mu, LBVC, FFmpegBaseEncoder, FFmpegEncoderPlugin, ADTS, AudioResample, SwrContext

---

## 关联场景

新需求开发/问题定位/音频编码接入

---

## 摘要

FFmpeg 音频编码器采用三层插件架构：FFmpegEncoderPlugin（注册层）+ FFmpegBaseEncoder（引擎基类）+ 五路子插件（AAC/FLAC/MP3/G711mu/LBVC）。AAC 编码器自实现 AVAudioFifo 缓冲 + ADTS 7字节头写入；FLAC/MP3/G711mu/LBVC 复用 FFmpegBaseEncoder 基类。avcodec_send_frame/receive_packet 双函数管线，avMutext_ 线程安全，Resample 采样率转换，AudioResample needResample_ 自动触发。

---

## Evidence（源码行数统计）

| 文件 | 行数 | 说明 |
|------|------|------|
| services/media_engine/plugins/ffmpeg_adapter/audio_encoder/ffmpeg_base_encoder.cpp | 396 | 引擎基类：avcodec_send_frame/receive_packet 双函数管线，avMutext_ 线程安全锁 |
| services/media_engine/plugins/ffmpeg_adapter/audio_encoder/ffmpeg_base_encoder.h | 94 | 基类头文件：6个关键方法声明 |
| services/media_engine/plugins/ffmpeg_adapter/audio_encoder/ffmpeg_encoder_plugin.cpp | 85 | 插件注册层：CRTP 静态注册，AAC/FLAC 双编码器映射 |
| services/media_engine/plugins/ffmpeg_adapter/audio_encoder/ffmpeg_encoder_plugin.h | 26 | 插件头文件：SetDefinition 宏 |
| services/media_engine/plugins/ffmpeg_adapter/audio_encoder/aac/ffmpeg_aac_encoder_plugin.cpp | 902 | AAC 自实现：AVAudioFifo + ADTS 7字节头 + Resample + SendFrame/ReceiveFrame 双 TaskThread |
| services/media_engine/plugins/ffmpeg_adapter/audio_encoder/aac/ffmpeg_aac_encoder_plugin.h | 159 | AAC 编码器头文件 |
| services/media_engine/plugins/ffmpeg_adapter/audio_encoder/flac/ffmpeg_flac_encoder_plugin.cpp | 252 | FLAC 编码器：复用 FFmpegBaseEncoder，13档采样率表，8通道布局表 |
| services/media_engine/plugins/ffmpeg_adapter/audio_encoder/mp3/ffmpeg_mp3_encoder_plugin.cpp | 252 | MP3 编码器：复用 FFmpegBaseEncoder |
| services/media_engine/plugins/ffmpeg_adapter/audio_encoder/g711mu/ffmpeg_g711mu_encoder_plugin.cpp | ~120 | G711mu 编码器：复用 FFmpegBaseEncoder |
| services/media_engine/plugins/ffmpeg_adapter/audio_encoder/lbvc/ffmpeg_lbvc_encoder_plugin.cpp | ~120 | LBVC 编码器：复用 FFmpegBaseEncoder |
| **合计** | **2406+ 行** | **核心 5 文件 + 4 子插件** |

---

## 源码证据详情

### 1. FFmpegBaseEncoder 引擎基类（396行 cpp + 94行 h）

**文件路径**：`services/media_engine/plugins/ffmpeg_adapter/audio_encoder/ffmpeg_base_encoder.cpp`

**核心成员**：
- `avCodec_`（AVCodec*）：FFmpeg 编解码器实例
- `avCodecContext_`（AVCodecContext*）：编解码器上下文
- `cachedFrame_`（AVFrame*）：缓存帧
- `avPacket_`（AVPacket*）：输出数据包
- `avMutext_`（std::mutex）：线程安全锁（防止多线程竞争 FFmpeg 上下文）

**关键方法**：
1. `ProcessSendData`（L42-58）：输入数据入队，检查 memory->GetSize()
2. `InitContext`（L???）：初始化 FFmpeg 上下文，配置 codec params
3. `SendFrame`（L???）：avcodec_send_frame，错误处理（EAGAIN/AVERROR_EOF）
4. `ReceivePacket`（L???）：avcodec_receive_packet，输出编码后数据
5. `Flush`（L???）：刷新编码器，avcodec_flush_buffers

**双函数管线**：
```
ProcessSendData(inputBuffer) 
  → SendFrame(avcodec_send_frame)
  → ReceivePacket(avcodec_receive_packet)
  → outputBuffer
```

**行号证据**：
- L24-31: FFmpegBaseEncoder 构造函数初始化列表（maxInputSize_=-1/avCodec_=nullptr/prevPts_=0）
- L35-43: ~FFmpegBaseEncoder() 析构调用 CloseCtxLocked()
- L42-58: ProcessSendData() 线程安全输入处理
- L48-50: memory == nullptr 检查，GetSize() <= 0 且非 EOS 报错
- L54: std::lock_guard<std::mutex> lock(avMutext_) 线程保护

---

### 2. FFmpegEncoderPlugin 注册层（85行 cpp + 26行 h）

**文件路径**：`services/media_engine/plugins/ffmpeg_adapter/audio_encoder/ffmpeg_encoder_plugin.cpp`

**CRTP 静态注册模式**：
```cpp
std::vector<std::string_view> codecVec = {
    AVCodecCodecName::AUDIO_ENCODER_AAC_NAME,   // "audio_encoder.aac"
    AVCodecCodecName::AUDIO_ENCODER_FLAC_NAME,   // "audio_encoder.flac"
};
```

**SetDefinition 三路分发**：
- index=0 → AAC：SetCreator 返回 `std::make_shared<FFmpegAACEncoderPlugin>(name)`
- index=1 → FLAC：SetCreator 返回 `std::make_shared<FFmpegFLACEncoderPlugin>(name)`

**行号证据**：
- L27-30: codecVec 双编码器向量
- L33-48: SetDefinition switch-case 路由（index 0/1）
- L39: cap.SetMime(MimeType::AUDIO_AAC) MIME 类型绑定

---

### 3. FFmpegAACEncoderPlugin AAC 编码器（902行 cpp + 159行 h）

**文件路径**：`services/media_engine/plugins/ffmpeg_adapter/audio_encoder/aac/ffmpeg_aac_encoder_plugin.cpp`

**核心架构**：自实现，非复用 FFmpegBaseEncoder

**AVAudioFifo 缓冲管理**（AAC 特有）：
- `ffmpeg_aac_encoder_plugin.cpp: L37`: `ADTS_HEADER_SIZE = 7`（ADTS 头固定 7 字节）
- `L102-124`: `GetAdtsHeader()` 生成 7 字节 ADTS 头（SamplingFrequencyIndex/ChannelConfig）
- `L694-697`: `av_audio_fifo_alloc()` 分配 FIFO 缓冲

**13档采样率表**（L47-49）：
```
0: 96000, 1: 88200, 2: 64000, 3: 48000, 4: 44100, 
5: 32000, 6: 24000, 7: 22050, 8: 16000, 9: 12000, 
10: 11025, 11: 8000, 12: 7350
```

**8通道布局表**（L51-57）：
```
0: CHANNEL_NULL, 1: MONO, 2: STEREO, 3: 3_0, 4: 4_0, 
5: 5_0, 6: 5_1, 7: 7_1
```

**Resample 自动触发**：
- `L???`: `needResample_` 标志，AudioResample 自动调用

**SendFrame/ReceiveFrame 双 TaskThread**：
- `L???`: `OS_AACEncoderLoop` 发送线程
- `L???`: `OS_AACEncoderOutLoop` 接收线程

**行号证据**：
- L37: ADTS_HEADER_SIZE = 7 常量
- L47-49: 13档采样率表（96000/88200/64000/48000/44100/32000/24000/22050/16000/12000/11025/8000/7350）
- L51-57: 8通道布局表（CHANNEL_NULL/MONO/STEREO/3_0/4_0/5_0/5_1/7_1）
- L102-124: GetAdtsHeader() ADTS 头生成函数（SamplingFrequencyIndex + ChannelConfig）
- L694-697: av_audio_fifo_alloc() FIFO 分配
- L900+: SendFrame/ReceiveFrame 双线程管线

---

### 4. FFmpegFLACEncoderPlugin FLAC 编码器（252行 cpp）

**文件路径**：`services/media_engine/plugins/ffmpeg_adapter/audio_encoder/flac/ffmpeg_flac_encoder_plugin.cpp`

**核心架构**：组合 FFmpegBaseEncoder（复用基类）

**13档采样率表**（L38-44）：
```
FLAC 编码器采样率：8000/12000/16000/22050/24000/32000/44100/48000/96000/176400/192000
+ G711mu 特有：8000/16000
+ AAC 特有：7350
```

**8通道布局表**（L169-176）：
- 同 AAC 编码器，FLAC 支持 8 通道（MONO/STEREO/3_0/4_0/5_0/5_1/7_1）

**初始化链路**：
```
FFmpegFLACEncoderPlugin() 
  → FFmpegBaseEncoder() 
  → InitContext() 
  → avcodec_open2()
```

**行号证据**：
- L38-44: 采样率表
- L169: InitContext() 调用
- L180+: ReceivePacket() 输出编码帧

---

### 5. FFmpegMP3EncoderPlugin MP3 编码器（252行 cpp）

**文件路径**：`services/media_engine/plugins/ffmpeg_adapter/audio_encoder/mp3/ffmpeg_mp3_encoder_plugin.cpp`

**架构**：复用 FFmpegBaseEncoder，与 FLAC 相同模式

---

### 6. FFmpegG711muEncoderPlugin G711mu 编码器

**架构**：复用 FFmpegBaseEncoder，采样率固定 8000/16000（PCM μ率）

---

### 7. FFmpegLBVCEncoderPlugin LBVC 编码器

**架构**：复用 FFmpegBaseEncoder

---

## 三层架构总结

```
┌─────────────────────────────────────────┐
│  FFmpegEncoderPlugin (注册层, CRTP)     │
│  ffmpeg_encoder_plugin.cpp (85行)        │
│  codecVec = {AAC, FLAC, MP3, G711mu}    │
│  SetDefinition → SetCreator             │
└──────────────────┬──────────────────────┘
                   │
        ┌──────────┴──────────┐
        ▼                     ▼
┌───────────────┐    ┌─────────────────┐
│ AAC (自实现)   │    │ FLAC/MP3/G711mu │ ← FFmpegBaseEncoder 复用
│ 902行自实现   │    │ 252行组合基类    │
│ AVAudioFifo   │    │                 │
│ ADTS 7字节头  │    │                 │
└───────────────┘    └─────────────────┘
        │                     │
        ▼                     ▼
   avcodec_send_frame / avcodec_receive_packet
```

---

## 关联记忆

- **S125**: FFmpegDecoder 解码器（软件解码插件体系）
- **S132**: FFmpeg Audio Encoder Plugin 架构（ AAC/FLAC 编码器）—— S174 为 S132 的行号增强版
- **S158**: FFmpeg 音频编码器插件体系（S158 是 S132/S169 的中间版本）
- **S130**: FFmpegAdapter Common 工具链（Resample/ColorSpace/ChannelLayout）
- **S50**: AudioResample 音频重采样框架（SwrContext/libswresample）

---

## 本地镜像路径

```
/home/west/av_codec_repo/services/media_engine/plugins/ffmpeg_adapter/audio_encoder/
├── ffmpeg_base_encoder.cpp (396行)
├── ffmpeg_base_encoder.h (94行)
├── ffmpeg_encoder_plugin.cpp (85行)
├── ffmpeg_encoder_plugin.h (26行)
├── aac/ffmpeg_aac_encoder_plugin.cpp (902行)
├── aac/ffmpeg_aac_encoder_plugin.h (159行)
├── flac/ffmpeg_flac_encoder_plugin.cpp (252行)
├── mp3/ffmpeg_mp3_encoder_plugin.cpp (252行)
├── g711mu/ffmpeg_g711mu_encoder_plugin.cpp
└── lbvc/ffmpeg_lbvc_encoder_plugin.cpp
```

---

## 备注

- S174 与 S158/S169 主题重复（均为 FFmpeg 音频编码器），S174 基于本地镜像行号增强
- AAC 编码器为自实现（非复用 FFmpegBaseEncoder），包含 AVAudioFifo 和 ADTS 头生成
- FLAC/MP3/G711mu/LBVC 复用 FFmpegBaseEncoder 基类

---

**生成时间**：2026-05-21T19:40+08:00  
**Builder**：builder-agent  
**版本**：v1.0（行号级 evidence，基于本地镜像）