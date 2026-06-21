---
status: draft
mem_id: MEM-ARCH-AVCODEC-S246
title: "HttpSourcePlugin 离线缓存与流媒体工具链——MediaCachedBuffer LRU分片缓存 + AesDecryptor AES-128解密 + XmlParser + HttpMediaUtils DFX 四组件"
scope: "AVCodec, MediaEngine, SourcePlugin, HttpSourcePlugin, MediaCachedBuffer, AesDecryptor, XmlParser, HttpMediaUtils, LRU, AES-128, CBC, DRM, DASH, HLS, OfflineCache, Download"
scenario: "DASH/HLS流播放/离线缓存/AES-128解密/DFX可观测性"
assoc_s: "S138, S222, S234, S195, S225"
evidence_count: 12
source: "GitCode web_fetch + 本地镜像 /home/west/av_codec_repo/services/media_engine/plugins/source/http_source/"
builder_timestamp: "2026-06-21"
---

# MEM-ARCH-AVCODEC-S246: HttpSourcePlugin 离线缓存与流媒体工具链——MediaCachedBuffer LRU分片缓存 + AesDecryptor AES-128解密 + XmlParser + HttpMediaUtils DFX 四组件

## 概述

本文档记录 OpenHarmony 多媒体 AVCodec HttpSourcePlugin 子系统的四个关键工具组件：

1. **MediaCachedBuffer** (`media_cached_buffer.cpp/h`) — LRU 分片缓存，支持离线播放的 Seek 操作
2. **AesDecryptor** (`aes_decryptor.cpp/h`) — AES-128-CBC 软件解密器，用于解密 AES-128 加密的 HLS/DASH 媒体分片
3. **XmlParser** (`xml_parser.cpp/h`) — 基于 libxml2 的 MPD XML 解析器（复用自 DASH MPD 解析，S138 基础上补充工具层视角）
4. **HttpMediaUtils** (`http_media_utils.cpp/h`) — Bundle 名称查询工具，为流媒体 DFX 打点提供调用方身份

这些组件共同支撑流媒体的离线缓存、内容解密、配置解析和指标上报能力。

---

## E1. MediaCachedBuffer — LRU 分片缓存架构

**文件**: `services/media_engine/plugins/source/http_source/utils/media_cached_buffer.cpp` + `.h`

**核心类型**: `CacheMediaChunkBufferImpl`

**架构设计**: 两层缓存结构
- 外层：`FragmentCacheBuffer` 分片列表（`std::list`），每个分片含多个 `CacheChunk`
- 内层：`LruCache<...>` LRU 淘汰策略，限制最大分片数
- Chunk 大小：`CHUNK_SIZE = 16KB` (`media_cached_buffer.cpp` L29)
- 最大分片数：`CACHE_FRAGMENT_MAX_NUM_DEFAULT = 300`（普通偏移）或 `CACHE_FRAGMENT_MAX_NUM_LARGE = 10`（大偏移跨度）
- 最小分片数：`CACHE_FRAGMENT_MIN_NUM_DEFAULT = 3`
- 最大总缓存：`MAX_CACHE_BUFFER_SIZE = 19MB` (`media_cached_buffer.cpp` L32)
- 每次 `Write` 以 chunk 为单位分配；支持跨分片写（`WriteMergerPre/Post`）

**初始化参数** (`media_cached_buffer.h`):
```cpp
bool Init(uint64_t totalBuffSize, uint32_t chunkSize);  // totalBuffSize=总缓存大小, chunkSize=16KB
```

**Seek 优化** (`media_cached_buffer.cpp`):
- `NEW_FRAGMENT_INIT_CHUNK_NUM = 8` — Seek 操作限制缓存大小为 8 chunks（约 128KB）
- Seek 时 `GetOffsetFragmentCache()` 线性搜索分片列表，通过 `BoundedIntervalComp`/`LeftBoundedRightOpenComp` 谓词判断 offset 是否落在区间内
- 支持大偏移跨度模式 `isLargeOffsetSpan_`，自动缩减分片最大数量

**LRU 淘汰** (`media_cached_buffer.h`):
```cpp
LruCache<uint64_t, CacheChunk*> lruCache_;  // LRU 淘汰最久未访问的分片
```
- `DeleteHasReadFragmentCacheBuffer()` — 已读分片达到 `allowChunkNum` 后删除
- `DeleteUnreadFragmentCacheBuffer()` — 未读分片超时淘汰
- `ClearMiddleReadFragment()` — 清理中间读取区域，保留首尾

**读写操作**:
```cpp
size_t Read(void* ptr, uint64_t offset, size_t readSize);   // 带超时的循环读
size_t Write(void* ptr, uint64_t inOffset, size_t inWriteSize);  // 分片+chunk写入
bool Seek(uint64_t offset);  // 定位到指定偏移
bool IsReadSplit(uint64_t offset);  // 判断 offset 是否落在分片边界
```

