---
id: MEM-ARCH-AVCODEC-S2
title: interfaces/kits C API 视频编解码使用场景与 key 搭配
scope: [AVCodec, API, Integration]
status: draft
author: Builder Agent
created_at: "2026-04-21T23:07:00+08:00"
type: architecture_fact
confidence: medium
tags: [AVCodec, API, Integration, VideoDecoder, VideoEncoder, OH_MD_KEY]
evidence_links:
  - https://gitee.com/openharmony/multimedia_av_codec/blob/master/interfaces/kits/c/native_avcodec_base.h
  - https://gitee.com/openharmony/multimedia_av_codec/blob/master/interfaces/kits/c/native_avcodec_videodecoder.h
  - https://gitee.com/openharmony/multimedia_av_codec/blob/master/interfaces/kits/c/native_avcodec_videoencoder.h
related:
  - MEM-ARCH-AVCODEC-011
  - MEM-ARCH-AVCODEC-013
  - MEM-ARCH-AVCODEC-010
owner: 耀耀
review:
  owner: 耀耀
  change_policy: update_on_code_change
update_trigger: code_change
created_at: "2026-04-21"
updated_at: "2026-04-21"
summary: >
  综合 AVCodec C API 契约（MEM-ARCH-AVCODEC-011）、参数配置体系（MEM-ARCH-AVCODEC-013）、
  实例生命周期（MEM-ARCH-AVCODEC-010），形成面向三方接入和新人的接口使用场景指南。
  覆盖视频解码/编码标准流程、关键 Format Key 搭配、回调机制、Surface vs 内存模式选型、
  以及典型错误码排查。用于指导三方应用接入和新人入项快速上手。
关联场景: [三方应用接入, 新人入项]
related:
  - MEM-ARCH-AVCODEC-011
  - MEM-ARCH-AVCODEC-013
  - MEM-ARCH-AVCODEC-010
owner: 耀耀
review:
  owner: 耀耀
  change_policy: update_on_code_change
update_trigger: code_change
created_at: "2026-04-21"
updated_at: "2026-04-21"
---

# interfaces/kits C API 视频编解码使用场景与 key 搭配

## 1. 视频解码标准流程

视频解码遵循 **先配置后启动、先入后出** 的流水线模式，整体分为 6 个阶段：

```
CreateByMime / CreateByName  →  SetCallback  →  Configure  →  Start
   ↓（启动后进入循环）
PushInputData  →  QueryOutputBuffer  →  GetOutputBuffer  →  RenderOutputData / FreeOutputBuffer
   ↓（循环直到全部解码完成）
Stop  →  Destroy
```

### 1.1 各阶段详解

| 阶段 | 关键 API | 说明 |
|------|----------|------|
| 创建 | `OH_VideoDecoder_CreateByMime(mime)` / `CreateByName(name)` | ByMime 自动匹配合适 codec；ByName 用于精确指定 codec（如硬解型号） |
| 回调 | `OH_VideoDecoder_SetCallback(cb)` | 注册 4 类回调（见第 4 节），回调必须在 Configure 前注册 |
| 配置 | `OH_VideoDecoder_Configure(format)` | 传入 OH_AVFormat，设置 WIDTH/HEIGHT/PIXEL_FORMAT |
| 启动 | `OH_VideoDecoder_Start()` | 启动解码器，状态切换为 Running |
| 输入 | `OH_VideoDecoder_PushInputData(index, info)` | 将压缩帧（ES/NALU）推入解码器，触发 OnNeedInputBuffer 回调 |
| 输出 | `QueryOutputBuffer` → `GetOutputBuffer` → `RenderOutputData` | Surface 模式走 Render；内存模式走 GetOutputBuffer + FreeOutputBuffer |
| 停止 | `OH_VideoDecoder_Stop()` | 停止解码，可重新 Start；内部清空 buffer |
| 销毁 | `OH_VideoDecoder_Destroy()` | 释放实例，调用后句柄不可再用 |

### 1.2 关键约束

- **Configure 必须在 Start 之前**；Configure 会校验 WIDTH/HEIGHT/PIXEL_FORMAT 与硬件能力是否匹配
- **PushInputData 的 index 来自 OnNeedInputBuffer 回调**，不允许自行分配或复用 index
- **每个 GetOutputBuffer 必须配对 FreeOutputBuffer**，漏掉会导致 buffer 泄漏、硬件输出阻塞
- **Surface 模式下**：RenderOutputData 后无需手动 FreeOutputBuffer（Surface 内部管理）
- **Stop 后可重新 Start**，实例配置保持不变；Flush 会清空 buffer 但保留配置

