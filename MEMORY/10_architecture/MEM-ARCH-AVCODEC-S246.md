# MEM-ARCH-AVCODEC-S246: HttpSourcePlugin 离线缓存与流媒体工具链

> **主题**: S246 — HttpSourcePlugin 离线缓存与流媒体工具链——MediaCachedBuffer LRU分片缓存 + AesDecryptor AES-128解密 + XmlParser + HttpMediaUtils DFX 四组件
> **scope**: AVCodec, MediaEngine, SourcePlugin, HttpSourcePlugin, MediaCachedBuffer, AesDecryptor, XmlParser, HttpMediaUtils, LRU, AES-128, CBC, DRM, DASH, HLS, OfflineCache, Download
> **关联场景**: DASH/HLS流播放/离线缓存/AES-128解密/DFX可观测性
> **状态**: pending_approval
> **mem_id**: MEM-ARCH-AVCODEC-S246
> **来源**: 基于本地镜像 `/home/west/av_codec_repo/services/media_engine/plugins/source/http_source/` 探索
> **生成时间**: 2026-06-26T01:05 GMT+8
> **关联**: S138(S222/S234/S195/S225关联)

---

## 一、架构总览

HttpSourcePlugin 离线缓存工具链由四个独立组件构成，分布在 `services/media_engine/plugins/source/http_source/utils/` 目录：

```
┌─────────────────────────────────────────────────────────┐
│            HttpSourcePlugin 工具链（四组件）              │
├──────────────┬──────────────┬──────────────┬────────────┤
│ MediaCached  │  AesDecryptor │   XmlParser  │HttpMedia   │
│   Buffer     │  (AES-128-CBC)│  (libxml2)  │  Utils     │
│  LRU分片缓存  │   硬件/软件解密 │  XML解析    │  DFX工具   │
│  1674行      │    140行      │   183行     │   104行    │
└──────────────┴──────────────┴──────────────┴────────────┘
```

- **MediaCachedBuffer**: LRU分片缓存，MAX=19MB，Chunk=16KB，支持随机读写seek
- **AesDecryptor**: AES-128-CBC解密，依赖OpenSSL，支持key切换
- **XmlParser**: 基于libxml2的XML解析器，支持从Buffer/String/File三种方式解析
- **HttpMediaUtils**: DFX工具，通过BundleMgr获取客户端BundleName做流量统计

---

## 二、MediaCachedBuffer LRU分片缓存（1674行）

### 2.1 核心数据结构

**CacheChunk** (`media_cached_buffer.h:28`)
```cpp
struct CacheChunk {
    uint32_t chunkSize;    // 每个chunk固定16KB
    uint32_t dataLength;   // 当前chunk内有效数据长度
    uint64_t offset;       // 媒体流全局字节偏移
    uint8_t data[];        // 柔性数组（变长数据区）
};
```

**FragmentCacheBuffer** (`media_cached_buffer.h:39-49`) — LRU链表的节点结构：
```cpp
struct FragmentCacheBuffer {
    uint64_t offsetBegin;       // 当前分片的起始偏移
    int64_t dataLength;         // 当前分片总长度
    int64_t accessLength;       // 本次访问长度（用于热点检测）
    uint64_t totalReadSize;     // 累计读出字节数
    TimePoint readTime;         // 最近访问时间戳（LRU排序依据）
    CacheChunkList chunks;      // 该分片内所有chunk的链表
    ChunkIterator accessPos;     // 在全局LRU链表中的位置（用于O(1)移动）
    bool isSplit {false};       // 是否为跨边界分片
};
```

### 2.2 关键常量（`media_cached_buffer.cpp:29-36`）

| 常量 | 值 | 说明 |
|------|-----|------|
| `CHUNK_SIZE` | 16×1024 | 每个chunk固定16KB |
| `MAX_CACHE_BUFFER_SIZE` | 19×1024×1024 | 缓存最大19MB |
| `CACHE_FRAGMENT_MAX_NUM_DEFAULT` | 300 | 默认最大分片数 |
| `CACHE_FRAGMENT_MAX_NUM_LARGE` | 10 | 大偏移场景分片上限 |
| `CACHE_FRAGMENT_MIN_NUM_DEFAULT` | 3 | 默认最小分片数 |
| `NEW_FRAGMENT_INIT_CHUNK_NUM` | 8.0 | seek操作初始缓存8个chunk（128KB）|

