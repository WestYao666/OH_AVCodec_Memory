---
id: MEM-ARCH-AVCODEC-S103
title: "AV1 Decoder 架构——dav1d 解码器集成与 Av1DecoderLoader 动态加载"
scope: [AVCodec, VideoDecoder, AV1, dav1d, Av1DecoderLoader, dlopen, HDR_VIVID, VideoCodecLoader]
status: pending_approval
approved_at: ~pending~
approved_by: ~pending~
approval_submitted_at: "2026-05-09T11:48:00+08:00"
created_by: builder-agent
created_at: "2026-05-09T02:50:00+08:00"
evidence_sources:
  - "services/engine/codec/video/av1decoder/av1decoder.h (65行)"
  - "services/engine/codec/video/av1decoder/av1decoder.cpp (596行)"
  - "services/engine/codec/video/av1decoder/av1_decoder_api.cpp (38行)"
  - "services/engine/codec/video/av1_decoder_loader.cpp (88行)"
  - "services/services/codec/server/video/codec_factory.cpp"
---

# S103: AV1 Decoder 架构——dav1d 解码器集成与 Av1DecoderLoader 动态加载

## 一句话总结

AV1 Decoder 是 OpenHarmony 多媒体架构中**唯一使用 dav1d 开源解码库的硬件编解码组件**，通过 Av1DecoderLoader 动态加载 `libav1_decoder.z.so`，实现最大 64 实例并发、1920x1080 分辨率、8/10bit 色深的 AV1 视频解码，并支持 HDR VIVID 元数据透传。

## 源码分析

### 1. 核心类继承关系

**文件**: `av1decoder.h:28-65`
```
VideoDecoder (base)
  └── Av1Decoder  (实现类)
```

```cpp
class Av1Decoder : public VideoDecoder {
public:
    explicit Av1Decoder(const std::string &name);
    ~Av1Decoder() override;
    int32_t CreateDecoder() override;
    void DeleteDecoder() override;
    void ConfigurelWidthAndHeight(...) override;
    void FlushAllFrames() override;
    void FillHdrInfo(sptr<SurfaceBuffer> surfaceBuffer) override;
    static int32_t GetCodecCapability(std::vector<CapabilityData> &capaArray);
protected:
    int32_t Initialize() override;
    void InitParams() override;
    void SendFrame() override;
    int32_t DecodeFrameOnce() override;
    int32_t DecodeAv1FrameOnce();   // dav1d 单帧解码
    void ConvertDecOutToAVFrame();  // DAV1D→AVFrame 转换
private:
    AVPixelFormat ConvertAv1FmtToAVPixFmt(Dav1dPixelLayout fmt, int32_t bpc);
    void UpdateColorAspects(Dav1dSequenceHeader *seqHdr);
    int32_t ConvertHdrStaticMetadata(...);

    Dav1dContext *dav1dCtx_ = nullptr;     // dav1d 解码上下文
    AV1_DEC_INARGS av1DecoderInputArgs_;   // 输入参数
    Dav1dPicture *av1DecOutputImg_ = nullptr; // 输出图像
    AV1ColorSpaceInfo colorSpaceInfo_;      // 色彩空间信息
};
```

### 2. dav1d 解码库集成

**文件**: `av1decoder.cpp:113-132` — 解码器创建:
```cpp
int32_t Av1Decoder::CreateDecoder()
{
    std::unique_lock<std::mutex> runLock(decRunMutex_);
    int32_t createRet = 0;
    if (dav1dCtx_ == nullptr) {
        Dav1dSettings dav1dSettings;
        dav1d_default_settings(&dav1dSettings);
        dav1dSettings.logger.callback = AV1DecLog;      // 日志回调
        dav1dSettings.n_threads = 2;                    // 2 线程
        dav1dSettings.max_frame_delay = 1;               // 最大帧延迟 1
        dav1dSettings.apply_grain = 1;                  // 应用影片颗粒度
        createRet = dav1d_open(&dav1dCtx_, &dav1dSettings);
    }
    runLock.unlock();
    CHECK_AND_RETURN_RET_LOG(createRet >= 0 && dav1dCtx_ != nullptr,
        AVCS_ERR_INVALID_OPERATION, "av1 decoder create failed");
    return AVCS_ERR_OK;
}
```

**关键 dav1d 参数**:
| 参数 | 值 | 含义 |
|------|-----|------|
| `n_threads` | 2 | 解码线程数 |
| `max_frame_delay` | 1 | 最大帧延迟（低延迟模式） |
| `apply_grain` | 1 | 保留 film grain 特效 |

### 3. Av1DecoderLoader 动态加载模式

**文件**: `av1_decoder_loader.cpp:19-87`

```cpp
const char *AV1_DECODER_LIB_PATH = "libav1_decoder.z.so";
const char *AV1_DECODER_CREATE_FUNC_NAME = "CreateAv1DecoderByName";
const char *AV1_DECODER_GETCAPS_FUNC_NAME = "GetAv1DecoderCapabilityList";

class Av1DecoderLoader : public VideoCodecLoader {
    // 继承 dlopen 动态加载基类
};
```

