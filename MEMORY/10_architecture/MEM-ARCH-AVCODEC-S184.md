# MEM-ARCH-AVCODEC-S184.md — FFmpeg Audio Decoder Plugin体系

**版本**：v1.0  
**日期**：2026-05-25  
**状态**：draft → pending_approval  
**主题**：FFmpeg Audio Decoder Plugin体系——FfmpegBaseDecoder基类+29子插件+Resample重采样三层架构  
**Tags**：AVCodec, FFmpeg, AudioDecoder, Plugin, SoftwareCodec, Resample, SwrContext, libavcodec, avcodec_send_packet, avcodec_receive_frame, FfmpegBaseDecoder, FfmpegDecoderPlugin, AAC, FLAC, MP3, Vorbis, WMA, DTS, COOK, ADPCM, AMR, ALAC, ILBC, TrueHD, APE, GSM, DTS  
**关联**：S125(FFmpegDecoder基类), S130(FFmpegAdapterCommon), S50(AudioResample), S158(FFmpegEncoder), S169(FFmpegAudioEncoder)  

---

## 一、三层插件架构（证据驱动）

FFmpeg Audio Decoder体系采用**注册层→引擎基类→29子插件**三层架构。注册层（ffmpeg_decoder_plugin.cpp）在插件加载时通过`RegisterAudioDecoderPlugins`一次性注册全部50个codec变体；引擎基类（FfmpegBaseDecoder）封装avcodec_send_packet/avcodec_receive_frame管线及SwrContext重采样；子插件继承引擎基类，各自实现具体codec初始化参数。

### Evidence #1 — 插件头文件包含29子插件
```
文件：services/media_engine/plugins/ffmpeg_adapter/audio_decoder/ffmpeg_decoder_plugin.h
行号：23-46
源码：
#include "aac/ffmpeg_aac_decoder_plugin.h"
#include "ac3/ffmpeg_ac3_decoder_plugin.h"
#include "flac/ffmpeg_flac_decoder_plugin.h"
#include "mp3/ffmpeg_mp3_decoder_plugin.h"
#include "vorbis/ffmpeg_vorbis_decoder_plugin.h"
#include "amrnb/ffmpeg_amrnb_decoder_plugin.h"
#include "amrwb/ffmpeg_amrwb_decoder_plugin.h"
#include "ape/ffmpeg_ape_decoder_plugin.h"
#include "gsm_ms/ffmpeg_gsm_ms_decoder_plugin.h"
#include "gsm/ffmpeg_gsm_decoder_plugin.h"
#include "alac/ffmpeg_alac_decoder_plugin.h"
#include "wma/ffmpeg_wma_decoder_plugin.h"
#include "adpcm/ffmpeg_adpcm_decoder_plugin.h"  // ← 含34种ADPCM变体
#include "ilbc/ffmpeg_ilbc_decoder_plugin.h"
#ifdef SUPPORT_CODEC_TRUEHD
#include "truehd/ffmpeg_truehd_decoder_plugin.h"
#endif
#include "twinvq/ffmpeg_twinvq_decoder_plugin.h"
#include "dvaudio/ffmpeg_dvaudio_decoder_plugin.h"
#ifdef SUPPORT_CODEC_DTS
#include "dts/ffmpeg_dts_decoder_plugin.h"
#endif
#include "cook/ffmpeg_cook_decoder_plugin.h"
```
**解读**：条件编译控制TRUEHD/DTS；adpcm子插件被复用34次（不同ADPCM变体共用同一个FFmpegADPCMDecoderPlugin类，通过codec名称区分）；wma子插件被复用3次（wmaav1/wmav2/wmapro共用FFmpegWMADecoderPlugin）。

