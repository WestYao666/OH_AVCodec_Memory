# MEM-ARCH-AVCODEC-S199.md

## 主题
VideoCodecLoader 视频编解码器动态加载架构——dlopen/RTLD_LAZY双函数指针注入与七类Loader工厂

## 状态
draft

## 提交时间
2026-06-04T17:35

## scope
AVCodec, VideoCodecLoader, dlopen, RTLD_LAZY, CreateByName, GetCapabilityList, CodecBase, CodecFactory, FCodec, HevcDecoder, AvcEncoder, AV1, VP8, VP9, Hcodec, VideoCodec

## 关联场景
新人入项/代码导航/动态库加载/Factory模式

## 关联记忆
- S178: AVCodec源代码双目录架构（services/engine/codec 与 services/media_engine/plugins 并行）
- S183: AvcEncoder H.264软件编码器体系
- S137: SA Codec IPC服务框架
- S95: AudioCodec C API实现

## 源码行数
- video_codec_loader.cpp: ~70行
- fcodec_loader.cpp: ~72行
- hevc_decoder_loader.cpp: ~72行
- avc_encoder_loader.cpp: ~72行
- av1_decoder_loader.cpp: ~70行
- vp8_decoder_loader.cpp: ~70行
- vp9_decoder_loader.cpp: ~70行
- hcodec_loader.cpp: ~70行
- 总计约: 600行

## source_files
- services/engine/codec/video/video_codec_loader.cpp
- services/engine/codec/video/fcodec_loader.cpp
- services/engine/codec/video/hevc_decoder_loader.cpp
- services/engine/codec/video/avc_encoder_loader.cpp
- services/engine/codec/video/av1_decoder_loader.cpp
- services/engine/codec/video/vp8_decoder_loader.cpp
- services/engine/codec/video/vp9_decoder_loader.cpp
- services/engine/codec/video/hcodec_loader.cpp
- services/engine/codec/video/video_codec_loader.h

## GitCode URL
https://gitcode.com/openharmony/multimedia_av_codec/tree/master/services/engine/codec/video

## 行号级 evidence

### E1
**文件**: `services/engine/codec/video/video_codec_loader.cpp`
**行号**: ~30-35
**内容**: VideoCodecLoader::Init() 实现
```cpp
int32_t VideoCodecLoader::Init()
{
  if (codecHandle_ != nullptr) {
    return AVCS_ERR_OK;
  }
  void *handle = dlopen(libPath_, RTLD_LAZY);
  CHECK_AND_RETURN_RET_LOG(handle != nullptr, AVCS_ERR_UNKNOWN, "Load codec failed: %{public}s", libPath_);
  auto handleSP = std::shared_ptr<void>(handle, dlclose);
  auto createFunc = reinterpret_cast<CreateByNameFuncType>(dlsym(handle, createFuncName_));
  CHECK_AND_RETURN_RET_LOG(createFunc != nullptr, AVCS_ERR_UNKNOWN, "Load createFunc failed: %{public}s", createFuncName_);
  auto getCapsFunc = reinterpret_cast<GetCapabilityFuncType>(dlsym(handle, getCapsFuncName_));
  CHECK_AND_RETURN_RET_LOG(getCapsFunc != nullptr, AVCS_ERR_UNKNOWN, "Load getCapsFunc failed: %{public}s", getCapsFuncName_);
  codecHandle_ = handleSP;
  createFunc_ = createFunc;
  getCapsFunc_ = getCapsFunc;
  AVCODEC_LOGI("Init library:%{public}s", libPath_);
  return AVCS_ERR_OK;
}
```
**说明**: VideoCodecLoader 基类 Init() 使用 dlopen/RTLD_LAZY 延迟加载动态库，dlsym 解析 CreateByName 和 GetCapabilityList 双函数指针

### E2
**文件**: `services/engine/codec/video/video_codec_loader.cpp`
**行号**: ~50-58
**内容**: VideoCodecLoader::Create() 工厂方法
```cpp
std::shared_ptr<CodecBase> VideoCodecLoader::Create(const std::string &name)
{
  std::shared_ptr<CodecBase> codec;
  (void)createFunc_(name, codec);
  return codec;
}
```
**说明**: 通过 createFunc_ 函数指针调用动态库中的 CreateFCodecByName/CreateHevcDecoderByName 等工厂函数

### E3
**文件**: `services/engine/codec/video/video_codec_loader.cpp`
**行号**: ~60-65
**内容**: VideoCodecLoader::GetCaps() 能力查询
```cpp
int32_t VideoCodecLoader::GetCaps(std::vector<CapabilityData> &caps)
{
  return getCapsFunc_(caps);
}
```
**说明**: 通过 getCapsFunc_ 函数指针获取编解码能力列表