**加载流程**:
1. `Av1DecoderLoader::CreateByName()` 调用 `Init()` → `dlopen(libav1_decoder.z.so)`
2. `dlsym(CreateAv1DecoderByName)` 获取创建函数
3. 调用创建函数得到 `CodecBase*` 指针
4. 包装为 `shared_ptr`，析构时调用 `CloseLibrary()`（当实例计数为 0 时 `dlclose`）

**实例管理**:
```cpp
static std::mutex mutex_;
static int32_t av1DecoderCount_ = 0;  // 活跃实例计数
void Av1DecoderLoader::CloseLibrary() {
    if (av1DecoderCount_ != 0) return;  // 有实例时不关闭 so
    Close();  // dlclose
}
```

### 4. 解码循环（SendFrame + DecodeFrameOnce）

**文件**: `av1decoder.cpp:215-270`

```cpp
void Av1Decoder::SendFrame()  // TaskThread 驱动
{
    if (state_ != State::RUNNING) { /* sleep */ return; }
    uint32_t index = inputAvailQue_->Front();
    auto &inputBuffer = buffers_[INDEX_INPUT][index];

    if (inputBuffer->flag_ & AVCODEC_BUFFER_FLAG_EOS) {
        isSendEos_ = true;
    } else {
        av1DecoderInputArgs_.pStream = inputBuffer->memory_->GetAddr();
        av1DecoderInputArgs_.uiStreamLen = inputBuffer->memory_->GetSize();
        av1DecoderInputArgs_.uiTimeStamp = inputBuffer->pts_;
    }

    std::unique_lock<std::mutex> runLock(decRunMutex_);
    do {
        ret = DecodeFrameOnce();  // 循环直到 EOS 或错误
    } while (isSendEos_ && ret == 0);
    runLock.unlock();

    if (isSendEos_) {
        frameBuffer->flag_ = AVCODEC_BUFFER_FLAG_EOS;
        state_ = State::EOS;
    }
    inputAvailQue_->Pop();
}
```

**关键返回值处理**:
```cpp
constexpr int32_t DAV1D_AGAIN = -11;  // dav1d 需要更多数据
int32_t Av1Decoder::DecodeAv1FrameOnce() {
    int32_t ret = 0;
    if (dav1dCtx_ != nullptr) {
        if (!isSendEos_) {
            Dav1dData dav1dDataBuf;
            ret = dav1d_data_wrap(&dav1dDataBuf, ...);
            ret = dav1d_send_data(dav1dCtx_, &dav1dDataBuf);  // 喂入数据
        }
        ret = dav1d_get_picture(dav1dCtx_, av1DecOutputImg_);   // 获取图像
        if (ret < 0 && ret != DAV1D_AGAIN && av1DecOutputImg_ != nullptr) {
            dav1d_picture_unref(av1DecOutputImg_);  // 出错时释放
            av1DecOutputImg_ = nullptr;
        }
    }
    return ret;
}
```

### 5. 色彩空间与 HDR 元数据处理

**文件**: `av1decoder.cpp:280-360`

**DAV1D → AVFrame 转换** (`ConvertDecOutToAVFrame`):
```cpp
AVPixelFormat ConvertAv1FmtToAVPixFmt(Dav1dPixelLayout fmt, int32_t bpc) {
    if (bpc == BITS_PER_PIXEL_COMPONENT_8) {
        switch (fmt) {
            case DAV1D_PIXEL_LAYOUT_I400: return AV_PIX_FMT_GRAY8;
            case DAV1D_PIXEL_LAYOUT_I420: return AV_PIX_FMT_YUV420P;
            case DAV1D_PIXEL_LAYOUT_I422: return AV_PIX_FMT_YUV422P;
            case DAV1D_PIXEL_LAYOUT_I444: return AV_PIX_FMT_YUV444P;
        }
    } else if (bpc == BITS_PER_PIXEL_COMPONENT_10) {
        switch (fmt) {
            case DAV1D_PIXEL_LAYOUT_I400: return AV_PIX_FMT_GRAY10LE;
            case DAV1D_PIXEL_LAYOUT_I420: return AV_PIX_FMT_YUV420P10LE;
            ...
        }
    }
}
```

**HDR 元数据填充** (`FillHdrInfo`):
```cpp
void Av1Decoder::FillHdrInfo(sptr<SurfaceBuffer> surfaceBuffer) {
    if (av1DecOutputImg_->seq_hdr != nullptr) {
        // 1. 色彩空间信息 → ATTRKEY_COLORSPACE_INFO
        ConvertParamsToColorSpaceInfo(...);
        surfaceBuffer->SetMetadata(ATTRKEY_COLORSPACE_INFO, colorSpaceInfoVec);

        // 2. 静态 HDR 元数据 → ATTRKEY_HDR_STATIC_METADATA
        if (av1DecOutputImg_->content_light && av1DecOutputImg_->mastering_display) {
            ConvertHdrStaticMetadata(...);  // SMPTE 2086 + CTA 861
            surfaceBuffer->SetMetadata(ATTRKEY_HDR_STATIC_METADATA, ...);
        }

        // 3. 动态元数据 → ATTRKEY_HDR_DYNAMIC_METADATA
        if (av1DecOutputImg_->itut_t35 != nullptr) {  // HDR VIVID
            surfaceBuffer->SetMetadata(ATTRKEY_HDR_DYNAMIC_METADATA, ...);
            *metadataType = CM_VIDEO_HDR_VIVID;
        }

        // 4. 更新色彩方面 → callback_->OnOutputFormatChanged
        UpdateColorAspects(seqHdr);
    }
}
```

