# MEM-ARCH-AVCODEC-S183

status: draft

## 标题

AVC H.264 软件编码器体系——AvcEncoder + AvcEncoderLoader + AvcEncoderConvert + AvcEncoderUtil 四组件2747行

## 标签

AVCodec, VideoEncoder, H264, AVC, SoftwareCodec, libavcenc, ColorSpace, RateControl, AvcEncoder, AvcEncoderLoader

## 证据列表（行号级）

E1: avc_encoder.cpp:83-86 四常量（AVC_ENC_LIB_PATH/SO_EXTENSION/create/encode/delete函数名）
E2: avc_encoder.cpp:158-166 dlopen RTLD_LAZY 加载 libavcenc_ohos.z.so + 错误处理
E3: avc_encoder.cpp:84-86 三函数指针 InitEncoder/EncodeProcess/ReleaseEncoder
E4: avc_encoder.h:56-62 FBuffer::Owner 枚举四态（OWNED_BY_USER/CODEC/US/SURFACE）
E5: avc_encoder.cpp:817-818 BlockQueue inputAvailQue/codecAvailQue 双队列
E6: avc_encoder.cpp:395-396 TaskThread sendTask_(SendFrame) + RegisterHandler
E7: avc_encoder.cpp:133 state_(State::UNINITIALIZED) 九状态机起点
E8: avc_encoder.cpp:918 state_ = State::RUNNING
E9: avc_encoder.cpp:699 SignalRequestIDRFrame()
E10: avc_encoder.cpp:1189 NotifyEos()
E11: avc_encoder.cpp:1601 SendFrame() TaskThread驱动主循环
E12: avc_encoder_convert.cpp:38-48 BT601_MATRIX/BT709_MATRIX [2][3][3] int16_t 色域矩阵
E13: avc_encoder_convert.cpp:68-83 ConvertRGB2YUV420 色彩空间转换主函数
E14: avc_encoder_util.cpp:235 工具函数集合（行数验证）
E15: avc_encoder_loader.cpp:36-37 AVC_ENCODER_LIB_PATH="libavc_encoder.z.so" 外壳库
E16: avc_encoder_loader.cpp:25-30 CreateByName 工厂方法 + mutex_/Init()/Create()
E17: avc_encoder_loader.cpp:39-51 GetCapabilityList → loader.GetCaps()
E18: avc_encoder_api.cpp:36 API 导出函数（行数验证）
E19: avc_encoder.cpp:864 FillAvcInitParams 填充 AVC_ENC_INIT_PARAM
E20: avc_encoder.cpp:397 sendTask_->RegisterHandler([this] { SendFrame(); }) TaskThread注册

## 源码分析

### 1. 整体架构

S183 覆盖 AVC H.264 软件编码器四组件，总计 2747 行源码，位于 `services/engine/codec/video/avcencoder/` 目录：

| 文件 | 行数 | 职责 |
|------|------|------|
| avc_encoder.cpp | 1765 | 核心编码器 AvcEncoder 类 |
| avc_encoder.h | 270 | 类定义与内嵌 FBuffer 类 |
| avc_encoder_convert.cpp | 369 | RGB→YUV420 色彩空间转换 |
| avc_encoder_util.cpp | 235 | 工具函数 |
| avc_encoder_api.cpp | 36 | API 导出封装 |
| avc_encoder_loader.cpp | 72 | 工厂加载器 |

注意：与 S59（AvcEncoder 硬件编码器，libavcenc_ohos.z.so）不同，S183 分析的是**软件编码器** AvcEncoder，使用的是 libavc_encoder.z.so 外壳库，其内部最终调用 libavcenc_ohos.z.so 内核。两者的 Loader 路径不同：硬件用 HCodecLoader，软件用 AvcEncoderLoader。

### 2. AvcEncoder 核心类

`AvcEncoder` 继承 `CodecBase` 和 `RefBase`，通过 dlopen RTLD_LAZY 动态加载底层编码库。

**dlopen 加载链路**（avc_encoder.cpp:158-166）：

```cpp
const char *AVC_ENC_LIB_PATH = "libavcenc_ohos.z.so"; // 实际内核库
handle_ = dlopen(AVC_ENC_LIB_PATH, RTLD_LAZY);
```

