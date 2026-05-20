---
type: architecture
id: MEM-ARCH-AVCODEC-S169
status: draft
topic: FrameDropFilter + FastKitsInterface 预处理器框架——双策略丢帧(Ratio/Timestamp)与硬件加速图像处理
scope: [AVCodec, PreProcessing, FrameDrop, FastKitsInterface, Preprocessor, RatioDropStrategy, TimestampDropStrategy, ImageProcessing, Crop, Downsample, Scale, dlopen]
created_at: "2026-05-21T02:30:00+08:00"
updated_at: "2026-05-21T02:30:00+08:00"
source_repo: /home/west/av_codec_repo
source_root: frameworks/native/avcodec/pre_processing/
evidence_version: local_mirror
关联主题: S33(PreProcessing) / S85(PreprocessorManager) / S14(FilterChain) / S20(PostProcessing)
---

# MEM-ARCH-AVCODEC-S169: FrameDropFilter + FastKitsInterface 预处理器框架

> **状态**: draft
> **生成时间**: 2026-05-21T02:30:00+08:00
> **Builder**: builder-agent

---

## 一、架构总览

预处理器框架位于 `frameworks/native/avcodec/pre_processing/`，包含两个独立子模块：

| 子模块 | 路径 | 行数 | 职责 |
|--------|------|------|------|
| **FrameDropFilter** | `frame_drop/frame_drop_filter.{h,cpp}` + `frame_drop_strategy.{h,cpp}` | 67+87 | 视频帧智能丢帧，支持 RatioDropStrategy（等比例保留）和 TimestampDropStrategy（时间戳间隔）两种策略 |
| **FastKitsInterface** | `fast_kits_interface.{h,cpp}` | 101+204 | 硬件加速图像处理接口，封装裁剪(Crop)、缩放(Downsample/Scale) 等操作 |

**与 S85(PreprocessorManager) 的关系**：
- S85 从 CAPI 层视角描述 PreprocessorManager 如何编排 FastKitsInterface + FrameDropFilter
- S169 从源码层深入 FrameDropFilter 双策略实现细节 + FastKitsInterface 硬件加速能力

```
frameworks/native/avcodec/pre_processing/
├── frame_drop/
│   ├── frame_drop_filter.h   (67行)   Filter主类 + Configure/ShouldDropFrame/FlushTimeStamp
│   ├── frame_drop_filter.cpp (127行)  三态决策逻辑(首帧/策略选择/丢帧判定)
│   ├── frame_drop_strategy.h (93行)   IDropStrategy抽象基类 + RatioDropStrategy + TimestampDropStrategy
│   └── frame_drop_strategy.cpp (93行)  两策略实现(等比例帧保留 vs PTS间隔丢帧)
└── fast_kits_interface/
    ├── fast_kits_interface.h (101行)  图像处理接口(CropRect/缩放/格式转换)
    └── fast_kits_interface.cpp (204行) dlopen libfast_image.z.so + 12个图像处理函数
```

---

## 二、FrameDropFilter 丢帧过滤器

**源码路径**：`frameworks/native/avcodec/pre_processing/frame_drop/frame_drop_filter.h` + `.cpp`

### 2.1 类定义与接口

**证据**：`frame_drop_filter.h:23-57`

```cpp
class FrameDropFilter {
public:
    FrameDropFilter() = default;
    ~FrameDropFilter() = default;

    int32_t Configure(double dropToFps, double frameRate);  // L26: 配置目标帧率
    bool ShouldDropFrame(uint64_t pts);                        // L27: 丢帧判定入口
    void FlushTimeStamp();                                    // L28: 清空时间戳状态

private:
    double dropToFps_ = 0.0;            // L32: 目标帧率
    double frameRate_ = 0.0;            // L33: 源帧率
    bool strategyDecided_ = false;      // L35: 策略是否已确定
    bool hasFirstPts_ = false;          // L36: 是否收到首帧
    uint64_t firstPts_ = 0;             // L37: 首帧PTS
    std::unique_ptr<IDropStrategy> activeStrategy_;  // L40: 当前策略
    std::mutex mutex_;                  // L42: 线程安全保护
};
```

### 2.2 三态决策逻辑

**证据**：`frame_drop_filter.cpp:43-77`（ShouldDropFrame 核心逻辑）