### 2.3 LRU缓存实现（`lru_cache.h:26-37, 56-65`）

```cpp
// Refer: O(1)插入热点数据到链表头部
void Refer(const KeyT& key, const ValueT& val) {
    if (it != itemMap_.end()) { itemList_.erase(it->second); itemMap_.erase(it); }
    itemList_.push_front(make_pair(key, val));  // 插入链表头部（最新）
    itemMap_.insert(make_pair(key, itemList_.begin()));
    Clean();  // 超限时淘汰尾部（最久未用）
}

// Clean: 淘汰直到size <= cacheSize_
void Clean() {
    while (itemMap_.size() > cacheSize_) {
        auto last_it = itemList_.end(); --last_it;
        itemMap_.erase(last_it->first);
        itemList_.pop_back();  // 淘汰尾部（LRU）
    }
}
```

---

## 三、AesDecryptor AES-128-CBC解密（140行）

### 3.1 关键结构（`aes_decryptor.h:24-31`）

```cpp
class AesDecryptor {
    static constexpr uint64_t BLOCK_LEN = 16;     // AES块大小
    static constexpr uint32_t KEY_BITS = 128;     // 密钥长度
    uint8_t key_[BLOCK_LEN] = {0};
    uint8_t iv_[BLOCK_LEN] = {0};                // 当前CBC IV
    uint8_t initIv_[BLOCK_LEN] = {0};            // 初始IV（key切换后恢复）
    AES_KEY aesKey_;                              // OpenSSL解密密钥结构
};
```

### 3.2 密钥更新与解密（`aes_decryptor.cpp:62-67, 78-89`）

```cpp
// OnSourceKeyChange: 设置新密钥和IV，建立解密上下文
void AesDecryptor::OnSourceKeyChange(const uint8_t* key, size_t keyLen, const uint8_t* iv) {
    AES_set_decrypt_key(key_, KEY_BITS, &aesKey_);  // OpenSSL设置解密密钥
}

// Decrypt: AES-128-CBC解密（in-place或out-of-place）
void AesDecryptor::Decrypt(uint8_t *in, uint8_t *out, uint32_t len) {
    AES_cbc_encrypt(in, out, len, &aesKey_, iv_, AES_DECRYPT);  // CBC模式解密
}
```

---

## 四、XmlParser libxml2解析器（183行）

### 4.1 接口（`xml_parser.h:24-33`）

```cpp
class XmlParser {
    int32_t ParseFromBuffer(const char *buf, int32_t length);  // 从内存缓冲区解析
    int32_t ParseFromString(const std::string &xmlStr);        // 从字符串解析
    int32_t ParseFromFile(const std::string &filePath);        // 从文件解析
    std::shared_ptr<XmlElement> GetRootElement();              // 获取根节点
    int32_t GetAttribute(XmlElement, attrName, value);          // 读取属性值
};
```

### 4.2 缓冲区解析（`xml_parser.cpp:39-50`）

```cpp
int32_t XmlParser::ParseFromBuffer(const char *buf, int32_t length) {
    xmlInitParser();
    xmlDocPtr doc = xmlReadMemory(buf, length, nullptr, nullptr,
        XML_PARSE_NONET |   // 禁用网络访问（安全）
        XML_PARSE_NOERROR |  // 抑制错误输出
        XML_PARSE_NOWARNING); // 抑制警告输出
    xmlDocPtr_ = doc;
    return (doc != nullptr) ? 0 : -1;
}
```

---

## 五、HttpMediaUtils DFX工具（104行）

### 5.1 接口（`http_media_utils.h:19-22`）

```cpp
class HttpMediaUtils {
    static constexpr int32_t BUNDLE_MGR_SERVICE_SYS_ABILITY = 401;  // BundleMgr SA号
    static constexpr int32_t DEFAULT_USER_ID = 100;
    static std::string GetClientBundleName(int32_t uid);  // 根据UID查BundleName
    static bool GetAppVersion(const std::string &bundleName, uint32_t &versionCode);
};
```

### 5.2 BundleName查询（`http_media_utils.cpp:32-47`）

