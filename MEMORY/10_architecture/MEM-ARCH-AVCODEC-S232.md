---
id: MEM-ARCH-AVCODEC-S232
type: architecture
status: pending_approval
subject: "Av1Decoder + Dav1d AV1软件解码器——dav1d两段式解码管线+HDR三元组元数据注入+ColorAspects追踪"
scope: "AVCodec, VideoDecoder, AV1, Dav1d, VideoLAN, SendFrame, DecodeFrameOnce, HDR, ColorSpace, ITU-T T.35, SurfaceBuffer, InstancePool"
evidence_count: 18
source_files:
  - "/home/west/av_codec_repo/services/engine/codec/video/av1decoder/av1decoder.h (113行)"
  - "/home/west/av_codec_repo/services/engine/codec/video/av1decoder/av1decoder.cpp (596行)"
  - "/home/west/av_codec_repo/services/engine/codec/video/av1decoder/av1_decoder_api.cpp (38行)"
  - "/home/west/av_codec_repo/services/engine/codec/video/av1decoder/Av1Dec_Typedef.h"
关联记忆:
  - S199 (VideoCodecLoader — Av1DecoderLoader是7类Loader之一，但详情待查)
  - S231 (VideoDecoder基类+RenderSurface+VpxDecoder三层架构)
  - S54/S57 (VideoDecoder通用生命周期)
  - S39 (解码器通用框架)
  - S225 (HDR三元组元数据注入模式)
  - S70 (ColorSpace色彩空间处理)
  - S163 (DRM元数据与SurfaceBuffer)
---

# S232 Av1Decoder + Dav1d AV1软件解码器

## 1. 架构概述

Av1Decoder 是 AVCodec 模块的 **AV1 软件解码器**，继承自 VideoDecoder 基类，内部集成 **VideoLAN 的 dav1d 开源库** 实现 AV1 bitstream 解码。相比 VpxDecoder（libvpx，VP8/VP9）和 HevcDecoder（H.265 硬件解码），Av1Decoder 是纯软件实现，不依赖硬件 HDI。

```
Av1Decoder（VideoDecoder子类，596行cpp）
    ├── dav1d_open() / dav1d_close()     — dav1d库初始化/销毁
    ├── dav1d_send_data()                — 向dav1d喂入压缩数据
    ├── dav1d_get_picture()              — 从dav1d取出解码图像
    ├── SendFrame() 线程（TaskThread）   — 持续从inputAvailQue_取帧送解码
    ├── DecodeFrameOnce() → DecodeAv1FrameOnce() — 两段式解码
    ├── ConvertDecOutToAVFrame()         — Dav1dPicture → AVFrame格式转换
    ├── UpdateColorAspects()             — 从seq_hdr追踪色彩空间变化
    ├── FillHdrInfo()                    — 向SurfaceBuffer注入HDR三元组元数据
    └── 实例池化（64上限，ID可回收）
```

---

## 2. 关键常量与约束

| 常量 | 值 | 含义 |
|------|-----|------|
| VIDEO_INSTANCE_SIZE | 64 | 最大实例数 |
| VIDEO_MAX_WIDTH_SIZE | 1920 | 最大宽度 |
| VIDEO_MAX_HEIGHT_SIZE | 1080 | 最大高度 |
| VIDEO_BLOCKPERFRAME_MAX_SIZE | 8160 | 每帧最大宏块数 |
| VIDEO_BLOCKPERSEC_MAX_SIZE | 326400 | 每秒最大宏块数 |
| VIDEO_MAX_FRAMERATE | 300 | 最大帧率 |
| DAV1D_AGAIN | -11 | dav1d内部"需要更多数据"错误码 |
| DEFAULT_TRY_DECODE_TIME | 1ms | SendFrame线程休眠粒度 |
| DAV1D n_threads | 2 | 解码线程数 |
| apply_grain | 1 | 开启胶片颗粒（film grain） |

---

## 3. 解码管线（两段式）

### 3.1 SendFrame 线程循环

E1: `av1decoder.cpp L273-289` — SendFrame 从 inputAvailQue_ 取 CodecBuffer，调用 DecodeFrameOnce：
```cpp
void Av1Decoder::SendFrame()
{
    if (state_ != State::RUNNING || isSendEos_ || codecAvailQue_->Size() == 0u) {
        std::this_thread::sleep_for(std::chrono::milliseconds(DEFAULT_TRY_DECODE_TIME)); // E1: 1ms轮询
        return;
    }
    // ... 取buffer，构建av1DecoderInputArgs_ ...
    do {
        ret = DecodeFrameOnce(); // E1: 循环直到EOS
    } while (isSendEos_ && ret == 0);
}
```