---

## 2. 视频编码标准流程

视频编码与解码流程类似，但方向相反，且**应用层需要主动获取输入 buffer 填充原始帧**：

```
CreateByName  →  SetCallback  →  Configure(format)  →  Start
   ↓
GetInputBuffer  →  PushInputData（原始帧） →  QueryOutputBuffer  →  GetOutputBuffer
   ↓
Stop  →  Destroy
```

### 2.1 各阶段详解

| 阶段 | 关键 API | 说明 |
|------|----------|------|
| 创建 | `OH_VideoEncoder_CreateByName(name)` | 通常先通过 Capability API 查询设备支持列表再创建 |
| 配置 | `OH_VideoEncoder_Configure(format)` | 必须包含：WIDTH/HEIGHT/PIXEL_FORMAT + BITRATE + VIDEO_ENCODE_BITRATE_MODE + I_FRAME_INTERVAL |
| 启动 | `OH_VideoEncoder_Start()` | 启动后 OnNeedInputBuffer 回调开始触发 |
| 输入 | `GetInputBuffer(index)` → 填充 YUV 数据 → `PushInputData(index, info)` | 应用层主动获取空输入 buffer，填入原始帧后再推回编码器 |
| 输出 | `QueryOutputBuffer` → `GetOutputBuffer` | 获取编码后的压缩数据（NALU），由应用层处理（封装/发送/存储） |
| 结束 | `OH_VideoEncoder_Stop()` | 停止前应调用 `NotifyEndOfStream` 通知编码器输入结束，确保输出完整 GOP |
| 销毁 | `OH_VideoEncoder_Destroy()` | 释放实例 |

### 2.2 关键约束

- **GetInputBuffer 和 PushInputData 必须配对**，一个 index 对应一次拿取和一次推送
- **输入格式必须是 OH_MD_KEY_PIXEL_FORMAT 支持的 YUV 格式**（NV12/NV21 最常见），RGBA 会导致编码失败或画质损失
- **码控模式（CBR/VBR/UBR）影响输出码率稳定性**：直播推荐 CBR，点播推荐 VBR，UBR 适用于复杂场景
- **I_FRAME_INTERVAL**：设为 0 表示全 I 帧（仅适用于特殊场景；通常设为 1s 或 GOP 大小）

---

## 3. 关键 Format Key 搭配

### 3.1 解码配置 Key（Configure 时传入）

| Key | 类型 | 说明 | 必须 |
|-----|------|------|------|
| `OH_MD_KEY_WIDTH` | int32 | 视频宽度（像素） | ✅ |
| `OH_MD_KEY_HEIGHT` | int32 | 视频高度（像素） | ✅ |
| `OH_MD_KEY_PIXEL_FORMAT` | int32 | 期望输出像素格式（见 OH_AVPixelFormat） | ✅ |
| `OH_MD_KEY_FRAME_RATE` | int32 | 帧率（仅部分解码器需要hint） | △ |
| `OH_MD_KEY_COLOR_PRIMARIES` | int32 | 色彩空间（影响 HDR 显示） | △ |
| `OH_MD_KEY_TRANSFER_CHARACTERISTICS` | int32 | 传输特性（BT.709/BT.2020 等） | △ |

> **解码器通常不需要主动设置 BITRATE**，解码输出由输入码流决定。

### 3.2 编码配置 Key（Configure 时传入）

| Key | 类型 | 说明 | 必须 |
|-----|------|------|------|
| `OH_MD_KEY_WIDTH` | int32 | 视频宽度 | ✅ |
| `OH_MD_KEY_HEIGHT` | int32 | 视频高度 | ✅ |
| `OH_MD_KEY_PIXEL_FORMAT` | int32 | 输入像素格式（通常 NV12/NV21） | ✅ |
| `OH_MD_KEY_BITRATE` | int32 | 目标码率（bps） | ✅ |
| `OH_MD_KEY_VIDEO_ENCODE_BITRATE_MODE` | int32 | CBR(0) / VBR(1) / UBR(2) | ✅ |
| `OH_MD_KEY_I_FRAME_INTERVAL` | int32 | I 帧间隔（ms），0=全I帧 | ✅ |
| `OH_MD_KEY_PROFILE` | int32 | 编码 Profile（H.264: Baseline/Main/High；H.265: Main） | △ |
| `OH_MD_KEY_VIDEO_IS_HDR_VIVID` | bool | 是否 HDR Vivid | △ |
| `OH_MD_KEY_MAX_BITRATE` | int32 | VBR 模式下的最大码率 | △ |
| `OH_MD_KEY_FRAME_RATE` | int32 | 目标帧率 | △ |