### Evidence #2 — codecVec：50个FFmpeg codec名称映射
```
文件：services/media_engine/plugins/ffmpeg_adapter/audio_decoder/ffmpeg_decoder_plugin.cpp
行号：51-83
static const std::vector<std::string_view> codecVec = {
    AVCodecCodecName::AUDIO_DECODER_MP3_NAME,              //  0: mp3
    AVCodecCodecName::AUDIO_DECODER_AAC_NAME,              //  1: aac
    AVCodecCodecName::AUDIO_DECODER_FLAC_NAME,             //  2: flac
    AVCodecCodecName::AUDIO_DECODER_VORBIS_NAME,           //  3: vorbis
    AVCodecCodecName::AUDIO_DECODER_AMRNB_NAME,            //  4: amrnb
    AVCodecCodecName::AUDIO_DECODER_AMRWB_NAME,             //  5: amrwb
    AVCodecCodecName::AUDIO_DECODER_APE_NAME,              //  6: ape
    AVCodecCodecName::AUDIO_DECODER_AC3_NAME,              //  7: ac3
    AVCodecCodecName::AUDIO_DECODER_GSM_NAME,              //  8: gsm
    AVCodecCodecName::AUDIO_DECODER_GSM_MS_NAME,           //  9: gsm_ms
    // ADPCM × 34 复用同一类
    AVCodecCodecName::AUDIO_DECODER_ADPCM_MS_NAME,         // 10: adpcm_ms
    AVCodecCodecName::AUDIO_DECODER_ADPCM_IMA_QT_NAME,     // 11: adpcm_ima_qt
    ...
    AVCodecCodecName::AUDIO_DECODER_ADPCM_YAMAHA_NAME,     // 39: adpcm_yamaha
    AVCodecCodecName::AUDIO_DECODER_WMAV1_NAME,            // 40: wmav1
    AVCodecCodecName::AUDIO_DECODER_WMAV2_NAME,            // 41: wmav2
    AVCodecCodecName::AUDIO_DECODER_WMAPRO_NAME,           // 42: wmapro
    AVCodecCodecName::AUDIO_DECODER_ALAC_NAME,             // 43: alac
    AVCodecCodecName::AUDIO_DECODER_ILBC_NAME,             // 44: ilbc
    // TRUEHD/DTS条件编译
    AVCodecCodecName::AUDIO_DECODER_TWINVQ_NAME,           // 46: twinvq
    AVCodecCodecName::AUDIO_DECODER_DVAUDIO_NAME,          // 47: dvaudio
    AVCodecCodecName::AUDIO_DECODER_COOK_NAME              // 49: cook
};
```
**解读**：50个codec名称用string_view存储，对应FFmpeg内部codec name字符串；ADPCM独占索引10-39（30个变体），WMA占40-42（3个变体）。

### Evidence #3 — codecMimeMap：50个MIME类型映射
```
文件：services/media_engine/plugins/ffmpeg_adapter/audio_decoder/ffmpeg_decoder_plugin.cpp
行号：86-137
static const std::vector<std::string> codecMimeMap = {
    MimeType::AUDIO_MPEG,             // 0: mp3
    MimeType::AUDIO_AAC,              // 1: aac
    MimeType::AUDIO_FLAC,             // 2: flac
    MimeType::AUDIO_VORBIS,           // 3: vorbis
    ...
    MimeType::AUDIO_ADPCM_MS,         // 10: adpcm_ms
    ...
    MimeType::AUDIO_WMAV1,            // 40: wmav1
    MimeType::AUDIO_WMAV2,            // 41: wmav2
    MimeType::AUDIO_WMAPRO,          // 42: wmapro
    MimeType::AUDIO_ALAC,            // 43: alac
    MimeType::AUDIO_ILBC,            // 44: ilbc
    MimeType::AUDIO_COOK             // 49: cook
};
```
**解读**：codecMimeMap与codecVec索引一一对应，共同构成"codec name ↔ MIME type"双向量路由表，由codecInitMap[index]统一驱动初始化。

### Evidence #4 — codecInitMap：函数指针向量驱动模板实例化
```
文件：services/media_engine/plugins/ffmpeg_adapter/audio_decoder/ffmpeg_decoder_plugin.cpp
行号：140-208
static const std::vector<void(*)(const std::string&, const std::string_view&,
                                 CodecPluginDef&, Capability&)> codecInitMap = {
    InitDefinition<FFmpegMp3DecoderPlugin>,    // 0: mp3
    InitDefinition<FFmpegAACDecoderPlugin>,    // 1: aac
    InitDefinition<FFmpegFlacDecoderPlugin>,   // 2: flac
    ...
    InitDefinition<FFmpegADPCMDecoderPlugin>,  // 10-39: ADPCM×30复用同类
    ...
    InitDefinition<FFmpegWMADecoderPlugin>,    // 40-42: WMA×3复用同类
    ...
    InitDefinition<FFmpegCookDecoderPlugin>     // 49: cook
};
```
**解读**：FFmpegADPCMDecoderPlugin被实例化30次（对应30种ADPCM变体），FFmpegWMADecoderPlugin被实例化3次（wmav1/wmav2/wmapro），实现"一模板多注册"节省代码量。