三函数指针通过 dlsym 获取：
- `InitEncoder`（avc_encoder.cpp:84）
- `EncodeProcess`（avc_encoder.cpp:85）
- `ReleaseEncoder`（avc_encoder.cpp:86）

**FBuffer 缓冲区四态所有权**（avc_encoder.h:56-62）：

```cpp
enum class Owner { OWNED_BY_USER, OWNED_BY_CODEC, OWNED_BY_US, OWNED_BY_SURFACE };
```

inputBuffer.owner_ 三次状态迁移（avc_encoder.cpp:303/712/1159）：
- `OWNED_BY_USER` → `OWNED_BY_CODEC`（QueueInputBuffer）
- `OWNED_BY_CODEC` → `OWNED_BY_USER`（SendFrame 归还）

### 3. 九状态机

CodecBase 定义的 State 九状态（avc_encoder.cpp:133 起点）：UNINITIALIZED → INITIALIZED → CONFIGURED → RUNNING → STOPPING → FLUSHING → FLUSHED → EOS → ERROR。

关键转换：
- `Configure()` 成功：INITIALIZED → CONFIGURED（avc_encoder.cpp:461）
- `Start()` 成功：CONFIGURED → RUNNING（avc_encoder.cpp:918）
- `Flush()` 开始：RUNNING → FLUSHING（avc_encoder.cpp:976）
- `Flush()` 完成：FLUSHING → FLUSHED（avc_encoder.cpp:987）

### 4. TaskThread 双驱动

SendFrame TaskThread（avc_encoder.cpp:395-396）：

```cpp
sendTask_ = std::make_shared<TaskThread>("SendFrame");
sendTask_->RegisterHandler([this] { SendFrame(); });
```

SendFrame 循环（avc_encoder.cpp:1601）从 inputAvailQue 取 Buffer，经过色彩空间转换后调用 EncodeProcess。TaskThread 五态机（STOPPED/STARTED/PAUSING/PAUSED/STOPPING）+ 500ms 自醒机制。

### 5. 色彩空间转换

avc_encoder_convert.cpp 实现 BT601/BT709 两种转换矩阵（avc_encoder_convert.cpp:38-48）：

```cpp
static const int16_t BT601_MATRIX[2][3][3];
static const int16_t BT709_MATRIX[2][3][3];
```

COLOR_RANGE 分为 RANGE_FULL/RANGE_LIMITED 两种模式，通过 colorRange - 1 索引选择矩阵行。ConvertRGB2YUV420（avc_encoder_convert.cpp:68-83）是主转换函数，zeroLvl（16 for limited / 0 for full）和 maxLvlLuma/Chroma 共同决定输出值域。

### 6. AvcEncoderLoader 工厂

AvcEncoderLoader 继承 VideoCodecLoader（avc_encoder_loader.cpp:72），加载 libavc_encoder.z.so 外壳库：

```cpp
const char *AVC_ENCODER_LIB_PATH = "libavc_encoder.z.so";
const char *AVC_ENCODER_CREATE_FUNC_NAME = "CreateAvcEncoderByName";
const char *AVC_ENCODER_GETCAPS_FUNC_NAME = "GetAvcEncoderCapabilityList";
```

CreateByName（avc_encoder_loader.cpp:25-30）经过 mutex_ → Init() → Create() 三步，失败时 CloseLibrary() 卸载。GetCapabilityList（avc_encoder_loader.cpp:39-51）委托 loader.GetCaps(caps) 填充能力数组。

### 7. 关键 API

- SignalRequestIDRFrame（avc_encoder.cpp:699）：请求输出 IDR 帧
- NotifyEos（avc_encoder.cpp:1189）：通知编码器 EOS
- FillAvcInitParams（avc_encoder.cpp:864）：填充 AVC_ENC_INIT_PARAM 结构体

## 关联主题

S59（AvcEncoder 硬件编码器，libavcenc_ohos.z.so）、S70（CodecFactory 工厂与 Loader 插件体系）、S54（HevcDecoder + VpxDecoder）、S50（AudioResample 音频重采样）、S57（HDecoder/HEncoder 硬件编码器）