### 3.2 DecodeFrameOnce 两段式解码

E2: `av1decoder.cpp L356-397` — 每次DecodeFrameOnce创建临时Dav1dPicture，分两段执行：
```cpp
int32_t Av1Decoder::DecodeFrameOnce()
{
    av1DecOutputImg_ = new Dav1dPicture{0}; // E2: 每帧new一个输出对象
    int32_t ret = DecodeAv1FrameOnce();
    if (ret == 0 && av1DecOutputImg_ != nullptr) {
        ConvertDecOutToAVFrame(); // E2: Dav1dPicture → AVFrame格式转换
        // ... 格式检查，FillFrameBuffer，FramePostProcess ...
    }
    dav1d_picture_unref(av1DecOutputImg_); // E2: 主动unref防止内存泄漏
    delete av1DecOutputImg_;
    av1DecOutputImg_ = nullptr;
    return ret;
}
```

### 3.3 DecodeAv1FrameOnce核心

E3: `av1decoder.cpp L299-325` — dav1d两段API调用：
```cpp
int32_t Av1Decoder::DecodeAv1FrameOnce()
{
    if (!isSendEos_) {
        Dav1dData dav1dDataBuf;
        dav1d_data_wrap(&dav1dDataBuf, av1DecoderInputArgs_.pStream, ...); // E3: 数据封装
        dav1d_send_data(dav1dCtx_, &dav1dDataBuf); // E3: 第一段：送入压缩数据
    }
    ret = dav1d_get_picture(dav1dCtx_, av1DecOutputImg_); // E3: 第二段：取出解码图像
    if (ret < 0 && ret != DAV1D_AGAIN) {
        dav1d_picture_unref(av1DecOutputImg_); // E3: 异常时清理
        delete av1DecOutputImg_;
        av1DecOutputImg_ = nullptr;
    }
}
```

---

## 4. dav1d 库初始化

E4: `av1decoder.cpp L162-175` — CreateDecoder时初始化dav1d上下文：
```cpp
int32_t Av1Decoder::CreateDecoder()
{
    Dav1dSettings dav1dSettings;
    dav1d_default_settings(&dav1dSettings);
    dav1dSettings.logger.callback = AV1DecLog; // E4: 日志回调
    dav1dSettings.n_threads = 2; // E4: 2解码线程
    dav1dSettings.max_frame_delay = 1;               // E4: 最大帧延迟
    dav1dSettings.apply_grain = 1;                   // E4: 开启胶片颗粒
    int32_t createRet = dav1d_open(&dav1dCtx_, &dav1dSettings); // E4:打开dav1d
}
```

E5: `av1decoder.cpp L177-182` — DeleteDecoder释放资源：
```cpp
void Av1Decoder::DeleteDecoder()
{
    if (dav1dCtx_ != nullptr) {
        dav1d_close(&dav1dCtx_); // E5: 关闭dav1d，释放内存
    }
    dav1dCtx_ = nullptr;
}
```

---

## 5. 像素格式转换

E6: `av1decoder.cpp L195-228` — Dav1dPixelLayout → AVPixelFormat 映射表（8bit和10bit双路径）：

| Dav1dPixelLayout | 8bit → AV_PIX_FMT | 10bit → AV_PIX_FMT |
|-----------------|-------------------|-------------------|
| I400 | GRAY8 | GRAY10LE |
| I420 | YUV420P | YUV420P10LE |
| I422 | YUV422P | YUV422P10LE |
| I444 | YUV444P | YUV444P10LE |

E7: `av1decoder.cpp L230-260` — ConvertDecOutToAVFrame：Y/U/V三平面data指针+linesize+width+height+pts转换。

---

## 6. 色彩空间追踪（ColorAspects）