### Evidence #5 — 注册循环：50插件一次性注册
```
文件：services/media_engine/plugins/ffmpeg_adapter/audio_decoder/ffmpeg_decoder_plugin.cpp
行号：211-231
void SetDefinition(size_t index, CodecPluginDef &definition, Capability &cap)
{
    if (index >= codecVec.size() || index >= codecMimeMap.size() || index >= codecInitMap.size()) {
        MEDIA_LOG_I("codec is not supported right now");
        return;
    }
    codecInitMap[index](codecMimeMap[index], codecVec[index], definition, cap);
}

Status RegisterAudioDecoderPlugins(const std::shared_ptr<Register> &reg)
{
    for (size_t i = 0; i < codecVec.size(); i++) {
        CodecPluginDef definition;
        definition.pluginType = PluginType::AUDIO_DECODER;
        definition.rank = 100; // 100:rank
        Capability cap;
        SetDefinition(i, definition, cap);
        cap.AppendFixedKey<CodecMode>(Tag::MEDIA_CODEC_MODE, CodecMode::SOFTWARE);
        definition.AddInCaps(cap);
        if (reg->AddPlugin(definition) != Status::OK) {
            AVCODEC_LOGD("register dec-plugin codecName:%{public}s failed", definition.name.c_str());
        }
    }
    return Status::OK;
}
```
**解读**：注册层循环遍历codecVec，在AddPlugin调用时通过PluginManager建立codec name→具体插件实例的工厂映射；rank=100表示FFmpeg软件解码器的优先级（低于硬件codec）。

---

## 二、FfmpegBaseDecoder 引擎基类

### Evidence #6 — 公开接口（ProcessSendData/ProcessReceiveData为核心）
```
文件：services/media_engine/plugins/ffmpeg_adapter/audio_decoder/ffmpeg_base_decoder.h
行号：23-47
public:
    FfmpegBaseDecoder();
    ~FfmpegBaseDecoder();
    Status ProcessSendData(const std::shared_ptr<AVBuffer> &inputBuffer);  // ← 输入
    Status ProcessReceiveData(std::shared_ptr<AVBuffer> &outBuffer);        // ← 输出
    Status Reset();
    Status Release();
    Status Flush();
    Status AllocateContext(const std::string &name);    // ← 分配FFmpeg codec上下文
    Status InitContext(const std::shared_ptr<Meta> &format);  // ← 初始化采样率/通道布局
    Status OpenContext();                                // ← 打开codec
    void SetMaxInputSize(int32_t setSize);
    std::shared_ptr<Meta> GetFormat() const noexcept;
    std::shared_ptr<AVCodecContext> GetCodecContext() const noexcept;
    void SetCallback(DataCallback *callback);
    bool CheckSampleFormat(const std::shared_ptr<Meta> &format, int32_t channels);
    Status ReceiveBuffer(std::shared_ptr<AVBuffer> &outBuffer);
```
**解读**：基类暴露完整生命周期API（AllocateContext→InitContext→OpenContext→ProcessSendData/ProcessReceiveData循环→Release），供子插件按需调用；内部自行管理AVCodecContext/AVFrame/AVPacket生命周期。

### Evidence #7 — 私有成员：resample_/needResample_/convertedFrame_重采样三件套
```
文件：services/media_engine/plugins/ffmpeg_adapter/audio_decoder/ffmpeg_base_decoder.h
行号：48-56
private:
    std::shared_ptr<AVCodec> avCodec_;
    std::shared_ptr<AVCodecContext> avCodecContext_;
    std::shared_ptr<AVFrame> cachedFrame_;
    std::shared_ptr<AVPacket> avPacket_;
    std::mutex avMutext_;                  // ← codec操作锁
    Ffmpeg::Resample resample_;            // ← SwrContext重采样器
    bool needResample_;                    // ← 重采样使能标志
    std::shared_ptr<AVFrame> convertedFrame_;  // ← 重采样输出帧
    DataCallback *dataCallback_{nullptr};
```
**解读**：needResample_由CheckSampleFormat在SetParameter时判定（若目标格式与codec输出格式不一致则开启）；convertedFrame_在needResample_=true时由InitResample通过av_frame_alloc分配。

