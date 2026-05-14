# MEM-ARCH-AVCODEC-S135

> **Draft** — Pending Approval
> Generated: 2026-05-14T21:08 by Builder Agent (Subagent)
> Topic: S135 — WaterMarkFilter 水印过滤器

---

## 1. Topic Summary

**主题**: WaterMarkFilter 水印过滤器——OpenGL ES GPU 加速视频水印叠加

**一句话描述**: OpenGL ES GPU 渲染管线 + OH_NativeImage 视频纹理绑定，支持 5 个水印 20MB 限制，专用于转码管线水印注入。

**关联场景**: 新需求开发 / 问题定位

**关联主题**: S14(FilterChain) / S20(PostProcessing) / S46(DecoderSurfaceFilter)

---

## 2. Evidence (行号级)

### 核心文件

| 文件 | 行数 | 说明 |
|------|------|------|
| `services/media_engine/filters/water_mark_filter.cpp` | 1001 | Filter 实现 + OpenGL 渲染管线 |
| `interfaces/inner_api/native/water_mark_filter.h` | 155 | 头文件公开接口 |

### 注册机制

```cpp
// water_mark_filter.cpp:124-130
static AutoRegisterFilter<WaterMarkFilter> g_registerWaterMarkFilter("builtin.transcoder.watermark",
    FilterType::WATERMARK,
    [](const std::string& name, const FilterType type) {
        return std::make_shared<WaterMarkFilter>(name, FilterType::WATERMARK);
    });
```
- 注册名: `"builtin.transcoder.watermark"`
- FilterType: `WATERMARK`
- AutoRegisterFilter CRTP 静态注册

### 常量定义

```cpp
// water_mark_filter.cpp:31-37
const uint32_t MAX_WATERMARK_NUMBER = 5;
const uint64_t MAX_WATERMARK_SIZE = 20 * 1024 * 1024;  // 20MB
const uint32_t DRAW_COUNT = 4;
const uint32_t ELEMENT_COUNT = 6;
const uint32_t POINTS_COUNT = 3;
const uint32_t MATRIX4V_COUNT = 16;
```

### FilterLinkCallback 回调链路

```cpp
// water_mark_filter.cpp:130-160
class WaterMarkFilterLinkCallback : public FilterLinkCallback {
public:
    explicit WaterMarkFilterLinkCallback(std::shared_ptr<WaterMarkFilter> WaterMarkFilter)
        : waterMarkFilter_(std::move(WaterMarkFilter)) {}
    void OnLinkedResult(const sptr<AVBufferQueueProducer> &queue, std::shared_ptr<Meta> &meta) override
    void OnUnlinkedResult(std::shared_ptr<Meta> &meta) override
    void OnUpdatedResult(std::shared_ptr<Meta> &meta) override
};
```

### OpenGL 顶点着色器

```cpp
// water_mark_filter.cpp:37-52
std::string vertexShader = R"delimiter(
attribute vec3 position;
attribute vec2 texCoord;
varying vec2 vTexCoord;
uniform mat4 matTransform;
void main()
{
    gl_Position = vec4(position, 1.0);
    vTexCoord = texCoord;
}
)delimiter";
```

### EGL 上下文初始化

```cpp
// water_mark_filter.cpp:204-222
bool WaterMarkFilter::InitializeEGLContext()
{
    renderContext_ = std::make_unique<EglRenderContext>();
    FALSE_RETURN_V_MSG(renderContext_->Init(), false, "Failed to initialize EGL render context");
    eglSurface_ = renderContext_->CreateEglSurface(static_cast<EGLNativeWindowType>(nativeWindow_));
    renderContext_->MakeCurrent(eglSurface_);
    return true;
}
```

### OH_NativeImage 视频纹理绑定

```cpp
// water_mark_filter.cpp:178-196
bool WaterMarkFilter::CreateNativeImage()
{
    nativeImage_ = OH_NativeImage_Create(-1, GL_TEXTURE_EXTERNAL_OES);
    nativeImageWindow_ = OH_NativeImage_AcquireNativeWindow(nativeImage_);
    nativeImageFrameAvailableListener_.context = this;
    nativeImageFrameAvailableListener_.onFrameAvailable = &WaterMarkFilter::OnNativeImageFrameAvailable;
    ret = OH_NativeImage_SetOnFrameAvailableListener(nativeImage_, nativeImageFrameAvailableListener_);
}

// water_mark_filter.cpp:261-271
bool WaterMarkFilter::CreateVideoTexture()
{
    glGenTextures(1, &nativeImageTexId_);
    glBindTexture(GL_TEXTURE_EXTERNAL_OES, nativeImageTexId_);
    // OH_NativeImage_AttachContext 将 NativeImage 与 OpenGL 纹理关联
    OH_NativeImage_AttachContext(nativeImage_, nativeImageTexId_);
}
```

### 水印 OpenGL 纹理创建

