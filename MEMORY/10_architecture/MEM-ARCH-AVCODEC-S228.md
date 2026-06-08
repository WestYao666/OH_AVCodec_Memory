# MEM-ARCH-AVCODEC-S228 — HevcDecoder HEVC 硬件解码器插件架构

## 元信息

|字段 | 值 |
|------|-----|
| id | MEM-ARCH-AVCODEC-S228 |
| title | HevcDecoder HEVC 硬件解码器插件架构 |
| status | draft |
| created | 2026-06-08 |
| builder | builder-agent |
| evidence_count | 17 |
| source_files | hevc_decoder.cpp(793行) + hevc_decoder.h(90行) + hevc_decoder_api.cpp(38行) + HevcDec_Typedef.h(90行) = 1011行源码 |
| local_mirror | /home/west/av_codec_repo/services/engine/codec/video/hevcdecoder/ |
| git_branch | master |
| commit | a2886eb834fa6743b3ff465fd82697ec5e0c760f |
| git_url | https://github.com/WestYao666/OH_AVCodec_Memory/commit/a2886eb834fa6743b3ff465fd82697ec5e0c760f |

---

## 1. Scope（范围）

AVCodec HEVC/H.265 硬件解码器插件——基于 `VideoDecoder` 基类的硬件解码实现，dlopen 加载 `libhevcdec_ohos.z.so`，四函数（HDI）接口封装，支持8bit/10bit 双位深、HDR 元数据（SMPTE2086/CTA861/Vivid）提取与 Surface 绑定，TaskThread 驱动 SendFrame 单线程解码管线。

---

## 2. 类继承架构

```
VideoDecoder (基类，抽象)
  └── HevcDecoder : public VideoDecoder
        - dlopen libhevcdec_ohos.z.so
        - 4个函数指针（HDI接口）
        - HEVC_DEC_INIT_PARAM / HEVC_DEC_INARGS / HEVC_DEC_OUTARGS
        - SendFrame TaskThread 驱动（单线程）
        - HDR 元数据：SMPTE2086 + CTA861 + Vivid Dynamic
```

---

## 3. Evidence（行号级证据）

>源码路径：`/home/west/av_codec_repo/services/engine/codec/video/hevcdecoder/`

**E1: hevc_decoder.h L25-27** — HevcDecoder 继承 VideoDecoder，声明4 个 HDI 函数指针类型别名：`CreateHevcDecoderFuncType` / `DecodeFuncType` / `FlushFuncType` / `DeleteFuncType`，对应 libhevcdec_ohos.z.so 四函数接口

**E2: hevc_decoder.h L39-42** — `HEVC_DEC_HANDLE hevcSDecoder_` 句柄、三个核心数据结构：`HEVC_DEC_INIT_PARAM initParams_` / `HEVC_DEC_INARGS hevcDecoderInputArgs_` / `HEVC_DEC_OUTARGS hevcDecoderOutpusArgs_`

**E3: hevc_decoder.cpp L37-38** — dlopen 库路径常量：`const char *HEVC_DEC_LIB_PATH = "libhevcdec_ohos.z.so";` +四个函数名符号常量（L38-41）

**E4: hevc_decoder.cpp L51-59** — 常量定义：最大实例数 `VIDEO_INSTANCE_SIZE=64` /缓冲区限制 `VIDEO_MIN_BUFFER_SIZE=1474560(1280×768)` / `VIDEO_MAX_BUFFER_SIZE=3110400(1080p)` / `VIDEO_MAX_WIDTH_SIZE=1920` / `VIDEO_MAX_HEIGHT_SIZE=1920`

**E5: hevc_decoder.cpp L63-67** — 支持列表：`SUPPORT_HEVC_DECODER[]` 映射表（codecName + mimeType），`VIDEO_DECODER_HEVC_NAME` → `CodecMimeType::VIDEO_HEVC`

