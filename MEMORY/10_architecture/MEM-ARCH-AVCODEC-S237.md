# MEM-ARCH-AVCODEC-S237: AVCodec Native CENC Info API

**状态**: draft → enhanced (E27-E30 added)  
**Builder**: builder-agent (subagent) @2026-06-09T05:53+08:00 → **builder-agent 增强版** @2026-06-09T06:25+08:00 → **builder-agent E27-E30** @2026-06-09T06:40+08:00  
**源码基于**: 本地镜像 `/home/west/av_codec_repo`

---

## 主题概述

AVCodec Native CENC Info API（OH_AVCencInfo）是 AVCodec C API 体系中**独立于 CodecServer 的客户端 DRM CENC 信息 API**，用于在 AVBuffer 上附加 DRM Common Encryption 元数据，使 DRM 解密模块能够对加密媒体流进行解密。

**定位对比**：
- S63/S225 `CodecDrmDecrypt`：CodecServer 端 DRM 解密引擎（服务端）
- S237 `OH_AVCencInfo`：Native C API 端 CENC 信息附着 API（客户端）

**关联场景**：DRM 加密媒体播放 / 三方应用 DRM接入 / 新人入项

**关联 S 系列**：
- S63（S225增强版）：`CodecDrmDecrypt` DRM CENC 解密核心（服务端解密引擎）
- S225：`CodecDrmDecrypt` 本地镜像增强版
- S162/S83：CodecAbility/CodecList 能力查询体系
- S94：`OH_AVDemuxer` C API 三件套（Demuxer 读取加密流）

---

## 一、API 架构总览

### 1.1 库与 SysCap

| 属性 | 值 |
|------|------|
| 动态库 | `libnative_media_avcencinfo.so` |
| 头文件 | `interfaces/kits/c/native_cencinfo.h` (248 行) |
| 实现文件 | `frameworks/native/capi/avcencinfo/native_cencinfo.cpp` (193 行) |
| SysCap | `SystemCapability.Multimedia.Media.Spliter` |
| 最低版本 | API 12 |

### 1.2 数据结构

```c
// native_cencinfo.h
typedef struct OH_AVBuffer OH_AVBuffer;     // 前向声明：AVBuffer
typedef struct OH_AVCencInfo OH_AVCencInfo; // CENC 信息对象

typedef struct DrmSubsample {
    uint32_t clearHeaderLen;  // 明文块长度（字节）
    uint32_t payLoadLen;      // 密文块长度（字节）
} DrmSubsample;

typedef enum DrmCencAlgorithm {
    DRM_ALG_CENC_UNENCRYPTED = 0x0,  // 不加密
    DRM_ALG_CENC_AES_CTR = 0x1,  // AES-CTR 模式（标准 CENC）
    DRM_ALG_CENC_AES_WV       = 0x2,  // AES-WV 模式（Widevine）
    DRM_ALG_CENC_AES_CBC      = 0x3,  // AES-CBC 模式
    DRM_ALG_CENC_SM4_CBC      = 0x4,  // 国密 SM4-CBC 模式
    DRM_ALG_CENC_SM4_CTR      = 0x5,  // 国密 SM4-CTR 模式
} DrmCencAlgorithm;

typedef enum DrmCencInfoMode {
    DRM_CENC_INFO_KEY_IV_SUBSAMPLES_SET       = 0x0, // key/iv/subsample 已设置
    DRM_CENC_INFO_KEY_IV_SUBSAMPLES_NOT_SET    = 0x1, // key/iv/subsample 未设置
} DrmCencInfoMode;
```

**关键常量**：
- `DRM_KEY_ID_SIZE = 16` — Key ID 固定16 字节
- `DRM_KEY_IV_SIZE = 16` — IV（Initialisation Vector）固定 16 字节
- `DRM_KEY_MAX_SUB_SAMPLE_NUM = 64` — 最大 subsample 数量

---

## 二、OH_AVCencInfo 对象模型

### 2.1 内部结构（opaque struct）

```cpp
// native_cencinfo.cpp L34-56
struct OH_AVCencInfo {
    explicit OH_AVCencInfo() {
        cencInfo_.algo = META_DRM_ALG_CENC_UNENCRYPTED;
        for (int32_t i = 0; i < META_DRM_KEY_ID_SIZE; i++) {
            cencInfo_.keyId[i] = 0;
        }
        cencInfo_.keyIdLen = 0;
        for (int32_t i = 0; i < META_DRM_IV_SIZE; i++) {
            cencInfo_.iv[i] = 0;
        }
        cencInfo_.ivLen = 0;
        cencInfo_.encryptBlocks = 0;
        cencInfo_.skipBlocks = 0;
        cencInfo_.firstEncryptOffset = 0;
        cencInfo_.subSamples[0].clearHeaderLen = 0;
        cencInfo_.subSamples[0].payLoadLen = 0;
        cencInfo_.subSampleNum = 1;
        cencInfo_.mode = META_DRM_CENC_INFO_KEY_IV_SUBSAMPLES_SET;
    }
    ~OH_AVCencInfo() = default;
    MetaDrmCencInfo cencInfo_;  // 内部元数据结构体
};
```

