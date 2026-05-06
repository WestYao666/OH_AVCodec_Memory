---
id: MEM-ARCH-AVCODEC-S33
title: PreProcessing 预处理器框架——FastKitsInterface 快速图像处理 + FrameDropFilter 智能丢帧策略
type: architecture_fact
scope: [AVCodec, Framework, PreProcessing, FastImage, FrameDrop, dlopen, ImageProcessing]
status: approved
approved_at: "2026-05-06"
author: builder-agent
created: 2026-04-25
updated: 2026-04-25
submitted_at: 2026-04-25T12:21:00+08:00
finalized_at: 2026-04-25T13:51:00+08:00

summary: PreProcessing 框架位于 frameworks/native/avcodec/pre_processing/，包含 FastKitsInterface（硬件加速图像缩放/裁剪，dlopen libfast_image.so，引用计数生命周期）和 FrameDropFilter（智能丢帧，RatioDropStrategy 按帧比例/TimestampDropStrategy 按时间戳两种策略）。

## 架构位置

PreProcessing 是 AVCodec Native Framework 的预处理子模块，位于 `frameworks/native/avcodec/pre_processing/`，为视频编码器提供图像预处理和帧率控制能力：

```
视频输入 → FastKitsInterface (缩放/裁剪) → FrameDropFilter (丢帧) → 编码器
```

```
frameworks/native/avcodec/pre_processing/
├── fast_kits_interface/
│   ├── fast_kits_interface.h          # 头文件
│   └── fast_kits_interface.cpp        # 实现
└── frame_drop/
    ├── frame_drop_filter.h            # FrameDropFilter 头文件
    ├── frame_drop_filter.cpp          # FrameDropFilter 实现
    ├── frame_drop_strategy.h          # IDropStrategy 接口 + 双策略
    └── frame_drop_strategy.cpp        # 两种策略实现
```

---

## 一、FastKitsInterface 快速图像处理

### 1.1 概述

FastKitsInterface 是一个单例模式的图像预处理接口，通过 dlopen 动态加载 `libfast_image.so`，提供硬件加速的图像缩放、裁剪操作。位于 `OHOS::MediaAVCodec::PreProcessing` 命名空间。

**Evidence:**
- `frameworks/native/avcodec/pre_processing/fast_kits_interface/fast_kits_interface.h:52` — 类定义
- `frameworks/native/avcodec/pre_processing/fast_kits_interface/fast_kits_interface.cpp:12` — 库路径常量定义

### 1.2 动态库加载机制（dlopen/RTLD_NOW）

**Evidence:**
- `frameworks/native/avcodec/pre_processing/fast_kits_interface/fast_kits_interface.cpp:91-98` — OpenLibrary() 使用 dlopen(RTLD_NOW) 加载 libfast_image.so
- `frameworks/native/avcodec/pre_processing/fast_kits_interface/fast_kits_interface.cpp:100-107` — ReadSymbols() 使用 dlsym 解析6个函数符号
- `frameworks/native/avcodec/pre_processing/fast_kits_interface/fast_kits_interface.h:26-31` — 6个函数指针类型定义

**加载流程（Init）：**
```cpp
// fast_kits_interface.cpp:74-89
int32_t FastKitsInterface::Init(uint32_t format, FastResizeAlgoType algo) {
    // 1. dlopen("libfast_image.so", RTLD_NOW) → handle_
    // 2. dlsym 解析6个符号
    // 3. initFunc_(format, algo) 初始化
    // 成功返回 AVCS_ERR_OK
}
```

**卸载时机（Release）：**
```cpp
// fast_kits_interface.cpp:38-53
void FastKitsInterface::Release() {
    // refCount_ 减1
    // refCount_ == 0 时：
    //   1. fastScaleClearGPUFunc_() 清GPU资源
    //   2. ClearSymbols() 置空函数指针
    //   3. dlclose(handle_) 卸载动态库
}
```

### 1.3 引用计数生命周期（RefCount）

**Evidence:**
- `frameworks/native/avcodec/pre_processing/fast_kits_interface/fast_kits_interface.h:60-61` — refCount_ 成员变量
- `frameworks/native/avcodec/pre_processing/fast_kits_interface/fast_kits_interface.cpp:30-36` — Retain() 递增 refCount_
- `frameworks/native/avcodec/pre_processing/fast_kits_interface/fast_kits_interface.cpp:38-53` — Release() 递减并卸载

FastKitsInterface 是单例模式，调用方通过 Retain()/Release() 管理引用计数：
- Retain() 增加引用计数
- Release() 减少引用计数
- refCount_ == 0 时卸载 libfast_image.so

### 1.4 函数符号表（6个导出函数）