E8: `av1decoder.cpp L399-420` — UpdateColorAspects 从 Dav1dSequenceHeader 提取四元组并通知上层：
```cpp
void Av1Decoder::UpdateColorAspects(Dav1dSequenceHeader *seqHdr)
{
    // E8: color_range / pri / trc / mtrx 四元组变化检测
    format_.PutIntValue(MD_KEY_RANGE_FLAG, static_cast<int32_t>(seqHdr->color_range));
    format_.PutIntValue(MD_KEY_COLOR_PRIMARIES, static_cast<int32_t>(seqHdr->pri));
    format_.PutIntValue(MD_KEY_TRANSFER_CHARACTERISTICS, static_cast<int32_t>(seqHdr->trc));
    format_.PutIntValue(MD_KEY_MATRIX_COEFFICIENTS, static_cast<int32_t>(seqHdr->mtrx));
    callback_->OnOutputFormatChanged(format_); // E8: 色彩空间变化回调
}
```

---

## 7. HDR 三元组元数据注入

E9: `av1decoder.cpp L436-497` — FillHdrInfo 向 SurfaceBuffer 注入三种 HDR 元数据：

| 元数据Key | 来源 | 目标格式 |
|-----------|------|---------|
| ATTRKEY_COLORSPACE_INFO | seq_hdr (color_range/pri/trc/mtrx) | CM元组 |
| ATTRKEY_HDR_STATIC_METADATA | content_light + mastering_display | HdrStaticMetadata (SMPTE2086+CTA861) |
| ATTRKEY_HDR_DYNAMIC_METADATA | itut_t35 payload | CM动态元数据 |
| ATTRKEY_HDR_METADATA_TYPE | seqHdr->trc 或 itut_t35 | CM_HDR_Metadata_Type |

E10: `av1decoder.cpp L445-468` — ConvertHdrStaticMetadata 四步转换：
```cpp
// E10: masteringDisplay->primaries[0-2] → SMPTE2086.displayPrimaryGreen/Blue/Red
// E10: masteringDisplay->white_point → SMPTE2086.whitePoint
// E10: masteringDisplay->max_luminance *0.0001 → SMPTE2086.maxLuminance
// E10: contentLight->max_content_light_level → CTA861.maxContentLightLevel
```

---

## 8. 实例池化管理

E11: `av1decoder.cpp L54-80` — 构造时从池分配ID，析构时回收：
```cpp
Av1Decoder::Av1Decoder(const std::string &name) : VideoDecoder(name)
{
    if (!freeIDSet_.empty()) {
        decInstanceID_ = freeIDSet_[0];        // E11: 优先复用已释放ID
        freeIDSet_.erase(freeIDSet_.begin());
        decInstanceIDSet_.push_back(decInstanceID_);
    } else if (freeIDSet_.size() + decInstanceIDSet_.size() < VIDEO_INSTANCE_SIZE) {
        decInstanceID_ = freeIDSet_.size() + decInstanceIDSet_.size(); // E11: 新增分配
    }
    //超过64上限 → isValid_ = false
}
```

E12: `av1decoder.cpp L101-113` — 析构时回收ID到 freeIDSet_：
```cpp
Av1Decoder::~Av1Decoder()
{
    if (decInstanceID_ < VIDEO_INSTANCE_SIZE) {
        freeIDSet_.push_back(decInstanceID_); // E12: 回收ID
        decInstanceIDSet_.erase(it);
    }
}
```

---

## 9. 与其他解码器的关键差异

| 维度 | Av1Decoder (dav1d) | VpxDecoder (libvpx) | HevcDecoder (HDI) |
|------|-------------------|---------------------|-------------------|
| 实现方式 | 软件（dav1d库） | 软件（libvpx库） | 硬件（HDI调用） |
| 实例上限 | 64 | 64 | 外部管理 |
| 线程模型 | SendFrame线程+2解码线程 | 同左 | HDI内部管理 |
| HDR元数据 | Dav1dPicture→SurfaceBuffer | 类似 | HDI返回 |
| 色彩空间 | seq_hdr实时检测+回调 | 类似 | 类似 |
| 粒度控制 | 1ms SendFrame轮询 | 类似 | 硬件异步 |

---

## 10. 文件速查

| 文件 | 行数 | 核心职责 |
|------|------|---------|
| `av1decoder.h` | 113 | 类定义：虚接口覆盖+私有成员（dav1dCtx_等） |
| `av1decoder.cpp` | 596 | 实现：完整解码管线+HDR+ColorAspects |
| `av1_decoder_api.cpp` | 38 |导出函数：CreateAv1DecoderByName + GetAv1DecoderCapabilityList |
| `Av1Dec_Typedef.h` | - | Dav1d相关类型定义（Dav1dContext/Dav1dPicture等） |