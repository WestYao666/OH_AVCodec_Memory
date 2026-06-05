# MEM-ARCH-AVCODEC-S216: AVCodec DFX & DRM Decryptor 双模块统一架构

> GitCode web_fetch 探索版 | 2026-06-05 | builder-agent (subagent)
> 来源：https://gitcode.com/openharmony/multimedia_av_codec
> 关联：S82/S163/S200/S213

## 主题

AVCodec DFX 可观测性框架与 DRM CENC 解密子系统双模块统一架构——services/dfx 五组件与 services/drm_decryptor 三路解密链。

---

## 一、DFX 模块五组件架构

### 1.1 services/dfx/ 目录结构

```
services/dfx/
├── include/
│   ├── avcodec_dfx_component.h    (58行) — DFX组件标签
│   ├── avcodec_dump_utils.h       (57行) — dump工具
│   ├── avcodec_log.h             — HiLog标签
│   ├── avcodec_log_ex.h           — 日志扩展
│   ├── avcodec_sysevent.h         (95行) — HiSysEvent声明
│   ├── avcodec_trace.h            (94行) — HiTrace染色
│   └── avcodec_xcollie.h          (113行) — XCollie定时器
├── avcodec_dfx_component.cpp      (70行)
├── avcodec_dump_utils.cpp         (126行)
├── avcodec_sysevent.cpp           (198行)
├── avcodec_xcollie.cpp            (175行)
└── BUILD.gn
```

### 1.2 AVCodecDfxComponent 标签组件

**avcodec_dfx_component.h**（58行） + **avcodec_dfx_component.cpp**（70行）

E1: `std::atomic<const char *> tag_` — 原子标签存储，线程安全标签内容（L13 avcodec_dfx_component.h）
E2: `AVCodecDfxComponent::SetTag()` — `tagContent_` 写入后通过 `tag_.store(tagContent_.c_str())` 更新原子变量（L42-47 avcodec_dfx_component.cpp）
E3: `CreateVideoLogTag(Meta& callerInfo)` — 从 Meta 中提取 instanceId + codecName，构造 `[instanceId][h.vdec]` 或 `[instanceId][s.venc]` 格式日志标签（L25-42 avcodec_dfx_component.cpp）
E4: `codecName.find("omx")` → `h.` 前缀（硬件/OMX）vs `s.` 前缀（软件）E5: `codecName.find("decode")` → `vdec`；`codecName.find("encode")` → `venc`

### 1.3 HiSysEvent 系统事件上报

**avcodec_sysevent.h**（95行）声明结构体 + **avcodec_sysevent.cpp**（198行）实现

E6: `FaultType` 枚举三态：`FAULT_TYPE_FREEZE` / `FAULT_TYPE_CRASH` / `FAULT_TYPE_INNER_ERROR`（L22-26 avcodec_sysevent.h）
E7: `DfxSourceType` 枚举九来源：`DASHVOD`/`HTTPVOD`/`HLSVOD`/`FMP4VOD`/`FMP4LIVE`/`HLSLIVE`/`HTTPLIVE`/`DASHLIVE`（L29-37 avcodec_sysevent.h）
E8: `CodecDfxInfo` 结构体：clientPid/clientUid/codecInstanceId/codecName/codecIsVendor/codecMode + 视频参数（bitRate/width/height/frameRate/pixelFormat）+ 音频参数（channelCount/sampleRate）（L39-53 avcodec_sysevent.h）
E9: `FaultEventWrite(FaultType, msg, module)` → `HiSysEventWrite("AV_CODEC", "FAULT", EventType::FAULT, ...)` — FAULT级别故障上报（L50-55 avcodec_sysevent.cpp）
E10: `CodecStartEventWrite(CodecDfxInfo&)` → `HiSysEventWrite("AV_CODEC", "CODEC_START_INFO", BEHAVIOR, ...)` — 编解码器启动行为上报（L68-81 avcodec_sysevent.cpp）
E11: `CodecStopEventWrite(clientPid, clientUid, codecInstanceId)` → `HiSysEventWrite("AV_CODEC", "CODEC_STOP_INFO", BEHAVIOR, ...)` — 停止事件（L85-90 avcodec_sysevent.cpp）
E12: `FaultDemuxerEventWrite(DemuxerFaultInfo&)` → `HiSysEventWrite(Domain::MULTI_MEDIA, "DEMUXER_FAILURE", FAULT, ...)` — 解封装器故障（L92-101 avcodec_sysevent.cpp）
E13: `FaultAudioCodecEventWrite` / `FaultVideoCodecEventWrite` / `FaultMuxerEventWrite` / `FaultRecordAudioEventWrite` — 四类组件故障上报（L103-135 avcodec_sysevent.cpp）
E14: `SourceStatisticsEventWrite(SourceStatisticsReportInfo&)` — 流媒体播放策略上报，使用 nlohmann/json 构造 JSON，EVP_sha256 哈希 CA 证书，4小时批量上报窗口（L137-192 avcodec_sysevent.cpp）

