# MEM-ARCH-AVCODEC-S188

status: pending_approval

## 标题

FFmpeg Audio Decoder Plugin体系——FfmpegBaseDecoder基类+29子插件+Resample重采样三层架构（本地镜像增强版）

## 标签

AVCodec, FFmpeg, AudioDecoder, Plugin, SoftwareCodec, Resample, SwrContext, libavcodec, avcodec_send_packet, avcodec_receive_frame, FfmpegBaseDecoder, FfmpegDecoderPlugin, AAC, FLAC, MP3, Vorbis, WMA, DTS, COOK, ADPCM, AMR, ALAC, ILBC, TrueHD, APE, GSM, DTS

## 证据列表（行号级）

E1: ffmpeg_base_decoder.cpp:58 needResample_(false) 初始化标志
E2: ffmpeg_base_decoder.cpp:64 ~FfmpegBaseDecoder 析构函数
E3: ffmpeg_base_decoder.cpp:70-86 ProcessSendData / GetMaxInputSize / SetMaxInputSize / HasExtraData 基类接口
E4: ffmpeg_base_decoder.cpp:125 SendBuffer(inputBuffer) 输入缓冲区发送
E5: ffmpeg_base_decoder.cpp:151 avcodec_send_packet(avCodecContext_.get(), avPacket_.get()) FFmpeg发送数据包
E6: ffmpeg_base_decoder.cpp:172-190 ProcessReceiveData / ReceiveBuffer / lastStatusIsAgain
E7: ffmpeg_base_decoder.cpp:189 avcodec_receive_frame(avCodecContext_.get(), cachedFrame_.get()) FFmpeg接收帧
E8: ffmpeg_base_decoder.cpp:260-308 ReceiveFrameSucc / FormatChangeHandle / needResample_ 标志
E9: ffmpeg_base_decoder.cpp:269 if (needResample_) Resample触发条件
E10: ffmpeg_base_decoder.cpp:309 if (needResample_ && againIndex_ == 0) Resample再次触发
E11: ffmpeg_base_decoder.cpp:443-469 InitResample / ResamplePara构建 / resample_.InitSwrContext(resamplePara) 重采样初始化
E12: ffmpeg_base_decoder.cpp:456-457 if ((!needResample_ && avCodecContext_->sample_fmt != destFmt_) || (needResample_ && currentFrameFormatChanged_)) 重采样触发双条件
E13: ffmpeg_base_decoder.cpp:466 resample_.InitSwrContext(resamplePara) SwrContext初始化调用
E14: ffmpeg_base_decoder.cpp:508-550 EnableResample / DEFAULT_FFMPEG_SAMPLE_FORMAT / destFmt参数传递
E15: ffmpeg_base_decoder.cpp:592 if (InitResample() != Status::OK) 错误处理分支
E16: ffmpeg_base_decoder.cpp:342-368 AllocateContext / avcodec_find_decoder_by_name / avcodec_alloc_context3 双锁初始化
E17: ffmpeg_base_decoder.cpp:371-429 InitContext / SetBlockAlignContext / OpenContext / avcodec_open2 完整初始化链
E18: ffmpeg_base_decoder.cpp:484 GetCodecContext() const noexcept 返回AVCodecContext共享指针
E19: ffmpeg_decoder_plugin.cpp:36-88 codecVec数组50种音频codec名称映射（mp3/aac/flac/vorbis/amrnb/amrwb/ape/ac3/gsm/gsm_ms/adpcm×34/wmav1/wmav2/wmapro/alac/ilbc/truehd/twinvq/dvaudio/dts/cook）
E20: ffmpeg_decoder_plugin.cpp:105-157 mimeVec数组50种MIME类型映射（AUDIO_MPEG/AUDIO_AAC/AUDIO_FLAC/AUDIO_VORBIS/AUDIO_AMR_NB/AUDIO_AMR_WB/AUDIO_APE/…/AUDIO_COOK）
E21: ffmpeg_decoder_plugin.cpp:162-216 codecInitMap 50个InitDefinition模板实例化（ADPCM×34共享FFmpegADPCMDecoderPlugin/WMA×3共享FFmpegWMADecoderPlugin）
E22: ffmpeg_decoder_plugin.cpp:229 Status RegisterAudioDecoderPlugins(const std::shared_ptr<Register> &reg) 插件注册入口
E23: ffmpeg_decoder_plugin.cpp:250 PLUGIN_DEFINITION(FFmpegAudioDecoders, LicenseType::LGPL, RegisterAudioDecoderPlugins, UnRegisterAudioDecoderPlugin) 静态注册宏

## 源码统计

