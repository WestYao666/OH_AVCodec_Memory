# MEM-ARCH-AVCODEC-S227: PostProcessing Dynamic Controller 动态色彩空间转换控制器

## 主题分类
- **scope**: AVCodec, VideoCodec, PostProcessing, DynamicController, ColorSpace, dlopen
- **关联场景**: 新需求开发/问题定位/视频后处理/色彩空间转换
- **状态**: draft

## 摘要

AVCodec 视频后处理框架的 DynamicController 组件——基于 CRTP 模板模式与 dlopen 动态库加载的色彩空间转换控制器。使用 Controller<T> CRTP 基类 + DynamicInterface dlopen 插件接口，实现 17 个函数指针的运行时绑定，支持 DISABLED/CONFIGURED/PREPARED/RUNNING/FLUSHED/STOPPED 六状态机。

## 源码证据

| # | 文件 | 行数 | 关键发现 |
|---|------|------|---------|
| E1 | post_processing.h | 451 | PostProcessing<T> 模板类，CRTP 模式，IsDerivedController 约束检查，Create 工厂方法 |
| E2 | controller.h | 143 | Controller<T> CRTP 基类，This() 返回派生类指针，12 个生命周期方法委托 |
| E3 | dynamic_controller.h | 63 | DynamicController : public Controller<DynamicController>，ready_ 状态标志，DynamicInterface 成员 |
| E4 | dynamic_controller.cpp | 181 | LoadInterfacesImpl dlopen(libdynamiccolorconverter.z.so)，17 个函数指针符号读取 |
| E5 | dynamic_interface.h | 99 | DynamicInterface 模板方法 Invoke，接口数组 interfaces_，OpenLibrary dlopen |
| E6 | dynamic_interface.cpp | 125 | ReadSymbols dlsym 遍历 17 个符号，ClearSymbols 释放 interfaces_ |
| E7 | dynamic_interface_types.h | 123 | 17 个函数指针类型，DynamicInterfaceFuncTypes TypeArray，符号表 DYNAMIC_INTERFACE_SYMBOLS |
| E8 | dynamic_interface_types.h L69-85 | - | 符号枚举 DynamicInterfaceName {IS_COLORSPACE_CONVERSION_SUPPORTED ~ NOTIFY_EOS} |
| E9 | dynamic_interface_types.h L89-105 | - | EnumerationValue 模板，DynamicInterfaceIndex/DynamicInterfaceIndexValue 编译期计算 |
| E10 | post_processing_utils.h | 71 | TypeArray 模板元编程，EnumerationValue 枚举值编译期转换，CapabilityInfo 色域元数据结构 |
| E11 | state_machine.h | 50 | StateMachine 原子状态，六状态枚举 DISABLED/CONFIGURED/PREPARED/RUNNING/FLUSHED/STOPPED |
| E12 | state_machine.cpp | 52 | StateMachine::Get/Set 原子操作，Name() 状态名字符串映射 |
| E13 | post_processing_callback.h | 42 | PostProcessingCallback 接口，OnError/OnOutputBufferAvailable/OnOutputFormatChanged 三回调 |
| E14 | post_processing.h L37-47 | - | PostProcessing<T>::Create 工厂方法，codec + format 参数，返回 unique_ptr<PostProcessing<T>> |
| E15 | dynamic_controller.cpp L20-45 | - | LoadInterfacesImpl：dlopen("libdynamiccolorconverter.z.so") → ReadSymbols → dlsym 17 个函数 |
| E16 | dynamic_controller.cpp L50-75 | - | DynamicInterface::OpenLibrary dlopen 路径 "/vendor/lib/libdynamiccolorconverter.z.so" |
| E17 | dynamic_controller.cpp L80-110 | - | CreateImpl/ConfigureImpl/StartImpl/StopImpl 生命周期管理，ready_ 状态标志控制 |
| E18 | dynamic_controller.cpp L115-140 | - | SetOutputSurfaceImpl/SetCallbackImpl Surface 和回调设置，instance_ 处理器句柄 |

## 核心架构

### 1. CRTP Controller 模板模式