**内部 `MetaDrmCencInfo` 字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `algo` | `MetaDrmCencAlgorithm` | 加密算法 |
| `keyId[16]` | `uint8_t[16]` | 16字节 Key ID |
| `keyIdLen` | `uint32_t` | Key ID 长度（=16） |
| `iv[16]` | `uint8_t[16]` | 16字节 IV |
| `ivLen` | `uint32_t` | IV 长度（=16） |
| `encryptBlocks` | `uint32_t` | 加密块数量 |
| `skipBlocks` | `uint32_t` | 跳过（明文）块数量 |
| `firstEncryptOffset` | `uint32_t` | 首个加密块偏移 |
| `subSamples[64]` | `DrmSubsample[64]` | 子样本数组（上限64个） |
| `subSampleNum` | `uint32_t` | 实际 subsample 数量 |
| `mode` | `MetaDrmCencInfoMode` |模式标志 |

**MetaDrmCencInfo 总大小**：`sizeof(MetaDrmCencInfo)`，通过 `reinterpret_cast` + `vector<uint8_t>` 序列化后经 `Tag::DRM_CENC_INFO` 存入 AVBuffer（E27/E28/E30）

---

## 三、七函数 API 详解

### 3.1 OH_AVCencInfo_Create

```c
// native_cencinfo.h L133
OH_AVCencInfo *OH_AVCencInfo_Create();
```

**说明**：在堆上分配并构造 `OH_AVCencInfo` 对象，初始值全部为 0 或默认值。

**Evidence**：
- E1: `native_cencinfo.cpp L62-67` — `new (std::nothrow) OH_AVCencInfo()`，失败返回 nullptr
- E2: `native_cencinfo.cpp L68-75` — `memset_s` 零初始化 MetaDrmCencInfo 结构体

**返回**：成功返回 `OH_AVCencInfo*`，失败返回 `nullptr`（地址空间满或初始化失败）

### 3.2 OH_AVCencInfo_Destroy

```c
// native_cencinfo.h L149
OH_AVErrCode OH_AVCencInfo_Destroy(OH_AVCencInfo *cencInfo);
```

**说明**：销毁 OH_AVCencInfo 实例并释放内部资源。

**Evidence**：
- E3: `native_cencinfo.cpp L77-79` — `delete cencInfo`，返回 `AV_ERR_OK`

**错误码**：`AV_ERR_INVALID_VAL`（cencInfo 为 nullptr）

### 3.3 OH_AVCencInfo_SetAlgorithm

```c
// native_cencinfo.h L163
OH_AVErrCode OH_AVCencInfo_SetAlgorithm(OH_AVCencInfo *cencInfo, enum DrmCencAlgorithm algo);
```

**说明**：设置 CENC 加密算法，将 `DrmCencAlgorithm` 枚举映射为 `MetaDrmCencAlgorithm`。

**Evidence**：
- E4: `native_cencinfo.cpp L82-100` — switch-case 6路分发（UNENCRYPTED/AES-CTR/AES-WV/AES-CBC/SM4-CBC/SM4-CTR）

**错误码**：`AV_ERR_INVALID_VAL`（cencInfo 为 nullptr）

### 3.4 OH_AVCencInfo_SetKeyIdAndIv

```c
// native_cencinfo.h L186
OH_AVErrCode OH_AVCencInfo_SetKeyIdAndIv(OH_AVCencInfo *cencInfo,
    uint8_t *keyId, uint32_t keyIdLen,
    uint8_t *iv, uint32_t ivLen);
```

**说明**：设置 16 字节 Key ID 和 16 字节 IV（Initialisation Vector），使用 `memcpy_s` 安全拷贝。

**Evidence**：
- E5: `native_cencinfo.cpp L103-107` — 参数校验（keyIdLen==16, ivLen==16）
- E6: `native_cencinfo.cpp L118-123` — KeyId 拷贝（`keyIdLen` + `memcpy_s` 到 `cencInfo_.keyId`）
- E7: `native_cencinfo.cpp L124-130` — IV 拷贝（`ivLen` + `memcpy_s` 到 `cencInfo_.iv`）

