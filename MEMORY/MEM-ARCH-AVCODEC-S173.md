# MEM-ARCH-AVCODEC-S173

## 主题
AudioCodecAdapter + AudioCodecWorker 音频编解码适配器——AudioBaseCodec工厂注入与双TaskThread驱动

## 状态
status: draft

## 生成时间
2026-05-25T22:48:00+08:00

## Builder
builder-agent (subagent)

---

## source_files
| 文件 | 行数 | 职责 |
|------|------|------|
| services/engine/codec/audio/audio_codec_adapter.cpp | 467 | AudioCodecAdapter 适配器（CodecBase子类），状态机管理，工厂创建AudioBaseCodec |
| services/engine/codec/include/audio/audio_codec_adapter.h | 77 | AudioCodecAdapter 类定义 |
| services/engine/codec/audio/audio_codec_worker.cpp | 429 | AudioCodecWorker 双TaskThread驱动，输入/输出缓冲管理 |
| services/engine/codec/include/audio/audio_codec_worker.h | 95 | AudioCodecWorker 类定义 |

---

## evidence_count
20

---

## 20条行号级 evidence

E1: audio_codec_adapter.cpp(L30) — AudioCodecAdapter构造函数：state_(CodecState::RELEASED)，初始化即进入已释放态，符合CodecBase生命周期规范

E2: audio_codec_adapter.cpp(L49) — SetCallback接收shared_ptr<AVCodecCallback>，状态必须为RELEASED/INITIALIZED/INITIALIZING才允许设置回调

E3: audio_codec_adapter.cpp(L64) — Init(Media::Meta)进入INITIALIZING状态，state_必须为RELEASED才允许初始化

E4: audio_codec_adapter.cpp(L71) — Init成功后state_从INITIALIZING转为INITIALIZED

E5: audio_codec_adapter.cpp(L100) — Configure配置格式，state_必须为INITIALIZED

E6: audio_codec_adapter.cpp(L111) — Start()：state_为FLUSHED时特殊处理（从FLUSHED直接返回RUNNING），否则state_必须为CONFIGURED

E7: audio_codec_adapter.cpp(L121) — Start后state_经STARTING最终转为RUNNING

E8: audio_codec_adapter.cpp(L133) — Stop()允许的状态：INITIALIZED/CONFIGURED，state_设为STOPPING后回到CONFIGURED

E9: audio_codec_adapter.cpp(L152) — Flush()：state_必须为RUNNING才允许刷新，否则报错

E10: audio_codec_adapter.cpp(L162) — Flush状态从FLUSHING最终转为FLUSHED

E11: audio_codec_adapter.cpp(L335) — AudioBaseCodec::make_sharePtr(name_)工厂方法创建具体AudioCodec实例，adapter持有audioCodec_成员

E12: audio_codec_adapter.cpp(L378) — Start时创建AudioCodecWorker：worker_ = make_shared<AudioCodecWorker>(audioCodec, callback_)，注入AudioBaseCodec实例

E13: audio_codec_worker.cpp(L32-33) — INPUT_BUFFER="inputBuffer" / OUTPUT_BUFFER="outputBuffer" 常量定义，标识双缓冲池角色

E14: audio_codec_worker.cpp(L34-35) — ASYNC_HANDLE_INPUT="OS_AuCodecIn" / ASYNC_DECODE_FRAME="OS_AuCodecOut" TaskThread命名，标识输入/输出异步线程

E15: audio_codec_worker.cpp(L37) — AudioCodecWorker构造函数接收shared_ptr<AudioBaseCodec>，完成codec_注入

E16: audio_codec_worker.cpp(L46-47) — 创建inputTask_(OS_AuCodecIn)和outputTask_(OS_AuCodecOut)两个TaskThread线程

E17: audio_codec_worker.cpp(L49-50) — 创建inputBuffer_和outputBuffer_两个AudioBuffersManager缓冲池（各DEFAULT_BUFFER_COUNT个缓冲区）

E18: audio_codec_worker.cpp(L52-53) — RegisterHandler将ProduceInputBuffer()注册给inputTask_，ConsumerOutputBuffer()注册给outputTask_

E19: audio_codec_worker.cpp(L232) — ProduceInputBuffer()：inputTask_线程驱动，从inputBuffer_取可用缓冲区，调用codec_->ProcessSendData()送入编码/解码

E20: audio_codec_worker.cpp(L307) — ConsumerOutputBuffer()：outputTask_线程驱动，消费codec_输出，回调OnOutputBufferAvailable

---

## 架构摘要

### 三层调用链
```
AudioCodecAdapter (L30/L378)
  └─持有 audioCodec_ = AudioBaseCodec::make_sharePtr()  (L335)
       └─注入 worker_ = AudioCodecWorker(audioCodec, callback_)  (L378)
            ├─inputTask_(OS_AuCodecIn) → ProduceInputBuffer()  (L46/L52)
            ├─outputTask_(OS_AuCodecOut) → ConsumerOutputBuffer()  (L47/L53)
            ├─inputBuffer_(AudioBuffersManager)  (L49)
            └─outputBuffer_(AudioBuffersManager)  (L50)
```

### AudioCodecAdapter 状态机（七态）
RELEASED → INITIALIZING → INITIALIZED → CONFIGURED → STARTING → RUNNING → FLUSHING → FLUSHED
stop时回退到CONFIGURED，reset时回退到INITIALIZED

### AudioCodecWorker 双TaskThread
- OS_AuCodecIn：驱动ProduceInputBuffer()，从inputBuffer_取空闲缓冲区，填入数据后送codec_->ProcessSendData()
- OS_AuCodecOut：驱动ConsumerOutputBuffer()，从outputBuffer_取已填充缓冲区，回调OnOutputBufferAvailable

### AudioBaseCodec工厂注入
AudioCodecAdapter不直接创建AudioCodec，而是调用AudioBaseCodec::make_sharePtr(name_)获取具体编码器/解码器实例，实现插件化

---

## 关联主题
- S35 (AudioDecoderFilter)：Filter层封装，对应S173在engine层
- S62 (AudioBuffersManager)：双缓冲队列管理，S173中的inputBuffer_/outputBuffer_类型
- S50 (AudioResample)：SwrContext重采样，S173中AudioBaseCodec可能使用
- S18 (AudioCodecServer)：音频服务架构，S173是Codec引擎层

---

## git_branch / commit
master / pending (local draft)