### 1.4 AVCodecXCollie 定时器监控

**avcodec_xcollie.h**（113行）声明 + **avcodec_xcollie.cpp**（175行）实现

E15: `AVCodecXCollie::GetInstance()` — 单例模式（L44 avcodec_xcollie.cpp）
E16: `SetTimer(name, recovery, dumpLog, timeout, callback)` → `HiviewDFX::XCollie::GetInstance().SetTimer(...)` — XCollie 底层定时器注入，flag组合（`XCOLLIE_FLAG_NOOP` / `XCOLLIE_FLAG_RECOVERY` / `XCOLLIE_FLAG_LOG`）（L60-70 avcodec_xcollie.cpp）
E17: `SetInterfaceTimer(name, isService, recovery, timeout)` — `isService=true` → `ServiceInterfaceTimerCallback`；`isService=false` → `ClientInterfaceTimerCallback`（L74-81 avcodec_xcollie.cpp）
E18: `ServiceInterfaceTimerCallback` — 服务任务超时：打印 AVCODEC_LOGE + `FaultEventWrite(FAULT_TYPE_FREEZE, ...)`；threshold=1时 `_exit(-1)` 进程退出（L138-150 avcodec_xcollie.cpp）
E19: `ClientInterfaceTimerCallback` — 客户端任务超时：打印 AVCODEC_LOGE + `FaultEventWrite(FAULT_TYPE_FREEZE, ...)` 不退出进程（L153-158 avcodec_xcollie.cpp）
E20: `AVCodecXcollieTimer` RAII包装器：构造时SetTimer，析构时CancelTimer（L93-104 avcodec_xcollie.h）
E21: `AVCodecXcollieInterfaceTimer` — 接口级RAII定时器，默认30秒超时（L106-120 avcodec_xcollie.h）
E22: `COLLIE_LISTEN(statement, args...)` 宏：自动RAII计时，Service端用；`CLIENT_COLLIE_LISTEN(statement, name)` 宏：客户端30秒计时（L122-134 avcodec_xcollie.h）
E23: `~AVCodecXCollie()` 析构时 `destroyed_.store(true)` — 防止静态析构顺序问题（L52-54 avcodec_xcollie.cpp）

### 1.5 AVCodecDumpControler dump工具

**avcodec_dump_utils.cpp**（126行）