```
状态机演进：
┌─────────────────┐
│  INIT (首帧到达前) │  hasFirstPts_=false
└────────┬────────┘
         │ 首帧到达 (pts)
         ▼
┌─────────────────┐
│  STRATEGY_DECIDE │  strategyDecided_=false → true
└────────┬────────┘
         │ 决策时刻：pts<=firstPts_? Ratio策略 : Timestamp策略
         ▼
┌─────────────────┐
│  ACTIVE          │  activeStrategy_->ShouldDropFrame(pts)
└─────────────────┘
```

**首帧保留逻辑**（L46-51）：
```cpp
if (!hasFirstPts_) {
    hasFirstPts_ = true;
    firstPts_ = pts;
    AVCODEC_LOGI("First frame kept, pts=%{public}" PRIu64, pts);
    return false;  // 首帧永远不丢
}
```

**策略选择**（L53-59）：
```cpp
strategyDecided_ = true;
if (pts <= firstPts_) {
    // 录像回退场景：使用 RatioDropStrategy（按帧率比例丢帧）
    activeStrategy_ = std::make_unique<RatioDropStrategy>(frameRate_, dropToFps_);
    AVCODEC_LOGI("Timestamp unchanged, using ratio strategy (frameRate=%{public}.2f)", frameRate_);
} else {
    // 实时流场景：使用 TimestampDropStrategy（按时间戳间隔丢帧）
    activeStrategy_ = std::make_unique<TimestampDropStrategy>(dropToFps_);
    AVCODEC_LOGI("Timestamp changed, using timestamp strategy (targetFps=%{public}.2f)", dropToFps_);
}
```

### 2.3 双策略实现

**源码路径**：`frameworks/native/avcodec/pre_processing/frame_drop/frame_drop_strategy.h` + `.cpp`

#### RatioDropStrategy：等比例帧保留

**证据**：`frame_drop_strategy.cpp:24-50`

```cpp
// L24-28: 构造函数
RatioDropStrategy::RatioDropStrategy(double srcFrameRate, double targetFrameRate)
    : srcFrameRate_(srcFrameRate), targetFrameRate_(targetFrameRate) {}

// L29-48: 丢帧判定（每帧都检查，保持比例）
bool RatioDropStrategy::ShouldDropFrame(uint64_t pts)
{
    totalFrames_++;                           // L31: 累计总帧数
    if (static_cast<double>(keptFrames_) / totalFrames_ >= targetFrameRate_ / srcFrameRate_) {
        keptFrames_++;                        // L34: 超出比例则保留
        return false;
    }
    return true;                             // L36: 其余丢弃
}
```

**算法**：`keptFrames_/totalFrames_ >= targetFps/srcFps`，即保留 `targetFps/srcFps` 比例的帧。

#### TimestampDropStrategy：时间戳间隔丢帧

**证据**：`frame_drop_strategy.cpp:56-91`

```cpp
// L56-61: 构造函数
TimestampDropStrategy::TimestampDropStrategy(double targetFrameRate)
    : frameIntervalUs_(0) {
    frameIntervalUs_ = static_cast<uint64_t>(1000000.0 / targetFrameRate);  // L59: 目标帧间隔(μs)
}

// L66-85: 丢帧判定
bool TimestampDropStrategy::ShouldDropFrame(uint64_t pts)
{
    if (!hasBase_) {
        basePts_ = pts;           // L68: 基准PTS
        hasBase_ = true;
        return false;            // 首帧保留
    }
    uint64_t elapsed = pts - basePts_;        // L71: 相对时间
    uint64_t expectedFrames = elapsed / frameIntervalUs_;  // L72: 应有帧数
    uint64_t actualFrames = expectedFrames;     // 实际到达帧数即为expectedFrames
    if (actualFrames > 0) {
        basePts_ += frameIntervalUs_;          // L76: 更新基准
        return false;
    }
    return true;
}
```

**算法**：保持 `1/frameIntervalUs_` 帧/秒的目标帧率，在基准PTS上叠加间隔后更新。

---

## 三、FastKitsInterface 硬件图像处理

**源码路径**：`frameworks/native/avcodec/pre_processing/fast_kits_interface/fast_kits_interface.h` + `.cpp`

### 3.1 类定义

**证据**：`fast_kits_interface.h:26-101`

