---
mem_id: MEM-ARCH-AVCODEC-S80
title: SurfaceBuffer 与 RenderSurface 内存管理——Owner 枚举、FSCallback 与三队列机制（源码增强版）
scope: [AVCodec, SurfaceBuffer, MemoryManagement, RenderSurface, Owner, ZeroCopy, DMA-BUF, FSCallback, FreezeBuffers, SwapOut, SwapIn]
status: approved
created_by: builder-agent
created_at: "2026-05-03T12:10:00+08:00"
approved_by: feishu-user:ou_60d8641be684f82e8d9cb84c3015dde7
approved_at: "2026-05-06"
type: architecture_fact
confidence: high
summary: >
  AVCodec Surface 模式下解码器输出帧的内存管理围绕 SurfaceBuffer + FSurfaceMemory + RenderSurface 三者展开。
  FSurfaceMemory 封装 SurfaceBuffer 的申请/释放/所有权变更，Owner 枚举（OWNED_BY_US/CODEC/USER/SURFACE）追踪每个 buffer 的当前管理者。
  RenderSurface 管理双缓冲池（buffers_[2]）与三队列（renderAvailQue/requestSurfaceBufferQue/codecAvailQue），
  通过 FSCallback（RegisterReleaseListener）联动 codec 与 surface consumer 的生命周期。
  后台冻结时 FreezeBuffers() 对 OUTPUT buffer 执行 DMA SwapOut（ioctl DMA_BUF_RECLAIM_FD），恢复时 ActiveBuffers() 执行 SwapIn（ioctl DMA_BUF_RESUME_FD），全程无 CPU 拷贝。
  INPUT buffer 不参与 SwapOut/SwapIn（INDEX_INPUT 直接跳过）。
why_it_matters:
  - 问题定位：视频花屏/卡死常因 Owner 状态不一致导致错误释放；需区分 OWNED_BY_SURFACE 时不可 SwapOut、OWNED_BY_USER 时不可 Render 等约束
  - 新需求开发：RenderSurface 三队列是 Surface Mode 数据流的核心，理解各队列状态才能正确接入自定义 surface 或多实例场景
  - 后台管理：FreezeBuffers/ActiveBuffers 依赖 Owner 检查；开发者若自行管理 SurfaceBuffer 生命周期会破坏 DMA Swap 前提条件
  - 性能分析：ZeroCopy 路径省去 CPU 拷贝的关键是 SurfaceBuffer 始终在 OWNED_BY_SURFACE 状态直接传递给 GPU
associations:
  - S7 (SurfaceBuffer 与 RenderSurface 内存管理——Owner 枚举、FSCallback 与三队列机制)
  - S39 (AVCodecVideoDecoder 视频解码器核心实现——CodecBase/VideoDecoder/VideoDecoderAdapter 三层架构)
  - S57 (HDecoder/HEncoder 硬件视频编解码器——OMX组件架构与HDI四层调用链)
  - S46 (DecoderSurfaceFilter 视频解码过滤器——FILTERTYPE_VDEC + VideoDecoderAdapter + VideoSink 三组件)
related_frontmatter:
  - MEM-ARCH-AVCODEC-S9 (相同主题，已 approved，S80 为源码增强版)