### 3.3 典型场景 Key 配置推荐

| 场景 | 分辨率 | 码率 | 码控模式 | I帧间隔 | 备注 |
|------|--------|------|----------|---------|------|
| 实时通信（RTC） | 1280×720 | 1~2 Mbps | CBR | 1000ms | 低延迟优先 |
| 直播推流 | 1920×1080 | 4~8 Mbps | CBR | 2000ms | 稳定性优先 |
| 短视频录制 | 1920×1080 | 8~12 Mbps | VBR | 2000ms | 画质优先 |
| 视频监控存储 | 2560×1440 | 2~4 Mbps | UBR | 5000ms | 低码率长存储 |

### 3.4 OH_AVFormat 使用示例

```c
// 解码配置
OH_AVFormat *decFmt = OH_AVFormat_Create();
OH_AVFormat_SetInt32(decFmt, OH_MD_KEY_WIDTH, 1920);
OH_AVFormat_SetInt32(decFmt, OH_MD_KEY_HEIGHT, 1080);
OH_AVFormat_SetInt32(decFmt, OH_MD_KEY_PIXEL_FORMAT, OH_AVPixelFormat_YUV_SEMIPLANAR_NV12);
OH_VideoDecoder_Configure(decoder, decFmt);

// 编码配置
OH_AVFormat *encFmt = OH_AVFormat_Create();
OH_AVFormat_SetInt32(encFmt, OH_MD_KEY_WIDTH, 1920);
OH_AVFormat_SetInt32(encFmt, OH_MD_KEY_HEIGHT, 1080);
OH_AVFormat_SetInt32(encFmt, OH_MD_KEY_PIXEL_FORMAT, OH_AVPixelFormat_YUV_SEMIPLANAR_NV12);
OH_AVFormat_SetInt32(encFmt, OH_MD_KEY_BITRATE, 8 * 1000 * 1000);  // 8Mbps
OH_AVFormat_SetInt32(encFmt, OH_MD_KEY_VIDEO_ENCODE_BITRATE_MODE, CBR);
OH_AVFormat_SetInt32(encFmt, OH_MD_KEY_I_FRAME_INTERVAL, 2000);    // 2s
OH_VideoEncoder_Configure(encoder, encFmt);
```

---

## 4. OH_AVCodecCallback 四类回调

所有 AVCodec 实例（解码器/编码器）共享同一回调结构，由应用层实现并通过 `SetCallback` 注册：

```c
typedef struct OH_AVCodecCallback {
    void (*OnError)(OH_AVCodec *codec, int32_t errorCode, void *userData);          // 错误通知
    void (*OnStreamChanged)(OH_AVCodec *codec, OH_AVFormat *format, void *userData); // 格式变化
    void (*OnNeedInputBuffer)(OH_AVCodec *codec, uint32_t index, OH_AVBuffer *buffer, void *userData); // 需要输入
    void (*OnNewOutputBuffer)(OH_AVCodec *codec, uint32_t index, OH_AVBuffer *buffer, void *userData); // 输出就绪
} OH_AVCodecCallback;
```

### 4.1 OnError（错误回调）

| 触发时机 | errorCode | 应用处理 |
|----------|-----------|----------|
| 硬件异常 | `AV_ERR_INVALID_VAL` | 检查 Configure 参数是否超出硬件能力范围 |
| 内存不足 | `AV_ERR_NO_MEMORY` | 降低分辨率/码率，或释放其他资源 |
| 超时/卡死 | `AV_ERR_TIMEOUT` | 检查输入是否持续饿死（PushInputData 频率） |
| 未知错误 | `AV_ERR_UNKNOWN` | Dump 现场，联系芯片厂商 |

### 4.2 OnStreamChanged（格式变化回调）

| 触发时机 | 含义 | 应用处理 |
|----------|------|----------|
| 解码器内部分辨率切换 | 码流中分辨率变化（如 Adaptive Streaming） | 更新应用层 Surface 大小；重新 QueryOutputBuffer |
| 编码器输出格式动态调整 | 编码器内部参数变化（通常不应发生） | 调用 `GetOutputDescription` 获取新格式并处理 |

> **重要**：Format 参数仅包含变化的字段（如 WIDTH/HEIGHT），非全部参数。

### 4.3 OnNeedInputBuffer（输入请求回调）

