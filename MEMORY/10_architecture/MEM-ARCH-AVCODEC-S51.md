---
id: MEM-ARCH-AVCODEC-S51
title: "Av1Decoder 视频解码器——dav1d 库封装与 AV1 解码管线"
scope: [AVCodec, VideoDecoder, AV1, dav1d, SoftwareCodec, VideoCodecLoader, HDR, ColorSpace]
status: pending_approval
created_by: builder-agent
created_at: "2026-04-26T15:21:00+08:00"
---

# MEM-ARCH-AVCODEC-S51: Av1Decoder 视频解码器——dav1d 库封装与 AV1 解码管线

## 1. 概述

Av1Decoder 是 OpenHarmony AVCodec 体系中支持 AV1（Alliance for Open Media Video 1）视频格式的软件解码器，底层封装了 VideoLAN 的 dav1d 解码库（libdav1d.z.so）。它继承自 VideoDecoder 基类，遵循 CodecBase 生命周期，提供完整的 AV1 影片解码能力。AV1 是新一代开源视频编码标准，主打免专利费、高压缩率，支持 HDR 和屏幕内容编码。

**适用场景**：
- 三方应用接入：播放 AV1 编码的影片（如 WebM 容器、MP4 封装）
- 问题定位：AV1 解码失败、花屏、无图像，需排查 dav1d 库加载、分辨率限制、HDR 元数据传递
- 新需求开发：新增 AV1 Profile 支持或调优解码性能（线程数、apply_grain）

**与其他解码器的对称关系**：
- S39（AVCodecVideoDecoder）：通用视频解码器基类 + Adapter 三层架构，Av1Decoder 是该三层架构的具体软件解码器实现
- Av1Decoder vs H264Decoder/H265Decoder/VPXDecoder：均继承 VideoDecoder，各自封装不同解码库（dav1d / libavcodec / libvpx）

## 2. 核心机制

### 2.1 类层次结构与继承链

**证据**：`services/engine/codec/video/av1decoder/av1decoder.h`

```cpp
class Av1Decoder : public VideoDecoder {
public:
    explicit Av1Decoder(const std::string &name);
    ~Av1Decoder() override;
    int32_t CreateDecoder() override;         // 创建 dav1d 解码上下文
    void DeleteDecoder() override;              // 销毁 dav1d 解码上下文
    void ConfigurelWidthAndHeight(...) override;
    void FlushAllFrames() override;             // 清空所有_pending 的帧
    void FillHdrInfo(sptr<SurfaceBuffer>) override; // 填充 HDR 元数据到 SurfaceBuffer
    static int32_t GetCodecCapability(std::vector<CapabilityData> &capaArray); // 能力查询

protected:
    int32_t Initialize() override;
    void InitParams() override;
    void SendFrame() override;
    int32_t DecodeFrameOnce() override;         // 基类虚函数（调用 DecodeAv1FrameOnce）
    int32_t DecodeAv1FrameOnce();               // AV1 专用单帧解码
    void ConvertDecOutToAVFrame();

private:
    Dav1dContext *dav1dCtx_ = nullptr;          // dav1d 解码器上下文（核心成员）
    AV1_DEC_INARGS av1DecoderInputArgs_;        // 输入参数：码流指针/长度/时间戳
    Dav1dPicture *av1DecOutputImg_ = nullptr;   // 解码输出图像
    AV1ColorSpaceInfo colorSpaceInfo_;           // 色彩空间信息
};
```

**关键**：Av1Decoder 继承 VideoDecoder，实现 CreateDecoder/DeleteDecoder/SendFrame/DecodeFrameOnce 四个关键虚函数，遵循软件 Codec 插件的标准模板。

### 2.2 dav1d 解码上下文创建与销毁

**证据**：`services/engine/codec/video/av1decoder/av1decoder.cpp` 行 166-195