```cpp
class FastKitsInterface {
public:
    struct CropRect {
        int32_t x;
        int32_t y;
        int32_t width;
        int32_t height;
    };

    enum PixelFormat : int32_t { ... };  // 像素格式枚举
    enum Rotation : int32_t { ROTATION_0 = 0, ROTATION_90, ROTATION_180, ROTATION_270 };
    enum ScaleMode : int32_t { ... };

    FastKitsInterface();
    ~FastKitsInterface();

    // L47-51: 初始化
    int32_t Init();
    // L53-56: 图像缩放
    int32_t Scale(const uint8_t* src, int32_t srcWidth, int32_t srcHeight,
                  PixelFormat srcFormat, uint8_t* dst, int32_t dstWidth, int32_t dstHeight,
                  PixelFormat dstFormat, ScaleMode mode);
    // L58-63: 图像裁剪
    int32_t Crop(const uint8_t* src, int32_t srcWidth, int32_t srcHeight,
                 PixelFormat srcFormat, uint8_t* dst, int32_t dstWidth, int32_t dstHeight,
                 PixelFormat dstFormat, const CropRect& rect);
    // L65-68: 格式转换
    int32_t ConvertFormat(const uint8_t* src, int32_t width, int32_t height,
                          PixelFormat srcFormat, uint8_t* dst, PixelFormat dstFormat);

private:
    void* libHandle_ = nullptr;      // dlopen句柄
    // 函数指针表...
};
```

### 3.2 dlopen 动态加载

**证据**：`fast_kits_interface.cpp:L70-100`

```cpp
// L70-85: dlopen加载libfast_image.z.so
libHandle_ = dlopen("libfast_image.z.so", RTLD_NOW);
if (!libHandle_) {
    MEDIA_LOG_E("dlopen libfast_image failed: %{public}s", dlerror());
    return AVCS_ERR_UNKNOWN;
}

// L86-100: dlsym加载12个图像处理函数符号
auto scaleFunc = dlsym(libHandle_, "Scale");
auto cropFunc = dlsym(libHandle_, "Crop");
auto convertFunc = dlsym(libHandle_, "ConvertFormat");
auto rotateFunc = dlsym(libHandle_, "Rotate");
// ... 共12个函数指针
```

---

## 四、与 S85(PreprocessorManager) 的关系

**证据**：`frameworks/native/avcodec/pre_processing/frame_drop/frame_drop_filter.h` + `services/media_engine/filters/`

```
PreprocessorManager (S85 CAPI层)
  └── Preprocessor (封装层)
       ├── FastKitsInterface  ──> 图像裁剪/缩放/格式转换 (本记忆 S169 §3)
       └── FrameDropFilter      ──> 智能丢帧 (本记忆 S169 §2)
```

**S85 已有信息**：PreprocessorManager 的 EncoderThreadLoop（`OS_Preproc_{encoderId}_Loop`）线程驱动预处理循环，调用 Preprocessor 的 Crop/Downsample/DropFrame 三模式。

**本记忆 S169 新增**：
- FrameDropFilter 内部双策略（Ratio/Timestamp）的源码级决策逻辑
- FastKitsInterface dlopen 加载 libfast_image.z.so 的 12 个函数指针
- 第一帧永远保留的机制（hasFirstPts_ 标志）

---

## 五、关键行号索引

| 证据位置 | 行号 | 描述 |
|----------|------|------|
| `frame_drop_filter.h` | 23-57 | FrameDropFilter 类定义 |
| `frame_drop_filter.cpp` | 43-77 | ShouldDropFrame 三态决策逻辑 |
| `frame_drop_filter.cpp` | 26-30 | Configure 接口实现 |
| `frame_drop_strategy.h` | 23-50 | IDropStrategy/RatioDropStrategy/TimestampDropStrategy 类定义 |
| `frame_drop_strategy.cpp` | 24-50 | RatioDropStrategy::ShouldDropFrame |
| `frame_drop_strategy.cpp` | 56-91 | TimestampDropStrategy::ShouldDropFrame |
| `fast_kits_interface.h` | 26-101 | FastKitsInterface 类定义 |
| `fast_kits_interface.cpp` | 70-100 | dlopen libfast_image.z.so + dlsym |

---

## 六、关联记忆

| 关联编号 | 关系 |
|----------|------|
| S33 | PreProcessing 预处理器框架（总览），S169 补充 FrameDropFilter 源码细节 |
| S85 | PreprocessorManager CAPI 层，S169 提供底层 FrameDropFilter/FastKitsInterface 实现 |
| S14 | Filter Chain 架构，FrameDropFilter 不属于 Filter Pipeline，属于预处理阶段 |
| S20 | PostProcessing VPE 后处理，与 FastKitsInterface 同类硬件加速但位置不同（预处理 vs 后处理） |