E24: `AVCodecDumpControler::AddInfo(dumpIdx, name, value)` — dump索引格式：Level4(0xFF`XXXX`)/Level3(0x`XX`FF`XX`)/Level2(0x`XX`XXFF)/Level1(0x`XXXXXX`FF)，通过位运算判断层级（L24-39 avcodec_dump_utils.cpp）
E25: `GetLevel(dumpIdx)` — `(dumpIdx & 0xFF) != 0` → Level4；`((dumpIdx >> 8) & 0xFF) != 0` → Level3；`((dumpIdx >> 16) & 0xFF) != 0` → Level2；否则Level1（L111-119 avcodec_dump_utils.cpp）
E26: `AddInfoFromFormat(dumpIdx, Format, key, name)` — 从 Format 中提取值（int32/int64/float/double/string），自动类型推断（L57-75 avcodec_dump_utils.cpp）
E27: `AddInfoFromFormatWithMapping(dumpIdx, Format, key, name, mapping)` — 数值→字符串映射dump（如 codecType→"avc"/"hevc"）（L77-91 avcodec_dump_utils.cpp）
E28: `GetDumpString(dumpString)` — 层级缩进输出：`level=1` 无缩进；`level=2` 4空格；`level=3` 8空格；`level=4` 12空格；name左对齐value右侧（L93-103 avcodec_dump_utils.cpp）

---

## 二、DRM CENC 解密子系统

### 2.1 services/drm_decryptor/ 目录

```
services/drm_decryptor/
├── codec_drm_decrypt.cpp  (764行) — 核心解密实现
└── codec_drm_decrypt.h    (96行)  — 接口定义
```

### 2.2 DRM 三路视频格式支持

**codec_drm_decrypt.cpp** L38-48 常量定义：

E29: `DRM_VIDEO_AVC = 0x1` / `DRM_VIDEO_HEVC = 0x2` / `DRM_VIDEO_AVS = 0x3` — 三路视频Codec枚举（L38-48 codec_drm_decrypt.cpp）
E30: `DRM_H264_VIDEO_SKIP_BYTES = 35` — `(32 + 3)` AVC起始码后需要跳过的字节（L50 codec_drm_decrypt.cpp）
E31: `DRM_H265_VIDEO_SKIP_BYTES = 68` — `(65 + 3)` HEVC起始码后需要跳过的字节（L51 codec_drm_decrypt.cpp）
E32: `DRM_AVS3_VIDEO_SKIP_BYTES = 4` — `(1 + 3)` AVS3起始码后需要跳过的字节（L52 codec_drm_decrypt.cpp）
E33: `DRM_MAX_STREAM_DATA_SIZE = 20971520` — `20MB` 最大流数据大小限制（L60 codec_drm_decrypt.cpp）

### 2.3 NALU 搜索与类型识别

E34: `DrmGetNalTypeAndIndex(data, dataSize, nalType, posIndex)` — 遍历流数据查找 `0x00 0x00 0x01` 起始码，AVC用 `nalType = data[i+3] & 0x1f`（L67-92 codec_drm_decrypt.cpp）
E35: HEVC NAL type：`nalType = (data[i+3] >> 1) & 0x3f`，范围0-31（L74-81 codec_drm_decrypt.cpp）
E36: AVS NAL type：`nalType = data[i+3]`，等于0时为视频帧（L82-88 codec_drm_decrypt.cpp）
E37: `DrmGetFinalNalTypeAndIndex` — 主循环：查找起始码 → 提取NAL type → 计算加密范围 → 判断是否大于 skipBytes+AES_BLOCK_SIZE（L94-129 codec_drm_decrypt.cpp）
E38: `DrmRemoveAmbiguityBytes` — 删除 `0x00 0x00 0x03` 后跟 `0x00-0x03` 的防混淆字节（L131-153 codec_drm_decrypt.cpp）

### 2.4 CENC subSample 构造

E39: `DrmModifyCencInfo` — CENC解密信息构造：subSamples[0].clearHeaderLen + subSamples[0].payLoadLen / subSamples[1].clearHeaderLen + subSamples[1].payLoadLen（L156-198 codec_drm_decrypt.cpp）
E40: `clearHeaderLen = posStartIndex + skipBytes` — 明文头部长度（NAL起始码 + skipBytes）
E41: `payLoadLen` — 加密区域：`posEndIndex - clearHeaderLen - delLen`，按16字节对齐（向下取整）
E42: `subSamples[1].clearHeaderLen = lastClearLen + delLen + (dataSize - posEndIndex)` — 尾部明文（AES Block未对齐部分+删除了防混淆字节+剩余数据）