```cpp
int32_t Av1Decoder::CreateDecoder()
{
    int32_t createRet = AVCS_ERR_OK;
    if (dav1dCtx_ == nullptr) {
        Dav1dSettings dav1dSettings;
        dav1d_default_settings(&dav1dSettings);       // 填充默认配置
        dav1dSettings.logger.callback = AV1DecLog;     // 日志回调
        dav1dSettings.n_threads = 2;                   // 解码线程数：2
        dav1dSettings.max_frame_delay = 1;             // 最大帧延迟：1
        dav1dSettings.apply_grain = 1;                 // 开启颗粒度噪声（film grain）
        createRet = dav1d_open(&dav1dCtx_, &dav1dSettings); // 打开解码器
    }
    CHECK_AND_RETURN_RET_LOG(createRet >= 0 && dav1dCtx_ != nullptr,
        AVCS_ERR_INVALID_OPERATION, "dav1d open failed");
    return AVCS_ERR_OK;
}

void Av1Decoder::DeleteDecoder()
{
    std::unique_lock<std::mutex> runlock(decRunMutex_);
    if (dav1dCtx_ != nullptr) {
        dav1d_close(&dav1dCtx_);     // 关闭 dav1d 解码器，释放内存
    }
    dav1dCtx_ = nullptr;
}
```

**关键参数**：
- `n_threads = 2`：解码使用 2 个线程，适用于移动设备功耗控制
- `max_frame_delay = 1`：实时解码模式，最多缓存 1 帧
- `apply_grain = 1`：保留 film grain（电影颗粒感），HDR 内容通常开启

### 2.3 AV1 解码管线（输入→dav1d→输出）

**证据**：`services/engine/codec/video/av1decoder/av1decoder.cpp` 行 323-370

```cpp
int32_t Av1Decoder::DecodeAv1FrameOnce()
{
    int32_t ret = DAV1D_AGAIN;
    if (dav1dCtx_ != nullptr) {
        // Step 1: 将输入码流包装为 dav1d 数据结构
        Dav1dData dav1dDataBuf;
        ret = dav1d_data_wrap(&dav1dDataBuf,
                               av1DecoderInputArgs_.pStream,    // 码流起始地址
                               av1DecoderInputArgs_.uiStreamLen, // 码流长度
                               AV1FreeCallback,                 // 释放回调（no-op）
                               nullptr);
        dav1dDataBuf.m.timestamp = av1DecoderInputArgs_.uiTimeStamp; // PTS
        ret = dav1d_send_data(dav1dCtx_, &dav1dDataBuf);  // 发送数据到解码器
        if (dav1dDataBuf.sz > 0) {
            dav1d_data_unref(&dav1dDataBuf);              // 释放码流数据引用
        }
        // Step 2: 获取解码图像
        ret = dav1d_get_picture(dav1dCtx_, av1DecOutputImg_); // 非阻塞获取输出帧
        if (ret < 0 && ret != DAV1D_AGAIN && av1DecOutputImg_ != nullptr) {
            dav1d_picture_unref(av1DecOutputImg_);          // 出错时释放图像
        }
    }
    return ret;
}
```

**DAV1D_AGAIN = -11**：dav1d 返回值，表示"需要更多数据"（EAGAIN），属正常状态，非错误。

**解码循环**：`SendFrame()` 调用 `DecodeAv1FrameOnce()` 尝试消费输入并产出图像；基类 `DecodeFrameOnce()` 循环调用直到不返回 AGAIN。

### 2.4 像素格式转换：Dav1dPixelLayout → AVPixelFormat

**证据**：`services/engine/codec/video/av1decoder/av1decoder.cpp` 行 200-230

```cpp
AVPixelFormat Av1Decoder::ConvertAv1FmtToAVPixFmt(Dav1dPixelLayout fmt, int32_t bpc)
{
    switch (fmt) {
        case DAV1D_PIXEL_LAYOUT_I400: return (bpc == 1) ? AV_PIX_FMT_YUV420P : AV_PIX_FMT_YUV420P16;
        case DAV1D_PIXEL_LAYOUT_I420: return (bpc == 1) ? AV_PIX_FMT_YUV420P : AV_PIX_FMT_YUV420P16;
        case DAV1D_PIXEL_LAYOUT_I422: return (bpc == 1) ? AV_PIX_FMT_YUV422P : AV_PIX_FMT_YUV422P16;
        case DAV1D_PIXEL_LAYOUT_I444: return (bpc == 1) ? AV_PIX_FMT_YUV444P : AV_PIX_FMT_YUV444P16;
        // ... 其他格式
    }
}
```

