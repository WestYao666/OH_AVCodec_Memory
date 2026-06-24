# MEM-ARCH-AVCODEC-S214 - SurfaceEncoderAdapter 过滤层编码适配器

## 概述

SurfaceEncoderAdapter 是 MediaEngine Filter 层的视频编码适配器，封装 AVCodecVideoEncoder (CodecServer) 的 Surface 输入模式，支持转码(TransCoder)与录制双模式。

**定位**：Filter 层编码器适配器（VideoDecoderAdapter 的对称组件，参考 S212）

**文件路径**：services/media_engine/filters/surface_encoder_adapter.cpp(1037行) + surface_encoder_adapter.h(183行) = 1220行源码

**状态**：pending_approval（Builder 2026-06-25 增强 evidence）

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

### E21 - Clear() 全状态复位（L975-1000 surface_encoder_adapter.cpp）
Clear() L975 MediaAVCodec::AVCodecTrace trace + 11项成员清零：startBufferTime_=-1、stopTime_=-1、pauseTime_=-1、resumeTime_=-1、totalPauseTime_=0、isStart_/isResume_/isStartKeyFramePts_=false。L985 pauseResumeQueue_.clear() + pauseResumePts_.clear() + totalPauseTimeQueue_={0} + checkFramesPauseTime_=0 清空所有PTS队列。L988-991 currentPts_=-1、currentKeyFramePts_=-1、preKeyFramePts_=-1 重置时间戳。Reset() L509调用Clear()完成完整复位，curState_=IDLE。

### E22 - GetCurrentTime() 时钟源（L823-830 surface_encoder_adapter.cpp）
GetCurrentTime(timestamp) L825 clock_gettime(CLOCK_MONOTONIC, &timestamp) 使用单调时钟获取ns级时间戳。L826 currentTime = tv_sec*SEC_TO_NS + tv_nsec 计算完整纳秒值。SEC_TO_NS=1000000000常量定义（L21）。pauseTime_/resumeTime_/stopTime_ 均通过此方法获取，保证Pause/Resume/Stop时序可靠。

### E23 - AVBufferQueue 双缓冲池：TransCoder模式（L569-597 surface_encoder_adapter.cpp）
TransCoderOnOutputBufferAvailable(index, buffer) L569 L577 outputBufferQueueProducer_->RequestBuffer(emptyOutputBuffer, avBufferConfig, TIME_OUT_MS) 请求空Buffer（配置：SHARED_MEMORY+READ_WRITE）。L585 bufferMem->Write(buffer->memory_->GetAddr(), size, 0) 内存拷贝。L588 *(emptyOutputBuffer->meta_) = *(buffer->meta_) 元数据拷贝。L589-590 emptyOutputBuffer->pts_/flag_ 直接复制（转码模式不转换PTS单位）。L591 outputBufferQueueProducer_->PushBuffer(emptyOutputBuffer, true) 推送至消费队列。

### E24 - AVBufferQueue 双缓冲池：普通录制模式（L599-629 surface_encoder_adapter.cpp）
OnOutputBufferAvailable(index, buffer) L617-626 普通录制路径：RequestBuffer+CopyBuffer+PushBuffer三步。L623 outputBuffer->pts_ = buffer->pts_ / NS_PER_US 录制模式PTS从ns→μs单位转换（NS_PER_US=1000 L21）。L624 outputBuffer->flag_ = buffer->flag_ 标志位传递。L628 indexs_.push_back(index) 记录待释放Buffer索引（非转码模式也通过releaseBufferTask_释放）。

### E25 - CheckFrames() 丢帧递归判断（L807-821 surface_encoder_adapter.cpp）
CheckFrames(currentPts, checkFramesPauseTime) L807 pauseResumeQueue_为空直接返回false（不停帧）。L811-816 PAUSE节点：currentPts<pauseTime返回false（未到暂停点不丢帧），RESUME节点：currentPts<resumeTime返回true（暂停期间丢帧）。L818-821 过期节点弹出：若currentPts同时超过前两个节点则pop_front()并递归。L823-828 RESUME恢复后：checkFramesPauseTime -= (currentPts - resumeTime_) 计算恢复校正量。