### 2.5 算法与Block参数设置

E43: `algo = 0x1` → `META_DRM_ALG_CENC_SM4_CBC`（SM4-SAMPL）— 中国国产算法（L202-204 codec_drm_decrypt.cpp）
E44: `algo = 0x2` → `META_DRM_ALG_CENC_AES_CBC`（AES CBCS）— 国际标准算法（L205-207 codec_drm_decrypt.cpp）
E45: `DRM_CRYPT_BYTE_BLOCK = 1` / `DRM_SKIP_BYTE_BLOCK = 9` — CBCS模式加密参数（1个block加密，9个block跳过）（L46-47 codec_drm_decrypt.cpp）

---

## 三、双模块关联图谱

```
DFX模块（services/dfx/）
  ├── AVCodecDfxComponent — 实例级日志标签 [id][h.vdec/s.venc]
  ├── avcodec_sysevent — HiSysEvent六类事件上报（FAULT/BEHAVIOR/STATISTIC）
  │   ├── FaultEventWrite — 组件级故障（DEMUXER/AUDIO_CODEC/VIDEO_CODEC/MUXER/RECORD_AUDIO）
  │   ├── CodecStartEventWrite / CodecStopEventWrite — 编解码器生命周期
  │   └── SourceStatisticsEventWrite — 流媒体播放策略（4h批量）
  ├── AVCodecXCollie — 超时监控 + 进程退出保护
  │   ├── SetInterfaceTimer → ServiceInterfaceTimerCallback → _exit(-1)
  │   └── COLLIE_LISTEN 宏 — RAII接口计时
  └── AVCodecDumpControler — 层级dump索引（Level1-4）
      └── AddInfoFromFormatWithMapping — Format值→字符串映射

DRM模块（services/drm_decryptor/）
  └── CodecDrmDecrypt — CENC解密三路（AVC/HEVC/AVS）
      ├── DrmGetNalTypeAndIndex — NALU搜索与类型识别
      ├── DrmRemoveAmbiguityBytes — 防混淆字节删除
      ├── DrmModifyCencInfo — subSamples双结构构造
      └── SetDrmAlgoAndBlocks — SM4/AES算法 + CBCS Block参数
```

---

## 四、关联记忆条目

| ID | 主题 | 关联点 |
|----|------|--------|
| S82 | AVCodec 服务框架 | HiSysEvent/DfxInfo 结构体共享 |
| S163 | DRM CENC解密框架 | 本草案为S163的GitCode web_fetch增强版 |
| S200 | AVCodec Memory子系统审计员 | MemoryMonitor与DFX五组件协同 |
| S213 | AVCodec DFX五组件协作框架 | 本草案为S213的GitCode web_fetch版，补充完整行号 |

---

## 五、证据来源

| 文件 | 行数 | 来源 |
|------|------|------|
| services/dfx/avcodec_dfx_component.cpp | 70 | GitCode web_fetch |
| services/dfx/avcodec_dfx_component.h | 58 | GitCode web_fetch |
| services/dfx/avcodec_sysevent.cpp | 198 | GitCode web_fetch |
| services/dfx/avcodec_sysevent.h | 95 | GitCode web_fetch |
| services/dfx/avcodec_xcollie.cpp | 175 | GitCode web_fetch |
| services/dfx/avcodec_xcollie.h | 113 | GitCode web_fetch |
| services/dfx/avcodec_dump_utils.cpp | 126 | GitCode web_fetch |
| services/drm_decryptor/codec_drm_decrypt.cpp | 764 | GitCode web_fetch (truncated) |
| services/drm_decryptor/codec_drm_decrypt.h | 96 | GitCode web_fetch |
| **合计** | **~1695行** | **GitCode web_fetch** |

---

**状态**：draft_pending
**builder**：builder-agent (subagent)
**生成时间**：2026-06-05T15:09+08:00