### Evidence #8 — 命名空间常量：默认S16LE格式和4种支持格式
```
文件：services/media_engine/plugins/ffmpeg_adapter/audio_decoder/ffmpeg_base_decoder.cpp
行号：18-37
namespace {
constexpr OHOS::HiviewDFX::HiLogLabel LABEL = {LOG_CORE, LOG_DOMAIN_AUDIO, "AvCodec-FfmpegBaseDecoder"};
constexpr AVSampleFormat DEFAULT_FFMPEG_SAMPLE_FORMAT = AV_SAMPLE_FMT_S16;
static std::vector<OHOS::MediaAVCodec::AudioSampleFormat> supportedSampleFormats = {
    OHOS::MediaAVCodec::AudioSampleFormat::SAMPLE_U8,
    OHOS::MediaAVCodec::AudioSampleFormat::SAMPLE_S16LE,
    OHOS::MediaAVCodec::AudioSampleFormat::SAMPLE_S32LE,
    OHOS::MediaAVCodec::AudioSampleFormat::SAMPLE_F32LE
};
static std::set<OHOS::Media::Status> invalidStatus = {
    OHOS::Media::Status::ERROR_NOT_ENOUGH_DATA,
    OHOS::Media::Status::ERROR_UNKNOWN,
    OHOS::Media::Status::ERROR_NO_MEMORY
};
} // namespace
```
**解读**：默认解码输出格式为AV_SAMPLE_FMT_S16（planar S16），若OHOS目标格式不在4种支持列表中则触发重采样；invalidStatus用于过滤 ReceiveFrameSucc返回的可忽略错误。

### Evidence #9 — avcodec_send_packet管线：错误码全分支处理
```
文件：services/media_engine/plugins/ffmpeg_adapter/audio_decoder/ffmpeg_base_decoder.cpp
行号：151-173
auto ret = avcodec_send_packet(avCodecContext_.get(), avPacket_.get());
av_packet_unref(avPacket_.get());
if (ret == 0) {
    SafeCallInputBufferDone(dataCallback_, inputBuffer);
    return Status::OK;
} else if (ret == AVERROR(EAGAIN)) {
    // codec输入缓冲满，需要先调用Receive再Send
    return Status::ERROR_NOT_ENOUGH_DATA;
} else if (ret == AVERROR_EOF) {
    SafeCallInputBufferDone(dataCallback_, inputBuffer);
    return Status::END_OF_STREAM;
} else if (ret == AVERROR_INVALIDDATA) {
    return Status::ERROR_INVALID_DATA;
} else {
    return Status::ERROR_UNKNOWN;
}
```
**解读**：avcodec_send_packet返回0表示成功入队；AVERROR(EAGAIN)表示codec内部缓冲满（需先读取输出）；AVERROR_EOF表示已到EOS；AVERROR_INVALIDDATA表示输入数据格式错误；每次Send后立即av_packet_unref释放packet引用。

### Evidence #10 — avcodec_receive_frame + againIndex_分片输出
```
文件：services/media_engine/plugins/ffmpeg_adapter/audio_decoder/ffmpeg_base_decoder.cpp
行号：188-219
Status FfmpegBaseDecoder::ReceiveBuffer(std::shared_ptr<AVBuffer> &outBuffer)
{
    const bool lastStatusIsAgain = againIndex_ > 0;
    auto ret = lastStatusIsAgain ? 0 : avcodec_receive_frame(avCodecContext_.get(), cachedFrame_.get());
    if (ret >= 0) {
        if (needResample_) {
            if (ConvertPlanarFrame() != Status::OK) { ... }
            outFrame = convertedFrame_;
        }
        int32_t outputSize = outFrame->nb_samples * bytePerSample * outFrame->ch_layout.nb_channels - index;
        if (ioInfoMem->GetCapacity() < outputSize) {
            againIndex_ = index + outputSize;  // ← 输出缓冲不足，记录断点
            outputSize = ioInfoMem->GetCapacity();
        } else {
            againIndex_ = 0;  // ← 完成本次输出
        }
    }
    ...
}
```
**解读**：againIndex_是FFmpeg音频解码器分片输出机制——当OHOS输出缓冲不足以容纳一整帧时，先写部分数据并记录againIndex_，下次ProcessReceiveData直接复用cachedFrame_（不再调用avcodec_receive_frame），直到againIndex_归零。

