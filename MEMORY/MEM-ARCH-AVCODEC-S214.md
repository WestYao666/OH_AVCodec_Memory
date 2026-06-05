# MEM-ARCH-AVCODEC-S214 - SurfaceEncoderAdapter 过滤层编码适配器

## 概述

SurfaceEncoderAdapter 是 MediaEngine Filter 层的视频编码适配器，封装 AVCodecVideoEncoder (CodecServer) 的 Surface 输入模式，支持转码(TransCoder)与录制双模式。

**定位**：Filter 层编码器适配器（VideoDecoderAdapter 的对称组件，参考 S212）

**文件路径**：services/media_engine/filters/surface_encoder_adapter.cpp(1037行) + surface_encoder_adapter.h(183行) = 1220行源码

**状态**：draft（Builder 2026-06-05 基于本地镜像生成）

## 证据列表（E1-E20）

### E1 - SurfaceEncoderAdapter 类定义（L73-183 surface_encoder_adapter.h）
SurfaceEncoderAdapter 继承 std::enable_shared_from_this，组合 CodecServer(AVCodecVideoEncoder) + AVBufferQueueProducer(outputBufferQueueProducer_)。关键成员：ProcessStateCode 五态机(curState_)、pauseResumeQueue_双端队列暂停恢复、isTransCoderMode转码模式标志、codecServer_智能指针、releaseBufferTask_后台释放线程。关键回调：EncoderAdapterCallback(错误+格式变化) + EncoderAdapterKeyFramePtsCallback(关键帧PTS+首帧PTS)。

### E2 - SurfaceEncoderAdapterCallback 回调桥接器（L44-86 surface_encoder_adapter.cpp）
SurfaceEncoderAdapterCallback 继承 MediaAVCodec::MediaCodecCallback，实现 OnCodecError/OnOutputFormatChanged/OnInputBufferAvailable/OnOutputBufferAvailable 四路回调桥接。L74 OnOutputBufferAvailable 直接转发 surfaceEncoderAdapter->OnOutputBufferAvailable(index, buffer)。TransCoderMode 专用错误回调 transCoderErrorCbOnce_ 确保转码错误只上报一次。

### E3 - DroppedFramesCallback 丢帧监控回调（L88-106 surface_encoder_adapter.cpp）
DroppedFramesCallback 继承 MediaAVCodec::MediaCodecParameterWithAttrCallback，监控转码模式的丢帧事件。L54 GetIsTransCoderMode() 判断是否转码模式，transCoderErrorCbOnce_ 保证错误只触发一次回调。

### E4 - 构造函数与资源初始化（L109-121 surface_encoder_adapter.cpp）
SurfaceEncoderAdapter() 析构函数释 codecServer_(codecServer_->Release())。L140-142 releaseBufferTask_ = std::make_shared<Task>("SurfaceEncoder") 后台线程处理输出 Buffer 归还，避免阻塞编码管线。

### E5 - Init() + VideoEncoderFactory::CreateByMime（L123-148 surface_encoder_adapter.cpp）
Init(mime, isEncoder) L133 VideoEncoderFactory::CreateByMime(mime, format, codecServer_) 创建视频编码器实例。L135-137 codecServer_空指针检查 + SetFaultEvent("SurfaceEncoderAdapter::Init Create codecServer failed") 错误上报。L150-194 ConfigureGeneralFormat() 设置视频编码通用参数。

### E6 - ConfigureGeneralFormat() 通用编码参数配置（L150-194 surface_encoder_adapter.cpp）
ConfigureGeneralFormat(format, meta) L152 MEDIA_LOG_I("ConfigureGeneralFormat") 开始配置。ConfigureAboutRGBA 处理 RGBA 格式。设置视频分辨率、帧率、码率控制等通用参数。

### E7 - ConfigureEnableFormat() 使能参数配置（L195-204 surface_encoder_adapter.cpp）
ConfigureEnableFormat(format, meta) L197 MEDIA_LOG_I("ConfigureEnableFormat") 配置使能特性：B-Frame使能(BVideoEnableBFrame)、时域可分级(TemporalScale)、水印(AddWatermark)。