### 6. 能力数据（Codec Capability）

| 属性 | 值 |
|------|-----|
| 最大实例数 | 64 (`VIDEO_INSTANCE_SIZE`) |
| 最大分辨率 | 1920x1080 (HD，不支持 4K) |
| 最小分辨率 | 4x4 |
| 最大帧率 | 300 fps |
| 位深支持 | 8bit / 10bit |
| AV1 Profile | MAIN / HIGH |
| AV1 Level | 0 ~ 73 (全部等级) |
| 像素格式 | NV12, NV21, P010 |
| Graphic 格式 | YCBCR_420_SP, YCRCB_420_SP, YCBCR_P010, YCRCB_P010 |

### 7. 实例管理与资源回收

```cpp
// 实例 ID 分配（最多 64 个）
constexpr int32_t VIDEO_INSTANCE_SIZE = 64;
// 分配：取 freeIDSet_[0] 或新建
// 释放：归还到 freeIDSet_

// 解码器删除（dav1d 上下文）
void Av1Decoder::DeleteDecoder() {
    std::unique_lock<std::mutex> runLock(decRunMutex_);
    if (dav1dCtx_ != nullptr) {
        dav1d_close(&dav1dCtx_);  // 释放 dav1d 上下文
    }
    dav1dCtx_ = nullptr;
}

// Flush：消费所有残留帧
void Av1Decoder::FlushAllFrames() {
    std::unique_lock<std::mutex> runlock(decRunMutex_);
    while (ret == 0) {
        Dav1dPicture pic = {0};
        ret = dav1d_get_picture(dav1dCtx_, &pic);
        dav1d_picture_unref(&pic);  // 释放每帧
    }
}
```

## 关键设计亮点

### dav1d send_data / get_picture 流水线模式

AV1 解码器使用 dav1d 的**双阶段解码模式**：
1. `dav1d_send_data()` — 异步喂入压缩数据（可能返回 `DAV1D_AGAIN` 表示需要更多数据）
2. `dav1d_get_picture()` — 获取已解码图像

这与 FFmpeg 的 `avcodec_send_packet / avcodec_receive_frame` 模式完全一致，是 AV1 解码器的标准做法。

### dlopen/dlsym 热加载

AV1 解码器通过 `libav1_decoder.z.so` 插件式加载，与硬编码实现的其他解码器（H.264/HEVC/VP8/VP9）形成对比：
- **AV1**: dlopen 动态加载（`SUPPORT_CODEC_AV1` 宏控制编译）
- **H.264/HEVC/VP8/VP9**: 静态链接或硬编码

### HDR VIVID 完整链路

```
dav1d_get_picture()
  → seq_hdr (Sequence Header)
  → content_light (Content Light Level)
  → mastering_display (Display Primaries)
  → itut_t35 (HDR VIVID User Data)
        ↓
SurfaceBuffer SetMetadata(ATTRKEY_HDR_*)
        ↓
Surface 输出到显示系统
```

## 关联记忆

| 关联 | 说明 |
|------|------|
| S39（VideoDecoder 三层架构） | Av1Decoder 是 VideoDecoder 基类的具体实现之一 |
| S93（StreamParserManager VVC/HEVC/AVC） | StreamParserManager 处理 AV1/H.266/H.264 AnnexB 格式转换 |
| S42（VideoEncoder） | 与 Av1Decoder 对应的编码器侧 |
| S81（AVCodecSuspend 三模式） | Av1Decoder 冻结/解冻受 CodecState 管理 |

## 适用场景

- **问题定位**：AV1 解码花屏/黑帧 → 检查 `DAV1D_AGAIN` 返回值；HDR VIVID 不显示 → 检查 `itut_t35` 元数据是否正确设置
- **新需求开发**：新增 AV1 主字幕轨道支持 / AV1 4K 解码（需修改 max 分辨率常量）
- **性能分析**：dav1d 2 线程配置是否合理 → 可通过 HiDumper 抓取解码时延 trace
- **架构演进**：AV1 解码是否升配 4K → 需同时更新 `VIDEO_MAX_WIDTH_SIZE` 和 `VIDEO_MAX_HEIGHT_SIZE`

## 尚未覆盖（待后续探索）

- AV1 编码器（当前仅有解码器）
- AV1 Film Grain Apply 特效对播放功耗的影响
- libav1_decoder.z.so 内部实现细节（闭源插件）