### E4
**文件**: `services/engine/codec/video/fcodec_loader.cpp`
**行号**: ~20-25
**内容**: FCodecLoader 常量定义
```cpp
const char *FCODEC_LIB_PATH = "libfcodec.z.so";
const char *FCODEC_CREATE_FUNC_NAME = "CreateFCodecByName";
const char *FCODEC_GETCAPS_FUNC_NAME = "GetFCodecCapabilityList";
```
**说明**: FCodec 使用 libfcodec.z.so 动态库，导出 CreateFCodecByName 和 GetFCodecCapabilityList 双函数

### E5
**文件**: `services/engine/codec/video/fcodec_loader.cpp`
**行号**: ~35-50
**内容**: FCodecLoader::CreateByName 实现
```cpp
std::shared_ptr<CodecBase> FCodecLoader::CreateByName(const std::string &name)
{
  FCodecLoader &loader = GetInstance();
  CodecBase *noDeleterPtr = nullptr;
  {
    std::lock_guard<std::mutex> lock(loader.mutex_);
    CHECK_AND_RETURN_RET_LOG(loader.Init() == AVCS_ERR_OK, nullptr, "Create codec by name failed: init error");
    noDeleterPtr = loader.Create(name).get();
    CHECK_AND_RETURN_RET_LOG(noDeleterPtr != nullptr, nullptr, "Create fcodec by name failed: no memory");
    ++(loader.fcodecCount_);
  }
  auto deleter = [&loader](CodecBase *ptr) {
    std::lock_guard<std::mutex> lock(loader.mutex_);
    FCodec *codec = reinterpret_cast<FCodec*>(ptr);
    codec->DecStrongRef(codec);
    --(loader.fcodecCount_);
    loader.CloseLibrary();
  };
  return std::shared_ptr<CodecBase>(noDeleterPtr, deleter);
}
```
**说明**: FCodecLoader::CreateByName 使用引用计数 fcodecCount_ 控制动态库生命周期，CloseLibrary 仅在计数归零时关闭句柄

### E6
**文件**: `services/engine/codec/video/hevc_decoder_loader.cpp`
**行号**: ~20-25
**内容**: HevcDecoderLoader 常量定义
```cpp
const char *HEVC_DECODER_LIB_PATH = "libhevc_decoder.z.so";
const char *HEVC_DECODER_CREATE_FUNC_NAME = "CreateHevcDecoderByName";
const char *HEVC_DECODER_GETCAPS_FUNC_NAME = "GetHevcDecoderCapabilityList";
```
**说明**: HEVC 解码器使用 libhevc_decoder.z.so，导出 CreateHevcDecoderByName 和 GetHevcDecoderCapabilityList 双函数

### E7
**文件**: `services/engine/codec/video/hevc_decoder_loader.cpp`
**行号**: ~40-55
**内容**: HevcDecoderLoader::CreateByName 实现
```cpp
std::shared_ptr<CodecBase> HevcDecoderLoader::CreateByName(const std::string &name)
{
  HevcDecoderLoader &loader = GetInstance();
  CodecBase *noDeleterPtr = nullptr;
  {
    std::lock_guard<std::mutex> lock(loader.mutex_);
    CHECK_AND_RETURN_RET_LOG(loader.Init() == AVCS_ERR_OK, nullptr, "Create codec by name failed: init error");
    noDeleterPtr = loader.Create(name).get();
    CHECK_AND_RETURN_RET_LOG(noDeleterPtr != nullptr, nullptr, "Create hevcdecoder by name failed");
    ++(loader.hevcDecoderCount_);
  }
  auto deleter = [&loader](CodecBase *ptr) {
    std::lock_guard<std::mutex> lock(loader.mutex_);
    HevcDecoder *codec = static_cast<HevcDecoder*>(ptr);
    codec->DecStrongRef(codec);
    --(loader.hevcDecoderCount_);
    loader.CloseLibrary();
  };
  return std::shared_ptr<CodecBase>(noDeleterPtr, deleter);
}
```
**说明**: HevcDecoderLoader 与 FCodecLoader 结构完全一致，使用 hevcDecoderCount_ 引用计数

### E8
**文件**: `services/engine/codec/video/avc_encoder_loader.cpp`
**行号**: ~20-25
**内容**: AvcEncoderLoader 常量定义
```cpp
const char *AVC_ENCODER_LIB_PATH = "libavc_encoder.z.so";
const char *AVC_ENCODER_CREATE_FUNC_NAME = "CreateAvcEncoderByName";
const char *AVC_ENCODER_GETCAPS_FUNC_NAME = "GetAvcEncoderCapabilityList";
```
**说明**: AVC 编码器使用 libavc_encoder.z.so，导出 CreateAvcEncoderByName 和 GetAvcEncoderCapabilityList 双函数

