# MEM-ARCH-AVCODEC-S145: FFmpeg Adapter 通用工具链与编解码插件体系

**状态**: draft  
**生成时间**: 2026-05-15T04:25+08:00  
**Builder**: builder-agent  
**来源**: 本地镜像 /home/west/av_codec_repo

---

## 主题

FFmpeg Adapter 通用工具链与编解码插件体系——common/ 四组件（ffmpeg_utils/ffmpeg_convert/ffmpeg_converter/stream_parser_manager/hdi_codec）与 audio_encoder/ 五子插件（AAC/FLAC/MP3/G711mu/LBVC）+ audio_decoder/ 17+ 子插件矩阵。

---

## 摘要

FFmpeg Adapter 是 AVCodec 对 FFmpeg libavcodec/libavutil/libavformat 的统一封装层，分为 common 通用工具链和 audio 两大分支。common 提供色彩空间/通道布局/NALU/Resample/Scale 转换工具；audio_encoder 提供基于 FFmpeg 的音频编码器基类和 5 个子插件；audio_decoder 提供音频解码基类和 17+ 子插件，涵盖 AAC/AC3/MP3/FLAC/Vorbis/WMA/DTS 等所有主流音频格式。

---

## 一、FFmpeg Adapter 目录结构

```
services/media_engine/plugins/ffmpeg_adapter/
├── common/                    # 通用工具链
│   ├── ffmpeg_utils.cpp      # 505行  - MIME映射/色彩空间/通道布局工具
│   ├── ffmpeg_utils.h        # 76行
│   ├── ffmpeg_convert.cpp    # 247行  - Resample/Scale/SwrContext封装
│   ├── ffmpeg_convert.h      # 98行
│   ├── ffmpeg_converter.cpp  # 201行  - 格式转换工具
│   ├── ffmpeg_converter.h    # 53行
│   ├── stream_parser_manager.cpp  # 227行 - NALU起始码查找/HEVC流解析
│   ├── stream_parser_manager.h    # 73行
│   ├── hdi_codec.cpp         # 365行  - HDI编解码器统一封装层
│   ├── hdi_codec.h           # 140行
│   └── BUILD.gn
├── audio_encoder/            # FFmpeg音频编码器
│   ├── ffmpeg_base_encoder.cpp   # 396行  - 编码器引擎基类
│   ├── ffmpeg_base_encoder.h     # 94行
│   ├── ffmpeg_encoder_plugin.cpp # 85行   - 插件注册层
│   ├── ffmpeg_encoder_plugin.h   # 26行
│   ├── aac/
│   │   ├── ffmpeg_aac_encoder_plugin.cpp
│   │   └── ffmpeg_aac_encoder_plugin.h
│   ├── flac/
│   ├── mp3/
│   ├── g711mu/
│   ├── lbvc/
│   └── BUILD.gn
├── audio_decoder/            # FFmpeg音频解码器（17+子插件）
│   ├── ffmpeg_base_decoder.cpp   # 605行  - 解码器引擎基类
│   ├── ffmpeg_base_decoder.h     # 129行
│   ├── ffmpeg_decoder_plugin.cpp # 250行  - 插件注册层
│   ├── ffmpeg_decoder_plugin.h  # 46行
│   ├── aac/
│   ├── ac3/
│   ├── adpcm/
│   ├── alac/
│   ├── amrnb/
│   ├── amrwb/
│   ├── ape/
│   ├── cook/
│   ├── dts/
│   ├── dvaudio/
│   ├── eac3/
│   ├── flac/
│   ├── g711a/
│   ├── g711mu/
│   ├── gsm/
│   ├── gsm_ms/
│   ├── ilbc/
│   ├── lbvc/
│   ├── mp3/
│   ├── raw/
│   ├── truehd/
│   ├── twinvq/
│   ├── vorbis/
│   ├── wma/
│   └── BUILD.gn
├── muxer/
│   └── (FFmpegMuxerPlugin封装修复器)
└── BUILD.gn
```

总计：约 1985 行 common 工具链 + audio_encoder + audio_decoder

---

## 二、common/ 通用工具链

### 2.1 ffmpeg_utils（505行cpp + 76行h）

**Evidence**: `ffmpeg_utils.cpp:1-505`, `ffmpeg_utils.h:1-76`