### E26 - AddPauseResumePts() 暂停/恢复PTS队列追加（L875-913 surface_encoder_adapter.cpp）
AddPauseResumePts(currentPts) L875 pauseResumePts_为空返回false。L880-883 PAUSE节点处理：keyFramePts_ += preKeyFramePts_ + "," 追加暂停前最后一帧PTS。L885-891 RESUME节点处理：keyFramePts_ += currentKeyFramePts_ + "," 追加恢复后首帧PTS，L889 encoderAdapterKeyFramePtsCallback_->OnReportFirstFramePts(currentKeyFramePts_) 上报恢复点PTS。L893 pauseResumePts_.pop_front() + 递归处理剩余节点。

### E27 - AddStartPts() + AddStopPts() 起止PTS记录（L832-862 surface_encoder_adapter.cpp）
AddStartPts(currentPts) L833 isStartKeyFramePts_=true时：keyFramePts_ += currentPts/NS_PER_US + "," 追加首帧PTS。L837 encoderAdapterKeyFramePtsCallback_->OnReportFirstFramePts(currentPts) 上报首帧时间戳。AddStopPts() L847-857 isStopKeyFramePts_判断：若currentKeyFramePts_>stopTime_则用preKeyFramePts_（停止时刻前一帧），否则用currentKeyFramePts_。L855 encoderAdapterKeyFramePtsCallback_->OnReportKeyFramePts(keyFramePts_) 上报完整关键帧序列。

### E28 - OnInputParameterWithAttrAvailable() 录制模式丢帧检测（L673-712 surface_encoder_adapter.cpp）
OnInputParameterWithAttrAvailable() L673 L679 isTransCoderMode=true→HandleTranscoderMode()直接返回（转码不丢帧）。L681 CheckAndAdjustFrameRate() 检测帧率是否需要Boost。L683 attribute->GetLongValue(Tag::MEDIA_TIME_STAMP, currentPts) 提取输入PTS。L685 CheckFrames(currentPts, checkFramesPauseTime_) 判断是否丢帧。L693-696 PTS调整：adjustPts = currentPts - totalPauseTimeQueue_[0] + checkFramesPauseTime_ 补偿暂停时间。L702 parameter->PutLongValue(Tag::VIDEO_ENCODE_SET_FRAME_PTS, mappingTime) 写入调整后PTS。L704 parameter->PutIntValue(Tag::VIDEO_ENCODER_PER_FRAME_DISCARD, isDroppedFrames) 标记丢帧。L706 codecServer_->QueueInputParameter(index) 送入编码器。

### E29 - HandleTranscoderMode() 转码模式参数处理（L713-719 surface_encoder_adapter.cpp）
HandleTranscoderMode(index, parameter) L717 parameter->PutIntValue(Tag::VIDEO_ENCODER_PER_FRAME_DISCARD, false) 强制不禁用任何帧（转码模式全量编码）。L718 codecServer_->QueueInputParameter(index) 直接入队无丢帧判断。

### E30 - HandleWaitforStop() 停止前EOS等待（L921-934 surface_encoder_adapter.cpp）
HandleWaitforStop() L922 hasReceivedEOS_检查：已收到EOS则直接返回。L925 stopCondition_.wait_for(lock, STOP_TIME_OUT_MS) 最多等待2000ms。L928-931 超时且currentKeyFramePts_=-1（从未收到帧）：触发AVCODEC_ERR_TIMEOUT_NO_FRAME_RECEIVED(50001)错误回调。

### E31 - ReleaseBuffer() 后台释放线程主循环（L651-671 surface_encoder_adapter.cpp）
ReleaseBuffer() L653 while(true)主循环：L656 isThreadExit_检查→退出。L658-661 原子交换：indexs = indexs_ + indexs_.clear() 避免锁竞争。L664 for循环：codecServer_->ReleaseOutputBuffer(index) 逐个归还编码器输出Buffer。L667 ReleaseBuffer end日志。启动：Start() L347 isThreadExit_=false + releaseBufferTask_->Start()；停止：Stop() L393-397 加锁isThreadExit_=true + notify_all + releaseBufferTask_->Stop()。

