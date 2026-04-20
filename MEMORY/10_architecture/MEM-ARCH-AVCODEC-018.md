---
id: MEM-ARCH-AVCODEC-018
title: 硬件编解码器 HDI 架构——IPC vs Passthrough 双模式与 CodecComponentManager 工厂
type: architecture_fact
scope: [AVCodec, HardwareCodec, HDI, IPC, Passthrough, CodecComponentManager]
status: approved
confidence: high
created_at: "2026-04-20T21:00:00+08:00"
approved_at: "2026-04-21T02:05:00+08:00"
author: builder-agent
related_scenes: [新需求开发, 问题定位, 硬件/软件Codec区分, 安全视频路径]
service_scenario: 新需求开发 / 问题定位 / 安全视频
summary: >
  AVCodec 的硬件编解码器（HCodec）通过 HDI V4_0 接口（OHOS::HDI::Codec::V4_0）访问底层硬件 Codec 驱动。
  访问路径分为 IPC 和 Passthrough 两种模式：
  (1) IPC 模式（g_compMgrIpc）：Codec 硬件运行在独立进程，通过 IPC stub 代理访问；
  (2) Passthrough 模式（g_compMgrPassthru）：直接访问 Codec 硬件驱动，省去 IPC 开销。
  模式选择由 DecideMode() 决定，依据：系统参数 hcodec.usePassthrough、是否为安全Codec、硬件是否支持 Passthrough。
  ICodecComponentManager::Get(isPassthrough) 是组件管理器工厂，按名称加载具体 Codec 组件。
  安全 Codec（isSecure）通过名称后缀 ".secure" 判断。
why_it_matters:
 - 问题定位：IPC vs Passthrough 路径不同——Passthrough 绕过了 codec_service 进程，崩溃现场和日志归属不同
 - 新需求开发：理解 GetManager(isPassthrough) 的模式选择逻辑，才能判断硬件 Codec 是独立进程还是直连驱动
 - 安全视频路径：DRM 解密（HVCodec）和硬件解码（HVCodec + IsSecureMode）都依赖 HDI 直连路径
 - 性能分析：Passthrough 模式比 IPC 模式少一次进程间数据拷贝，适合低延迟场景

---

## 1. HDI 接口定义

**证据**：`services/engine/codec/video/hcodec/codec_hdi.h:25-29`

```cpp
#include "v4_0/codec_types.h"
#include "v4_0/icodec_callback.h"
#include "v4_0/icodec_component.h"
#include "v4_0/icodec_component_manager.h"

namespace CodecHDI = OHOS::HDI::Codec::V4_0;
```

所有 HDI 层的类型（`CodecCommandType`、`CodecEventType`、`OmxCodecBuffer`、`ICodecComponentManager` 等）均来自 `v4_0` 命名空间。

---

## 2. 双组件管理器：IPC vs Passthrough

**证据**：`services/engine/codec/video/hcodec/hcodec_list.cpp:36-37`

```cpp
static sptr<ICodecComponentManager> g_compMgrIpc;      // IPC 模式（独立进程）
static sptr<ICodecComponentManager> g_compMgrPassthru; // Passthrough 模式（直连驱动）
```

两个静态单例管理器分别对应两种访问模式：
- `g_compMgrIpc`：Codec 硬件运行在 `codec_service` 独立进程，AVCodec 服务通过 HDI IPC stub 与其通信
- `g_compMgrPassthru`：AVCodec 服务直接与硬件驱动交互，无 IPC 中转

---

## 3. 模式选择：DecideMode()

**证据**：`services/engine/codec/video/hcodec/hcodec_list.cpp:56-79`

```cpp
static bool DecideMode(bool supportPassthrough, bool isSecure)
{
#ifdef BUILD_ENG_VERSION
    string mode = OHOS::system::GetParameter("hcodec.usePassthrough", "");
    if (mode == "1") {
        LOGI("force passthrough"); return true;
    } else if (mode == "0") {
        LOGI("force ipc"); return false;
    } else if (mode == "-1") {
        if (isSecure) {
            return supportPassthrough;  // 安全Codec：跟随硬件能力
        } else {
            bool passthrough = (g_cnt++ % 3 == 0); // 轮询切换（仅eng版本）
            return passthrough;
        }
    }
#endif
    return supportPassthrough; // 非eng版本：严格跟随硬件能力
}
```

**关键逻辑**：
- `hcodec.usePassthrough=1`：强制 Passthrough
- `hcodec.usePassthrough=0`：强制 IPC
- `hcodec.usePassthrough=-1`：开发调试模式，安全 Codec 走硬件支持路径，非安全 Codec 轮询切换
- 无参数（非 eng 版本）：严格按 `supportPassthrough` 硬件标志决定

---

## 4. 组件管理器工厂：GetManager()

**证据**：`services/engine/codec/video/hcodec/hcodec_list.cpp:82-97`

