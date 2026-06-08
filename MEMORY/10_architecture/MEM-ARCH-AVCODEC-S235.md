# MEM-ARCH-AVCODEC-S235: AudioCodecAdapter + AudioCodecWorker 双组件架构

## 概述

**主题**: AudioCodecAdapter + AudioCodecWorker 双组件架构——CodecBase适配器+双TaskThread流水线+AudioBuffersManager双缓冲池

**Scope**: AVCodec, AudioCodec, AudioCodecAdapter, AudioCodecWorker, CodecBase, TaskThread, AudioBuffersManager, Pipeline, CodecState, ProcessSendData, ProcessRecieveData

**关联场景**: 新需求开发/问题定位/音频编码解码/新人入项

**来源**: 本地镜像 /home/west/av_codec_repo

---

## 架构概览

```
AudioCodecAdapter (CodecBase子类)
  ├── state_ (std::atomic<CodecState>)
  ├── audioCodec (std::shared_ptr<AudioBaseCodec>)  ← 核心编解码引擎
  ├── worker_ (std::shared_ptr<AudioCodecWorker>)    ← 双线程驱动
  └── callback_ (std::shared_ptr<AVCodecCallback>)

AudioCodecWorker
  ├── inputTask_ (TaskThread, "OS_AuCodecIn")  → ProduceInputBuffer()
  ├── outputTask_ (TaskThread, "OS_AuCodecOut") → ConsumerOutputBuffer()
  ├── inputBuffer_ (AudioBuffersManager)  ← 输入缓冲池 (8个buffer)
  ├── outputBuffer_ (AudioBuffersManager) ← 输出缓冲池 (8个buffer)
  ├── codec_ (AudioBaseCodec)             ← 核心编解码引擎
  └── inBufIndexQue_ / inBufAvaIndexQue_ ← 队列协调
```

三层调用链：
1. **AudioCodecAdapter** (C++ API层) → 处理外部API调用（SetCallback/Configure/Start/Stop/QueueInputBuffer等）
2. **AudioCodecWorker** (线程调度层) → 双TaskThread驱动input/output流水线
3. **AudioBaseCodec** (编解码引擎层) → 实际编解码实现（FFmpeg/硬件编解码器）

---

## Evidence（行号级证据）

**E1** (audio_codec_adapter.h L19-55): AudioCodecAdapter类定义——继承CodecBase和NoCopyable，成员包含state_/name_/callback_/audioCodec/worker_，实现了完整的CodecBase生命周期API

**E2** (audio_codec_adapter.cpp L32-42): 析构函数——释放worker_/callback_/audioCodec，调用mallopt(M_FLUSH_THREAD_CACHE, 0)清理线程缓存资源

**E3** (audio_codec_adapter.cpp L47-53): SetCallback——状态校验（RELEASED/INITIALIZED/INITIALIZING才可设回调），防重复设置

**E4** (audio_codec_adapter.cpp L325-345): doInit——AudioBaseCodec::make_sharePtr(name_)创建核心编解码引擎，状态从RELEASED→INITIALIZED

**E5** (audio_codec_adapter.cpp L347-363): doConfigure——audioCodec->Init(format)初始化codec，mallopt禁用线程缓存优化（内存分配策略），状态INITIALIZED→CONFIGURED

**E6** (audio_codec_adapter.cpp L368-379): doStart——创建AudioCodecWorker(audioCodec, callback_)，调用worker_->Start()启动双线程，状态STARTING→RUNNING

**E7** (audio_codec_adapter.cpp L155-184): QueueInputBuffer——输入缓冲入队流程：校验callback_/audioCodec/bufferSize，worker_->GetInputBufferInfo(index)获取buffer，SetUsing()标记占用，PushInputData(index)推入worker

**E8** (audio_codec_adapter.cpp L186-201): ReleaseOutputBuffer——输出缓冲释放：worker_->GetOutputBufferInfo(index)获取outBuffer，callback_->OnOutputBufferAvailable回调给客户端

**E9** (audio_codec_adapter.cpp L383-392): doResume——FLUSHED状态恢复：worker_->Start()重新启动双线程，状态RESUMING→RUNNING

**E10** (audio_codec_worker.h L30-60): AudioCodecWorker类定义——双TaskThread(inputTask_/outputTask_)+双AudioBuffersManager(inputBuffer_/outputBuffer_)+四队列mutex(inAvaMutex_/inputMutex_/outputMutex_/stateMutex_)+双condition_variable

**E11** (audio_codec_worker.cpp L36-43): 构造函数——DEFAULT_BUFFER_COUNT=8，inputTask_创建"OS_AuCodecIn"线程，outputTask_创建"OS_AuCodecOut"线程，inputBuffer_/outputBuffer_各8个buffer，Begin()预填充inBufAvaIndexQue_(0-7)

**E12** (audio_codec_worker.cpp L52-53): 线程注册——inputTask_->RegisterHandler([this]{ProduceInputBuffer()})注册输入线程处理函数；outputTask_->RegisterHandler([this]{ConsumerOutputBuffer()})注册输出线程处理函数

**E13** (audio_codec_worker.cpp L232-256): ProduceInputBuffer——输入缓冲生产：当inBufAvaIndexQue_非空时，循环pop索引→GetInputBufferInfo(index)→SetBufferOwned()→callback_->OnInputBufferAvailable(index, buffer)通知客户端；超时1000ms等待