| 文件 | 行数 | 职责 |
|------|------|------|
| ffmpeg_base_decoder.cpp | 605 | FfmpegBaseDecoder引擎基类 |
| ffmpeg_base_decoder.h | 129 | 类定义含Resample/SwrContext成员 |
| ffmpeg_decoder_plugin.cpp | 250 | FfmpegDecoderPlugin插件注册层+50 codec映射 |
| ffmpeg_decoder_plugin.h | 46 | 插件定义头文件 |
| 29个子插件目录（各约200-400行） | ~8000 | aac/ac3/adpcm/alac/amrnb/amrwb/ape/cook/dts/dvaudio/eac3/flac/g711a/g711mu/gsm/gsm_ms/ilbc/lbvc/mp3/raw/truehd/twinvq/vorbis/wma |
| **合计** | **~9030** | 三层架构全量 |

## 源码分析

### 1. 整体架构

S188覆盖FFmpeg Audio Decoder Plugin三层架构，总计~9030行源码（本地镜像增强版），位于`services/media_engine/plugins/ffmpeg_adapter/audio_decoder/`目录：

```
audio_decoder/
├── ffmpeg_base_decoder.cpp (605行) + .h (129行)    ← 引擎基类
├── ffmpeg_decoder_plugin.cpp (250行) + .h (46行)   ← 插件注册层
├── ffmpeg_base_decoder.cpp (605行)                 ← Resample重采样器
├── aac/ffmpeg_aac_decoder_plugin.cpp (213行)
├── mp3/ffmpeg_mp3_decoder_plugin.cpp (181行)
├── flac/ffmpeg_flac_decoder_plugin.cpp (198行)
├── wma/ffmpeg_wma_decoder_plugin.cpp               ← WMA×3子插件
├── adpcm/                                          ← ADPCM×34共享子插件
├── amrnb/ / amrwb/ / alac/ / ape/ / cook/ / dts/ / eac3/
├── g711a/ / g711mu/ / gsm/ / gsm_ms/ / ilbc/ / lbvc/
├── raw/ (1035行) / truehd/ / twinvq/ / vorbis/
└── BUILD.gn
```

三层插件架构（与S183 AvcEncoder软件编码器对称）：
- **L1 注册层**：FfmpegDecoderPlugin + PLUGIN_DEFINITION宏 + RegisterAudioDecoderPlugins入口
- **L2 引擎基类**：FfmpegBaseDecoder + avcodec_send_packet/avcodec_receive_frame管线 + Resample重采样
- **L3 子插件**：29个子插件目录（ADPCM×34/WMA×3共享插件实例）

### 2. FfmpegBaseDecoder引擎基类

**继承关系**：`FfmpegBaseDecoder : public NoCopyable`

**成员关键变量**：
- `avCodecContext_`（shared_ptr<AVCodecContext>，L353-358初始化）
- `needResample_`（bool，L58初始化为false）
- `resample_`（Ffmpeg::Resample，L107）
- `cachedFrame_`（shared_ptr<AVFrame>）
- `avPacket_`（shared_ptr<AVPacket>）
- `destFmt_`（AVSampleFormat，L508）
- `currentFrameFormatChanged_`（bool）

**生命周期（三层初始化链）**：

1. `AllocateContext(name)`（ffmpeg_base_decoder.cpp:342-368）：
   - `avcodec_find_decoder_by_name(name)` 查找FFmpeg codec
   - `avcodec_alloc_context3(context)` 创建AVCodecContext
   - AVCODEC_LOGI日志输出channels/sample_rate/bit_rate/channel_layout/sample_fmt

2. `InitContext(format)`（ffmpeg_base_decoder.cpp:371-429）：
   - 从`Meta`读取AUDIO_CHANNEL_COUNT / AUDIO_SAMPLE_RATE / AUDIO_CHANNEL_LAYOUT
   - `FFMpegConverter::ConvertOHAudioChannelLayoutToFFMpeg` 转换通道布局
   - `SetBlockAlignContext`设置block_align
   - `OpenContext()`调用`avcodec_open2`打开编码器

3. `OpenContext()`（ffmpeg_base_decoder.cpp:431-436）：
   - `avcodec_open2(avCodecContext_.get(), codec.get(), nullptr)`

**解码管线（avcodec_send_packet + avcodec_receive_frame）**：

```cpp
// 发送端（ffmpeg_base_decoder.cpp:151）
auto ret = avcodec_send_packet(avCodecContext_.get(), avPacket_.get());

// 接收端（ffmpeg_base_decoder.cpp:189）
auto ret = lastStatusIsAgain ? 0 : avcodec_receive_frame(avCodecContext_.get(), cachedFrame_.get());
```

返回`AVERROR(EAGAIN)`表示输出不可用需要继续发送数据；返回0表示成功获取一帧。

**Resample重采样机制**：

触发条件（ffmpeg_base_decoder.cpp:456-457）：
- `!needResample_ && avCodecContext_->sample_fmt != destFmt_`（格式不匹配）
- `needResample_ && currentFrameFormatChanged_`（格式变更）