核心功能：
- `Mime2CodecId()`: MIME类型到FFmpeg CodecID映射（15+映射条目）
- 色彩空间相关函数：`g_toFFMPEGColorSpace`（PQ/HLG/BT2020三函数映射）
- 通道布局转换：`g_toFFMPEGChannelLayout`（18种通道布局表）
- `FindNalStartCode()`: NALU起始码查找（AnnexB 0x000001/0x00000001）
- `g_pixelFormatToFFMpegPixFmt`: 像素格式枚举映射
- `g_ffmpegPixFmtToPixelFormat`: 反向映射

### 2.2 ffmpeg_convert（247行cpp + 98行h）

**Evidence**: `ffmpeg_convert.cpp:1-247`, `ffmpeg_convert.h:1-98`

核心功能：
- `FFmpegConvert` 类封装 FFmpeg 转换器
- **Resample**（SwrContext封装）: `InitSwrContext()`/`swr_convert()`
- **Scale**（SwsContext封装）: `InitSwsContext()`/`sws_scale()`
- 输入输出格式校验：`CanConvert()` / `IsResampleNeeded()`
- `g_audioSampleFormatToBitDepth`: 音频采样格式→位深映射表（8/16/24/32/64bit）

### 2.3 ffmpeg_converter（201行cpp + 53行h）

**Evidence**: `ffmpeg_converter.cpp:1-201`, `ffmpeg_converter.h:1-53`

核心功能：
- `AudioResampleConverter`: 音频重采样转换器（组合FFmpegConvert）
- `VideoFormatConverter`: 视频格式转换器
- `ColorSpaceConverter`: 色域转换器
- 支持 FFmpeg→Native / Native→FFmpeg 双向转换

### 2.4 stream_parser_manager（227行cpp + 73行h）

**Evidence**: `stream_parser_manager.cpp:1-227`, `stream_parser_manager.h:1-73`

核心功能：
- `StreamParserManager` 类管理所有流解析器
- `FindNalStartCode()`: NALU起始码定位（支持 AVC AnnexB / HEVC AnnexB 双格式）
- `HevcParseFormat()`: HEVC流解析（VPS/SPS/PPS提取）
- `PacketConvertToBufferInfo()`: 码流包→BufferInfo转换
- `ConvertPacketToAnnexb()`: AVCC→AnnexB转换（用于解码器输入标准化）
- `ParseExtraData()`: 解析编解码器ExtraData（H.264 avcC / HEVC hvcC）
- 支持 dlopen 动态加载 HEVC 插件

### 2.5 hdi_codec（365行cpp + 140行h）

**Evidence**: `hdi_codec.cpp:1-365`, `hdi_codec.h:1-140`

核心功能：
- `HdiCodec` 类: FFmpeg 与 HDI 编解码器的统一封装层
- `CreateCodec()`: 工厂创建接口
- `InitCodec()`: 初始化（设置 codec context）
- `DecodeFrame()` / `EncodeFrame()`: 编解码帧接口
- `Flush()`: 刷新codec状态
- 与 libavcodec AVCodecContext 直接绑定

---

## 三、audio_encoder/ FFmpeg 音频编码器

### 3.1 FFmpegBaseEncoder（396行cpp + 94行h）

**Evidence**: `audio_encoder/ffmpeg_base_encoder.cpp:1-396`, `audio_encoder/ffmpeg_base_encoder.h:1-94`

三层调用链：
```
FFmpegBaseEncoder（基类）
  └─> AAC/FLAC/MP3/G711mu/LBVC 子编码器插件
        └─> FFmpeg libavcodec（avcodec_send_frame/receive_packet）
```

核心接口：
- `InitContext()`: 初始化 FFmpeg AVCodecContext
- `EncodeFrame()`: avcodec_send_frame + avcodec_receive_packet 管线
- `EncodeImpl()`: 子类实现编码逻辑
- `SendEos()`: 发送EOS标志
- 支持 ADTS 头注入（AAC编码器）

### 3.2 FFmpegEncoderPlugin（85行cpp + 26行h）

**Evidence**: `audio_encoder/ffmpeg_encoder_plugin.cpp:1-85`, `audio_encoder/ffmpeg_encoder_plugin.h:1-26`

- `FFmpegEncoderPlugin`: CRTP模板插件注册层
- 继承 `AudioBaseCodec` 基类
- `AudioEncoderCreateByMime()` 工厂函数

### 3.3 AAC 编码器（ffmpeg_aac_encoder_plugin.cpp, 902行）

**Evidence**: `audio_encoder/aac/ffmpeg_aac_encoder_plugin.cpp:1-902`