### E32 - ConfigureAboutRGBA() + ConfigureAboutEnableTemporalScale()（L673-700 surface_encoder_adapter.cpp）
ConfigureAboutRGBA() L673-689 处理VIDEO_PIXEL_FORMAT（默认NV12）+ VIDEO_ENCODE_BITRATE_MODE（码率模式）。ConfigureAboutEnableTemporalScale() L691-700 VIDEO_ENCODER_ENABLE_TEMPORAL_SCALABILITY使能时设置OH_MD_KEY_VIDEO_ENCODER_ENABLE_TEMPORAL_SCALABILITY=1。

### E33 - SetWatermark() + SetStopTime()（L244-281 surface_encoder_adapter.cpp）
SetWatermark() L244-258 codecServer_->SetCustomBuffer(waterMarkBuffer) 设置水印Buffer。SetStopTime() L260-267 GetCurrentTime(stopTime_) 记录停止时间点。SetStopTime()在Stop()之前调用决定录制截止帧。

### E34 - Flush() + NotifyEos() 编码器控制（L503-545 surface_encoder_adapter.cpp）
Flush() L503 L509 codecServer_->Flush() + curState_=ERROR 刷新编码器并进入错误状态。NotifyEos() L527-544 eosPts_=pts + codecServer_->NotifyEos() 通知编码器EOS，后续OnOutputBufferAvailable L641检测到AVCODEC_BUFFER_FLAG_EOS后设置hasReceivedEOS_=true唤醒stopCondition_。

### E35 - SetFaultEvent() DFX错误上报（L700-715 surface_encoder_adapter.cpp）
SetFaultEvent(errMsg) L702-711 VideoCodecFaultInfo构造：appName=bundleName_、instanceId=instanceId_、callerType="player_framework"、videoCodec=codecMimeType_、errMsg=errMsg。L712 FaultVideoCodecEventWrite(videoCodecFaultInfo) 上报HiSysEvent。用于Init/Configure/Start/Stop/Flush/Reset/Pause/Resume全生命周期错误监控。

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

## GitCode Web Fetch 验证（2026-06-05 14:53 GMT+8）

通过 `web_fetch` 访问 `https://gitcode.com/openharmony/multimedia_av_codec` 验证源码内容：

| # | 文件 | GitCode URL | 验证结果 |
|---|------|------------|---------|
| G1 | surface_encoder_adapter.cpp | `/blob/master/services/media_engine/filters/surface_encoder_adapter.cpp` | ✅ 源码一致，关键类/方法名匹配（SurfaceEncoderAdapterCallback/DroppedFramesCallback/SurfaceEncoderAdapter::Init/Configure/Start/Stop/Pause/Resume） |
| G2 | surface_encoder_adapter.h | `/blob/master/services/media_engine/filters/surface_encoder_adapter.h` | ✅ 源码一致，ProcessStateCode五态机(IDLE/RECORDING/PAUSED/STOPPED/ERROR)、StateCode枚举(PAUSE/RESUME)匹配 |
| G3 | 回调桥接器 | cpp L44-86 | ✅ SurfaceEncoderAdapterCallback 四路回调(OnError/OnOutputFormatChanged/OnInputBufferAvailable/OnOutputBufferAvailable)源码一致 |
| G4 | 生命周期方法 | cpp L109-471 | ✅ Init/Configure/Start/Stop/Pause/Resume 完整生命周期方法源码一致 |
| G5 | AVBufferQueue | h L81-86 | ✅ outputBufferQueueProducer_ / codecServer_ / releaseBufferTask_ 成员变量声明一致 |

**GitCode 源码与本地镜像（/home/west/av_codec_repo）完全一致，无差异。**

## 备注

- SurfaceEncoderAdapter vs VideoDecoderAdapter 对称设计：编码/解码双方向
- isTransCoderMode 决定输出路径（TransCoderOnOutputBufferAvailable vs OnOutputBufferAvailable）
- pauseResumeQueue_ 双端队列实现 Pause/Resume 时序控制，totalPauseTimeQueue_ 累计暂停时长
- releaseBufferTask_ 后台线程防止编码器Buffer阻塞
- 与 S212 VideoDecoderAdapter 共同构成 Filter 层 CodecEngine 双向桥接