---
id: MEM-ARCH-AVCODEC-S11
type: architecture_fact
scope: [AVCodec, HardwareCodec, HDI, IPC, Passthrough, CodecComponentManager, Factory]
status: approved
approved_at: "2026-05-06"
created_by: builder-agent
created_at: 2026-04-23T21:07:00+08:00
summary: |
  硬件Codec通过ICodecComponentManager工厂+双模式(Passthrough/IPC)+HDI三层结构实现组件管理。
  GetManager()根据DecideMode()选择IPC或Passthrough路径，创建g_compMgrIpc/g_compMgrPassthru单例；
  HCodec::Create(name)通过GetCapList()查到的能力列表匹配codec名称，返回HDecoder(解码)或HEncoder(编码)实例；
  OnAllocateComponent()中compMgr_->CreateComponent()向HDI服务创建OMX组件。
evidence:
  # 源码路径（本地镜像 /home/west/av_codec_repo，对应 GitCode master 分支）
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/hcodec/hcodec_list.cpp
    anchor: "Line 35-48: g_compMgrIpc/g_compMgrPassthru 双单例 + Listener 服务死亡监听"
    desc: "静态 Manager 单例 + 服务死亡重置逻辑"
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/hcodec/hcodec_list.cpp
    anchor: "Line 56-79: DecideMode() 决定 IPC 还是 Passthrough"
    desc: "GetManager()双模式工厂函数（eng build 三段式强制/轮询决策）"
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/hcodec/hcodec_list.cpp
    anchor: "Line 82-101: GetManager(bool, bool, bool) 工厂函数"
    desc: "GetCapList()从HDI获取硬件Codec能力列表"
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/hcodec/hcodec_list.cpp
    anchor: "Line 112: GetManager(true) 用于能力查询"
    desc: "GetCapList()从HDI获取硬件Codec能力列表（能力查询走Passthrough路径）"
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/hcodec/hcodec_list.cpp
    anchor: "Line 142-149: GetCapList() 带缓存的硬件能力查询"
    desc: "GetCapList()从HDI获取硬件Codec能力列表"
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/hcodec/hcodec_list.cpp
    anchor: "Line 162-200: HCodecList::GetCapabilityList() + HdiCapToUserCap 能力转换"
    desc: "HCodecList::GetCapabilityList()能力转换"
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/hcodec/hcodec.cpp
    anchor: "Line 55-80: HCodec::Create(name) 工厂方法"
    desc: "HCodec::Create(name)工厂方法"
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/hcodec/hcodec.cpp
    anchor: "Line 1500-1520: OnAllocateComponent() + CreateComponent"
    desc: "OnAllocateComponent()调用CreateComponent"
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/hcodec/hdecoder.h
    anchor: "Line 29: class HDecoder"
    desc: "HDecoder类声明"
  - kind: local_file
    path: /home/west/av_codec_repo/services/engine/codec/video/hcodec/hencoder.h
    anchor: "Line 38: class HEncoder"
    desc: "HEncoder类声明"
---

# S11: HCodec CodecComponentManager 工厂与插件注册机制

## 1. 整体架构

硬件Codec组件管理采用**ICodecComponentManager工厂 + 双路径(Passthrough/IPC) + HDI服务**三层结构：

```
App/CodecServer
    │
    ▼
CodecFactory (codec_factory.cpp) — 创建CodecBase
    │
    ▼
HCodec::Create(name) ──→ GetCapList() ──→ ICodecComponentManager::Get()
    │ (factory)                                    │
    │                                    ┌────────┴────────┐
    ▼                                    │                 │
HDecoder / HEncoder                     ▼                 ▼
(CodecBase子类)              ICodecComponentManager  ICodecComponentManager
                                   (IPC)              (Passthrough)
                                       │                     │
                                       ▼                     ▼
                              HDF Codec Service     本地Codec Stub (直连)
                              (codec_component_
                               manager_service)
```

## 2. 双模式工厂：GetManager()

**文件**: `hcodec_list.cpp:82-101`

```cpp
sptr<ICodecComponentManager> GetManager(bool getCap, bool supportPassthrough, bool isSecure)
{
    lock_guard<mutex> lk(g_mtx);
    bool isPassthrough = getCap ? true : DecideMode(supportPassthrough, isSecure);
    sptr<ICodecComponentManager>& mng = (isPassthrough ? g_compMgrPassthru : g_compMgrIpc);
    if (mng) return mng;
    // IPC模式：注册服务死亡监听
    if (!isPassthrough) {
        sptr<IServiceManager> serviceMng = IServiceManager::Get();
        serviceMng->RegisterServiceStatusListener(new Listener(), DEVICE_CLASS_DEFAULT);
    }
    mng = ICodecComponentManager::Get(isPassthrough);  // HDI获取manager
    return mng;
}
```

**两个静态单例**:
- `g_compMgrIpc` (line 36) — IPC模式，通过HDF服务名获取
- `g_compMgrPassthru` (line 37) — Passthrough模式，直连本地Stub

## 3. 模式决策：DecideMode()

**文件**: `hcodec_list.cpp:56-79`