```cpp
// water_mark_filter.cpp:247-268
bool WaterMarkFilter::CreateWatermarkTextures()
{
    watermarkTexIds_.resize(watermarkList_.size());
    glGenTextures(watermarkList_.size(), watermarkTexIds_.data());
    for (size_t i = 0; i < watermarkList_.size(); i++) {
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, config.rawWidth, config.rawHeight,
                     0, GL_RGBA, GL_UNSIGNED_BYTE, config.buffer);
    }
}
```

### FBO 水印合并渲染

```cpp
// water_mark_filter.cpp:460-492
bool WaterMarkFilter::RenderWatermarksToFBO(int32_t width, int32_t height)
{
    glBindFramebuffer(GL_FRAMEBUFFER, watermarkFBO_);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, mergedWatermarkTexId_, 0);
    // 每个水印绘制到 FBO
    for (size_t i = 0; i < watermarkList_.size(); i++) {
        float x = static_cast<float>(config.left) * 2.0f / width - 1.0f;
        float y = -1.0f + static_cast<float>(config.top) * 2.0f / height;
        // ... 顶点坐标计算 ...
        glDrawArrays(GL_TRIANGLE_FAN, 0, DRAW_COUNT);
    }
}
```

### 水印合并合成

```cpp
// water_mark_filter.cpp:495-520
bool WaterMarkFilter::MergeWaterMarksWithOpenGL()
{
    FALSE_RETURN_V_MSG(CreateWatermarkFBO(mergedWidth, mergedHeight), false, ...);
    FALSE_RETURN_V_MSG(CreateWatermarkMergeShader(), false, ...);
    FALSE_RETURN_V_MSG(RenderWatermarksToFBO(mergedWidth, mergedHeight), false, ...);
}
```

### RenderLoop 渲染主循环

```cpp
// water_mark_filter.cpp:383-417
void WaterMarkFilter::RenderLoop()
{
    while (running_) {
        std::unique_lock<std::mutex> lock(wakeUpMutex_);
        wakeUpCond_.wait(lock, [this]() { return availableFrameCnt_.load() > 0 || eosPts_.load() != -1; });
        if (availableFrameCnt_.load() > 0) {
            availableFrameCnt_.fetch_sub(1, std::memory_order_relaxed);
            renderContext_->MakeCurrent(eglSurface_);
            OH_NativeImage_UpdateSurfaceImage(nativeImage_);
            lastPts_.store(OH_NativeImage_GetTimestamp(nativeImage_));
            DrawImage(lastPts_.load());
        }
        if (eosPts_.load() == lastPts_.load()) {
            NotifyNextFilterEos();
            break;
        }
    }
}
```

### 帧绘制与 EGL Swap

```cpp
// water_mark_filter.cpp:225-237
void WaterMarkFilter::DrawImage(const int64_t pts)
{
    glViewport(0, 0, targetWidth_, targetHeight_);
    glClearColor(1.0f, 1.0f, 1.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glBindVertexArray(vertexArrayObject_);
    glEnable(GL_DEPTH_TEST);
    glDrawElements(GL_TRIANGLES, ELEMENT_COUNT, GL_UNSIGNED_INT, indices);
    OH_NativeWindow_NativeWindowHandleOpt(nativeWindow_, SET_UI_TIMESTAMP, pts);
    renderContext_->SwapBuffers(eglSurface_);
}
```

### SetOutputSurface 触发线程创建

```cpp
// water_mark_filter.cpp:697-710
Status WaterMarkFilter::SetOutputSurface(sptr<Surface> surface, int32_t width, int32_t height)
{
    targetWidth_ = width;
    targetHeight_ = height;
    auto window = CreateNativeWindowFromSurface(&surface);
    UpdateNativeWindow(window, width, height);
    FALSE_RETURN_V_MSG(!thread_.joinable(), Status::OK, "thread_ is run");  // 只创建一次
    thread_ = std::thread([this]() { ThreadMainLoop(); });  // 启动渲染线程
    return Status::OK;
}
```

### DoPrepare 七生命周期

```cpp
// water_mark_filter.cpp:713-730
Status WaterMarkFilter::DoPrepare()
{
    switch (filterType_) {
        case FilterType::WATERMARK:
            filterCallback_->OnCallback(shared_from_this(), FilterCallBackCommand::NEXT_FILTER_NEEDED,
                StreamType::STREAMTYPE_RAW_VIDEO);
            return Status::OK;
        ...
    }
}
Status WaterMarkFilter::DoStart() // line 728
Status WaterMarkFilter::DoPause() // line 734
Status WaterMarkFilter::DoResume() // line 740
Status WaterMarkFilter::DoStop() // line 746
Status WaterMarkFilter::DoFlush() // line 752
Status WaterMarkFilter::DoRelease() // line 757-797
```

### SetWatermark 水印配置

```cpp
// water_mark_filter.cpp:595-635
Status WaterMarkFilter::SetWatermark(std::shared_ptr<AVBuffer> &waterMarkBuffer, int32_t width, int32_t height)
{
    FALSE_RETURN_V_MSG(watermarkList_.size() < MAX_WATERMARK_NUMBER, ...);  // ≤5个
    FALSE_RETURN_V_MSG(hiheight <= MAX_WATERMARK_SIZE / histride, ...);     // ≤20MB
    FALSE_RETURN_V_MSG(bufferSize < MAX_WATERMARK_SIZE && bufferSize > 0, ...);
    watermarkList_.push_back({top, left, watermarkWidth, watermarkHeight, rawHeight, rawWidth, bufferSize, buffer});
}
```