---

## 三、上下文初始化三阶段

### Evidence #11 — AllocateContext：avcodec_find_decoder_by_name + avcodec_alloc_context3
```
文件：services/media_engine/plugins/ffmpeg_adapter/audio_decoder/ffmpeg_base_decoder.cpp
行号：347-366
Status FfmpegBaseDecoder::AllocateContext(const std::string &name)
{
    std::lock_guard<std::mutex> lock(avMutext_);
    avCodec_ = std::shared_ptr<AVCodec>(
        const_cast<AVCodec *>(avcodec_find_decoder_by_name(name.c_str())),
        [](AVCodec *ptr) { (void)ptr; });
    cachedFrame_ = std::shared_ptr<AVFrame>(av_frame_alloc(), [](AVFrame *fp) { av_frame_free(&fp); });
    CHECK_AND_RETURN_RET_LOG(avCodec_ != nullptr,
        Status::ERROR_INVALID_OPERATION, "AllocateContext failed %{public}s", name.c_str());
    AVCodecContext *context = nullptr;
    {
        std::lock_guard<std::mutex> lock(avMutext_);
        context = avcodec_alloc_context3(avCodec_.get());
        avCodecContext_ = std::shared_ptr<AVCodecContext>(context, [](AVCodecContext *ptr) {
            if (ptr) { avcodec_free_context(&ptr); ptr = nullptr; }
        });
    }
    return Status::OK;
}
```
**解读**：avcodec_find_decoder_by_name根据codec名称字符串（如"aac"）查找FFmpeg内置解码器；avcodec_alloc_context3分配解码器上下文；AVCodec/AVCodecContext/AVFrame均用shared_ptr包装并注册自定义deleter实现自动化释放。

### Evidence #12 — InitContext：采样率+通道布局+extradata三件套
```
文件：services/media_engine/plugins/ffmpeg_adapter/audio_decoder/ffmpeg_base_decoder.cpp
行号：377-404
Status FfmpegBaseDecoder::InitContext(const std::shared_ptr<Meta> &format)
{
    format->GetData(Tag::AUDIO_CHANNEL_COUNT, channels);
    format->GetData(Tag::AUDIO_SAMPLE_RATE, avCodecContext_->sample_rate);
    format->GetData(Tag::MEDIA_BITRATE, avCodecContext_->bit_rate);
    AudioChannelLayout channelLayout = UNKNOWN;
    format->GetData(Tag::AUDIO_CHANNEL_LAYOUT, channelLayout);
    auto ffChannelLayout = FFMpegConverter::ConvertOHAudioChannelLayoutToFFMpeg(channelLayout);
    if (channelLayout != UNKNOWN) {
        if (av_channel_layout_from_mask(&avCodecContext_->ch_layout, ffChannelLayout)) { ... }
    } else if (channels == 1) {
        av_channel_layout_from_mask(&avCodecContext_->ch_layout, AV_CH_LAYOUT_MONO);
    } else if (channels == 2) {
        av_channel_layout_from_mask(&avCodecContext_->ch_layout, AV_CH_LAYOUT_STEREO);
    }
    format->GetData(Tag::AUDIO_MAX_INPUT_SIZE, maxInputSize_);
    Status ret = SetCodecExtradata(format);   // ← 设置AAC等codec的extradata
    avCodecContext_->sample_fmt = AV_SAMPLE_FMT_S16;   // ← 强制输出S16 planer
    avCodecContext_->request_sample_fmt = avCodecContext_->sample_fmt;
    return Status::OK;
}
```
**解读**：InitContext从Meta元数据中提取codec参数；sample_fmt被强制设为AV_SAMPLE_FMT_S16——这意味着AAC/FLAC/Vorbis等无论输入什么格式，FFmpeg解码器输出统一为S16 planar，若OHOS需要其他格式（如S32LE/F32LE）则触发后续重采样。