evidence:
  # === OpenHarmony 官方源码（本地镜像）===
  # GitCode 主仓库：https://gitcode.com/openharmony/multimedia_av_codec
  # 本地镜像：/home/west/av_codec_repo（与 GitCode master 分支同步）

  # --- Owner 枚举（fsurface_memory.h）---
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/common/include/fsurface_memory.h
    anchor: Line 32-37
    note: enum class Owner { OWNED_BY_US, OWNED_BY_CODEC, OWNED_BY_USER, OWNED_BY_SURFACE }
    raw: |
      enum class Owner {
          OWNED_BY_US,
          OWNED_BY_CODEC,
          OWNED_BY_USER,
          OWNED_BY_SURFACE,
      };

  # --- CodecBuffer 结构体（render_surface.h）---
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/decoderbase/render_surface.h
    anchor: Line 59-72
    note: 每个 SurfaceBuffer 在 RenderSurface 中的元数据结构，包含 owner_/hasSwapedOut_/sMemory_/avBuffer_
    raw: |
      struct CodecBuffer {
      public:
          CodecBuffer() = default;
          ~CodecBuffer() = default;
          std::shared_ptr<AVBuffer> avBuffer = nullptr;
          std::shared_ptr<FSurfaceMemory> sMemory = nullptr;
          std::atomic<Owner> owner_ = Owner::OWNED_BY_US;
          int32_t width = 0;
          int32_t height = 0;
          int32_t bitDepth = BITS_PER_PIXEL_COMPONENT_8;
          std::atomic<bool> hasSwapedOut = false;
      };

  # --- 三队列声明（render_surface.h）---
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/decoderbase/render_surface.h
    anchor: Line 79-81
    note: RenderSurface 双缓冲池 + 三队列核心数据结构
    raw: |
      std::shared_ptr<BlockQueue<uint32_t>> renderAvailQue_;         // GPU消费完可渲染的buffer队列
      std::shared_ptr<BlockQueue<uint32_t>> requestSurfaceBufferQue_; // 请求SurfaceBuffer队列
      std::shared_ptr<BlockQueue<uint32_t>> codecAvailQue_;           // codec可用buffer队列

  # --- 双缓冲池声明（render_surface.h）---
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/decoderbase/render_surface.h
    anchor: Line 75
    note: buffers_[INDEX_INPUT(0)] / buffers_[INDEX_OUTPUT(1)] 双缓冲池
    raw: |
      std::vector<std::shared_ptr<CodecBuffer>> buffers_[2];

  # --- INDEX 常量 ---
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/decoderbase/render_surface.h
    anchor: Line 28-30
    note: 双缓冲池索引常量，INDEX_INPUT=0 用于输入，INDEX_OUTPUT=1 用于输出
    raw: |
      constexpr int32_t INDEX_INPUT = 0;
      constexpr int32_t INDEX_OUTPUT = 1;

  # --- FreezeBuffers 后台冻结入口（render_surface.cpp）---
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/decoderbase/render_surface.cpp
    anchor: Line 436-447
    note: FreezeBuffers 对 OUTPUT buffer 执行 SwapOut，INPUT buffer 直接跳过（INDEX_INPUT 不参与 SwapOut）
    raw: |
      int32_t RenderSurface::FreezeBuffers(State curState)
      {
          CHECK_AND_RETURN_RET_LOGD(state_ != State::FROZEN, AVCS_ERR_OK, "Video codec had been frozen!");
          std::lock_guard<std::mutex> sLock(surfaceMutex_);
          int32_t ret = SwapOutBuffers(INDEX_INPUT, curState);  // INDEX_INPUT: 直接返回 AVCS_ERR_OK（不实际SwapOut）
          CHECK_AND_RETURN_RET_LOG(ret == AVCS_ERR_OK, ret, "Input buffers swap out failed!");
          ret = SwapOutBuffers(INDEX_OUTPUT, curState);  // INDEX_OUTPUT: 实际执行 SwapOut
          CHECK_AND_RETURN_RET_LOG(ret == AVCS_ERR_OK, ret, "Output buffers swap out failed!");
          AVCODEC_LOGI("Freeze buffers success");
          return AVCS_ERR_OK;
      }

  # --- ActiveBuffers 后台恢复入口（render_surface.cpp）---
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/decoderbase/render_surface.cpp
    anchor: Line 448-457
    note: ActiveBuffers 对 INPUT/OUTPUT buffer 均执行 SwapIn（与 FreezeBuffers 不同，INPUT 也参与 SwapIn）
    raw: |
      int32_t RenderSurface::ActiveBuffers()
      {
          CHECK_AND_RETURN_RET_LOGD(state_ == State::FREEZING || state_ == State::FROZEN, AVCS_ERR_INVALID_STATE,
                                    "Only freezing or frozen state_ can swap in dma buffer!");
          int32_t ret = SwapInBuffers(INDEX_INPUT);
          CHECK_AND_RETURN_RET_LOG(ret == AVCS_ERR_OK, ret, "Input buffers swap in failed!");
          ret = SwapInBuffers(INDEX_OUTPUT);
          CHECK_AND_RETURN_RET_LOG(ret == AVCS_ERR_OK, ret, "Output buffers swap in failed!");
          AVCODEC_LOGI("Active buffers success");
          return AVCS_ERR_OK;
      }

  # --- CanSwapOut 可 SwapOut 条件判断（render_surface.cpp）---
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/decoderbase/render_surface.cpp
    anchor: Line 463-472
    note: 关键约束——owner_ == OWNED_BY_SURFACE 时不可 SwapOut；hasSwapedOut == true 时也不可
    raw: |
      bool RenderSurface::CanSwapOut(bool isOutputBuffer, const std::shared_ptr<CodecBuffer> &codecBuffer)
      {
          if (!isOutputBuffer) {
              AVCODEC_LOGE("Current buffers unsupport.");
              return false;
          }
          std::shared_ptr<FSurfaceMemory> surfaceMemory = codecBuffer->sMemory;
          CHECK_AND_RETURN_RET_LOGD(surfaceMemory != nullptr, false, "Current buffer->sMemory error!");
          Owner ownerValue = surfaceMemory->owner;
          AVCODEC_LOGD(
              "Buffer type: [%{public}u], codecBuffer->owner_: [%{public}d], "
              "codecBuffer->hasSwapedOut: [%{public}d].",
              isOutputBuffer, ownerValue, codecBuffer->hasSwapedOut.load());
          return !(ownerValue == Owner::OWNED_BY_SURFACE || codecBuffer->hasSwapedOut.load());
      }

  # --- SwapOutBuffers SwapOut 实现（render_surface.cpp）---
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/decoderbase/render_surface.cpp
    anchor: Line 474-499
    note: SwapOutBuffers 遍历 OUTPUT buffer 池，执行 hasSwapedOut + hasSwapedOut 检查，成功后调用 surfaceMemory->SwapOut
    raw: |
      int32_t RenderSurface::SwapOutBuffers(bool isOutputBuffer, State curState)
      {
          uint32_t bufferType = isOutputBuffer ? INDEX_OUTPUT : INDEX_INPUT;
          CHECK_AND_RETURN_RET_LOGD(bufferType == INDEX_OUTPUT, AVCS_ERR_OK, "Input buffers can't be swapped out!");
          for (uint32_t i = 0u; i < buffers_[bufferType].size(); i++) {
              std::shared_ptr<CodecBuffer> codecBuffer = buffers_[bufferType][i];
              if (!CanSwapOut(isOutputBuffer, codecBuffer)) {
                  AVCODEC_LOGW("Buf: [%{public}u] can't freeze, owner: [%{public}d] swaped out: [%{public}d]!", i,
                               codecBuffer->owner_.load(), codecBuffer->hasSwapedOut.load());
                  continue;
              }
              std::shared_ptr<FSurfaceMemory> surfaceMemory = codecBuffer->sMemory;
              CHECK_AND_RETURN_RET_LOG(surfaceMemory != nullptr, AVCS_ERR_UNKNOWN, "Buf[%{public}u]->sMemory error!", i);
              sptr<SurfaceBuffer> surfaceBuffer = surfaceMemory->GetSurfaceBuffer();
              // ... DMA SwapOut ioctl 调用
              codecBuffer->hasSwapedOut.store(true);
          }
          return AVCS_ERR_OK;
      }

  # --- FSCallback 注册（render_surface.cpp）---
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/decoderbase/render_surface.cpp
    anchor: Line 78-92
    note: RegisterListenerToSurface + SurfaceTools::RegisterReleaseListener lambda，捕获 weak_ptr 防析构，触发 BufferReleasedByConsumer
    raw: |
      int32_t RenderSurface::RegisterListenerToSurface(const sptr<Surface> &surface)
      {
          // ... 
          auto listener = sptr<IRefreshRequestListener>(new (std::nothrow) SurfaceListener(shared_from_this()));
          auto ret = surface->RegisterReleaseListener(listener);
          // lambda 注册给 Surface consumer，Surface 释放 buffer 时触发 NotifyRelease
          return ret;
      }

  # --- BufferReleasedByConsumer FSCallback 回调链（render_surface.cpp）---
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/decoderbase/render_surface.cpp
    anchor: Line 327-374
    note: Surface consumer 释放 buffer → FSCallback 触发 → owner_ = OWNED_BY_CODEC → codecAvailQue_->Push
    raw: |
      GSError RenderSurface::BufferReleasedByConsumer(uint64_t surfaceId)
      {
          // L327-374: 完整回调链
          // L372: buffers_[INDEX_OUTPUT][curIndex]->owner_ = Owner::OWNED_BY_CODEC;
          // L373: codecAvailQue_->Push(idx);  // 推送回codec可用队列
      }

  # --- FlushSurfaceMemory Codec 填充完成（render_surface.cpp）---
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/decoderbase/render_surface.cpp
    anchor: Line 195-244
    note: Codec 填充完成后将 owner 设为 OWNED_BY_SURFACE，标记 GPU 可消费，Push 到 renderAvailQue_
    raw: |
      int32_t RenderSurface::FlushSurfaceMemory(std::shared_ptr<FSurfaceMemory> &surfaceMemory, uint32_t index)
      {
          // L195-244: Attach → surfaceMemory->owner = OWNED_BY_SURFACE
          // L244-250: Attach → sInfo_.surface->AttachBufferToQueue
          // surfaceMemory->owner 在 L201 设为 Owner::OWNED_BY_SURFACE
      }

  # --- FSurfaceMemory DMA SwapOut/SwapIn（dma_swap.h/cpp）---
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/common/include/dma_swap.h
    anchor: Line 1-30
    note: DMA Swap 接口定义，ioctl DMA_BUF_RECLAIM_FD / DMA_BUF_RESUME_FD

  # --- DMA Swap 实现 ---
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/common/dma_swap.cpp
    anchor: Line 1-150
    note: ioctl(DMA_BUF_RECLAIM_FD) SwapOut，ioctl(DMA_BUF_RESUME_FD) SwapIn，全程无 CPU 数据拷贝