**Evidence:**
- `frameworks/native/avcodec/pre_processing/fast_kits_interface/fast_kits_interface.cpp:100-107` — ReadSymbols() 逐个解析
- `frameworks/native/avcodec/pre_processing/fast_kits_interface/fast_kits_interface.h:26-31` — 函数指针类型

| 函数指针 | 符号名 | 用途 |
|---------|--------|------|
| `FastScaleInitFunc initFunc_` | `FastScaleInit` | 初始化(format, algo) |
| `FastScaleDownSampleFunc downSampleFunc_` | `FastScaleDownSample` | 下采样缩放 |
| `FastScaleCropFunc cropFunc_` | `FastScaleCrop` | 裁剪 |
| `CreateCropRectFunc createRectFunc_` | `CreateCropRect` | 创建裁剪矩形 |
| `DestroyCropRectFunc destroyRectFunc_` | `DestroyCropRect` | 销毁裁剪矩形 |
| `FastScaleClearGPUFunc fastScaleClearGPUFunc_` | `FastScaleClearGPU` | 清GPU缓存 |

### 1.5 缩放算法类型（FastResizeAlgoType）

**Evidence:**
- `frameworks/native/avcodec/pre_processing/fast_kits_interface/fast_kits_interface.h:39-44`

```cpp
enum class FastResizeAlgoType {
    HARDWARE,  // 硬件加速（默认）
    BILINEAR,  // 双线性插值
    BICUBIC,   // 双立方插值（DownSample 默认）
    LANCZOS,   // Lanczos 插值
};
```

### 1.6 核心接口（Crop / DownSample）

**Crop — 图像裁剪：**
```cpp
// fast_kits_interface.cpp:120-142
// 输入/输出 SurfaceBuffer 必须格式一致(input->GetFormat() == output->GetFormat())
// createRectFunc_(top, left, bottom, right) 创建裁剪矩形
// cropFunc_(input, output, cropRect) 执行裁剪
// destroyRectFunc_(cropRect) 销毁裁剪矩形
```

**DownSample — 下采样缩放：**
```cpp
// fast_kits_interface.cpp:144-159
// 输入/输出 SurfaceBuffer 必须格式一致
// downSampleFunc_(input, output, algo) 执行下采样
// 默认算法：BICUBIC
```

### 1.7 错误码转换

**Evidence:**
- `frameworks/native/avcodec/pre_processing/fast_kits_interface/fast_kits_interface.cpp:56-65`

| libfast_image.so 错误码 | 转换为 AVCodec 错误码 |
|------------------------|---------------------|
| `FAST_ERR_SUCCESS(0)` / `FAST_ERR_SUCCESS_PARTIAL(1)` | `AVCS_ERR_OK` |
| `FAST_ERR_ILLEGAL_INPUT(2)` | `AVCS_ERR_INVALID_VAL` |
| `FAST_ERR_INVALID_PTR(3)` | `AVCS_ERR_INVALID_VAL` |
| 其他 | `AVCS_ERR_UNKNOWN` |

---

## 二、FrameDropFilter 智能丢帧过滤器

### 2.1 概述

FrameDropFilter 是丢帧策略过滤器，通过 `IDropStrategy` 接口支持两种丢帧策略。根据首帧时间戳是否推进自动选择策略：时间戳推进用 TimestampDropStrategy，否则用 RatioDropStrategy。

**Evidence:**
- `frameworks/native/avcodec/pre_processing/frame_drop/frame_drop_filter.h:32-49` — FrameDropFilter 类定义
- `frameworks/native/avcodec/pre_processing/frame_drop/frame_drop_filter.cpp:24-58` — Configure + ShouldDropFrame 策略选择逻辑

### 2.2 丢帧策略接口（IDropStrategy）

**Evidence:**
- `frameworks/native/avcodec/pre_processing/frame_drop/frame_drop_strategy.h:24-35`

```cpp
class IDropStrategy {
public:
    virtual ~IDropStrategy() = default;
    virtual bool ShouldDropFrame(uint64_t pts) = 0;      // 返回 true = 丢帧
    virtual void FlushTimeStamp() = 0;                   // 清时间戳状态
    virtual DropStrategyType GetType() const = 0;        // 返回策略类型
};
```

### 2.3 策略一：RatioDropStrategy（按帧比例丢帧）

**Evidence:**
- `frameworks/native/avcodec/pre_processing/frame_drop/frame_drop_strategy.cpp:18-38`

**原理：** 根据源帧率与目标帧率的比例 `keepRatio = targetFps / srcFps`，按帧数累计计算是否应保留当前帧。