**错误码**：`AV_ERR_INVALID_VAL`（任一参数无效或拷贝失败）

### 3.5 OH_AVCencInfo_SetSubsampleInfo

```c
// native_cencinfo.h L203
OH_AVErrCode OH_AVCencInfo_SetSubsampleInfo(OH_AVCencInfo *cencInfo,
    uint32_t encryptedBlockCount, uint32_t skippedBlockCount,
    uint32_t firstEncryptedOffset, uint32_t subsampleCount, DrmSubsample *subsamples);
```

**说明**：设置基于 subsample 的解密参数。一个 CENC subsample 描述一段明文+密文模式：
- `clearHeaderLen`：当前明文块长度
- `payLoadLen`：当前密文块长度

**Evidence**：
- E8: `native_cencinfo.cpp L133-142` — encryptedBlockCount→encryptBlocks, skippedBlockCount→skipBlocks, firstEncryptedOffset→firstEncryptOffset, subsampleCount→subSampleNum
- E9: `native_cencinfo.cpp L149-152` — 循环拷贝每个 subsample 的 clearHeaderLen 和 payLoadLen
- E30: `native_cencinfo.cpp L137` — `CHECK_AND_RETURN_RET_LOG(subsampleCount <= DRM_KEY_MAX_SUB_SAMPLE_NUM, ...)` 强制上限64，超限返回 `AV_ERR_INVALID_VAL`

**错误码**：`AV_ERR_INVALID_VAL`（cencInfo 为 nullptr 或 subsampleCount > 64 或 subsamples 为 nullptr）

### 3.6 OH_AVCencInfo_SetMode

```c
// native_cencinfo.h L224
OH_AVErrCode OH_AVCencInfo_SetMode(OH_AVCencInfo *cencInfo, enum DrmCencInfoMode mode);
```

**说明**：设置 CENC info 模式，标志 key/iv/subsample 是否已设置。

**Evidence**：
- E10: `native_cencinfo.cpp L155-168` — switch-case 两路分发（SET/NOT_SET）

**错误码**：`AV_ERR_INVALID_VAL`（cencInfo 为 nullptr）

### 3.7 OH_AVCencInfo_SetAVBuffer

```c
// native_cencinfo.h L239
OH_AVErrCode OH_AVCencInfo_SetAVBuffer(OH_AVCencInfo *cencInfo, OH_AVBuffer *buffer);
```

**说明**：将 CENC info 附加到 `OH_AVBuffer` 的 metadata 中。这是**关键的桥接函数**，通过 `Tag::DRM_CENC_INFO` 将 CENC 元数据序列化后存入 AVBuffer，供下游 CodecServer `CodecDrmDecrypt` 读取解密。

**Evidence**：
- E11: `native_cencinfo.cpp L179-182` — 参数三元校验（buffer && buffer->buffer_ && buffer->buffer_->meta_）
- E12: `native_cencinfo.cpp L185-186` — `reinterpret_cast` 将 `MetaDrmCencInfo` 转换为 `std::vector<uint8_t>`，范围为 `[reinterpret_cast<uint8_t*>(&cencInfo_)`, `+ sizeof(MetaDrmCencInfo))`
- E13: `native_cencinfo.cpp L188` — `buffer->buffer_->meta_->SetData(Tag::DRM_CENC_INFO, std::move(cencInfoVec))`，将 CENC 元数据注入 AVBuffer metadata

**错误码**：`AV_ERR_INVALID_VAL`（任一参数为 nullptr 或内部成员为 nullptr）

---

## 四、数据流：Demuxer → AVBuffer → CodecDrmDecrypt

```
┌─────────────────────────────────────────────────────────────────────┐
│  FFmpegDemuxerPlugin (ffmpeg_demuxer_plugin.cpp L659-714)            │
│  1. av_packet_get_side_data(AV_PKT_DATA_ENCRYPTION_INFO)            │
│     → 获取 MP4/ISOBMFF 容器中的 DRM 元数据                           │
│  2. 构造 std::vector<uint8_t> drmCencVec 从 MetaDrmCencInfo         │
│  3. sample->meta_->SetData(Tag::DRM_CENC_INFO, std::move(drmCencVec))│
│     → 写入 AVBuffer metadata │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  OH_AVCencInfo (libnative_media_avcencinfo.so)                       │
│  第三方应用：OH_AVCencInfo_Create → SetAlgorithm → SetKeyIdAndIv    │
│  → SetSubsampleInfo → SetMode → SetAVBuffer │
│  → 将自定义 DRM 元数据附加到 AVBuffer                                │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  CodecServer CodecDrmDecrypt (codec_drm_decrypt.cpp L551/L597)        │
│  1. DrmVideoCencDecrypt / DrmAudioCencDecrypt                        │
│  2. Tag::DRM_CENC_INFO 读取 → MetaDrmCencInfo 解包 │
│  3. DecryptMediaData → DRM 解密模块 proxy │
│  4. 输出解密后 AVBuffer                                              │
└─────────────────────────────────────────────────────────────────────┘
```