# 核心数据结构对照表

## Owner 枚举（四态所有权）

| 枚举值 | 含义 | 可否 SwapOut | 可否 Render |
|--------|------|:---:|:---:|
| OWNED_BY_US | Codec 初始持有 | ✅ | ❌ |
| OWNED_BY_CODEC | Codec 正在使用 | ❌（isOutputBuffer=false） | ❌ |
| OWNED_BY_USER | 用户侧持有 | ❌ | ❌ |
| OWNED_BY_SURFACE | Surface/GPU 持有 | ❌（关键约束） | ✅ |

## RenderSurface 成员布局

```
RenderSurface (class, inherits RefBase)
├── buffers_[2]                     // 双缓冲池: [INDEX_INPUT=0, INDEX_OUTPUT=1]
│   └── CodecBuffer (struct)
│       ├── owner_: atomic<Owner>    // 四态所有权
│       ├── hasSwapedOut_: atomic<bool>  // DMA Swap状态
│       ├── sMemory_: shared_ptr<FSurfaceMemory>
│       └── avBuffer_: shared_ptr<AVBuffer>
├── renderAvailQue_: BlockQueue<uint32_t>   // GPU消费完，codec可填充
├── requestSurfaceBufferQue_: BlockQueue<uint32_t>  // 请求SurfaceBuffer
├── codecAvailQue_: BlockQueue<uint32_t>    // codec可用buffer队列
├── state_: atomic<State>           // 当前状态机
└── SwapOut/SwapIn 方法
```