### E9
**文件**: `services/engine/codec/video/avc_encoder_loader.cpp`
**行号**: ~35-50
**内容**: AvcEncoderLoader::CreateByName 实现
```cpp
std::shared_ptr<CodecBase> AvcEncoderLoader::CreateByName(const std::string &name)
{
  AvcEncoderLoader &loader = GetInstance();
  std::lock_guard<std::mutex> lock(loader.mutex_);
  CHECK_AND_RETURN_RET_LOG(loader.Init() == AVCS_ERR_OK, nullptr, "Create codec by name failed: init error");
  std::shared_ptr<CodecBase> noDeletePtr = loader.Create(name);
  if (noDeletePtr == nullptr) {
    AVCODEC_LOGE("Loader create coder by name failed!");
    loader.CloseLibrary();
  }
  return noDeletePtr;
}
```
**说明**: AvcEncoderLoader::CreateByName 与 FCodecLoader 结构一致，不同之处是没有自定义 deleter，依赖 shared_ptr 默认删除行为

### E10
**文件**: `services/engine/codec/video/video_codec_loader.cpp`
**行号**: ~70-75
**内容**: VideoCodecLoader::Close() 实现
```cpp
void VideoCodecLoader::Close()
{
  codecHandle_ = nullptr;
  createFunc_ = nullptr;
  getCapsFunc_ = nullptr;
  AVCODEC_LOGI("Close library:%{public}s", libPath_);
}
```
**说明**: Close() 清空句柄和函数指针，但实际关闭由 shared_ptr<void> 析构时调用 dlclose

### E11
**文件**: `services/engine/codec/video/fcodec_loader.cpp`
**行号**: ~60-65
**内容**: FCodecLoader::CloseLibrary() 实现
```cpp
void FCodecLoader::CloseLibrary()
{
  if (fcodecCount_) {
    return;
  }
  Close();
}
```
**说明**: FCodecLoader 重写了 CloseLibrary()，仅在 fcodecCount_ 为 0 时才真正关闭动态库，实现延迟关闭

### E12
**文件**: `services/engine/codec/video/fcodec_loader.cpp`
**行号**: ~65-70
**内容**: FCodecLoader::GetInstance() 单例模式
```cpp
FCodecLoader &FCodecLoader::GetInstance()
{
  static FCodecLoader loader;
  return loader;
}
```
**说明**: 每个 Loader 都是单例模式（static 局部变量），保证全局只有一个 Loader 实例管理动态库

### E13
**文件**: `services/engine/codec/video/video_codec_loader.cpp`
**行号**: ~15-20
**内容**: VideoCodecLoader 构造函数初始化成员变量
```cpp
FCodecLoader::FCodecLoader() : VideoCodecLoader(FCODEC_LIB_PATH, FCODEC_CREATE_FUNC_NAME, FCODEC_GETCAPS_FUNC_NAME) {}
```
**说明**: FCodecLoader 调用基类 VideoCodecLoader 构造函数，传入 libPath_、createFuncName_、getCapsFuncName_ 三个参数

### E14
**文件**: `services/engine/codec/video/video_codec_loader.h`
**行号**: ~30-40
**内容**: VideoCodecLoader 基类定义（推测）
```cpp
class VideoCodecLoader {
protected:
    VideoCodecLoader(const std::string& libPath, const std::string& createFunc, const std::string& getCapsFunc);
    virtual ~VideoCodecLoader() = default;
    int32_t Init();
    void Close();
    std::shared_ptr<CodecBase> Create(const std::string& name);
    int32_t GetCaps(std::vector<CapabilityData>& caps);
    virtual void CloseLibrary(); // 子类可重写
private:
    std::shared_ptr<void> codecHandle_;
    CreateByNameFuncType createFunc_;
    GetCapabilityFuncType getCapsFunc_;
    std::string libPath_;
    std::string createFuncName_;
    std::string getCapsFuncName_;
    std::mutex mutex_;
};
```
**说明**: VideoCodecLoader 基类封装了 dlopen/dlsym/delay-close 通用逻辑，子类只需传入三个字符串常量