| 对象 | 含义 | 应用操作 |
|------|------|----------|
| 解码器 | 解码器已准备好接收压缩数据 | 调用 `PushInputData(index, buffer)` 推送 NALU/ES 数据 |
| 编码器 | 编码器已准备好接收原始帧 | 调用 `GetInputBuffer(index)` 获取空 buffer，填入 YUV 后 `PushInputData` |

- **index 是 buffer 的唯一标识**，必须使用回调提供的 index，不能自行计算
- **buffer 生命周期**：解码器回调中的 buffer 归解码器所有，应用 PushInputData 后 ownership 转移；编码器中 GetInputBuffer 获取的 buffer 应用层填充后 PushInputData 转移 ownership
- **典型问题**：PushInputData 用错 index 或重复使用同一个 index，会导致 `AV_ERR_INVALID_VAL`

### 4.4 OnNewOutputBuffer（输出就绪回调）

| 对象 | 含义 | 应用操作 |
|------|------|----------|
| 解码器（内存模式） | 解码输出已就绪 | `GetOutputBuffer` → 处理数据 → `FreeOutputBuffer` |
| 解码器（Surface模式） | 解码输出已在 Surface | `RenderOutputData`（可选）或直接结束（Surface 自动显示） |
| 编码器 | 编码输出已就绪 | `GetOutputBuffer` → 获取 NALU → 封装/传输/存储 → `FreeOutputBuffer` |

- **Surface 模式下**：`OnNewOutputBuffer` 的 buffer 直接关联 Surface，无需 GetOutputBuffer，只需决定是否 Render（影响显示时机）
- **内存模式下**必须严格配对：**GetOutputBuffer → 使用 → FreeOutputBuffer**，缺一不可

---

## 5. Surface 模式 vs 内存模式选择场景

AVCodec 解码输出支持两种模式，由 `SetSurface` 是否调用决定：

### 5.1 模式对比

| 特性 | Surface 模式 | 内存模式 |
|------|-------------|---------|
| 输出路径 | 解码结果直写 Surface（GPU 合成） | 解码结果写入内存（CPU 可访问） |
| 延迟 | 低（无内存拷贝） | 较高（有内存拷贝） |
| CPU 访问 | ❌ 不可直接访问像素 | ✅ 可读取/处理像素 |
| 渲染 | ✅ 适合视频播放、Camera Preview | ❌ 需应用层手动渲染到 View |
| 内存占用 | 较低 | 较高 |
| 实现复杂度 | 低（系统自动管理） | 高（需自己处理 RenderOutputData） |
| 典型场景 | 视频播放、Camera 预览、实时显示 | 视频分析、AI 识别、截图、图像处理 |

### 5.2 选型决策树

```
解码输出是否需要 CPU 访问像素？
├── 否（仅播放/预览）→ Surface 模式 ✅
│   └── OH_VideoDecoder_SetSurface(surface)
│
└── 是（AI分析/截图/二次处理）→ 内存模式
    └── OH_VideoDecoder_GetOutputBuffer → 处理 → FreeOutputBuffer
```

### 5.3 Surface 模式典型代码路径

```c
// 创建 Surface（通过 OH_NativeWindow）
OH_VideoDecoder_SetSurface(decoder, nativeWindow);

// 启动解码后，OnNewOutputBuffer 回调中：
void OnNewOutputBuffer(OH_AVCodec *codec, uint32_t index, OH_AVBuffer *buffer, void *userData) {
    // Surface 模式：RenderOutputData 将数据送入 Surface 合成管线
    OH_VideoDecoder_RenderOutputData(codec, index);
    // 注意：Surface 模式下不需要 FreeOutputBuffer
}
```

### 5.4 内存模式典型代码路径

```c
// 不调用 SetSurface，走内存路线

void OnNewOutputBuffer(OH_AVCodec *codec, uint32_t index, OH_AVBuffer *buffer, void *userData) {
    // 1. 获取输出 buffer 内容
    OH_AVBuffer *outputBuffer;
    OH_VideoDecoder_GetOutputBuffer(codec, index, &outputBuffer);
    
    // 2. 应用层处理（如 AI 推理、截图）
    ProcessDecodedFrame(outputBuffer);
    
    // 3. 释放 buffer（必须！否则泄漏）
    OH_VideoDecoder_FreeOutputBuffer(codec, index);
}
```

---

## 6. 典型错误码及排查方法

所有 AVCodec API 返回 `OH_AVErrCode`，`AV_ERR_OK(0)` 表示成功。

### 6.1 错误码速查表