### Evidence #13 — SetCodecExtradata：从Meta复制AAC/HEVC等解码器私有数据
```
文件：services/media_engine/plugins/ffmpeg_adapter/audio_decoder/ffmpeg_base_decoder.cpp
行号：542-563
Status FfmpegBaseDecoder::SetCodecExtradata(const std::shared_ptr<Meta> &format)
{
    if (format->GetData(Tag::MEDIA_CODEC_CONFIG, config_data)) {
        avCodecContext_->extradata =
            static_cast<uint8_t *>(av_mallocz(config_data.size() + AV_INPUT_BUFFER_PADDING_SIZE));
        avCodecContext_->extradata_size = static_cast<int>(config_data.size());
        errno_t rc = memcpy_s(avCodecContext_->extradata, config_data.size(),
                              config_data.data(), config_data.size());
        rc = memset_s(avCodecContext_->extradata + config_data.size(),
                       AV_INPUT_BUFFER_PADDING_SIZE, 0, AV_INPUT_BUFFER_PADDING_SIZE);
        hasExtra_ = true;
    }
    return Status::OK;
}
```
**解读**：AAC解码需要AudioSpecificConfig（ASC）作为extradata；HEVC需要VPS/SPS/PPS；FFmpeg要求extradata尾端填充AV_INPUT_BUFFER_PADDING_SIZE字节零（防越界读取）；hasExtra_标志影响是否调用avcodec_send_packet时的codec特定处理。

---

## 四、SwrContext 重采样器

### Evidence #14 — InitResample：swr_alloc_set_opts2 + swr_init
```
文件：services/media_engine/plugins/ffmpeg_adapter/audio_decoder/ffmpeg_base_decoder.cpp
行号：427-475
Status FfmpegBaseDecoder::InitResample()
{
    ResamplePara resamplePara;
    resamplePara.channels = static_cast<uint32_t>(avCodecContext_->ch_layout.nb_channels);
    resamplePara.sampleRate = static_cast<uint32_t>(avCodecContext_->sample_rate);
    resamplePara.channelLayout = avCodecContext_->ch_layout;
    resamplePara.destSamplesPerFrame = 0;
    resamplePara.bitsPerSample = 0;
    resamplePara.srcFfFmt = avCodecContext_->sample_fmt;   // ← 源格式=S16 planer
    resamplePara.destFmt = destFmt_;                        // ← 目标格式=OHOS格式
    Status ret = resample_.InitSwrContext(resamplePara);
    convertedFrame_ = std::shared_ptr<AVFrame>(av_frame_alloc(),
        [](AVFrame *fp) { av_frame_free(&fp); });
    needResample_ = true;
    return Status::OK;
}
```
**解读**：InitResample在HandleFirstFrame或CheckFormatChange时触发（首次送帧或格式变化）；ResamplePara封装swr_init所需的6个参数；InitSwrContext在ffmpeg_convert.cpp中调用swr_alloc_set_opts2。

### Evidence #15 — Resample::InitSwrContext：swr_alloc_set_opts2四参数
```
文件：services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_convert.cpp
行号：64-77
Status Resample::InitSwrContext(const ResamplePara &resamplePara)
{
    resamplePara_ = resamplePara;
    auto swrContext = swr_alloc();
    int32_t error = swr_alloc_set_opts2(&swrContext,
        &resamplePara_.channelLayout,   // 输出channel layout
        resamplePara_.destFmt,            // 输出格式（AVSampleFormat）
        resamplePara_.sampleRate,         // 输出采样率
        &resamplePara_.channelLayout,   // 输入channel layout（相同）
        resamplePara_.srcFfFmt,           // 输入格式（AVSampleFormat）
        resamplePara_.sampleRate,         // 输入采样率（相同）
        0, nullptr);
    CHECK_AND_RETURN_RET_LOG(error >= 0, Status::ERROR_UNKNOWN, "swr init error");
    if (swr_init(swrContext) != 0) { ... }
    swrCtx_ = std::shared_ptr<SwrContext>(swrContext, [](SwrContext *ptr) {
        if (ptr) { swr_free(&ptr); ptr = nullptr; }
    });
    return Status::OK;
}
```
**解读**：swr_alloc_set_opts2是FFmpeg 4.x+的现代API，替代旧版swr_alloc_set_opts；第3-4参数=输出格式/采样率，第6-7参数=输入格式/采样率；当输入输出相同时SwrContext仍会创建（FFmpeg内部会优化跳过空操作）。