```cpp
sptr<ICodecComponentManager> GetManager(bool getCap, bool supportPassthrough, bool isSecure)
{
    bool isPassthrough = getCap ? true : DecideMode(supportPassthrough, isSecure);
    sptr<ICodecComponentManager>& mng = (isPassthrough ? g_compMgrPassthru : g_compMgrIpc);
    // ...
    if (!isPassthrough) {
        // IPC 模式走 HDI 服务管理器（servicemanager）
        mng = ICodecComponentManager::Get(false);  // isPassthrough=false
    } else {
        // Passthrough 模式直连驱动
        mng = ICodecComponentManager::Get(true);  // isPassthrough=true
    }
}
```

- `getCap=true`（查询能力）：强制 Passthrough 模式以直接枚举驱动能力
- `getCap=false`（运行时使用）：DecideMode() 决定，走对应单例

---

## 5. 安全 Codec 识别

**证据**：`services/engine/codec/video/hcodec/hcodec_utils.h:33+`

```cpp
inline bool IsSecureMode(const std::string &name)
{
    std::string prefix = ".secure";
    if (name.length() <= prefix.length()) return false;
    // ...
}
```

安全 Codec 的名称以 `.secure` 后缀结尾。例如 `OMX.rk.h264Decoder.secure`。

**使用位置**：
- `services/engine/codec/video/hcodec/hcodec.cpp:426`：`isSecure_ = IsSecureMode(caps_.compName);`
- `services/engine/codec/video/hcodec/hcodec_list.cpp:191`：`userCap.isSecure = IsSecureMode(hdiCap.compName);`

---

## 6. HDI 能力转换：HdiCapToUserCap()

**证据**：`services/engine/codec/video/hcodec/hcodec_list.cpp:184-229`

`HCodecList::HdiCapToUserCap()` 将 HDI 层返回的 `CodecCompCapability` 转换为用户态 `CapabilityData`：

```cpp
CapabilityData HCodecList::HdiCapToUserCap(const CodecCompCapability &hdiCap)
{
    userCap.codecName = hdiCap.compName;              // OMX.rk.h264Decoder 等
    userCap.isSecure = IsSecureMode(hdiCap.compName); // 通过名称判断安全Codec
    userCap.codecType = TypeConverter::HdiCodecTypeToInnerCodecType(hdiCap.type);
    userCap.mimeType = TypeConverter::HdiRoleToMime(hdiCap.role); // VIDEO/AVC → "video/avc"
    userCap.maxInstance = hdiCap.maxInst;              // 最大实例数
    userCap.bitrate = {hdiCap.bitRate.min, hdiCap.bitRate.max};
    userCap.width = {hdiVideoCap.minSize.width, hdiVideoCap.maxSize.width};
    // ...
    LOGI("isSupportPassthrough: %d", FindFeature(hdiVideoCap.features, VIDEO_FEATURE_PASS_THROUGH).support);
}
```

关键转换点：
- `codecName`（OMX组件名）→ HDI组件名
- `isSecure`（.secure后缀判断）
- `role`（MEDIA_ROLETYPE_VIDEO_AVC）→ MIME类型（"video/avc"）
- `VIDEO_FEATURE_PASS_THROUGH` → `supportPassthrough` 标志

---

## 7. 服务存活监控

**证据**：`services/engine/codec/video/hcodec/hcodec_list.cpp:44-53`

```cpp
class Listener : public ServStatListenerStub {
public:
    void OnReceive(const ServiceStatus &status) override
    {
        if (status.serviceName == "codec_component_manager_service" && status.status == SERVIE_STATUS_STOP) {
            LOGW("codec_component_manager_service died");
            lock_guard<mutex> lk(g_mtx);
            g_compMgrIpc = nullptr; // IPC manager 断连后置空
        }
    }
};
```

当 `codec_component_manager_service` 异常退出时，`g_compMgrIpc` 被置空，后续调用会触发重新初始化。

---

## 8. 整体调用链

```
应用层（Native AVBuffer）
  → CodecBase::Configure() [hcodec.cpp]
      → HCodecList::GetManager(isPassthrough) [hcodec_list.cpp:82]
          → DecideMode(supportPassthrough, isSecure) [hcodec_list.cpp:56]
              → ICodecComponentManager::Get(isPassthrough) [HDI V4_0]
                  → IPC: codec_service 进程（HDI stub）
                  → Passthrough: 直接 /dev/hwcodec 驱动
      → IsSecureMode(compName) [hcodec_utils.h:33]
          → compName.endswith(".secure") → 安全Codec
```

---

## 相关条目

- MEM-ARCH-AVCODEC-009：硬件 vs 软件 Codec 区分（codecIsVendor / 切换机制）
- MEM-ARCH-AVCODEC-014：Codec Engine 架构（CodecBase + Loader + Factory 三层插件）
- MEM-ARCH-AVCODEC-017：DRM CENC 解密流程（SVP 安全视频路径）

---

## 变更记录

| 日期 | 操作 | 说明 |
|------|------|------|
| 2026-04-20 | 新建草案 | builder-agent 从 hcodec_list.cpp/hcodec_utils.h 提取 HDI IPC/Passthrough 架构 |