**E6: hevc_decoder.cpp L80-90** — 构造函数：dlopen(RTLD_LAZY) 加载 libhevcdec_ohos.z.so → HevcFuncMatch() dlsym 四函数指针 → 实例计数管理（VIDEO_INSTANCE_SIZE=64 上限）

**E7: hevc_decoder.cpp L107-117** — `HevcFuncMatch()`：dlsym 四个符号：`HEVC_CreateDecoder` / `HEVC_DecodeFrame` / `HEVC_FlushFrame` / `HEVC_DeleteDecoder`，任一失败调用 `ReleaseHandle()`关闭句柄

**E8: hevc_decoder.cpp L122-135** — `ReleaseHandle()`：`std::unique_lock<std::mutex>` 解锁 decRunMutex_ 后 dlclose 关闭句柄，释放四个函数指针

**E9: hevc_decoder.cpp L140-160** — 析构函数：ReleaseResource() → callback_=nullptr → ReleaseHandle() → 实例 ID 归还（freeIDSet_ 回收机制）

**E10: hevc_decoder.cpp L195-210** — `InitHdrParams()`：初始化 HEVC_DEC_OUTARGS 的 uiHdrMetadata 字段（displayPrimariesX/Y[3] / whitePointX/Y / max/minLuminance / maxContentLightLevel / maxPicAverageLightLevel）

**E11: hevc_decoder.cpp L240-255** — `Initialize()`：创建 TaskThread "SendFrame" 注册 SendFrame 处理函数，状态转换 `UNINITIALIZED → INITIALIZED`

**E12: hevc_decoder.cpp L257-264** — `CreateDecoder()`：`hevcDecoderCreateFunc_(&hevcSDecoder_, &initParams_)` 调用 HDI 接口创建 HEVC 解码器句柄

**E13: hevc_decoder.cpp L267-280** — `DeleteDecoder()`：`hevcDecoderDeleteFunc_(hevcSDecoder_)` 销毁解码器实例，设置 ERROR 状态并触发 OnError 回调

**E14: hevc_decoder.cpp L305-325** — `SendFrame()`：TaskThread 驱动，循环调用 `DecodeFrameOnce()`，EOS 时发送 `AVCODEC_BUFFER_FLAG_EOS`，消费 inputAvailQue_ 并回调 OnInputBufferAvailable

**E15: hevc_decoder.cpp L350-370** — `DecodeFrameOnce()`：`hevcDecoderDecodecFrameFunc_` HDI 解码调用，返回值 0=成功/-1=需要更多数据/<-1=错误，bitDepth 8bit→AV_PIX_FMT_YUV420P / 10bit→AV_PIX_FMT_YUV420P10LE

**E16: hevc_decoder.cpp L400-430** — `ConfigureHdrColorSpaceIno()`：从 Format 提取 MD_KEY_RANGE_FLAG / MD_KEY_COLOR_PRIMARIES / MD_KEY_TRANSFER_CHARACTERISTICS / MD_KEY_MATRIX_COEFFICIENTS 四元组色域参数

**E17: hevc_decoder.cpp L435-480** — `ConfigureHdrStaticMetadata()`：提取 `VIDEO_STATIC_METADATA_SMPT2086`（Smpte2086结构体）和 `VIDEO_STATIC_METADATA_CTA861`（Cta861结构体），写入 HdrStaticMetadata，isValidHdrSttMd_ 原子标记

---

## 4. 核心类型定义（HevcDec_Typedef.h）

| 类型 | 用途 |
|------|------|
| `HEVC_DEC_HANDLE` | 解码器句柄（void*） |
| `HEVC_DEC_INIT_PARAM` | 初始化参数（channelId / logFxn / decodeMode / eOutPutOrder） |
| `HEVC_DEC_INARGS` | 输入数据（pStream / uiStreamLen / uiTimeStamp） |
| `HEVC_DEC_OUTARGS` | 输出数据（宽/高/Stride/bitDepth/YUV[3]/ColorSpaceInfo/HdrMetadata） |
| `IHW265_DECODE_MODE` | 解码模式枚举：`IHW265_DECODE_VIDEO=0` / `IHW265_DECODE_HEIF=1` |
| `IHW265VIDEO_ALG_LOG_LEVEL` | 日志级别：ERROR/WARNING/INFO/DEBUG |