### Evidence #16 — Resample::ConvertFrame：swr_convert_frame高层API
```
文件：services/media_engine/plugins/ffmpeg_adapter/common/ffmpeg_convert.cpp
行号：178-192
Status Resample::ConvertFrame(AVFrame *outputFrame, const AVFrame *inputFrame)
{
    outputFrame->ch_layout = resamplePara_.channelLayout;
    outputFrame->format = resamplePara_.destFmt;
    outputFrame->sample_rate = static_cast<int>(resamplePara_.sampleRate);
    auto ret = swr_convert_frame(swrCtx_.get(), outputFrame, inputFrame);
    CHECK_AND_RETURN_RET_LOG(ret >= 0, Status::ERROR_UNKNOWN,
        "convert frame failed, %{public}s", AVStrError(ret).c_str());
    return Status::OK;
}
```
**解读**：swr_convert_frame是swr_convert的帧级封装——自动处理planar/packed格式转换、采样率转换、通道重排；outputFrame的format/ch_layout/sample_rate在调用前预先设置，swr_convert_frame内部使用这些字段作为目标格式。

### Evidence #17 — 转换帧→outBuffer写入
```
文件：services/media_engine/plugins/ffmpeg_adapter/audio_decoder/ffmpeg_base_decoder.cpp
行号：221-240
Status FfmpegBaseDecoder::ConvertPlanarFrame()
{
    if (resample_.ConvertFrame(convertedFrame_.get(), cachedFrame_.get()) != Status::OK) {
        return Status::ERROR_UNKNOWN;
    }
    return Status::OK;
}
Status FfmpegBaseDecoder::ReceiveFrameSucc(std::shared_ptr<AVBuffer> &outBuffer)
{
    auto outFrame = cachedFrame_;
    if (needResample_) {
        if (ConvertPlanarFrame() != Status::OK) { return Status::ERROR_UNKNOWN; }
        outFrame = convertedFrame_;  // ← 覆盖输出源
    }
    int32_t bytePerSample = av_get_bytes_per_sample(static_cast<AVSampleFormat>(outFrame->format));
    int32_t outputSize = outFrame->nb_samples * bytePerSample * outFrame->ch_layout.nb_channels - index;
    ioInfoMem->Write(outFrame->data[0] + index, outputSize, 0);  // ← 写outBuffer
    outBuffer->pts_ = cachedFrame_->pts;
    outBuffer->duration_ = duration;
}
```
**解读**：当needResample_=true时，ReceiveFrameSucc将重采样后的convertedFrame_数据写入outBuffer；重采样后convertedFrame_->data[0]包含连续PCM数据，直接写入AVBuffer内存。

---

## 五、子插件模式（FFmpeg AAC子类 + OHOS原生G711mu对比）

### Evidence #18 — FFmpegAACDecoderPlugin子类：组合FfmpegBaseDecoder
```
文件：services/media_engine/plugins/ffmpeg_adapter/audio_decoder/aac/ffmpeg_aac_decoder_plugin.cpp
行号：52-104
FFmpegAACDecoderPlugin::FFmpegAACDecoderPlugin(const std::string& name)
    : CodecPlugin(name), channels_(0), basePlugin(std::make_unique<FfmpegBaseDecoder>())
{ }

Status FFmpegAACDecoderPlugin::SetParameter(const std::shared_ptr<Meta> &parameter)
{
    Status ret = basePlugin->AllocateContext(aacName_);  // "aac" → FFmpeg内部名
    ret = basePlugin->InitContext(parameter);
    ret = basePlugin->OpenContext();  // ← avcodec_open2
    return Status::OK;
}

Status FFmpegAACDecoderPlugin::QueueInputBuffer(const std::shared_ptr<AVBuffer> &inputBuffer)
{
    return basePlugin->ProcessSendData(inputBuffer);  // → avcodec_send_packet
}

Status FFmpegAACDecoderPlugin::QueueOutputBuffer(std::shared_ptr<AVBuffer> &outputBuffer)
{
    return basePlugin->ProcessReceiveData(outputBuffer);  // → avcodec_receive_frame
}
```
**解读**：子插件持有unique_ptr<FfmpegBaseDecoder>，通过组合模式复用基类的FFmpeg管线；SetParameter中调用AllocateContext→InitContext→OpenContext三阶段初始化；QueueInput/OutputBuffer直接代理到基类。