**DFX 超时保护** (`media_cached_buffer.cpp` L13-14):
- `LOOP_TIMEOUT = 60s` — 防止 `GetOffsetFragmentCache` 循环超时
- `MAX_TOTAL_READ_SIZE = 2MB` — 单次读取上限，`UP_LIMIT_MAX_TOTAL_READ_SIZE = 3MB`

---

## E2. AesDecryptor — AES-128-CBC 软件解密器

**文件**: `services/media_engine/plugins/source/http_source/utils/aes_decryptor.cpp` + `.h`

**用途**: 在 HLS/DASH 流媒体下载链路中，对 AES-128 加密的媒体分片进行软件解密（AES-128-CBC 模式）

**常量**:
```cpp
static constexpr uint64_t BLOCK_LEN = 16;       // AES 块大小
static constexpr uint32_t KEY_BITS = 128;        // 128 位密钥
```

**OpenSSL 依赖**:
```cpp
#include <openssl/aes.h>
#include <openssl/crypto.h>
AES_KEY aesKey_;  // OpenSSL AES 密钥结构
```

**核心方法**:

```cpp
// 密钥初始化（内容密钥变更时回调）
void OnSourceKeyChange(const uint8_t* key, size_t keyLen, const uint8_t* iv);
// key: AES 密钥字节
// iv:  初始向量（ CBC 模式）
// 实现: AES_set_decrypt_key() 设置解密密钥，memcpy_s 复制 key_/iv_
// 失败时 Reset() 清空密钥
```

```cpp
// AES-CBC 解密（输入输出均为 16 字节对齐）
void Decrypt(uint8_t* in, uint8_t* out, uint32_t len);
// len 必须是 BLOCK_LEN=16 的倍数
// 使用 AES_cbc_encrypt() 进行 CBC 模式解密
```

```cpp
void Reset();  // 清空密钥和 IV，调用 OPENSSL_cleanse 敏感数据清理
```

**成员变量**:
```cpp
uint8_t key_[BLOCK_LEN];       // 用户密钥（最多 16 字节）
size_t keyLen_;                  // 密钥长度
uint8_t iv_[BLOCK_LEN];         // 当前 CBC IV
uint8_t initIv_[BLOCK_LEN];     // 初始 IV（Reset 时恢复）
```

**特点**:
- 纯软件实现，调用 OpenSSL libcrypto
- 无硬件 DRM 依赖，适用于非安全路径的测试/明文场景
- 与 DashSegmentDownloader / HlsSegmentManager 集成，在分片数据下载后立即解密

---

## E3. XmlParser — MPD XML 解析器

**文件**: `services/media_engine/plugins/source/http_source/xml/xml_parser.cpp` + `.h`

**底层库**: libxml2（`xmlInitParser`/`xmlReadMemory`/`xmlReadDoc` 等）

**安全标志**: `XML_PARSE_NONET | XML_PARSE_NOERROR | XML_PARSE_NOWARNING` — 禁用网络访问，忽略解析错误/警告

**三种解析入口**:

```cpp
// 从内存缓冲区解析
int32_t ParseFromBuffer(const char* buf, int32_t length);

// 从字符串解析
int32_t ParseFromString(const std::string& xmlStr);

// 从文件路径解析
int32_t ParseFromFile(const std::string& filePath);
```

**DOM 树访问**:
```cpp
std::shared_ptr<XmlElement> GetRootElement();  // 获取根节点
int32_t GetAttribute(std::shared_ptr<XmlElement> element, 
                     const std::string attrName, std::string& value);  // 读取属性
```

**命名空间处理**:
```cpp
void SkipElementNameSpace(std::string& elementName) const;
// 剥离 "cxml:Element" → "Element" 形式的前缀
```

**生命周期管理**:
```cpp
~XmlParser();  // 调用 DestroyDoc()
void DestroyDoc();  // xmlFreeDoc + xmlCleanupParser + xmlMemoryDump
```

**与 DashMpdParser (S138) 关系**:
- XmlParser 是底层 XML 解析工具
- DashMpdParser 调用 XmlParser 实现 MPD 节点的属性解析
- S138 侧重 MPD 语义节点类（DASH MPD 的五层结构）
- S246 补充 XmlParser 的工具层实现细节

---

## E4. HttpMediaUtils — Bundle 名称查询与 DFX 工具

**文件**: `services/media_engine/plugins/source/http_source/utils/http_media_utils.cpp` + `.h`

**核心功能**: 根据进程 UID 查询调用方 Bundle 名称，用于流媒体 DFX 上报区分应用来源