```cpp
std::string HttpMediaUtils::GetClientBundleName(int32_t uid) {
    auto samgr = SystemAbilityManagerClient::GetInstance().GetSystemAbilityManager();
    sptr<IBundleMgr> bms = iface_cast<IBundleMgr>(samgr->GetSystemAbility(BUNDLE_MGR_SERVICE_SYS_ABILITY));
    bms->GetNameForUid(uid, bundleName);  // DFX: 记录哪个App在使用HttpSourcePlugin
    return bundleName;
}
```

---

## 六、DownloadMonitor 装饰器（辅助DFX，906行）

### 6.1 重试错误码分类（`download_monitor.cpp:34-49`）

| 集合 | 包含的错误码 | 说明 |
|------|------------|------|
| `CLIENT_NOT_RETRY_ERROR_CODES` | {992} | 永不重试（应用层错误） |
| `CLIENT_RETRY_ERROR_CODES` | {-1,23,25,26,28,56,18,0} | 应用可恢复（超时/资源） |
| `SERVER_RETRY_ERROR_CODES` | {300,301,302,303,304,305,403,500,0} | 服务器可恢复（含302重定向） |

### 6.2 装饰器模式（`download_monitor.cpp:61-66`）

```cpp
DownloadMonitor::DownloadMonitor(std::shared_ptr<MediaDownloader> downloader) noexcept
    : downloader_(std::move(downloader))  // 持有真实downloader的引用
{}
// DownloadMonitor 继承 MediaDownloader 接口，内部调用 downloader_ 并在前后织入监控逻辑
```

---

## Evidence（行号级）

| # | 文件 | 行号 | 内容摘要 |
|---|------|------|---------|
| E1 | `media_cached_buffer.h` | 28 | `CacheChunk`结构体：chunkSize+dataLength+offset+柔性数组data[] |
| E2 | `media_cached_buffer.h` | 39-49 | `FragmentCacheBuffer`结构体：LRU节点（readTime+accessPos+chunks） |
| E3 | `media_cached_buffer.h` | 52-68 | `CacheMediaChunkBufferImpl`类：Read/Write/Seek/Dump/Clear五I/O方法 |
| E4 | `media_cached_buffer.cpp` | 29 | `CHUNK_SIZE = 16*1024`常量（16KB分片） |
| E5 | `media_cached_buffer.cpp` | 30 | `MAX_CACHE_BUFFER_SIZE = 19*1024*1024`常量（19MB上限） |
| E6 | `media_cached_buffer.cpp` | 31-32 | `CACHE_FRAGMENT_MAX_NUM_DEFAULT=300`/`LARGE=10`分片数限制 |
| E7 | `lru_cache.h` | 26-37 | `LruCache::Refer`：O(1)头部插入+Clean淘汰 |
| E8 | `lru_cache.h` | 56-65 | `LruCache::Clean`：超限时pop_back淘汰LRU尾部 |
| E9 | `aes_decryptor.h` | 24-31 | `AesDecryptor`类：BLOCK_LEN=16/KEY_BITS=128/key_/iv_/initIv_/aesKey_ |
| E10 | `aes_decryptor.cpp` | 62-67 | `OnSourceKeyChange`：AES_set_decrypt_key建立解密上下文 |
| E11 | `aes_decryptor.cpp` | 78-89 | `Decrypt`：AES_cbc_encrypt(in,out,len,&aesKey_,iv_,AES_DECRYPT) |
| E12 | `xml_parser.h` | 24-33 | `XmlParser`类：ParseFromBuffer/String/File三入口+GetRootElement+GetAttribute |
| E13 | `xml_parser.cpp` | 39-50 | `ParseFromBuffer`：xmlReadMemory+XML_PARSE_NONET安全标志 |
| E14 | `http_media_utils.h` | 19-22 | `HttpMediaUtils`：BUNDLE_MGR_SERVICE_SYS_ABILITY=401+GetClientBundleName声明 |
| E15 | `http_media_utils.cpp` | 32-47 | `GetClientBundleName`：SystemAbilityManager→BundleMgr→GetNameForUid DFX链路 |
| E16 | `download_monitor.cpp` | 34-49 | 三组重试错误码集合（CLIENT_NOT_RETRY/CLIENT_RETRY/SERVER_RETRY） |
| E17 | `download_monitor.cpp` | 61-66 | `DownloadMonitor`构造函数：装饰器模式持有`downloader_`引用 |
| E18 | `download_monitor.h` | 22-27 | `LoadingRequestStage`枚举：CONNECTION/PLAYLIST/MEDIA_DATA三阶段 |