### Evidence #19 — OHOS原生G711muDecoder：零FFmpeg依赖表驱动
```
文件：services/media_engine/plugins/ffmpeg_adapter/audio_decoder/g711mu/audio_g711mu_decoder_plugin.cpp
行号：25-67
constexpr int AUDIO_G711MU_SIGN_BIT = 0x80;
constexpr int AVCODEC_G711MU_QUANT_MASK = 0xf;
constexpr int AVCODEC_G711MU_SHIFT = 4;
constexpr int AVCODEC_G711MU_SEG_MASK = 0x70;
constexpr int G711MU_LINEAR_BIAS = 0x84;

Status AudioG711muDecoderPlugin::ProcessCB(const std::shared_ptr<AVBuffer> &inputBuffer,
                                           std::shared_ptr<AVBuffer> &outputBuffer)
{
    uint8_t* in = static_cast<uint8_t*>(inputBuffer->memory_->GetAddr());
    int32_t inSize = inputBuffer->memory_->GetSize();
    int32_t outSize = inSize * 2;  // μ-law: 1byte → 2bytes(16bit linear)
    int16_t* out = static_cast<int16_t*>(outputBuffer->memory_->GetAddr());
    for (int32_t i = 0; i < inSize; i++) {
        uint8_t ulaw = in[i] ^ AUDIO_G711MU_SIGN_BIT;  // μ-law → linear
        int32_t seg = (ulaw & AVCODEC_G711MU_SEG_MASK) >> AVCODEC_G711MU_SHIFT;
        int32_t q   =  ulaw & AVCODEC_G711MU_QUANT_MASK;
        int32_t a   =  (q << 1) + G711MU_LINEAR_BIAS;
        out[i] = static_cast<int16_t>(a << seg);
    }
    outputBuffer->memory_->SetSize(outSize);
    return Status::OK;
}
```
**解读**：G711muDecoder完全不依赖FFmpeg libavcodec，手写μ-law PCM解码表；每字节输入扩展为2字节16bit线性输出；这是OHOS自研零依赖路径，与FFmpegBaseDecoder基类路径并列存在——体现了架构的双轨决策：FFmpeg支持主流codec，G711mu等少量codec走极简自研路径。

---

## 六、与相关记忆的关联

| 关联记忆 | 关系 |
|---------|------|
| **S125** | S125是FFmpegBaseDecoder/FFmpegDecoderPlugin的前身注册（2026-05-14），S184在此基础上补充了29子插件的具体codec名称映射和G711mu双路径证据 |
| **S130** | S130共享ffmpeg_convert.cpp/ffmpeg_utils.cpp工具链，S184中的Resample重采样器直接依赖S130的Resample类和SwrContext封装 |
| **S50** | S50的AudioResample框架（SwrContext/libswresample）与S184的Resample成员（resample_）是同一FFmpeg重采样组件在不同层次的封装 |
| **S158** | S158是FFmpeg Encoder插件体系，与S184的Decoder体系构成完整的FFmpeg编解码对称架构 |
| **S169** | S169是FFmpeg音频编码器插件体系，与S184的FFmpeg音频解码器体系共同构成FFmpeg音频codec全量覆盖 |

---

## 七、关键架构决策总结

1. **三向量路由**：codecVec（50名称）+ codecMimeMap（50 MIME）+ codecInitMap（50函数指针），通过索引i统一驱动注册
2. **复用模式**：ADPCM×30 + WMA×3 + GSM×2 共用同一子插件类，通过codec名称区分
3. **againIndex_分片**：FFmpeg音频解码器输出帧可能大于OHOS输出缓冲，againIndex_实现跨调用状态续接
4. **双轨codec**：FFmpegBaseDecoder覆盖50种主流codec；OHOS原生G711mu走零依赖表驱动路径（体现极致轻量化）
5. **重采样触发**：InitContext强制sample_fmt=S16P，若OHOS需要其他4种格式则InitResample创建SwrContext
