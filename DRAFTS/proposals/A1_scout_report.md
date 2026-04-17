# A1 - AVCodec 模块总览：Scout 探索报告

**主题**：AVCodec 模块总览  
**探索时间**：2026-04-17  
**状态**：draft（待 Mapper + Synthesizer 合并）

---

## 关键发现

### 1. 顶层目录结构（5大块）

| 目录 | 职责 |
|------|------|
| `frameworks/native` | native C++ 框架代码，无具体Codec实现 |
| `interfaces` | 接口层：`kits`（应用接口）+ `inner_api`（系统内部件接口）|
| `services` | 服务实现，含 engine（功能层）+ services（IPC层）+ dfx + etc + utils |
| `test` | 测试代码 |
| `BUILD.gn` / `bundle.json` | 构建入口 |

### 2. 服务层分层架构（核心发现）

`services/` 下分为两层，职责清晰分离：

**engine 层**（功能实现）：
```
services/engine/
├── base       # 功能基类
├── codec      # 编解码功能实现
├── codeclist  # 编解码能力查询
├── common     # 公共库
├── demuxer    # 解封装
├── factory    # 工厂库
├── muxer      # 封装
├── plugin     # 插件机制
└── source     # 媒体资源读取
```

**services 层**（IPC封装）：
```
services/services/
├── codec        # 编解码IPC
├── codeclist    # 能力查询IPC
├── common       # IPC公共库
├── demuxer      # 解封装IPC
├── factory      # 工厂IPC
├── muxer        # 封装IPC
├── sa_avcodec   # 部件主进程IPC
└── source       # 资源读取IPC
```

**结论**：每一对 engine/xxx 对应 services/xxx，IPC 层透传 engine 的能力，不做业务逻辑。

### 3. 接口层分离

- `interfaces/kits` → 应用开发者可见
- `interfaces/inner_api` → 系统组件可见，含 HDI 硬件抽象接口

### 4. DFX 独立目录

`services/dfx` 是单独的目录，说明 DFX 作为横切模块独立于具体 codec/demuxer/muxer 功能。

### 5. 四大核心能力

1. **编解码**（codec）：音视频编码/解码
2. **解封装**（demuxer）：资源加载、轨道分离、数据读取
3. **封装**（muxer）：编码数据写入媒体文件
4. **能力查询**（codeclist）：所有 Codec 的元信息（名字、mimetype、分辨率等）

---

## 证据摘要

| 类型 | 路径 | 说明 |
|------|------|------|
| doc | README_zh.md | 官方模块说明 |
| code | services/engine/* | 9个子模块的功能实现 |
| code | services/services/* | 7个IPC模块 |
| build | BUILD.gn | 编译入口 |

---

## 待确认缺口（建议发飞书问题卡）

**缺口1**：DFX 统计事件框架的职责边界是什么？它和 engine 层的交互模式是什么？

**缺口2**：plugin 目录的插件机制是什么？Codec 是以插件形式加载的吗？

---

## 建议的 Memory Entry 摘要（供 Synthesizer 使用）

```yaml
id: MEM-ARCH-AVCODEC-001
title: AVCodec 模块总览
type: architecture_fact
summary: >
  av_codec部件包含5大模块：frameworks（框架）、interfaces（接口层）、
  services/engine（功能实现）、services/services（IPC层）、services/dfx（DFX）。
  功能层分为 codec/demuxer/muxer/source 四个领域，每个领域在 engine 层实现
  业务逻辑，在 services 层提供 IPC 封装。interfaces 层分离 kits（应用接口）
  和 inner_api（系统内部接口，包括 HDI 硬件抽象）。
scope: [AVCodec, Architecture]
evidence:
  - kind: doc
    ref: README_zh.md
    anchor: 模块介绍
  - kind: code
    ref: services/engine/
    anchor: 目录结构
  - kind: code
    ref: services/services/
    anchor: 目录结构
```

---

_本报告由 Scout Agent 生成（2026-04-17），原始 evidence bundle 存于 EVIDENCE/code/avcodec_module_overview.yaml_
