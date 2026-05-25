# MEM-ARCH-AVCODEC-S184

status: draft

## 标题

FFmpeg Audio Decoder Plugin 体系——FfmpegBaseDecoder 基类 + 29 子插件 + Resample 重采样三层架构

## 标签

AVCodec, FFmpeg, AudioDecoder, Plugin, SoftwareCodec, Resample, SwrContext, libavcodec, avcodec_send_packet, avcodec_receive_frame, FfmpegBaseDecoder, FfmpegDecoderPlugin, AAC, FLAC, MP3, Vorbis, WMA, DTS, COOK, ADPCM, AMR, ALAC, ILBC, TrueHD, APE, GSM, DTS

## 证据列表（行号级）

E1: ffmpeg_base_decoder.cpp:45 FfmpegBaseDecoder 构造函数
E2: ffmpeg_base_decoder.cpp:64 ~FfmpegBaseDecoder 析构函数
E3: ffmpeg_base_decoder.cpp:70-86 ProcessSendData / GetMaxInputSize / SetMaxInputSize / HasExtraData
E4: ffmpeg_base_decoder.cpp:92-102 SetSkipSamplesInfo 跳过样本标志
E5: ffmpeg_base_decoder.cpp:125 SendBuffer(inputBuffer) 输入缓冲区发送
E6: ffmpeg_base_decoder.cpp:151 avcodec_send_packet(avCodecContext_.get(), avPacket_.get()) FFmpeg 发送
E7: ffmpeg_base_decoder.cpp:172-190 ProcessReceiveData / ReceiveBuffer / lastStatusIsAgain
E8: ffmpeg_base_decoder.cpp:189 avcodec_receive_frame(avCodecContext_.get(), cachedFrame_.get()) FFmpeg 接收
E9: ffmpeg_base_decoder.cpp:225-234 ConvertPlanarFrame / CheckFormatChange 格式变更检测
E10: ffmpeg_base_decoder.cpp:260-308 ReceiveFrameSucc / FormatChangeHandle / needResample_ 标志
E11: ffmpeg_base_decoder.cpp:269 if (needResample_) Resample 触发条件
E12: ffmpeg_base_decoder.cpp:309 if (needResample_ && againIndex_ == 0) Resample 再次触发
E13: ffmpeg_base_decoder.cpp:443-469 InitResample / ResamplePara 构建 / resample_.InitSwrContext(resamplePara)
E14: ffmpeg_base_decoder.cpp:456-457 if ((!needResample_ && avCodecContext_->sample_fmt != destFmt_) || (needResample_ && currentFrameFormatChanged_)) Resample 触发条件
E15: ffmpeg_base_decoder.cpp:466 resample_.InitSwrContext(resamplePara) 重采样初始化
E16: ffmpeg_base_decoder.cpp:508-550 EnableResample / DEFAULT_FFMPEG_SAMPLE_FORMAT / destFmt 参数
E17: ffmpeg_base_decoder.cpp:592 if (InitResample() != Status::OK) 错误处理
E18: ffmpeg_base_decoder.cpp:342-368 AllocateContext / avcodec_find_decoder_by_name / avcodec_alloc_context3 双锁初始化
E19: ffmpeg_base_decoder.cpp:371-429 InitContext / SetBlockAlignContext / OpenContext / avcodec_open2 完整初始化链
E20: ffmpeg_decoder_plugin.cpp:37-88 codecVec 数组 50 种音频 codec 名称映射（mp3/aac/flac/vorbis/amrnb/amrwb/ape/ac3/gsm/gsm_ms/adpcm×34/wmav1/wmav2/wmapro/alac/ilbc/truehd/twinvq/dvaudio/dts/cook）
E21: ffmpeg_decoder_plugin.cpp:105-157 mimeVec 数组 50 种 MIME 类型映射（AUDIO_MPEG/AUDIO_AAC/AUDIO_FLAC/AUDIO_VORBIS/AUDIO_AMR_NB/AUDIO_AMR_WB/AUDIO_APE/…/AUDIO_COOK）
E22: ffmpeg_decoder_plugin.cpp:163-216 InitDefinition 模板实例化 50 个子插件（mp3×/aac/flac/vorbis/amrnb/amrwb/ape/ac3/gsm/gsm_ms/adpcm×34/alac/ilbc/truehd/twinvq/dvaudio/dts/cook）
E23: ffmpeg_decoder_plugin.cpp:229-250 RegisterAudioDecoderPlugins / PLUGIN_DEFINITION(FFmpegAudioDecoders) 插件注册入口

## 源码分析

### 1. 整体架构

S184 覆盖 FFmpeg Audio Decoder Plugin 三层架构，总计 984 行核心源码（不含 29 个子插件目录），位于 `services/media_engine/plugins/ffmpeg_adapter/audio_decoder/` 目录：

| 文件 | 行数 | 职责 |
|------|------|------|
| ffmpeg_base_decoder.cpp | 605 | FfmpegBaseDecoder 引擎基类 |
| ffmpeg_base_decoder.h | 129 | 类定义 |
| ffmpeg_decoder_plugin.cpp | 250 | FfmpegDecoderPlugin 插件注册层 + 50 个 codec 映射 |
| 子插件目录（29 个） | 各 100-500 | aac/ac3/adpcm/alac/amrnb/amrwb/ape/cook/dts/dvaudio/eac3/flac/g711a/g711mu/gsm/gsm_ms/ilbc/lbvc/mp3/raw/truehd/twinvq/vorbis/wma 等 |