### E8 - Configure() 主配置入口（L205-243 surface_encoder_adapter.cpp）
Configure(meta) L208 MediaAVCodec::AVCodecTrace trace("SurfaceEncoderAdapter::Configure") 染色追踪。L210 ConfigureGeneralFormat + L213 ConfigureEnableFormat 双阶段配置。L219-229 非转码模式配置DroppedFramesCallback。L229-238 转码模式配置 surfaceEncoderAdapterCallback。L240 codecServer_->Configure(format)。L242 SetFaultEvent("SurfaceEncoderAdapter::Configure error", ret) 错误处理。

### E9 - SetVideoEnableBFrame() B-Frame使能（L263-271 surface_encoder_adapter.cpp）
SetVideoEnableBFrame(enableBFrame) L265 MEDIA_LOG_I("SurfaceEncoderAdapter::SetVideoEnableBFrame in, enableBFrame is: %{public}d"). L266-268 codecServer_空检查 + SetFaultEvent。enableBFrame_ 成员变量记录B帧使能状态。

### E10 - SetOutputBufferQueue() 输出Buffer队列设置（L282-288 surface_encoder_adapter.cpp）
SetOutputBufferQueue(bufferQueueProducer) L285 outputBufferQueueProducer_ = bufferQueueProducer 建立 AVBufferQueueProducer 连接，后续 OnOutputBufferAvailable/TransCoderOnOutputBufferAvailable 通过此队列推送编码输出。

### E11 - SetEncoderAdapterCallback() 回调注册（L289-308 surface_encoder_adapter.cpp）
SetEncoderAdapterCallback(encoderAdapterCallback) L296-300 codecServer_->SetCallback(surfaceEncoderAdapterCallback) 注册到 CodecServer，L297 SetFaultEvent 错误处理。encoderAdapterCallback_ 成员保存回调实例。

### E12 - SetEncoderAdapterKeyFramePtsCallback() 关键帧PTS回调（L309-315 surface_encoder_adapter.cpp）
SetEncoderAdapterKeyFramePtsCallback 注册关键帧PTS上报回调(OnReportKeyFramePts)和首帧PTS上报回调(OnReportFirstFramePts)，用于转码场景的时间戳同步。

### E13 - SetTransCoderMode() + GetInputSurface()（L317-333 surface_encoder_adapter.cpp）
SetInputSurface(surface) L331 FALSE_RETURN_V_MSG(codecServer_ != nullptr, nullptr) 空检查。L332 return codecServer_->CreateInputSurface() 创建编码输入Surface。L322 SetTransCoderMode() L325 isTransCoderMode = true 设置转码模式标志。

### E14 - Start() + ProcessStateCode::RECORDING（L335-358 surface_encoder_adapter.cpp）
Start() L338 MediaAVCodec::AVCodecTrace trace("SurfaceEncoderAdapter::Start") 染色。L339-342 codecServer_空检查 + SetFaultEvent。L347-348 releaseBufferTask_->Start() 启动后台释放线程。L350 codecServer_->Start() L354 curState_ = ProcessStateCode::RECORDING 状态切换。

### E15 - Stop() + HandleWaitforStop() + pauseResumeQueue_（L363-416 surface_encoder_adapter.cpp）
Stop() L366 AVCodecTrace染色。L369-372 isTransCoderMode=false时处理暂停状态：stopTime_=pauseTime_ + HandleWaitforStop()。L375-386 处理录制状态：HandleWaitforStop() + AddStopPts()。L392-399 releaseBufferTask_->Stop() 停止后台线程。L409 curState_ = ProcessStateCode::STOPPED 状态切换。

### E16 - Pause() + pauseResumeQueue_双队列（L418-439 surface_encoder_adapter.cpp）
Pause() L421 AVCodecTrace染色。L423-424 isTransCoderMode=true时直接返回(L422 return Status::OK)。L430-435 pauseResumeQueue_.push_back({pauseTime_, StateCode::PAUSE}) + {numeric_limits<int64_t>::max(), StateCode::RESUME} 双元素占位。L437 curState_ = ProcessStateCode::PAUSED 状态切换。pauseResumePts_ 同步记录PTS。