### E15
**文件**: `services/engine/codec/video/fcodec_loader.cpp`
**行号**: ~10-15
**内容**: FCodecLoader 命名空间和引用
```cpp
namespace OHOS {
namespace MediaAVCodec {
namespace {
using FCodec = Codec::FCodec;
constexpr OHOS::HiviewDFX::HiLogLabel LABEL = {LOG_CORE, LOG_DOMAIN_FRAMEWORK, "FCodecLoader"};
} // namespace
```
**说明**: FCodec 类型别名指向 Codec::FCodec，LABEL 用于日志分类(LOG_DOMAIN_FRAMEWORK)

### E16
**文件**: `services/engine/codec/video/hevc_decoder_loader.cpp`
**行号**: ~60-65
**内容**: HevcDecoderLoader::GetInstance() 单例模式
```cpp
HevcDecoderLoader &HevcDecoderLoader::GetInstance()
{
  static HevcDecoderLoader loader;
  return loader;
}
```
**说明**: 与 FCodecLoader 相同，每个 Loader 都是 static 单例

### E17
**文件**: `services/engine/codec/video/video_codec_loader.cpp`
**行号**: ~55-58
**内容**: VideoCodecLoader::GetCapabilityList() 包装
```cpp
int32_t VideoCodecLoader::GetCapabilityList(std::vector<CapabilityData> &caps)
{
  return getCapsFunc_(caps);
}
```
**说明**: GetCapabilityList 调用 getCapsFunc_ 获取 CapabilityData 向量，用于 AVCodecList 能力查询

### E18
**文件**: `services/engine/codec/video/avc_encoder_loader.cpp`
**行号**: ~55-65
**内容**: AvcEncoderLoader::GetCapabilityList 实现
```cpp
int32_t AvcEncoderLoader::GetCapabilityList(std::vector<CapabilityData> &caps)
{
  FCodecLoader &loader = GetInstance();
  std::lock_guard<std::mutex> lock(loader.mutex_);
  CHECK_AND_RETURN_RET_LOG(loader.Init() == AVCS_ERR_OK, AVCS_ERR_UNKNOWN, "Get capability failed: init error");
  int32_t ret = loader.GetCaps(caps);
  if (ret != AVCS_ERR_OK) {
    AVCODEC_LOGE("Loader get caps failed!");
    loader.CloseLibrary();
  }
  return ret;
}
```
**说明**: GetCapabilityList 调用基类 GetCaps，失败时主动关闭库

## 架构总结

### 核心模式：动态库延迟加载 + 双函数指针注入

1. **dlopen + RTLD_LAZY**: 延迟加载动态库，避免启动时全部加载
2. **dlsym 解析双函数**: createFunc_(name, codec) 创建实例 + getCapsFunc_(caps) 查询能力
3. **引用计数延迟关闭**: FCodecLoader/HevcDecoderLoader 使用计数器，仅在计数归零时 dlclose
4. **单例模式**: 每个 Loader 是 static 单例，全局共享一份动态库句柄

### 七类Loader工厂

| Loader | 动态库 | 创建函数 | 能力函数 |
|--------|--------|---------|---------|
| FCodecLoader | libfcodec.z.so | CreateFCodecByName | GetFCodecCapabilityList |
| HevcDecoderLoader | libhevc_decoder.z.so | CreateHevcDecoderByName | GetHevcDecoderCapabilityList |
| AvcEncoderLoader | libavc_encoder.z.so | CreateAvcEncoderByName | GetAvcEncoderCapabilityList |
| Av1DecoderLoader | libav1_decoder.z.so | CreateAv1DecoderByName | GetAv1DecoderCapabilityList |
| Vp8DecoderLoader | libvpx.z.so | CreateVp8DecoderByName | GetVp8DecoderCapabilityList |
| Vp9DecoderLoader | libvpx.z.so | CreateVp9DecoderByName | GetVp9DecoderCapabilityList |
| HcodecLoader | libhcodec.z.so | CreateHcodecByName | GetHcodecCapabilityList |

### 继承层次

```
VideoCodecLoader (基类，dlopen/dlsym通用逻辑)
  ├── FCodecLoader (fcodecCount_ 引用计数)
  ├── HevcDecoderLoader (hevcDecoderCount_ 引用计数)
  ├── AvcEncoderLoader (无引用计数)
  ├── Av1DecoderLoader
  ├── Vp8DecoderLoader
  ├── Vp9DecoderLoader
  └── HcodecLoader
```

### 与 S178 的关系

S178 描述了 services/engine/codec/ 下的视频/音频引擎层目录结构，VideoCodecLoader 位于 video/ 子目录，是视频编解码器动态加载的核心基座。七类 Loader（FCodec/HEVC/AVC/AV1/VP8/VP9/HCodec）均通过 VideoCodecLoader 基类实现 dlopen 延迟加载。