- **AVAudioFifo 环形缓冲区**: L694-697 `av_audio_fifo_alloc(fmt, channels, frameSize)` 分配（L80 fifo_成员, L392/L445/L748/L818/L819/L826/L867 读写操作）
- **AudioResample 集成**: L530/L561-562 `needResample_` + `ResamplePara resamplePara` + `std::make_shared<Ffmpeg::Resample>()` 重采样（L571）
- **ADTS 7字节头注入**: L37 `constexpr ADTS_HEADER_SIZE = 7`，L102-124 `GetAdtsHeader()` 函数（L113-119 填充 0xFF/0xF1 + profile/freqIdx/chanCfg/frameLength）
- **采样率表**: L15-35 `sampleFreqMap`（13档采样率 8k-192k）
- **码率控制**: L100-121 bitrate 校验（FLAC_MIN_BIT_RATE/FLAC_MAX_BIT_RATE 不适用于 AAC）
- 支持 CBR/VBR 两种码率模式

### 3.4 FLAC 编码器（ffmpeg_flac_encoder_plugin.cpp, 252行）

**Evidence**: `audio_encoder/flac/ffmpeg_flac_encoder_plugin.cpp:1-252`

- 组合 FFmpegBaseEncoder 基类（L169 `basePlugin->InitContext(parameter)`）
- FLAC元数据块写入（STREAMINFO/MD5/SEEKTABLE/APPLICATION）
- **采样率表**: L38-40 `FLAC_ENCODER_SAMPLE_RATE_TABLE[]`（8000-192000Hz, 11档）
- **通道布局表**: L41-44 `FLAC_CHANNEL_LAYOUT_TABLE[]`（mono/stereo/surround/quad/5.1/7.1）
- **码率范围**: L32-33 `FLAC_MIN_BIT_RATE=32000 / FLAC_MAX_BIT_RATE=1536000`
- 无需重采样（FLAC固定支持 8-192kHz）

### 3.5 其他编码器子插件

- **MP3**: 复用 FFmpeg libmp3lame
- **G711mu**: G.711 μ-law 语音编码（无FFmpeg依赖，自实现）
- **LBVC**: 未知格式编码器

---

## 四、audio_decoder/ FFmpeg 音频解码器（17+子插件）

### 4.1 FFmpegBaseDecoder（605行cpp + 129行h）

**Evidence**: `audio_decoder/ffmpeg_base_decoder.cpp:1-605`, `audio_decoder/ffmpeg_base_decoder.h:1-129`

三层调用链：
```
FFmpegBaseDecoder（基类）
  └─> 17+ 子解码器插件（aac/ac3/mp3/flac/vorbis/wma/dts/...）
        └─> FFmpeg libavcodec（avcodec_send_packet/receive_frame）
```

核心接口：
- `DecodeFrame()`: avcodec_send_packet + avcodec_receive_frame 管线
- `InitCodecContext()`: MIME→CodecID映射 + AVCodecContext初始化
- `FlushCodec()`: 解码器刷新
- 双TaskThread驱动（由 AudioCodecWorker 提供）

### 4.2 FFmpegDecoderPlugin（250行cpp + 46行h）

**Evidence**: `audio_decoder/ffmpeg_decoder_plugin.cpp:1-250`, `audio_decoder/ffmpeg_decoder_plugin.h:1-46`

- `FFmpegDecoderPlugin`: 统一插件代理
- `AudioDecoderCreateByMime()` 工厂函数
- 支持 `Resample` 音频重采样（SwrContext）
- 子插件列表（17+）：
  | 格式 | 插件目录 | 备注 |
  |------|----------|------|
  | AAC | aac/ | 17种ADTS采样率，8通道 |
  | AC3 | ac3/ | Dolby Digital |
  | MP3 | mp3/ | libmp3lame |
  | FLAC | flac/ | Free Lossless |
  | Vorbis | vorbis/ | Ogg Vorbis |
  | WMA | wma/ | Windows Media Audio |
  | DTS | dts/ | Digital Theatre System |
  | COOK | cook/ | RealAudio |
  | APE | ape/ | Monkey's Audio |
  | AMR-NB | amrnb/ | 8kHz窄带 |
  | AMR-WB | amrwb/ | 16kHz宽带 |
  | GSM | gsm/gsm_ms/ | 移动语音 |
  | ALAC | alac/ | Apple Lossless |
  | ILBC | ilbc/ | Internet Low Bit Rate |
  | TrueHD | truehd/ | Dolby TrueHD |
  | TwinVQ | twinvq/ | NTT TwinVQ |
  | G.711 | g711a/g711mu/ | 语音编码 |
  | LBVC | lbvc/ | 未知格式 |
  | ADPCM | adpcm/ | 自适应差分PCM |
  | DV Audio | dvaudio/ | DV内嵌音频 |
  | EAC3 | eac3/ | Dolby Digital Plus |