### E17 - Resume() + totalPauseTime_累计暂停时间（L441-471 surface_encoder_adapter.cpp）
Resume() L444 AVCodecTrace染色。L445-446 isTransCoderMode=true时设置isResume_=true并返回。L457-458 pauseResumeQueue_.back().first = min(resumeTime_, ...) 更新RESUME时间。L462 totalPauseTime_ = totalPauseTime_ + resumeTime_ - pauseTime_ 累加暂停时长。L463-465 totalPauseTimeQueue_.push_back(totalPauseTime_) 记录历史。L468 curState_ = ProcessStateCode::RECORDING 恢复录制。

### E18 - OnOutputBufferAvailable() + TransCoderOnOutputBufferAvailable()（L569-629 surface_encoder_adapter.cpp）
TransCoderOnOutputBufferAvailable(index, buffer) L577 outputBufferQueueProducer_->RequestBuffer(emptyOutputBuffer, ...) 请求空Buffer。L592 outputBufferQueueProducer_->PushBuffer(emptyOutputBuffer, true) 归还编码器Buffer。OnOutputBufferAvailable(index, buffer) L605-607 AVCodecTrace染色 + L607 isTransCoderMode判断：true→TransCoderOnOutputBufferAvailable，false→普通路径。L617-626 普通路径：RequestBuffer+CopyBuffer+PushBuffer输出到队列。L629 indexs_.push_back(index) 记录待释放Buffer索引。

### E19 - releaseBufferTask_ 后台Buffer释放线程（L140-148 + L651-671 surface_encoder_adapter.cpp）
L141-142 releaseBufferTask_ = make_shared<Task>("SurfaceEncoder") + RegisterJob注册任务。L651-654 释放逻辑：indexs = indexs_（原子交换）+ indexs_.clear() + codecServer_->ReleaseOutputBuffer(index, false) 归还编码器Buffer。L652 isThreadExit_ || !indexs_.empty() 退出条件。

### E20 - ProcessStateCode 五态机（L67-71 surface_encoder_adapter.h）
enum ProcessStateCode { IDLE, RECORDING, PAUSED, STOPPED, ERROR }。curState_ 成员变量贯穿Start(PROCESS_STATE::RECORDING)/Stop(STOPPED)/Pause(PAUSED)/Resume(RECORDING)/Flush(ERROR)/Reset(IDLE)全生命周期。L158 curState_ = ProcessStateCode::ERROR 错误状态转换。

## 架构图

```
SurfaceEncoderAdapter (Filter适配器)
├── codecServer_ (AVCodecVideoEncoder / CodecServer)
├── outputBufferQueueProducer_ (AVBufferQueueProducer)
├── surfaceEncoderAdapterCallback_ (EncoderAdapterCallback)
├── pauseResumeQueue_ (deque<pair<int64_t, StateCode>>)
├── totalPauseTimeQueue_ (deque<int64_t>)
├── releaseBufferTask_ (Task后台释放线程)
└── ProcessStateCode五态机 (IDLE/RECORDING/PAUSED/STOPPED/ERROR)

SurfaceEncoderAdapterCallback 桥接 CodecServer → Filter
    └── onOutputBufferAvailable → outputBufferQueueProducer_->PushBuffer

DroppedFramesCallback 监控转码丢帧
```

## 关联主题

- **S212** VideoDecoderAdapter：对称的视频解码适配器（AVBufferQueue双队列 + CodecEngine三层回调）
- **S45/S46/S39** DecoderFilter系列：上游Filter链
- **S55** CodecCallback：回调链路体系
- **S92** MediaCodec：CodecServer IPC封装
- **S113** SeiParserFilter：Filter Chain架构

## 源码路径

```
/home/west/av_codec_repo/services/media_engine/filters/surface_encoder_adapter.cpp (1037行)
/home/west/av_codec_repo/services/media_engine/filters/surface_encoder_adapter.h (183行)
```

## 备注

- SurfaceEncoderAdapter vs VideoDecoderAdapter 对称设计：编码/解码双方向
- isTransCoderMode 决定输出路径（TransCoderOnOutputBufferAvailable vs OnOutputBufferAvailable）
- pauseResumeQueue_ 双端队列实现 Pause/Resume 时序控制，totalPauseTimeQueue_ 累计暂停时长
- releaseBufferTask_ 后台线程防止编码器Buffer阻塞
- 与 S212 VideoDecoderAdapter 共同构成 Filter 层 CodecEngine 双向桥接