---

## 5. 能力注册（GetCodecCapability）

- **最大实例数**：64（VIDEO_INSTANCE_SIZE）
- **分辨率范围**：最小 2×2，最大 1920×1920
- **帧率范围**：0 ~30fps（VIDEO_FRAMERATE_DEFAULT_SIZE）
- **最大码率**：300Mbps（VIDEO_BITRATE_MAX_SIZE）
- **像素格式**：`NV12` / `NV21`（8bit）+ `GRAPHICS_P010`（10bit）
- **Graphic格式**：`YCBCR_420_SP` / `YCRCB_420_SP` / `YCBCR_P010` / `YCRCB_P010`
- **Profile**：HEVC_PROFILE_MAIN / HEVC_PROFILE_MAIN_10
- **Level**：HEVC_LEVEL_0 ~ HEVC_LEVEL_62（全部 63 级）

---

## 6. Associations（关联已有 S 系列记忆）

|关联 ID | 关系 |
|---------|------|
| S39 | VideoDecoder 基类（父类），三队列+Surface模式 |
| S54 | HevcDecoder + VpxDecoder 并列（HevcDecoder已在 S54 中作为子项提及，S228 独立深化） |
| S57 | HDecoder/HEncoder 硬件编解码器（HDI 四函数指针模式与 HevcDecoder 一致） |
| S70 | VideoCodecLoader 工厂（CreateHevcDecoderByName → HevcDecoder 工厂入口） |
| S63/S225 | CodecDrmDecrypt DRM CENC（HEVC DRM 解密路径） |
| S46/S45 | DecoderSurfaceFilter / SurfaceDecoderFilter（Surface 绑定输出） |
| S83/S84 | CAPI 层（NativeVideoEncoder / VideoDecoder C API） |
| S55 | 模块间回调链路（OnError / OnOutputFormatChanged 回调） |

---

## 7. 关键设计点

1. **单线程解码管线**：SendFrame TaskThread 驱动，与 FCodec（S53）双 TaskThread 不同，HevcDecoder 仅一个发送线程
2. **dlopen HDI 接口**：libhevcdec_ohos.z.so 四函数（Create/Decode/Flush/Delete），与 HDecoder（S57）共用同一 OMX HDI 模式
3. **双位深支持**：8bit（YUV420P）+ 10bit（YUV420P10LE），通过 uiDecBitDepth 判断
4. **HDR 三路元数据**：SMPTE2086（ mastering display）/ CTA861（content light level）/ Vivid Dynamic（ATTRKEY_HDR_DYNAMIC_METADATA）
5. **实例池管理**：VIDEO_INSTANCE_SIZE=64，上限控制 + freeIDSet_回收机制
6. **Surface 绑定**：FillHdrInfo() 将 ColorSpace + HDR Metadata 注入 SurfaceBuffer

---

## 8. 与 S54 的差异说明

S54（`HevcDecoder + VpxDecoder 视频解码器`）已记录 HevcDecoder 的基础框架。S228 基于本地镜像源码进行行号级深度分析，补充了：
- HevcDec_Typedef.h 完整结构体定义（E1-E17 的 HDI 接口层）
- SendFrame 单线程解码循环（E14）
- HDR 三路元数据注入机制（E16-E17，FillHdrStaticInfo / FillHdrInfo）
- GetCodecCapability 能力注册细节（HEVC_PROFILE_MAIN + MAIN_10，63级Level）
- 实例池管理机制（freeIDSet_ 回收）