### 4.3 Resample 集成

**Evidence**: `audio_decoder/` 内 `Resample` 相关代码

- `FFmpegConvert` 提供 SwrContext 封装
- `needResample_` 标志：自动判断输入采样率/通道布局是否匹配目标
- 支持：
  - 采样率转换（32kHz/44.1kHz→48kHz）
  - 通道布局转换（立体声→单声道/环绕声）
  - 格式转换（planar↔packed）

---

## 五、muxer/ FFmpeg 封装修复器插件体系

### 5.1 FFmpegMuxerPlugin（1414行cpp + 126行h）

**Evidence**: `muxer/ffmpeg_muxer_plugin.cpp:1-1414`, `muxer/ffmpeg_muxer_plugin.h:1-126`

- `FFmpegMuxerPlugin`: 基于 libavformat 的封装修复器插件
- 支持 9 种格式: MP4/M4A/MP3/WAV/AAC/FLAC/OGG/FLV/AMR
- `AVFMT_FLAG_CUSTOM_IO`: 自定义 AVIOContext（用于 FileSink/DataSink 抽象）
- `WriteSample()` 三分支: H.264 / HEVC / FLAC / 普通样本

### 5.2 FFmpegMuxerRegister（377行cpp）

**Evidence**: `muxer/ffmpeg_muxer_register.cpp:1-377`

- `FFmpegMuxerRegister`: CRTP 模板插件注册表
- `CreateMuxerPlugin()`: MIME → 具体 MuxerPlugin 工厂分发

### 5.3 FFmpegFlvMuxerPlugin（586行cpp + 85行h）

**Evidence**: `muxer/flv_muxer/ffmpeg_flv_muxer_plugin.cpp:1-586`, `muxer/flv_muxer/ffmpeg_flv_muxer_plugin.h:1-85`

- FLV 容器专属封装修复器（相对于 MP4 的 FLV 特有格式）
- 支持 H.264 + AAC 封入 FLV

### 5.4 MPEG4MuxerPlugin（574行cpp）

**Evidence**: `muxer/mpeg4_muxer/mpeg4_muxer_plugin.cpp:1-574`

- 原生 MP4/MOV ISOBMFF 封装修复器（非 FFmpeg）
- `BasicBox` 树形层级: ftyp/moov/trak/mdia/minf

### 5.5 MP4 Box 写时构建体系

**Evidence**: `muxer/mpeg4_muxer/basic_box.cpp:1-1256`, `muxer/mpeg4_muxer/basic_box.h:1-575`

- `BasicBox`: ISOBMFF 原子结构基类（L575 h 定义）
- `FullBox`: 扩展 version+flags（L575）
- `BoxParser`: MoovBoxGenerate → MvhdBoxGenerate / TrakBoxGenerate / UdtaBox（L916-78 h）

### 5.6 Track 轨封装

**Evidence**: `muxer/mpeg4_muxer/video_track.cpp:1-753`, `muxer/mpeg4_muxer/audio_track.cpp:1-263`, `muxer/mpeg4_muxer/basic_track.cpp:1-282`

- `VideoTrack`: AvccBox(H.264)/HvccBox(HEVC)/ColrBox 视频轨封装（L753）
- `AudioTrack`: AAC/FLAC/PCM 音频轨封装（L263）
- `BasicTrack`: Track 基类（L282）
- `CoverTrack`: 封面轨（L93）
- `TimedMetaTrack`: 时间元数据轨（L49 h）

### 5.7 Parser 封装

**Evidence**: `muxer/mpeg4_muxer/avc_parser.cpp:1-211`, `muxer/mpeg4_muxer/hevc_parser.cpp:1-186`

- `AvcParser`: H.264 NALU → AVCC 格式封装（L211）
- `HevcParser`: HEVC NALU → HVCC 格式封装（L186）
- `VideoParser`: 视频码流解析基类（L121 h）

---

## 六、与 S125/S130 关联

| 对比维度 | S125 (FFmpegDecoder) | S130 (FFmpegAdapterCommon) | S145 (本记忆) |
|----------|----------------------|---------------------------|--------------|
| 层级 | 解码器引擎层 | 通用工具层 | 统一封装层 |
| 范围 | audio_decoder | common | common + audio_encoder + audio_decoder |
| 核心 | avcodec_send_packet/receive_frame | Resample/Scale/NALU转换 | 完整编解码矩阵 |
| 关系 | 子类 | 工具 | 父层（包含S130工具） |