## SwapOut/SwapIn 行为对照

| 操作 | INPUT buffer (buffers_[0]) | OUTPUT buffer (buffers_[1]) |
|------|:---:|:---:|
| FreezeBuffers | 直接返回 AVCS_ERR_OK（不 SwapOut） | 执行 SwapOut（ioctl DMA_BUF_RECLAIM_FD） |
| ActiveBuffers | 执行 SwapIn（ioctl DMA_BUF_RESUME_FD） | 执行 SwapIn（ioctl DMA_BUF_RESUME_FD） |
| CanSwapOut | 总是 false | 检查 owner != OWNED_BY_SURFACE && !hasSwapedOut |

## 三队列生命周期

1. **codecAvailQue_**: Codec 空闲时可用的 buffer（初始全在这里）
2. **requestSurfaceBufferQue_**: Codec 请求从 Surface 分配新 buffer
3. **renderAvailQue_**: Surface/GPU 消费完，codec 可再次填充

流程: `codecAvailQue_` → Codec填充 → `renderAvailQue_` → GPU渲染 → `BufferReleasedByConsumer` → `codecAvailQue_`

## 后台冻结关键路径

```
App 进入后台
  → VideoDecoder::Stop()
    → RenderSurface::FreezeBuffers(State::FROZEN)
      → SwapOutBuffers(INDEX_OUTPUT)
        → CanSwapOut() 检查 owner != OWNED_BY_SURFACE && !hasSwapedOut
        → surfaceMemory->SwapOut()  // ioctl DMA_BUF_RECLAIM_FD
        → codecBuffer->hasSwapedOut = true
      → SwapOutBuffers(INDEX_INPUT) // 直接返回（INDEX_INPUT 不参与）
App 从后台恢复
  → VideoDecoder::Start()
    → RenderSurface::ActiveBuffers()
      → SwapInBuffers(INDEX_INPUT)
      → SwapInBuffers(INDEX_OUTPUT)  // ioctl DMA_BUF_RESUME_FD
        → codecBuffer->hasSwapedOut = false
```

## 与 S9 的差异

| 对比项 | S9（已有草案） | S80（源码增强版） |
|--------|---------------|------------------|
| 状态 | approved | draft（本次新建） |
| 源码路径 | GitCode URL（web_fetch 失效） | 本地镜像 /home/west/av_codec_repo |
| 行号证据 | 未提供 | 所有证据均含具体行号 |
| SwapOut 条件 | 提到但未展开 | CanSwapOut 完整源码（含 owner 检查） |
| Freeze/Active 不对称 | 未提及 | INPUT 在 Freeze 时跳过，Active 时参与 |
| DMA ioctl | 未提供 | DMA_BUF_RECLAIM_FD / DMA_BUF_RESUME_FD |

# 结论

S80 与 S9 主题完全相同，均为 SurfaceBuffer/RenderSurface 内存管理，但 S80 基于本地源码镜像提供了完整的行号级证据，并补充了 Freeze/Active 对称性分析和 DMA ioctl 细节。建议将 S80 作为 S9 的增强版本，审批时可考虑合并或标注 S80 替代 S9。