AV1 支持 4 种像素布局：I400（灰度）、I420（4:2:0 YCbCr）、I422（4:2:2）、I444（4:4:4）。输出时按位深（bpc=8/10/12）选择对应的 FFmpeg AVPixelFormat。

### 2.5 HDR 元数据填充

**证据**：`services/engine/codec/video/av1decoder/av1decoder.cpp` 行 480-520

```cpp
void Av1Decoder::FillHdrInfo(sptr<SurfaceBuffer> surfaceBuffer)
{
    Dav1dSequenceHeader *seqHdr = ...; // 从解码输出提取 sequence header
    if (seqHdr != nullptr) {
        // 转换 HDR 静态元数据：ContentLightLevel + MasteringDisplay
        std::vector<uint8_t> staticMetadataVec;
        ConvertHdrStaticMetadata(contentLight, masteringDisplay, staticMetadataVec);
        // 设置元数据类型（根据 transfer function 选择 CM_HDR_Metadata_Type）
        auto *metadataType = static_cast<CM_HDR_Metadata_Type>(
            GetMetaDataTypeByTransFunc(seqHdr->trc));
        surfaceBuffer->SetMetadata(ATTRKEY_HDR_METADATA_TYPE, metadataTypeVec);
        UpdateColorAspects(seqHdr); // 更新色彩空间信息
    }
}
```

**关键**：AV1 HDR 支持从 sequence header 中提取 color primaries / transfer / matrix，传递给 SurfaceBuffer，供后续渲染管线做色域转换。

### 2.6 清空_pending帧（Flush）

**证据**：`services/engine/codec/video/av1decoder/av1decoder.cpp` 行 492-508

```cpp
void Av1Decoder::FlushAllFrames()
{
    std::unique_lock<std::mutex> runlock(decRunMutex_);
    int ret = 0;
    while (ret == 0) {
        Dav1dPicture pic = { 0 };
        Dav1dPicture *outputImg = &pic;
        if (dav1dCtx_ != nullptr) {
            ret = dav1d_get_picture(dav1dCtx_, outputImg);  // 循环取出所有_pending帧
            dav1d_picture_unref(outputImg);
        } else {
            ret = -1;
        }
    }
}
```

Flush 时连续调用 `dav1d_get_picture` 直到返回非 0，将解码器内部所有_pending帧全部清空，用于 Seek 场景。

## 3. 能力注册与动态加载

### 3.1 能力清单（GetCodecCapability）

**证据**：`services/engine/codec/video/av1decoder/av1decoder.cpp` 行 525-560

```cpp
int32_t Av1Decoder::GetCodecCapability(std::vector<CapabilityData> &capaArray)
{
    for (uint32_t i = 0; i < SUPPORT_AV1_DECODER_NUM; ++i) {
        CapabilityData capsData;
        capsData.codecName = AVCodecCodecName::VIDEO_DECODER_AV1_NAME; // "av1decoder.hisilicon"
        capsData.mimeType = CodecMimeType::VIDEO_AV1;                  // "video/av1"
        capsData.codecType = AVCODEC_TYPE_VIDEO_DECODER;
        capsData.isVendor = false;                                     // 软件解码器
        capsData.maxInstance = 64;                                      // 最多 64 个实例
        capsData.width.minVal = 4;     capsData.width.maxVal = 1920;   // 宽范围
        capsData.height.minVal = 4;    capsData.height.maxVal = 1080;  // 高范围（当前最大1080p）
        capsData.frameRate.maxVal = 300;                               // 最高 300fps
        capsData.pixFormat = { VideoPixelFormat::NV12, VideoPixelFormat::NV21 };
        capsData.graphicPixFormat = {
            GraphicPixelFormat::GRAPHIC_PIXEL_FMT_YCBCR_420_SP,   // NV12
            GraphicPixelFormat::GRAPHIC_PIXEL_FMT_YCRCB_420_SP,  // NV21
            GraphicPixelFormat::GRAPHIC_PIXEL_FMT_YCBCR_P010,     // 10bit
            GraphicPixelFormat::GRAPHIC_PIXEL_FMT_YCRCB_P010     // 10bit
        };
        capsData.profiles = { AV1_PROFILE_MAIN, AV1_PROFILE_HIGH };
        // 所有 AV1 Level（0.0 到 7.3）均支持
        capsData.profileLevelsMap = {
            { AV1_PROFILE_MAIN, levels },
            { AV1_PROFILE_HIGH, levels }
        };
    }
}
```