**DRM 算法支持（三路）**：
- **AES-CTR / SM4-CTR**：用于标准 CENC（AES-CTR 最常见）
- **AES-CBC / SM4-CBC**：用于某些变种 DRM（如 ChinaDRM）
- **AES-WV**：Widevine DRM专用

---

## 五、与 S63/S225 CodecDrmDecrypt 的关系

|维度 | S237 OH_AVCencInfo | S63/S225 CodecDrmDecrypt |
|------|-------------------|--------------------------|
| 层次 | Native C API（客户端） | CodecServer（服务端） |
| 功能 | 构造并附着 CENC 元数据到 AVBuffer | 读取 AVBuffer 中的 CENC 元数据并解密 |
| 库 | `libnative_media_avcencinfo.so` | `libcodec_drm_decrypt.z.so` |
| 调用方 | 第三方应用 / FFmpegDemuxerPlugin | CodecServer 内部 |
| 入口函数 | 7个 C 函数 | `DrmVideoCencDecrypt` / `DrmAudioCencDecrypt` |
| 目标 | `OH_AVBuffer->meta_->SetData` | `IMediaDecryptModuleService::DecryptMediaData` |

---

## 六、单元测试

测试文件：`test/unittest/avcenc_info_test/cenc_info_capi_unit_test.cpp` (~476 行)

| 测试用例 | 描述 |
|---------|------|
| `CencInfo_Create_001` | 创建 CENC info 对象 |
| `CencInfo_Destroy_001` | 销毁 CENC info 对象 |
| `CencInfo_Destroy_002` | 销毁空指针（返回错误） |
| `CencInfo_SetAlgorithm_001` | 设置全部 6 种算法 |
| `CencInfo_SetAlgorithm_002` | 空指针参数校验 |
| `CencInfo_SetKeyIdAndIv_001` | 设置 Key ID 和 IV |
| `CencInfo_SetKeyIdAndIv_002` | 空指针参数校验 |
| `CencInfo_SetKeyIdAndIv_003` | keyId=nullptr 校验 |
| `CencInfo_SetKeyIdAndIv_004` | keyIdLen != 16 校验 |
| `CencInfo_SetAVBuffer_001` | 完整流程：创建→设参数→附着到 AVBuffer |
| `CencInfo_SetAVBuffer_002` | cencInfo=nullptr 参数校验 |
| `CencInfo_SetAVBuffer_003` | buffer=nullptr 参数校验 |

模糊测试：`test/fuzztest/avcencinfo_fuzzer/avcencinfo_fuzzer.cpp` (~390 行)

---

## 七、关键 Evidence 汇总（E1-E30）