**E14** (audio_codec_worker.cpp L261-282): HandInputBuffer——输入处理核心：pop inBufIndexQue_获取索引→GetInputBufferInfo→CheckIsEos检测EOS→codec_->ProcessSendData(inputBuffer)发送数据→ReleaseBuffer→push回inBufAvaIndexQue_完成循环

**E15** (audio_codec_worker.cpp L307-355): ConsumerOutputBuffer——输出缓冲消费：当inBufIndexQue_非空时：HandInputBuffer处理输入→outputBuffer_->RequestAvailableIndex获取输出索引→codec_->ProcessRecieveData(outBuffer)接收编码结果→callback_->OnOutputBufferAvailable回调

**E16** (audio_codec_worker.cpp L374-394): Begin——启动初始化：预填充inBufAvaIndexQue_(0到bufferCount-1)，设置isRunning=true，SetRunning()激活两个buffer池，Start()启动inputTask_和outputTask_，notify_all唤醒条件变量

**E17** (audio_codec_worker.cpp L115-130): Stop——停止流程：Dispose()设置isRunning=false并notify_all，inputTask_->StopAsync()/outputTask_->StopAsync()停止线程，ReleaseAllInBufferQueue/ReleaseAllInBufferAvaQueue清空队列，inputBuffer_->ReleaseAll()/outputBuffer_->ReleaseAll()释放所有buffer

**E18** (audio_codec_worker.cpp L145-173): Pause/Resume——暂停恢复：Pause调用Dispose()并StopAsync线程，Resume重新调用Begin()恢复流水线；Dispose()原子设置isRunning=false并notify input/output条件变量

**E19** (audio_codec_adapter.cpp L163-180): doFlush——Flush流程：状态RUNNING→FLUSHING，调用doFlush()清空缓冲，状态→FLUSHED；Flush时Worker的input/outputTask继续运行但isRunning=false停止生产

**E20** (audio_codec_adapter.cpp L203-226): doRelease——Release流程：RELEASING→RELEASED状态转换，doRelease()释放audioCodec/worker_资源

**E21** (audio_codec_worker.cpp L289-305): ReleaseOutputBuffer——错误处理：ret非OK/END_OF_STREAM时ReleaseOutputBuffer(index, ret)记录错误状态，可能触发OnError回调

**E22** (audio_codec_worker.cpp L77-96): PushInputData——入队入口：PushInputData检查isRunning/callback_/codec_三检查，Dispose()错误处理，stateMutex_锁保护，inBufIndexQue_入队完成生产循环

**E23** (audio_codec_adapter.cpp L214-220): NotifyEos——EOS通知：NotifyEos调用Flush()实现EOS传播，FLUSHED状态后客户端收到EOS回调

**E24** (audio_codec_adapter.cpp L228-239): GetOutputFormat——格式查询：GetOutputFormat查询codec输出格式(format = audioCodec->GetFormat())，若缺少MD_KEY_CODEC_NAME则补充name_，AVCS_ERR_NO_MEMORY空指针保护

---

## 关键设计模式

### 1. 双缓冲队列协调
- `inBufAvaIndexQue_`: 客户端可用输入缓冲索引队列（初始填充0-7）
- `inBufIndexQue_`: 已排队待处理输入缓冲索引队列
- 生产者（ProduceInputBuffer）从inBufAvaIndexQue_取索引回调客户端
- 消费者（ConsumerOutputBuffer）从inBufIndexQue_取索引调用codec处理

### 2. TaskThread双线程流水线
- `OS_AuCodecIn`: 驱动ProduceInputBuffer()，等待inBufAvaIndexQue_非空时通知客户端OnInputBufferAvailable
- `OS_AuCodecOut`: 驱动ConsumerOutputBuffer()，等待inBufIndexQue_非空时执行codec处理+OnOutputBufferAvailable

### 3. CodecState状态机
RELEASED → INITIALIZING → INITIALIZED → CONFIGURED → STARTING → RUNNING → FLUSHED → CONFIGURED
                    ↑______________|            ↓                              ↓
                    (doInit失败)     (doStop)    (doFlush)                    (doResume)

### 4. 生命周期资源管理
- 析构函数释放所有资源（worker/callback/audioCodec）
- mallopt(M_FLUSH_THREAD_CACHE/M_DELAYED_FREE)禁用内存分配优化
- AudioCodecWorker析构调用Dispose+ResetTask+ReleaseAllBuffer

---

## 关联记忆

| 关联ID | 关系 |
|--------|------|
| S62 | AudioBuffersManager——Worker内的inputBuffer_/outputBuffer_都是AudioBuffersManager实例 |
| S35 | AudioDecoderFilter——Filter层适配器，AudioCodecAdapter是Engine层适配器 |
| S18 | AudioCodecServer——SA级服务，AudioCodecAdapter是Engine层Codec实例 |
| S95 | AudioCodec C API——Native层API通过AudioCodecAdapter分发到底层引擎 |
| S125 | FFmpeg音频编解码器——AudioBaseCodec的具体实现之一 |

---

## 附录：关键文件路径

```
services/engine/codec/audio/audio_codec_adapter.cpp   (467行)
services/engine/codec/audio/audio_codec_adapter.h      → include/audio/audio_codec_adapter.h
services/engine/codec/audio/audio_codec_worker.cpp     (429行)
services/engine/codec/include/audio/audio_codec_worker.h
services/engine/codec/include/audio/audio_base_codec.h
services/engine/codec/audio/audio_buffers_manager.cpp  (S62覆盖)
```