```cpp
// RatioDropStrategy::ShouldDropFrame
totalFrames_++;  // 总帧数+1
double keepRatio = targetFrameRate_ / srcFrameRate_;  // 保留比例
double targetCount = totalFrames_ * keepRatio;         // 应保留帧数
// keptFrames_ < ceil(targetCount) → 保留；否则 → 丢帧
if (keptFrames_ < static_cast<uint64_t>(std::ceil(targetCount))) {
    keptFrames_++; return false;  // 保留
}
return true;  // 丢帧
```

**示例：** 60fps→30fps，keepRatio=0.5，前30帧全部保留，第31帧开始新一轮周期。

### 2.4 策略二：TimestampDropStrategy（按时戳间隔丢帧）

**Evidence:**
- `frameworks/native/avcodec/pre_processing/frame_drop/frame_drop_strategy.cpp:41-64`

**原理：** 计算目标帧率对应的帧间隔 `frameIntervalUs = 1000000 / targetFps`，以 basePts_ 为锚点，每隔 frameIntervalUs 微秒保留一帧。

```cpp
// TimestampDropStrategy::ShouldDropFrame
if (!hasBase_) { basePts_ = pts; hasBase_ = true; return false; }  // 首帧保留
uint64_t elapsed = pts - basePts_;
if (elapsed >= frameIntervalUs_) {
    basePts_ += frameIntervalUs_;  // 推进锚点
    return false;  // 保留
}
return true;  // 丢帧
```

**示例：** 目标30fps，frameIntervalUs_=33333μs，第1帧(pts=0)保留，第2帧(pts≥33333)保留，第3帧(pts<66666)丢帧，以此类推。

### 2.5 策略自动选择逻辑

**Evidence:**
- `frameworks/native/avcodec/pre_processing/frame_drop/frame_drop_filter.cpp:31-58`

```cpp
bool FrameDropFilter::ShouldDropFrame(uint64_t pts) {
    if (!strategyDecided_) {
        if (!hasFirstPts_) {
            hasFirstPts_ = true; firstPts_ = pts;
            return false;  // 首帧固定保留
        }
        strategyDecided_ = true;
        if (pts <= firstPts_) {
            // pts 未推进 → 用 RatioDropStrategy（无时间戳信息的离线场景）
            activeStrategy_ = std::make_unique<RatioDropStrategy>(frameRate_, dropToFps_);
        } else {
            // pts 有推进 → 用 TimestampDropStrategy（实时流场景）
            activeStrategy_ = std::make_unique<TimestampDropStrategy>(dropToFps_);
        }
        // 回填首帧以初始化策略内部状态
        (void)activeStrategy_->ShouldDropFrame(firstPts_);
    }
    return activeStrategy_->ShouldDropFrame(pts);
}
```

**选择依据：**
- `pts > firstPts_`（时间戳推进）→ TimestampDropStrategy（实时流）
- `pts == firstPts_`（时间戳相同）→ RatioDropStrategy（离线/静态场景）

### 2.6 FlushTimeStamp（时间戳刷新）

**Evidence:**
- `frameworks/native/avcodec/pre_processing/frame_drop/frame_drop_filter.cpp:60-65`

FlushTimeStamp 调用 `activeStrategy_->FlushTimeStamp()` 重置策略内部状态：
- RatioDropStrategy：FlushTimeStamp 为空（无状态）
- TimestampDropStrategy：`hasBase_ = false`（清除 PTS 锚点）

### 2.7 与 AdaptiveFramerateController（S25）的区别

| | FrameDropFilter | AdaptiveFramerateController（S25） |
|--|----------------|----------------------------------|
| 定位 | Filter 层丢帧（pre_processing） | CodecServer 层降帧（AFC Loop） |
| 策略 | 按帧比例 / 按时间戳间隔 | 抖动过滤 + 升帧×2.5 + 降帧2次确认 |
| 触发 | Configure(dropToFps, frameRate) | DecodingBehaviorAnalyzer 分析 |
| 作用域 | 单个 Filter 实例 | 全局 CodecServer |

---

## 三、相关记忆引用

| 记忆ID | 标题 | 关联 |
|--------|------|------|
| MEM-ARCH-AVCODEC-S5 | 四层 Loader 插件热加载机制 | dlopen/RTLD_LAZY 与 FastKits dlopen/RTLD_NOW 对比 |
| MEM-ARCH-AVCODEC-S20 | PostProcessing 后处理框架 | VPE 插件 vs FastKits libfast_image.so 硬件加速 |
| MEM-ARCH-AVCODEC-S25 | AdaptiveFramerateController | 与 FrameDropFilter 丢帧策略层级对比 |
| MEM-ARCH-AVCODEC-S17 | SmartFluencyDecoding | AsyncDropDispatcher 丢帧 vs FrameDropFilter 对比 |
| MEM-ARCH-AVCODEC-S6 | 内存复用（ZeroCopy）与 DMA-BUF | SurfaceBuffer 在 FastKits 中的使用 |