```cpp
std::string HttpMediaUtils::GetClientBundleName(int32_t uid);
// uid=1003 → "bootanimation"（系统启动动画特殊处理）
// 其他：通过 BundleMgrService 查询 GetNameForUid()
```

**SAMgr 查询链**:
```cpp
SystemAbilityManagerClient::GetInstance().GetSystemAbilityManager()
  → GetSystemAbility(BUNDLE_MGR_SERVICE_SYS_ABILITY)
  → iface_cast<IBundleMgr>
  → GetNameForUid(uid, bundleName)
```

**DFX 打点上下文**: HttpMediaUtils 提供调用方身份识别，使得 `HiStreamer` DFX 打点可以区分是哪个应用在请求流媒体数据

---

## 组件协作关系

```
DashSegmentDownloader / HlsSegmentManager
    ↓ 下载分片数据
AesDecryptor::Decrypt()   ← AES-128-CBC 解密（AES-128 加密分片）
    ↓ 解密后数据
MediaCachedBuffer::Write()  ← LRU 分片缓存（Seek 支持）
    ↓
上层 Read() 调用 ← Seek 时通过 LRU 淘汰历史分片

HttpMediaUtils::GetClientBundleName() → DFX 打点（应用身份识别）
XmlParser → MPD XML 解析（为 DashMpdParser 提供工具支持）
```

---

## 与相关 S 编号关联

| S编号 | 主题 | 关联点 |
|-------|------|--------|
| S138 | DashMpdParser MPD 解析器 | XmlParser 是 MPD 节点解析的底层工具 |
| S222 | DashSegmentDownloader 分片下载 | AesDecryptor + MediaCachedBuffer 集成点 |
| S234 | HLS M3U8 Tag Parsing | XmlParser 解析 M3U8 中的 AES-128 key URL |
| S195 | Downloader 下载架构 | MediaCachedBuffer 下游消费者 |
| S225 | CodecDrmDecrypt DRM | AesDecryptor 与 Codec DRM 解密的边界：软件 AES vs 硬件 DRM |

---

## 关键常量速查

| 常量 | 值 | 文件位置 |
|------|-----|---------|
| CHUNK_SIZE | 16KB | `media_cached_buffer.cpp` L29 |
| MAX_CACHE_BUFFER_SIZE | 19MB | `media_cached_buffer.cpp` L32 |
| CACHE_FRAGMENT_MAX_NUM_DEFAULT | 300 | `media_cached_buffer.cpp` L17 |
| CACHE_FRAGMENT_MAX_NUM_LARGE | 10 | `media_cached_buffer.cpp` L18 |
| NEW_FRAGMENT_INIT_CHUNK_NUM | 8 (128KB) | `media_cached_buffer.cpp` L20 |
| LOOP_TIMEOUT | 60s | `media_cached_buffer.h` |
| AES BLOCK_LEN | 16 | `aes_decryptor.h` |
| AES KEY_BITS | 128 | `aes_decryptor.h` |
| BOOTANIMATION_UID | 1003 | `http_media_utils.cpp` L23 |

---

**来源**: GitCode 仓库 `https://gitcode.com/openharmony/multimedia_av_codec` + 本地镜像 `/home/west/av_codec_repo/services/media_engine/plugins/source/http_source/`

**本地镜像行号增强**（E5-E12，2026-06-21 builder-agent）:
- **E5** `media_cached_buffer.cpp` L28-37: CHUNK_SIZE=16KB / MAX_CACHE_BUFFER_SIZE=19MB / MAX_TOTAL_READ_SIZE=2MB 常量定义
- **E6** `media_cached_buffer.cpp` L30-36: CACHE_FRAGMENT_MAX_NUM_DEFAULT=300 / CACHE_FRAGMENT_MAX_NUM_LARGE=10 / NEW_FRAGMENT_INIT_CHUNK_NUM=8 常量
- **E7** `media_cached_buffer.cpp` L38-46: BoundedIntervalComp / LeftBoundedRightOpenComp 区间判断谓词（Seek优化）
- **E8** `aes_decryptor.cpp` L31-49: AesDecryptor 构造函数初始化 aesKey_.rounds=0 / memset_s 清零
- **E9** `aes_decryptor.cpp` L51-67: OnSourceKeyChange 密钥变更回调 / AES_set_decrypt_key / memcpy_s
- **E10** `aes_decryptor.cpp` L69-71+: Decrypt 方法 AES_cbc_encrypt 调用
- **E11** `http_media_utils.cpp` L33-49: GetClientBundleName / DEFAULT_ID=1003 / SAMgr 查询链
- **E12** `xml_parser.cpp` 131行: libxml2 XML_PARSE_NONET|NOERROR|NOWARNING 安全标志 / 三种解析入口