| ID | 文件 | 行号 | 内容 |
|----|------|------|------|
| E1 | native_cencinfo.cpp | 62-67 | OH_AVCencInfo_Create: new + nothrow |
| E2 | native_cencinfo.cpp | 68-75 | memset_s 零初始化 MetaDrmCencInfo |
| E3 | native_cencinfo.cpp | 77-79 | OH_AVCencInfo_Destroy: delete |
| E4 | native_cencinfo.cpp | 82-100 | SetAlgorithm:6路 switch-case 算法映射 |
| E5 | native_cencinfo.cpp | 103-107 | SetKeyIdAndIv: 参数校验（keyIdLen==16, ivLen==16） |
| E6 | native_cencinfo.cpp | 118-123 | KeyId memcpy_s 安全拷贝 |
| E7 | native_cencinfo.cpp | 124-130 | IV memcpy_s 安全拷贝 |
| E8 | native_cencinfo.cpp | 133-142 | SetSubsampleInfo: 4参数赋值 |
| E9 | native_cencinfo.cpp | 149-152 | subsample 数组循环拷贝 |
| E10 | native_cencinfo.cpp | 155-168 | SetMode: 两路 switch-case |
| E11 | native_cencinfo.cpp | 179-182 | SetAVBuffer: buffer 三元校验 |
| E12 | native_cencinfo.cpp | 185-186 | reinterpret_cast MetaDrmCencInfo→vector<uint8_t> |
| E13 | native_cencinfo.cpp | 188 | SetData(Tag::DRM_CENC_INFO) 注入 AVBuffer |
| E14 | native_cencinfo.h | 54 | DRM_KEY_ID_SIZE = 16 常量定义 |
| E15 | native_cencinfo.h | 56 | DRM_KEY_IV_SIZE = 16 常量定义 |
| E16 | native_cencinfo.h | 50 | DRM_KEY_MAX_SUB_SAMPLE_NUM = 64 常量定义 |
| E17 | native_cencinfo.h | 87-98 | DrmCencAlgorithm 6枚举值 |
| E18 | native_cencinfo.h | 106-111 | DrmCencInfoMode 2枚举值 |
| E19 | native_cencinfo.h | 114-118 | DrmSubsample 结构体（clearHeaderLen/payLoadLen） |
| E20 | ffmpeg_demuxer_plugin.cpp | 662-663 | av_packet_get_side_data(AV_PKT_DATA_ENCRYPTION_INFO) 提取 DRM 元数据 |
| E21 | codec_drm_decrypt.cpp | 42-43 | DRM_CRYPT_BYTE_BLOCK=1 / DRM_SKIP_BYTE_BLOCK=9 常量（解密块边界） |
| E22 | codec_drm_decrypt.cpp | 52 | DRM_TS_SUB_SAMPLE_NUM=2 常量（Transport Stream subsample数） |
| E23 | codec_drm_decrypt.cpp | 562 | `GetData(Media::Tag::DRM_CENC_INFO, drmCencVec)` 消费端读取 AVBuffer metadata |
| E24 | codec_drm_decrypt.cpp | 566-568 | encryptBlocks<=DRM_CRYPT_BYTE_BLOCK校验 + algo==UNENCRYPTED明文直通分支 |
| E25 | codec_drm_decrypt.cpp | 582-587 | mode==NOT_SET时走DrmGetCencInfo/DrmModifyCencInfo路径 + DRM_TS_SUB_SAMPLE_NUM=2 |
| E26 | codec_drm_decrypt.cpp | 615-622 | AES-CTR/SM4-CTR(流式解密) vs AES-CBC/SM4-CBC(块解密) 算法分发 |
| E27 | codec_drm_decrypt.cpp | 606 | `GetData(Media::Tag::DRM_CENC_INFO, drmCencVec)` 音频解密消费端读取 DRM 元数据 |
| E28 | codec_drm_decrypt.cpp | 631 | `sizeof(MetaDrmCencInfo)` memset 音频消费端零初始化 MetaDrmCencInfo |
| E29 | codec_drm_decrypt.cpp | 609-623 | subSampleNum==0 时自动推导：CTR→{subSampleNum=1,payLoadLen=dataSize}，CBC→{subSampleNum=2,分块16字节对齐+余数明文} |
| E30 | native_cencinfo.cpp | 187 | `sizeof(MetaDrmCencInfo)` 用于 vector<uint8_t> 序列化总大小（reinterpret_cast 范围计算） |

---

## 八、文件索引

| 角色 | 路径 | 行数 |
|------|------|------|
| C API 头文件 | `interfaces/kits/c/native_cencinfo.h` | 248 |
| C API 实现 | `frameworks/native/capi/avcencinfo/native_cencinfo.cpp` | 193 |
| CodecServer DRM 解密器 | `services/drm_decryptor/codec_drm_decrypt.cpp` | 764 |
| FFmpegDemuxer DRM 集成 | `services/media_engine/plugins/demuxer/ffmpeg_demuxer/ffmpeg_demuxer_plugin.cpp` | ~4129 |
| 单元测试 | `test/unittest/avcenc_info_test/cenc_info_capi_unit_test.cpp` | ~476 |
| 模糊测试 | `test/fuzztest/avcencinfo_fuzzer/avcencinfo_fuzzer.cpp` | ~390 |

---

**变更记录**：
- 2026-06-09T05:53+08:00：S237 注册草案生成（基于本地镜像 `/home/west/av_codec_repo`），20条行号级 evidence，与 S63/S225 CodecDrmDecrypt 区分
- 2026-06-09T06:25+08:00：S237 增强——E21-E26 新增（codec_drm_decrypt.cpp 消费端证据：DRM块常量/DRM_CENC_INFO读取/UNENCRYPTED明文直通/NOT_SET路径/CTR-CBC算法分发），从20条增强至26条行号级 evidence
- 2026-06-09T06:40+08:00：S237 E27-E30 新增——音频解密消费端 GetData/sizeof/自动推导 subsampleNum（E27-E29），sizeof(MetaDrmCencInfo)序列化大小（E30），共30条行号级 evidence