| 条件 | 模式 |
|------|------|
| `hcodec.usePassthrough=1` (eng) | 强制 Passthrough |
| `hcodec.usePassthrough=0` (eng) | 强制 IPC |
| `hcodec.usePassthrough=-1` (eng) + isSecure | `supportPassthrough`参数决定 |
| `hcodec.usePassthrough=-1` (eng) + 非Secure | 每3次轮流选一次Passthrough |
| 默认 | `supportPassthrough` 参数决定 |

Passthrough模式跳过了IPC/RPC开销，适合低延迟场景。

## 4. 能力发现：GetCapList()

**文件**: `hcodec_list.cpp:142-149`

```cpp
vector<CodecCompCapability> GetCapList()
{
    lock_guard<mutex> lk(g_deviceCapsMtx);
    if (g_deviceCapsInited) return g_deviceCaps;
    InitCapsLocked();  // 调用mnger->GetComponentCapabilityList()
    return g_deviceCaps;
}
```

`InitCapsLocked()` (line 117-137) 通过 `ICodecComponentManager::Get(true)->GetComponentCapabilityList()` 获取设备上所有硬件Codec能力。

## 5. 实例创建工厂：HCodec::Create()

**文件**: `hcodec.cpp:55-80`

```cpp
std::shared_ptr<HCodec> HCodec::Create(const std::string &name)
{
    vector<CodecCompCapability> capList = GetCapList();  // 从HDI获取能力
    for (const auto& cap : capList) {
        if (cap.compName != name) continue;
        if (cap.type == VIDEO_DECODER) {
            codec = make_shared<HDecoder>(cap, type.value());  // 解码器
        } else if (cap.type == VIDEO_ENCODER) {
            codec = make_shared<HEncoder>(cap, type.value());  // 编码器
        }
    }
    return codec;
}
```

**子类分工**:
- `HDecoder` (hcodec/hdecoder.h:29) — 视频解码器，继承自`HCodec`
- `HEncoder` (hcodec/hencoder.h:38) — 视频编码器，继承自`HCodec`

## 6. OMX组件创建：OnAllocateComponent()

**文件**: `hcodec.cpp:1500-1520`

```cpp
int32_t HCodec::OnAllocateComponent()
{
    HitraceMeterFmtScoped trace(HITRACE_TAG_ZMEDIA, "hcodec %s %s", __func__, caps_.compName.c_str());
    compMgr_ = GetManager(false,
        HCodecList::FindFeature(caps_.port.video.features, VIDEO_FEATURE_PASS_THROUGH).support,
        isSecure_);
    // ...
    compCb_ = new HdiCallback(m_token);
    int32_t ret = compMgr_->CreateComponent(compNode_, componentId_, caps_.compName, 0, compCb_);
    // ...
}
```

关键HDI调用：
- `ICodecComponentManager::Get(isPassthrough)` — 获取manager
- `compMgr_->CreateComponent(...)` — 向Codec HDI服务创建OMX组件实例
- 返回的`compNode_`（类型`sptr<ICodecComponent>`）是与硬件Codec通信的代理接口

## 7. 服务死亡监听

**文件**: `hcodec_list.cpp:35-52`

```cpp
static mutex g_mtx;
static sptr<ICodecComponentManager> g_compMgrIpc;
static sptr<ICodecComponentManager> g_compMgrPassthru;

class Listener : public ServStatListenerStub {
    void OnReceive(const ServiceStatus &status) override {
        if (status.serviceName == "codec_component_manager_service" &&
            status.status == SERVIE_STATUS_STOP) {
            LOGW("codec_component_manager_service died");
            g_compMgrIpc = nullptr;  // 触发重新获取
        }
    }
};
```

IPC模式下注册服务死亡监听，服务崩溃后下次`GetManager()`会重新获取。

## 8. 关键对比

| 维度 | IPC模式 | Passthrough模式 |
|------|---------|----------------|
| manager获取 | HDF IServiceManager | `ICodecComponentManager::Get(true)` |
| 通信方式 | IPC/RPC | 直连本地Stub |
| 服务死亡恢复 | 有监听自动重连 | 无需恢复 |
| 延迟 | 较高 | 低 |
| 适用场景 | 普通视频编解码 | 低延迟场景 |

## 9. 关键类型速查

| 类型 | 定义位置 | 作用 |
|------|---------|------|
| `CodecHDI::ICodecComponentManager` | HDI v4_0 | 组件管理器接口 |
| `CodecHDI::ICodecComponent` | HDI v4_0 | OMX组件实例代理 |
| `CodecHDI::CodecCompCapability` | HDI v4_0 | 硬件Codec能力 |
| `HCodec` | hcodec.h | 硬件Codec基类 |
| `HDecoder` | hdecoder.h | 解码器子类 |
| `HEncoder` | hencoder.h | 编码器子类 |
| `HCodecList` | hcodec_list.h | 能力列表转换 |
| `GetManager()` | hcodec_list.cpp:82 | Manager工厂 |
| `GetCapList()` | hcodec_list.cpp:142 | 能力发现 |