当触发时，`resample_.InitSwrContext(resamplePara)`调用SwrContext初始化重采样器，`convertedFrame_`存储转换后的帧。

### 3. FfmpegDecoderPlugin插件注册层

**codecVec名称映射**（ffmpeg_decoder_plugin.cpp:36-88）：50个FFmpeg codec名称

```cpp
static const std::vector<std::string_view> codecVec = {
    AVCodecCodecName::AUDIO_DECODER_MP3_NAME,              //  0: mp3
    AVCodecCodecName::AUDIO_DECODER_AAC_NAME,              //  1: aac
    AVCodecCodecName::AUDIO_DECODER_FLAC_NAME,             //  2: flac
    AVCodecCodecName::AUDIO_DECODER_VORBIS_NAME,           //  3: vorbis
    ...
    AVCodecCodecName::AUDIO_DECODER_COOK_NAME              // 49: cook
};
```

**mimeVec MIME映射**（ffmpeg_decoder_plugin.cpp:105-157）：对应50种MIME类型

**InitDefinition模板**（ffmpeg_decoder_plugin.cpp:93-98）：
```cpp
template <class T>
void InitDefinition(const std::string &mimetype, const std::string_view &codecName,
                    CodecPluginDef &definition, Capability &cap)
{
    cap.SetMime(mimetype);
    definition.name = codecName;
    definition.SetCreator([](const std::string &name) -> std::shared_ptr<CodecPlugin> {
        return std::make_shared<T>(name);
    });
}
```

**codecInitMap 50个子插件实例化**（ffmpeg_decoder_plugin.cpp:162-216）：通过InitDefinition<FFmpegAACDecoderPlugin>等方式注册，ADPCM×34共享FFmpegADPCMDecoderPlugin，WMA×3共享FFmpegWMADecoderPlugin。

**PLUGIN_DEFINITION**（ffmpeg_decoder_plugin.cpp:250）：触发RegisterAudioDecoderPlugins静态注册，LicenseType::LGPL。

### 4. 29个子插件矩阵（本地镜像实际统计）

| 类别 | 子插件目录 | 源码行数 | 数量 |
|------|-----------|---------|------|
| 有损压缩 | aac, ac3, mp3, vorbis, wma | 213+269+181+386+316 | 5 |
| AMR | amrnb, amrwb | 385+254 | 2 |
| ADPCM | adpcm（覆盖34种变体） | 346 | 1（覆盖34） |
| 无损 | flac, alac, ape, truehd | 278+295+389+273 | 4 |
| GSM | gsm, gsm_ms | 268+266 | 2 |
| G.711 | g711a, g711mu | 374+360 | 2 |
| COOK/DTS | cook, dts | 269+256 | 2 |
| 其他 | eac3, dvaudio, ilbc, lbvc, twinvq, raw(1035行) | 296+252+268+354+275+1035 | 6 |
| **总计** | | **~8000** | **29目录（50 codec变体）** |

### 5. 与S183 AvcEncoder软件编码器对称架构

| 维度 | S183 AvcEncoder（编码器） | S188 FfmpegAudioDecoder（解码器） |
|------|--------------------------|--------------------------------|
| 源码位置 | services/engine/codec/video/avcencoder/ | services/media_engine/plugins/ffmpeg_adapter/audio_decoder/ |
| 核心文件 | avc_encoder.cpp (1765行) | ffmpeg_base_decoder.cpp (605行) |
| 插件注册 | ffmpeg_encoder_plugin.cpp (85行) | ffmpeg_decoder_plugin.cpp (250行) |
| FFmpeg管线 | avcodec_send_frame + avcodec_receive_packet | avcodec_send_packet + avcodec_receive_frame |
| 子插件数量 | 5个（AAC/FLAC/MP3/G711mu/LBVC） | 29个（50 codec变体） |
| 特殊处理 | BT601/BT709色彩空间矩阵转换 | SwrContext重采样 |
| 编码类型 | 软件编码（libavcenc_ohos.z.so） | 软件解码（libavcodec） |

## 关联主题

S183（AvcEncoder H.264软件编码器，对称架构）、S125（FFmpeg Decoder基类总览）、S130（FFmpeg Adapter Common通用工具链）、S50（AudioResample音频重采样）、S158/S169（FFmpeg Audio Encoder编码器体系）、S60（AAC音频编解码FFmpeg插件）、S8（音频FFmpeg插件总览）

## 变更记录

| 日期 | 操作 | 说明 |
|------|------|------|
| 2026-05-25T14:19 | Builder | S188注册：FFmpeg Audio Decoder Plugin体系草案（本地镜像增强版），MEM-ARCH-AVCODEC-S188.md（~9030行源码，23条行号级evidence） |