| 错误码 | 含义 | 典型场景 | 排查方法 |
|--------|------|----------|----------|
| `AV_ERR_OK(0)` | 成功 | - | - |
| `AV_ERR_NO_MEMORY` | 内存不足 | 高分辨率编码时 OOM | 降低分辨率/码率；检查内存泄漏 |
| `AV_ERR_INVALID_VAL` | 参数非法 | Configure 时 WIDTH/HEIGHT 不支持 | 用 Capability API 查询支持范围；检查 PIXEL_FORMAT 是否匹配 |
| `AV_ERR_OPERATE_NOT_PERMITTED` | 操作不允许 | 未 Start 就 PushInputData；Stop 后继续 Push | 确认状态机顺序；检查回调是否正常触发 |
| `AV_ERR_TIMEOUT` | 操作超时 | 编码器长时间无输出 | 检查 I_FRAME_INTERVAL 是否过大；检查输入帧是否持续 |
| `AV_ERR_UNKNOWN` | 未知错误 | 硬件/驱动异常 | 查看内核日志；联系芯片厂商 |
| `AV_ERR_OUTPUT_CHANGED` | 输出格式变化 | 解码中码流分辨率变化 | 实现 OnStreamChanged 回调；应用层更新 Surface 大小 |

### 6.2 常见接入问题排查清单

**问题：解码器无图像输出**
- [ ] `Configure` 是否传入了正确的 WIDTH/HEIGHT/PIXEL_FORMAT？
- [ ] `PushInputData` 的数据是否为完整 NALU（带 start code 或 Annex-B 格式）？
- [ ] `OnNeedInputBuffer` 回调是否正常触发？（未触发说明 Start 未成功）
- [ ] 是否每个 `GetOutputBuffer` 都配对了 `FreeOutputBuffer`？
- [ ] Surface 模式下：Surface 是否已 attach 到正确的窗口？

**问题：编码器输出码流异常**
- [ ] `Configure` 是否包含全部必须 Key（BITRATE/ENCODE_BITRATE_MODE/I_FRAME_INTERVAL）？
- [ ] `GetInputBuffer` 获取后填充的 YUV 数据格式是否与 PIXEL_FORMAT 一致？
- [ ] 是否调用了 `NotifyEndOfStream` 再 Stop？否则最后一个 GOP 可能丢失
- [ ] VBR 模式下 `MAX_BITRATE` 是否设置合理？（应大于 BITRATE）

**问题：应用崩溃/内存泄漏**
- [ ] `Create` 和 `Destroy` 是否配对？（每次 Create 必须有对应 Destroy）
- [ ] `GetOutputBuffer` 和 `FreeOutputBuffer` 是否严格配对？
- [ ] `Stop` 后是否重新 `Start`？（Stop 后直接 Destroy 会丢失资源）
- [ ] Surface 模式下 `RenderOutputData` 后是否重复调用 `FreeOutputBuffer`？

---

## 7. 新人入项 checklist

接入 AVCodec C API 的最低完成步骤：

1. **理解目录结构**：所有 C API 定义在 `interfaces/kits/c/native_avcodec_*.h`
2. **链接正确 so**：链接 `libnative_media_codecbase.so`（Base）+ 对应 decoder/encoder so
3. **注册回调**：先 `SetCallback`，再 `Configure`，最后 `Start`
4. **配置格式**：使用 `OH_AVFormat` + `OH_MD_KEY_*`，解码必填 W/高/像素格式，编码额外必填码率/码控/I帧
5. **管理 Buffer 生命周期**：Get→使用→Free，三步缺一不可
6. **选模式**：播放/预览用 Surface；AI 处理用内存模式
7. **处理错误码**：所有 API 返回值检查 `!= AV_ERR_OK`
8. **实现全部 4 个回调**：OnError / OnStreamChanged / OnNeedInputBuffer / OnNewOutputBuffer

---

## 参考关联

| 关联记忆 | 说明 |
|----------|------|
| [MEM-ARCH-AVCODEC-011](MEM-ARCH-AVCODEC-011.md) | C API 契约总览（10个头文件、6类API） |
| [MEM-ARCH-AVCODEC-013](MEM-ARCH-AVCODEC-013.md) | OH_AVFormat + OH_MD_KEY 键值对完整体系 |
| [MEM-ARCH-AVCODEC-010](MEM-ARCH-AVCODEC-010.md) | Codec 实例生命周期管理 |
| FAQ-SCENE2-001 | 三方接入常见问题 |
| FAQ-SCENE2-002 | 回调使用常见问题 |
| FAQ-SCENE2-003 | Format 配置常见问题 |
