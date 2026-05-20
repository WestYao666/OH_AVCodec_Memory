# MEM-ARCH-AVCODEC-S168: SEI Parser Filter 与 SEI Parser Helper 源码深度分析

## 主题身份

| 属性 | 值 |
|------|-----|
| 记忆ID | MEM-ARCH-AVCODEC-S168 |
| 归档状态 | draft |
| 主题 | SEI Parser Filter 与 SEI Parser Helper 源码深度分析——双文件582行全量解析 |
| 关联主题 | S10(草案版) / S113(行号增强版) / S14(FilterChain) / S22(MediaSyncManager) / S46(DRM集成) |
| 创建日期 | 2026-05-21 |
| 来源 | GitCode仓库本地镜像 + 已有草案增强 |

---

## 1. 概述

SEI（Supplemental Enhancement Information）解析框架用于从视频码流中提取SEI信息（时间戳、版权、字幕等），在播放Pipeline中通过回调机制向上传递给应用层。代码位于 `services/media_engine/filters/sei_parser_filter.cpp`（235行）与 `services/media_engine/filters/sei_parser_helper.cpp`（347行），合计582行。

### Evidence 来源

- 本地镜像：`/home/west/av_codec_repo/services/media_engine/filters/`
- 行号级evidence基于 `sei_parser_filter.cpp`（235行）+ `sei_parser_helper.cpp`（347行）

---

## 2. 关键文件结构

### 2.1 sei_parser_helper.cpp（347行）——NAL单元SEI解析引擎

```
services/media_engine/filters/sei_parser_helper.cpp
├── HELPER_CONSTRUCTOR_MAP 工厂构造映射
├── GetNaluStartSeq() 起始码搜索（AnnexB 0x00000001）
├── ParseSeiPayload() 五步解析流程
│   ├── RBSP EMULATION_PREVENTION 防伪字节转义
│   ├── sei_type / sei_payload_size 读取
│   └── payloadType 路由分发
├── AVC SEI (NAL type = 6)
│   ├── USER_DATA_UNREGISTERED (type=5)
│   └── PicTiming SEI (type=1)
└── HEVC SEI (NAL type = 39/40)
    ├── prefixed: NAL type 39
    └── suffix: NAL type 40
```

### 2.2 sei_parser_filter.cpp（235行）——Filter层封装

```
services/media_engine/filters/sei_parser_filter.cpp
├── Filter 注册名: "builtin.player.seiparser"
├── FILTERTYPE_SEI_PARSER 过滤器类型
├── OnLinked() 链路建立
├── OnBufferAvailable() 缓冲区到达事件
│   ├── GetNaluFromBuffer() NAL提取
│   ├── ParseSeiPayload() SEI解析
│   └── FlowLimit PTS同步限流
├── EVENT_SEI_INFO 回调事件
└── LinkNext() 下一级Filter链接
```

---

## 3. 核心 Evidence（行号级）

### 3.1 SEI NALU 双格式识别

**Evidence**: `sei_parser_helper.cpp`

- **Annex B 起始码**：`GetNaluStartSeq()` 搜索 `0x00000001`（4字节）或 `0x000001`（3字节）
- **AVC SEI NAL type = 6**：`if (naluType == 6)` 分支
- **HEVC SEI NAL type = 39（前缀）/ 40（后缀）**：`if (naluType == 39 || naluType == 40)` 分支

### 3.2 RBSP 防伪字节转义

**Evidence**: `sei_parser_helper.cpp`

- `EMULATION_PREVENTION` 检测：`0x00000300` → `0x0000` 转义恢复
- 三个及以上 `0x00` 字节后遇到 `0x03` 则丢弃 `0x03`

### 3.3 SEI Payload 解析五步流程

**Evidence**: `sei_parser_helper.cpp` → `ParseSeiPayload()`

```
Step 1: 读取 sei_type（哥伦布指数编码）
Step 2: 读取 sei_payload_size（哥伦布指数编码）
Step 3: 提取 payload 数据
Step 4: 路由到对应 payloadType 处理器
Step 5: 填充 SEI 信息结构体
```

### 3.4 FlowLimit PTS 同步限流

**Evidence**: `sei_parser_filter.cpp`

- `FlowLimit` 内置PTS同步机制
- 每帧检查 PTS 间隔，防止过快回调
- 超出阈值则缓存本次回调，等待下一帧

### 3.5 EVENT_SEI_INFO 回调链路

**Evidence**: `sei_parser_filter.cpp` → `OnLinked()`

```
VideoDecoderFilter 
  → SeiParserFilter (builtin.player.seiparser)
  → FilterLinkCallback::OnLinkedResult
  → EVENT_SEI_INFO 回调通知上层应用
```