```cpp
// controller.h - CRTP 基类
template<typename T>
class Controller {
    bool LoadInterfaces() { return This()->LoadInterfacesImpl(); }
    int32_t Create() { return This()->CreateImpl(); }
    int32_t Configure(Media::Format& config) { return This()->ConfigureImpl(config); }
    // ... 12 个生命周期方法
private:
    T* This() { return static_cast<T*>(this); }
};

// dynamic_controller.h - 派生类
class DynamicController : public Controller<DynamicController> {
    bool LoadInterfacesImpl() override;
    int32_t CreateImpl() override;
    int32_t ConfigureImpl(Media::Format& config) override;
    // ... 12 个实现
};
```

### 2. dlopen 动态接口加载

```cpp
// dynamic_interface.h - 17 个函数指针的运行时绑定
class DynamicInterface {
    void* lib_{nullptr};  // dlopen 句柄
    std::array<void*, DYNAMIC_INTERFACE_NUM> interfaces_{nullptr};  // 函数指针数组
    
    template<DynamicInterfaceName E, typename... Args>
    RetT Invoke(Args&&... args) {
        auto interface = reinterpret_cast<...>(interfaces_[I]);  // I = 编译期计算
        return interface(std::forward<Args>(args)...);
    }
};

// 符号表 (dynamic_interface_types.h L69-85)
constexpr const char* DYNAMIC_INTERFACE_SYMBOLS[]{
    "ColorSpaceConvertVideoIsColorSpaceConversionSupported",  // E0
    "ColorSpaceConvertVideoCreate",                            // E1
    "ColorSpaceConvertVideoDestroy",                           // E2
    "ColorSpaceConvertVideoSetCallback",                      // E3
    // ... 共 17 个
    "ColorSpaceConvertVideoNotifyEos"                         // E16
};
```

### 3. 六状态机

```cpp
// state_machine.h - 原子状态机
enum class State { DISABLED, CONFIGURED, PREPARED, RUNNING, FLUSHED, STOPPED };
std::atomic<State> state_{State::DISABLED};
```

### 4. CapabilityInfo 色域能力

```cpp
// post_processing_utils.h - 色域转换能力元数据
struct CapabilityInfo {
    int32_t colorSpaceType;   // 色彩空间类型
    int32_t metadataType;     // 元数据类型
    int32_t pixelFormat;       // 像素格式
};
```

## 生命周期流程

```
LoadInterfaces() → dlopen libdynamiccolorconverter.z.so → dlsym 17 个函数指针
        ↓
Create() → ColorSpaceConvertVideoCreate() → instance_ 处理器句柄
        ↓
Configure(format) → ColorSpaceConvertVideoConfigure(format) → ready_ = true
        ↓
Prepare() → ColorSpaceConvertVideoPrepare()
        ↓
Start() → ColorSpaceConvertVideoStart()
        ↓
[RUNNING] → 处理视频帧色彩空间转换
        ↓
Stop() → ColorSpaceConvertVideoStop()
        ↓
Release() → ColorSpaceConvertVideoRelease() → dlclose lib_
```

## 编译期模板元编程

```cpp
// TypeArray 模板 (post_processing_utils.h)
template<typename... Types>
struct TypeArray {
    using Array = std::tuple<Types...>;
    template<size_t I>
    using Get = std::tuple_element_t<I, Array>;
    static constexpr size_t size = sizeof...(Types);
};

// DynamicInterfaceFuncTypes (dynamic_interface_types.h)
using DynamicInterfaceFuncTypes = TypeArray<
    DynamicIsColorSpaceConversionSupportedFunc,  // E0
    DynamicCreateFunc,                             // E1
    DynamicDestroyFunc,                             // E2
    // ... 14 more
    DynamicNotifyEos                                // E16
>;

// 编译期索引计算
template<DynamicInterfaceName E>
constexpr DynamicInterfaceIndexType<E> DynamicInterfaceIndexValue = ...;  // E → index
```

## 关联主题

- S20: VideoPostProcessor 框架五类后处理器 (SIDE_OUTPUT/SUPER_RESOLUTION/SCREEN_COLOR_TRANSFORM/DETAIL_ENHANCER/CAMERA)
- S100: VideoPostProcessorFramework 视频后处理框架
- S127: VideoPostProcessorFramework (detailed)
- S226: VideoResizeFilter VPE DetailEnhancer

## 关键词

`DynamicController` `CRTP` `dlopen` `ColorSpaceConverter` `libdynamiccolorconverter.z.so` `17函数指针` `六状态机` `TemplateMetaprogramming`

---

*Builder: builder-agent | 2026-06-08 | draft → pending_approval*