**依赖关系**:
- S145 common/ → S130（共享 ffmpeg_convert/stream_parser_manager/ffmpeg_utils）
- S145 audio_encoder → S145 common/（依赖 common 工具链）
- S145 audio_decoder → S145 common/（依赖 common 工具链）
- S145 audio_encoder ←→ S125 audio_decoder（编解码对称）

---

## 七、Evidence 汇总

| 文件 | 行号 | 关键内容 |
|------|------|----------|
| `ffmpeg_utils.cpp` | 1-505 | MIME映射/色彩空间/通道布局/NALU |
| `ffmpeg_utils.h` | 1-76 | 函数声明 |
| `ffmpeg_convert.cpp` | 1-247 | Resample/Scale SwrContext封装 |
| `ffmpeg_convert.h` | 1-98 | FFmpegConvert类定义 |
| `ffmpeg_converter.cpp` | 1-201 | 格式转换器 |
| `ffmpeg_converter.h` | 1-53 | 转换器类声明 |
| `stream_parser_manager.cpp` | 1-227 | NALU起始码/HEVC解析/AVCC→AnnexB |
| `stream_parser_manager.h` | 1-73 | StreamParserManager类定义 |
| `hdi_codec.cpp` | 1-365 | HDI编解码器统一封装层 |
| `hdi_codec.h` | 1-140 | HdiCodec类定义 |
| `audio_encoder/ffmpeg_base_encoder.cpp` | 1-396 | 音频编码器基类 |
| `audio_encoder/ffmpeg_base_encoder.h` | 1-94 | FFmpegBaseEncoder类定义 |
| `audio_encoder/ffmpeg_encoder_plugin.cpp` | 1-85 | 插件注册层 |
| `audio_encoder/aac/ffmpeg_aac_encoder_plugin.cpp` | 902 | AAC编码器：ADTS7字节头(L37/L102-124)、av_audio_fifo_alloc(L694)、Resample(L571) |
| `audio_encoder/flac/ffmpeg_flac_encoder_plugin.cpp` | 252 | FLAC编码器：采样率表(L38-40)、通道布局表(L41-44)、InitContext(L169) |
| `audio_decoder/ffmpeg_base_decoder.cpp` | 1-605 | 音频解码器基类 |
| `audio_decoder/ffmpeg_base_decoder.h` | 1-129 | FFmpegBaseDecoder类定义 |
| `audio_decoder/ffmpeg_decoder_plugin.cpp` | 1-250 | 解码器插件代理 |
| `muxer/ffmpeg_muxer_plugin.cpp` | 1414 | FFmpegMuxerPlugin封装修复器主文件 |
| `muxer/ffmpeg_muxer_register.cpp` | 377 | 插件注册表 |
| `muxer/ffmpeg_muxer_plugin.h` | 126 | FFmpegMuxerPlugin类定义 |
| `muxer/ffmpeg_flv_muxer_plugin.cpp` | 586 | FLV封装修复器 |
| `muxer/ffmpeg_flv_muxer_plugin.h` | 85 | FLV muxer类定义 |
| `muxer/mpeg4_muxer/mpeg4_muxer_plugin.cpp` | 574 | MPEG4 muxer插件 |
| `muxer/mpeg4_muxer/basic_box.cpp` | 1256 | ISOBMFF Box结构体 |
| `muxer/mpeg4_muxer/basic_box.h` | 575 | BasicBox类定义 |
| `muxer/mpeg4_muxer/box_parser.cpp` | 916 | Box解析器 |
| `muxer/mpeg4_muxer/box_parser.h` | 78 | BoxParser类定义 |
| `muxer/mpeg4_muxer/video_track.cpp` | 753 | 视频轨封装 |
| `muxer/mpeg4_muxer/audio_track.cpp` | 263 | 音频轨封装 |
| `muxer/mpeg4_muxer/basic_track.cpp` | 282 | 基础轨 |
| `muxer/mpeg4_muxer/avc_parser.cpp` | 211 | AVC H.264封装 |
| `muxer/mpeg4_muxer/hevc_parser.cpp` | 186 | HEVC H.265封装 |
| `muxer/mpeg4_muxer/avio_stream.cpp` | 221 | AVIO自定义流 |

---

## 八、变更记录

| 日期 | 操作 | 说明 |
|------|------|------|
| 2026-05-15T04:25 | Builder生成 | 本地镜像行号级evidence，S145覆盖common+encoder+decoder完整FFmpeg Adapter体系 |