### 3.2 动态加载：Av1DecoderLoader + extern "C" 三函数

**证据**：`services/engine/codec/video/av1decoder/include/av1_decoder_api.h` + `av1_decoder_api.cpp`

```cpp
extern "C" {
int32_t GetAv1DecoderCapabilityList(std::vector<CapabilityData> &caps);
void CreateAv1DecoderByName(const std::string &name, std::shared_ptr<CodecBase> &codec);
void Av1DecStrongRef(CodecBase *ptr);
}
```

**CreateAv1DecoderByName**：
```cpp
void CreateAv1DecoderByName(const std::string &name, std::shared_ptr<CodecBase> &codec)
{
    sptr<Av1Decoder> av1Decoder = new (std::nothrow) Av1Decoder(name);
    av1Decoder->IncStrongRef(av1Decoder.GetRefPtr());  // 增加强引用计数
    codec = std::shared_ptr<Av1Decoder>(av1Decoder.GetRefPtr(), [](Av1Decoder *ptr){});
}
```

**证据**：`services/engine/codec/video/av1decoder/av1decoder.cpp` 行 40-46

```cpp
constexpr OHOS::HiviewDFX::HiLogLabel LABEL = {LOG_CORE, LOG_DOMAIN_FRAMEWORK, "Av1DecoderLoader"};
constexpr struct {
    const std::string_view codecName;   // VIDEO_DECODER_AV1_NAME
    const std::string_view mimeType;   // VIDEO_AV1
} SUPPORT_AV1_DECODER[] = {
#ifdef SUPPORT_CODEC_AV1
    {AVCodecCodecName::VIDEO_DECODER_AV1_NAME, CodecMimeType::VIDEO_AV1},
#endif
};
```

编译开关 `SUPPORT_CODEC_AV1` 控制 AV1 解码器是否编译进系统。

## 4. 与其他 S 系列的关系

| 关系 | 说明 |
|------|------|
| S39 | AVCodecVideoDecoder 是 Av1Decoder 的基类；Av1Decoder 是 S39 三层架构中的"具体 Codec 引擎"层 |
| S40（FFmpegMuxerPlugin） | FFmpeg 同时支持 AV1 解码（libavcodec）和 MP4/MKV 封装，Av1Decoder 使用 FFmpeg 的 AVPixelFormat |
| S17（SmartFluencyDecoding） | 智能丢帧在解码后处理阶段生效，与 Av1Decoder 的 DecodeAv1FrameOnce 互补 |
| S22（MediaSyncManager） | Av1Decoder 输出帧的 PTS 由 MediaSyncManager 管理，用于音视频同步 |

## 5. 关键参数速查

| 参数 | 值 | 说明 |
|------|-----|------|
| 最大分辨率 | 1920×1080 | 硬件限制，当前不支持 4K AV1 解码 |
| 最大帧率 | 300fps | |
| 解码线程数 | 2 | 可通过 Dav1dSettings.n_threads 配置 |
| 最大实例数 | 64 | 多路解码场景 |
| 支持 Profile | MAIN / HIGH | 不支持 PROFESSIONAL（最高到 HIGH）|
| 支持 Level | 0.0 ~ 7.3 | 全部 74 个 Level |
| 颗粒度噪声 | apply_grain=1 | 开启，保留 film grain |
| 像素格式 | I400/I420/I422/I444 | 输入支持；输出 NV12/NV21/P010 |
| DAV1D_AGAIN | -11 | EAGAIN，需继续送数据 |