S125（FFmpeg 软件解码器基类）是本草案的前身，S183（AvcEncoder 软件编码器）与本草案对称，构成 FFmpeg 软件编解码器全矩阵。

### 2. FfmpegBaseDecoder 引擎基类

`FfmpegBaseDecoder` 继承 `NoCopyable`，是所有 FFmpeg 音频解码器子插件的公共基类。

**生命周期（三层初始化链）**：

1. `AllocateContext(name)`（ffmpeg_base_decoder.cpp:342-368）：通过 `avcodec_find_decoder_by_name(name)` 查找 FFmpeg codec，创建 `AVCodecContext`。
2. `InitContext(format)`（ffmpeg_base_decoder.cpp:371-429）：从 `Meta` 读取 AUDIO_CHANNEL_COUNT / AUDIO_SAMPLE_RATE / AUDIO_CHANNEL_LAYOUT，填充 `AVCodecContext`，通过 `FFMpegConverter::ConvertOHAudioChannelLayoutToFFMpeg` 转换通道布局。
3. `OpenContext()`（ffmpeg_base_decoder.cpp:431-436）：调用 `avcodec_open2` 打开编码器。

**解码管线（avcodec_send_packet + avcodec_receive_frame）**：

```cpp
// 发送端（ffmpeg_base_decoder.cpp:151）
auto ret = avcodec_send_packet(avCodecContext_.get(), avPacket_.get());

// 接收端（ffmpeg_base_decoder.cpp:189）
auto ret = lastStatusIsAgain ? 0 : avcodec_receive_frame(avCodecContext_.get(), cachedFrame_.get());
```

返回 `AVERROR(EAGAIN)` 表示输出不可用，需要继续发送数据；返回 0 表示成功获取一帧。

**Resample 重采样机制**：

`ResamplePara` 结构体传递采样参数，`resample_.InitSwrContext(resamplePara)` 调用 `SwrContext` 初始化重采样器。

触发条件（ffmpeg_base_decoder.cpp:456-457）：
- `!needResample_ && avCodecContext_->sample_fmt != destFmt_`（格式不匹配）
- `needResample_ && currentFrameFormatChanged_`（格式变更）

`needResample_` 标志由 `CheckFormatChange()` 检测，格式变更时需要重新初始化 SwrContext。

### 3. FfmpegDecoderPlugin 插件注册层

`FfmpegDecoderPlugin` 是 CRTP 模板实例化层，通过 `InitDefinition<T>` 模板函数为每个子插件填充 Capability 和 Creator。

**codecVec 名称映射**（ffmpeg_decoder_plugin.cpp:37-88）：50 个 FFmpeg codec 名称，如 `"mp3"/"aac"/"flac"/"vorbis"/"amrnb"/"wmapro"/"dts"/"cook"` 等。

**mimeVec MIME 映射**（ffmpeg_decoder_plugin.cpp:105-157）：对应 50 种 MIME 类型，如 `AUDIO_MPEG/AUDIO_AAC/AUDIO_FLAC/AUDIO_VORBIS/AUDIO_COOK` 等。

**InitDefinition 模板实例化**（ffmpeg_decoder_plugin.cpp:163-216）：50 个子插件通过 `InitDefinition<FFmpegAACDecoderPlugin>` 等方式注册。注意 `ADPCM` 共享同一子插件（`FFmpegADPCMDecoderPlugin`），覆盖了 34 种 ADPCM 变体。

**PLUGIN_DEFINITION**（ffmpeg_decoder_plugin.cpp:250）触发 `RegisterAudioDecoderPlugins` 静态注册。

### 4. 29 个子插件矩阵

| 类别 | 子插件 | 数量 |
|------|--------|------|
| 有损压缩 | AAC, AC3, MP3, Vorbis, WMAV1/V2/WMAPRO, DTS, COOK | 8 |
| AMR | AMR-NB, AMR-WB | 2 |
| ADPCM | ADPCM（34变体共享一个插件） | 1（覆盖34） |
| 无损 | FLAC, ALAC, APE, TrueHD, ILBC | 5 |
| GSM | GSM, GSM-MS | 2 |
| 其它 | DVAudio, TwinVQ | 2 |
| 总计 | | 50 codec 变体 |

### 5. 与 S125（S130/S50）关联对比

- S125：FFmpeg Decoder 基类总览（含 AudioFFMpegDecoderPlugin 注册）
- S130：FFmpeg Adapter Common 工具链（FFMpegConverter::ConvertOHAudioChannelLayoutToFFMpeg）
- S50：AudioResample SwrContext 封装（AudioResample needResample_ 触发）
- S158/S169：FFmpeg Audio Encoder 编码器体系（与本草案对称）

## 关联主题

S125（FFmpeg 软件解码器基类总览）、S130（FFmpeg Adapter Common 通用工具链）、S50（AudioResample 音频重采样）、S158/S169（FFmpeg Audio Encoder 编码器体系，对称架构）、S60（AAC 音频编解码 FFmpeg 插件）、S8（音频 FFmpeg 插件总览）