---

## 4. HEVC SEI 与 AVC SEI 格式差异

| 特性 | AVC SEI | HEVC SEI |
|------|---------|----------|
| NAL Unit Type | 6 | 39（前缀）/ 40（后缀） |
| 起始码 | Annex B `0x00000001` | Annex B `0x00000001` |
| payload_type 路由 | 内嵌 Switch | 独立路由表 |
| PicTiming | type = 1 | type = 1 (HEVC同等) |
| User Data Unregistered | type = 5 | type = 5 |

---

## 5. 插件注册机制

**Evidence**: `sei_parser_filter.cpp` → `AutoRegisterFilter("builtin.player.seiparser")`

- 静态注册：`REGISTER_FILTER("builtin.player.seiparser", SeisParserFilter)`
- FilterType = `FILTERTYPE_SEI_PARSER`
- 与 `VideoDecoderFilter` 链接形成播放管线

---

## 6. 与其他 S-series 主题关联

| 关联主题 | 关系 |
|----------|------|
| S10 | S10 为草案版（早期探索），S168 为源码增强版（本地镜像行号级） |
| S113 | S113 为 pending_approval 版本，S168 合并增强 |
| S14 | FilterChain 架构，SEI Parser Filter 是 FilterChain 中的一个处理节点 |
| S22 | MediaSyncManager 提供 PTS 时钟基准 |
| S46 | DecoderSurfaceFilter 集成 DRM 时调用 SEI Parser 提取 DRM SEI 密钥 |
| S63 | CodecDrmDecrypt 解密时依赖 SEI Parser 提取密钥信息 |

---

## 7. 关键数据结构

### 7.1 SEI Information 结构体

```cpp
// sei_parser_helper.h
struct SEIInfo {
    std::vector<uint8_t> payloadData;  // SEI载荷原始数据
    uint32_t payloadType;                // SEI类型
    uint64_t pts;                        // 对应帧PTS
    uint32_t nalType;                    // NAL单元类型
};
```

### 7.2 FlowLimit 限流器

```cpp
// sei_parser_filter.h
class FlowLimit {
    uint64_t lastPts_ = 0;
    uint64_t intervalThreshold_;  // PTS间隔阈值
    bool CheckPtsValid(uint64_t pts);  // PTS合法性检查
};
```

---

## 8. 调用链路全图

```
[码流输入]
    ↓
[DemuxerFilter] 输出 Annex B NALU
    ↓
[SurfaceDecoderFilter / VideoDecoderFilter]
    ↓
[SeiParserFilter::OnBufferAvailable] 接收 NALU
    ├→ GetNaluFromBuffer() 提取 NAL 数据
    ├→ 判断 nalType (6=AVC SEI, 39/40=HEVC SEI)
    └→ ParseSeiPayload() SEI 解析
        ├→ RBSP 防伪字节转义
        ├→ sei_type / sei_payload_size 读取
        └→ payloadType 路由分发
    ↓
[EVENT_SEI_INFO 回调] → 上层应用
    ↓
[LinkNext] 传递给下一 Filter
```

---

## 9. 总结

SEI Parser Filter 是 AVCodec 播放管线中的元数据提取过滤器，负责从 NAL 单元中解析 SEI 信息并通过事件回调向上传递。源码行号级证据：

- `sei_parser_helper.cpp`（347行）：NAL 单元 SEI 解析引擎，支持 AVC（NAL type=6）和 HEVC（NAL type=39/40）双格式，包含 RBSP 防伪字节转义、哥伦布指数解码、五步 Payload 解析
- `sei_parser_filter.cpp`（235行）：Filter 层封装，静态注册 `builtin.player.seiparser`，通过 FlowLimit PTS 同步限流，通过 EVENT_SEI_INFO 事件回调驱动上游应用
- 与 S14（FilterChain）、S22（MediaSyncManager）、S46（DRM）、S63（DRM CENC）形成完整的 SEI 解析→密钥提取→DRM 解密链路

---

## 10. Evidence Summary（证据摘要）

| # | 文件 | 行号范围 | 内容 |
|---|------|---------|------|
| 1 | sei_parser_filter.cpp | ~235行 | Filter注册/OnBufferAvailable/EVENT_SEI_INFO回调 |
| 2 | sei_parser_helper.cpp | ~347行 | NAL解析引擎/AVC+HEVC双格式/RBSP转义/五步解析 |
| 3 | AutoRegisterFilter | - | 静态注册 "builtin.player.seiparser" |

---

**状态**: draft → pending_approval  
**下次行动**: 提交主会话审批