### SetVideoResize 视频缩放

```cpp
// water_mark_filter.cpp:639-648
Status WaterMarkFilter::SetVideoResize(int32_t width, int32_t height)
{
    videoWidth_.store(width);
    videoHeight_.store(height);
    MEDIA_LOG_I("SetVideoResize videoWidth_: %{public}d videoHeight_: %{public}d", ...);
}
```

### SetFaultEvent DFX 错误上报

```cpp
// water_mark_filter.cpp:976-984
void WaterMarkFilter::SetFaultEvent(const std::string &errMsg, int32_t ret)
void WaterMarkFilter::SetFaultEvent(const std::string &errMsg)
```

### DoRelease 资源释放

```cpp
// water_mark_filter.cpp:757-797
Status WaterMarkFilter::DoRelease()
{
    MEDIA_LOG_I("DoRelease enter");
    FALSE_RETURN_V_MSG(!hasReleased_, Status::OK, "DoRelease already called, skip");
    running_ = false;
    wakeUpCond_.notify_one();
    if (thread_.joinable()) thread_.join();
    ReleaseEGLResources();
    ReleaseGpuResources();
    ReleaseCpuResources();
    hasReleased_ = true;
    MEDIA_LOG_I("DoRelease success");
}
```

---

## 3. Architecture Summary

```
┌─────────────────────────────────────────────────────────────┐
│                 WaterMarkFilter (Filter)                    │
│  FilterType::WATERMARK / "builtin.transcoder.watermark"     │
├─────────────────────────────────────────────────────────────┤
│  输入: OH_NativeImage (视频帧 Surface 纹理)                 │
│  水印: MAX_WATERMARK_NUMBER=5 / MAX_WATERMARK_SIZE=20MB    │
│  输出: OHNativeWindow (带水印的视频帧 Surface)              │
├─────────────────────────────────────────────────────────────┤
│  OpenGL ES 2.0 渲染管线                                      │
│  ├── EglRenderContext (EGL 上下文/表面)                      │
│  ├── ShaderProgram (顶点+片段着色器)                         │
│  ├── GL_TEXTURE_EXTERNAL_OES (视频帧纹理绑定)                │
│  └── GL_TEXTURE_2D (水印纹理，MAX=5)                         │
├─────────────────────────────────────────────────────────────┤
│  渲染线程 (std::thread)                                      │
│  ├── ThreadMainLoop() → InitializeEGLContext()              │
│  ├── CreateGLResources() → MergeWaterMarksWithOpenGL()     │
│  ├── RenderLoop(): wakeUpCond_ 等待帧 + OH_NativeImage      │
│  └── DrawImage(): glDrawElements + SwapBuffers              │
├─────────────────────────────────────────────────────────────┤
│  七 Filter 生命周期                                          │
│  DoPrepare → DoStart → DoPause → DoResume → DoStop         │
│  DoFlush → DoRelease                                         │
├─────────────────────────────────────────────────────────────┤
│  关键接口                                                    │
│  SetWatermark(AVBuffer, width, height)                      │
│  SetVideoResize(width, height)                               │
│  SetOutputSurface(Surface, width, height)                    │
│  SetFaultEvent(errMsg, ret)                                   │
│  SetCallingInfo(appUid, appPid, bundleName, instanceId)     │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. 与其他 Filter 的关系

| 关联 Filter | 关系 | 说明 |
|------------|------|------|
| DecoderSurfaceFilter (S45/S46) | 上游视频源 | 提供 OH_NativeImage 纹理 |
| VideoRenderFilter (S32) | 下游输出终点 | 水印叠加后输出到 Surface |
| VideoResizeFilter (S12) | 并列视频处理 | 都是转码管线 Filter |
| MuxerFilter (S34) | 下游终点 | 水印处理完进入封装 |

---

## 5. 关键设计点

1. **GPU 加速**: 所有水印叠加在 GPU 上执行 (OpenGL ES)，不占用 CPU
2. **FBO 合并**: 先将所有水印渲染到 FBO，再与视频帧合成
3. **OH_NativeImage**: 将视频帧 Surface 绑定为 GL_TEXTURE_EXTERNAL_OES 纹理
4. **独立渲染线程**: SetOutputSurface 时启动专用 RenderLoop 线程
5. **EOS 处理**: RenderLoop 检测到 eosPts_==lastPts_ 时调用 NotifyNextFilterEos
6. **DFX 错误上报**: SetFaultEvent 支持带错误码上报
7. **水印数量限制**: 最多 5 个水印，每个最大 20MB

---

## 6. 引用

- `repo_tmp/services/media_engine/filters/water_mark_filter.cpp:1001行`
- `repo_tmp/interfaces/inner_api/native/water_mark_filter.h:155行`
- FilterChain 架构: S14
- PostProcessing 框架: S20
- DecoderSurfaceFilter: S45/S46