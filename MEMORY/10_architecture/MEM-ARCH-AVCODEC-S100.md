# MEM-ARCH-AVCODEC-S100: PostProcessor Framework — BaseVideoPostProcessor + SuperResolutionPostProcessor + VPE 三层架构

## Status

```yaml
status: pending_approval
created: 2026-05-08T22:25
builder: builder-agent
source: /home/west/av_codec_repo/services/media_engine/modules/post_processor/
```

## Evidence

| 文件 | 行数 | 说明 |
|------|------|------|
| `base_video_post_processor.h` | 112行 | BaseVideoPostProcessor 抽象基类，VideoPostProcessorType 枚举(SUPER_RESOLUTION/CAMERA_INSERT_FRAME/CAMERA_MP_PWP) |
| `super_resolution_post_processor.cpp` | 357行 | SuperResolutionPostProcessor 实现，AutoRegisterPostProcessor 自动注册，VPE回调 |
| `super_resolution_post_processor.h` | 77行 | VpeVideoCallback 接口，OnError/OnState 回调 |
| `video_post_processor_factory.cpp` | 47行 | VideoPostProcessorFactory 工厂 |
| `audio_sampleformat.cpp` | 58行 | AudioSampleFormat 位深映射表 |

## 核心发现

### 1. VideoPostProcessorType 三类后处理器

位置：`base_video_post_processor.h:27-31`

```cpp
enum VideoPostProcessorType {
    NONE,
    SUPER_RESOLUTION,      // 超分
    CAMERA_INSERT_FRAME,   // 相机插帧
    CAMERA_MP_PWP,         // 相机多帧PWP
};
```

### 2. BaseVideoPostProcessor 生命周期 + Surface 接口

位置：`base_video_post_processor.h:33-87`

- 生命周期：Init/Start/Flush/Stop/Release/Pause/NotifyEos
- 双 Surface 接口：GetInputSurface() + SetOutputSurface(sptr<Surface>)
- 输出缓冲：ReleaseOutputBuffer/RenderOutputBufferAtTime
- 参数设置：SetParameter/SetPostProcessorOn/SetVideoWindowSize
- Seek支持：StartSeekContinous/StopSeekContinous/SetSeekTime/ResetSeekInfo
- 速度控制：SetSpeed

### 3. SuperResolutionPostProcessor 自动注册 + 过滤条件

位置：`super_resolution_post_processor.cpp:37-59`

```cpp
static AutoRegisterPostProcessor<SuperResolutionPostProcessor> g_registerSuperResolutionPostProcessor(
    VideoPostProcessorType::SUPER_RESOLUTION,
    []() -> std::shared_ptr<BaseVideoPostProcessor> { ... },
    &isSuperResolutionSupported);
```

过滤条件：`width<=1920 && height<=1080 && !isDrmProtected && !isHdrVivid`

### 4. VPECallback 三状态回调

位置：`super_resolution_post_processor.h` + `super_resolution_post_processor.cpp:81-100`

```cpp
class VPECallback : public VpeVideoCallback {
    void OnError(VPEAlgoErrCode errorCode);
    void OnState(VPEAlgoState state);
    void OnOutputBufferAvailable(uint32_t index, std::shared_ptr<AVBuffer> buffer);
};
```

### 5. AudioSampleFormat 位深映射表

位置：`audio_sampleformat.cpp:17-43`

```cpp
const std::map<Plugins::AudioSampleFormat, int32_t> SAMPLEFORMAT_INFOS = {
    {SAMPLE_S16LE, 16}, {SAMPLE_S24LE, 24}, {SAMPLE_S32LE, 32},
    {SAMPLE_F32LE, 32},  // float 32bit
    {SAMPLE_S64, 64}, {SAMPLE_F64, 64},
    // PLANAR 变体: S16P/S24P/S32P/F32P
    {INVALID_WIDTH, -1},  // 结束标记
};
```

### 6. VideoPostProcessorFactory 工厂模式

位置：`video_post_processor_factory.cpp:47行` + `video_post_processor_factory.h:140行`

- CreateVideoPostProcessor(VideoPostProcessorType) 路由创建
- 与 S85(PreprocessorManager) 对比：PreprocessorManager 处理编码前预处理，PostProcessor 处理解码后/编码后处理

## 关联记忆

- **S85** (PreprocessorManager): 编码前 Crop/Downsample/DropFrame 三功能，与 PostProcessor 处理阶段互补
- **S20** (PostProcessing): DynamicController+DynamicInterface+LockFreeQueue 三组件与 VPE 插件热加载，与 S100 对比增强
- **S80** (SurfaceBuffer): Owner 枚举与 SwapOut/SwapIn，与 PostProcessor 内存管理关联
- **S92** (MediaCodec): CodecState 十二态机，与 PostProcessor 生命周期同步

## Scope

AVCodec, PostProcessor, VideoProcessingEngine, VPE, SuperResolution, CameraPostProcessing, AutoRegisterPostProcessor