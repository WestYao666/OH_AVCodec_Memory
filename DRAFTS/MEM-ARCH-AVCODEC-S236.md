# MEM-ARCH-AVCODEC-S236: HCodec DFX Module — FuncTracker/HiSysEvent/BufferOwnerTracing

## Topic
HCodec DFX Module — FuncTracker + HiSysEvent + BufferOwner Tracing

## Scope
AVCodec, HardwareCodec, HCodec, DFX, HiSysEvent, HiTrace, BufferOwner, FuncTracker, BufferDump, BufferOwnerTrace

## Source Files
- services/engine/codec/video/hcodec/hcodec_dfx.cpp (513行)
- services/engine/codec/video/hcodec/hcodec_dfx.h (34行)
- services/engine/codec/video/hcodec/hcodec.cpp (1615行, DFX集成点)
- services/engine/codec/video/hcodec/hcodec_state.cpp (1083行)
- services/engine/codec/video/hcodec/hcodec.h (DFX数据结构定义)

## Evidence (E1-E20)

### E1: FUNC_TRACKER() RAII 追踪器 (hcodec_dfx.h L25-27)
```cpp
#define FUNC_TRACKER() FuncTracker tracker("[" + compUniqueStr_ + " " + __func__ + "]")
```
FuncTracker 栈对象在构造时打印 `>>`，析构时打印 `<<`，自动追踪函数入口/出口。与 SCOPED_TRACE() 宏配合使用。

### E2: SCOPED_TRACE_FMT 格式化追踪 (hcodec_dfx.h L19-22)
```cpp
#define SCOPED_TRACE_FMT(fmt, ...) \
    HITRACE_METER_FMT(HITRACE_TAG_ZMEDIA, "[hcodec][%s]%s " fmt, \
        compUniqueStr_.c_str(), __func__, ##__VA_ARGS__)
```
HITRACE_TAG_ZMEDIA 域，compUniqueStr_ 为组件唯一标识，格式化参数输出。

### E3: FuncTracker 构造函数入口日志 (hcodec_dfx.cpp L27-31)
```cpp
FuncTracker::FuncTracker(std::string value) : value_(std::move(value))
{
    PLOGI("%s >>", value_.c_str());
}
```
PLOGI 在函数进入时打印 `>>` 后缀。

### E4: FuncTracker 析构函数出口日志 (hcodec_dfx.cpp L32-36)
```cpp
FuncTracker::~FuncTracker()
{
    PLOGI("%s <<", value_.c_str());
}
```
析构时打印 `<<` 后缀，配合 RAII 自动追踪函数生命周期。

### E5: HiSysEvent FAULT 上报 (hcodec_dfx.cpp L125-130)
```cpp
void HCodec::FaultEventWrite(const string& faultType, const std::string& msg)
{
    HiSysEventWrite(HISYSEVENT_DOMAIN_HCODEC, "FAULT",
        OHOS::HiviewDFX::HiSysEvent::EventType::FAULT,
        "MODULE", "HardwareDecoder",
        "FAULTTYPE", faultType,
        "MSG", msg);
}
```
DOMAIN_HCODEC，FAULT 类型，MODULE=HardwareDecoder，FAULTTYPE 自定义故障类型。

### E6: BufferOwner 四方持有者枚举 (hcodec.h L115)
```cpp
enum BufferOwner {
    OWNED_BY_US = 0,      // HCodec自身持有
    OWNED_BY_USER, // 应用侧持有
    OWNED_BY_OMX,         // OMX硬件组件持有
    OWNED_BY_SURFACE,     // Surface持有
    OWNER_CNT
};
```
四方持有者：US/USER/OMX/SURFACE，用于 ChangeOwner 追踪。

### E7: Record 数据结构 (hcodec.h L153-189)
```cpp
struct Record {
    std::array<int, OWNER_CNT> currOwner_{};           // 各持有方当前buffer数量
    std::array<std::optional<TimePoint>, OWNER_CNT> lastOwnerChangeTime_{}; // 各方最近轮转时间
    std::array<TotalEvent, OWNER_CNT> holdTimeInterval_; // 持有时长（eventSum/eventCnt）
    std::array<TotalEvent, OWNER_CNT> holdCntInterval_; // 持有数量×时长
    uint64_t frameCntTotal_ = 0;
    uint64_t frameCntInterval_ = 0;
    uint64_t frameMbitsInterval_ = 0;
    int64_t lastPts_ = 0;
    std::optional<TimePoint> beginOfInterval_;
    std::array<uint64_t, OWNER_CNT> ownerTraceTag_{};
};
```
Record 双数组结构：currOwner_实时持有数 / holdTimeInterval_ 持有时长统计。

### E8: TotalEvent 累加统计结构 (hcodec.h L141-145)
```cpp
struct TotalEvent {
    uint64_t eventCnt = 0; // 事件次数
    uint64_t eventSum = 0;  // 事件值累加（时长×持有数）
};
```
eventSum / eventCnt = 平均持有时长或持有数。

### E9: ChangeOwner 持有者切换核心 (hcodec_dfx.cpp L158-205)
```cpp
TimePoint HCodec::ChangeOwner(BufferInfo& info, BufferOwner newOwner)
{
    auto now = chrono::steady_clock::now();
    // UpdateHoldCnt + UpdateHoldTime 累加统计
    currOwner_[oldOwner]--; currOwner_[newOwner]++;
    info.owner = newOwner; info.lastOwnerChangeTime = now;
    // frameCntTotal_计数 / mbits 计算
    if (info.isInput && oldOwner == OWNED_BY_US && newOwner == OWNED_BY_OMX) {
        record.frameCntTotal_++; record.frameMbitsInterval_ += ...;
    }
    CountTrace(HITRACE_TAG_ZMEDIA, record.ownerTraceTag_[newOwner], currOwner_[newOwner]);
    return now;
}
```
ChangeOwner 是 BufferOwner 追踪的核心入口，同时更新帧计数和码率统计。

### E10: UpdateHoldCnt 持有数量×时长统计 (hcodec_dfx.cpp L207-225)
```cpp
void HCodec::UpdateHoldCnt(const TimePoint& now, OMX_DIRTYPE port, BufferOwner owner)
{
    auto holdUs = chrono::duration_cast<chrono::microseconds>(
        now - record.lastOwnerChangeTime_[owner].value()).count();
    TotalEvent& holdCnt = record.holdCntInterval_[owner];
    holdCnt.eventCnt += static_cast<uint64_t>(holdUs);
    holdCnt.eventSum += (static_cast<uint64_t>(holdUs) *
                         static_cast<uint64_t>(record.currOwner_[owner]));
}
```
`eventSum += holdUs × currOwner_[owner]`，计算"某持有方持有buffer数量×时长"的累加值。

### E11: UpdateHoldTime 持有时长统计 (hcodec_dfx.cpp L227-248)
```cpp
void HCodec::UpdateHoldTime(const TimePoint& now, const BufferInfo& info, BufferOwner newOwner)
{
    auto holdUs = chrono::duration_cast<chrono::microseconds>(
        now - info.lastOwnerChangeTime).count();
    TotalEvent& oldOwnerHoldTime = record.holdTimeInterval_[oldOwner];
    oldOwnerHoldTime.eventCnt++; // 持有次数+1
    oldOwnerHoldTime.eventSum += static_cast<uint64_t>(holdUs); // 持有时长累加
}
```
每次切换时 oldOwner 的 eventCnt++ / eventSum += holdUs。

### E12: CalculateInterval 区间平均计算 (hcodec_dfx.cpp L250-280)
```cpp
bool HCodec::CalculateInterval(const TimePoint& now, OMX_DIRTYPE port, IntervalAverage& ave)
{
    ave.fps = record.frameCntInterval_ * US_TO_S / fromBeginOfIntervalToNowUs;
    ave.mbps = record.frameMbitsInterval_ * US_TO_S / fromBeginOfIntervalToNowUs;
    for (owner) {
        ave.holdCnt[owner] = holdCnt.eventSum / holdCnt.eventCnt; // 持有数量
        ave.holdMs[owner] = holdTime.eventSum / US_TO_MS / holdTime.eventCnt; // 持有时长ms
    }
}
```
IntervalAverage 包含 fps/mbps/各持有方平均持有数/平均持有时长。

### E13: OnPrintAllBufferOwner 循环停止检测 (hcodec_dfx.cpp L37-53)
```cpp
void HCodec::OnPrintAllBufferOwner(const MsgInfo& msg)
{
    msg.param->GetValue(KEY_LAST_OWNER_CHANGE_TIME, lastOwnerChangeTime);
    if (lastOwnerChangeTime == lastOwnerChangeTime_) {
        if (!circulateHasStopped_) {
            HLOGW("buffer circulate stoped"); PrintAllBufferInfo();
            circulateHasStopped_ = true;
        }
    }
    SendAsyncMsg(MsgWhat::PRINT_ALL_BUFFER_OWNER, param, THREE_SECONDS_IN_US);
}
```
若 lastOwnerChangeTime 不变（时间静止），判定 buffer 循环停止，打印警告。

### E14: PrintAllBufferInfo 输入/输出缓冲池快照 (hcodec_dfx.cpp L54-73)
```cpp
void HCodec::PrintAllBufferInfo(const TimePoint& now, OMX_DIRTYPE port)
{
    const char* inOutStr = (port == OMX_DirInput) ? " in" : "out";
    for (const BufferInfo& info : pool) {
        int64_t holdMs = chrono::duration_cast<chrono::milliseconds>(
            now - info.lastOwnerChangeTime).count();
        s << info.bufferId << ":" << ToString(info.owner) << "(" << holdMs << "), ";
    }
    HLOGI("%s: eos=%d, etb=%" PRIu64 ", %d/%d/%d/%d, %s", ...);
}
```
`%d/%d/%d/%d`打印 OWNED_BY_US / OWNED_BY_USER / OWNED_BY_OMX / OWNED_BY_SURFACE 四方持有数。

### E15: OnGetHidumperInfo HiDumper导出信息 (hcodec_dfx.cpp L75-109)
```cpp
std::string HCodec::OnGetHidumperInfo()
{
    s << "[" << compUniqueStr_ << "][" << currState_->GetName() << "]" << endl;
    s << "eos:" << inputPortEos_ << ", etb:" << record_[OMX_DirInput].frameCntTotal_ << endl;
    s << "inBufId = " << info.bufferId << ", owner = " << ToString(info.owner);
    s << ", holdMs = " << holdMs << endl;
}
```
HiDumper 信息导出，包含状态/帧计数/各buffer持有者/hold时间。

### E16: SCOPED_TRACE() 在 hcodec.cpp 的集成 (hcodec.cpp L194/L221/L229/L236/L243/L254)
```cpp
SCOPED_TRACE();  // 出现在所有主要入口函数：Init/Start/Stop/Flush/Release等
FUNC_TRACKER();  // 在关键路径（Start L222/Stop L230）额外使用
```
hcodec.cpp 所有主要函数均使用 SCOPED_TRACE()，关键路径额外使用 FUNC_TRACKER()。

### E17: SCOPED_TRACE_FMT 带缓冲区ID的精细化追踪 (hcodec.cpp L1003/L1012/L1085/L1177)
```cpp
SCOPED_TRACE_FMT("id: %u", info.bufferId);       // L1003
SCOPED_TRACE_FMT("id: %u, pts: %" PRId64, info.bufferId, info.omxBuffer->pts); // L1085
```
关键 Buffer 操作用 SCOPED_TRACE_FMT 携带 bufferId + pts 信息，便于精确定位。

### E18: BufferInfo::DumpSurfaceBuffer YUV/RGBA 转储 (hcodec_dfx.cpp L404-447)
```cpp
void HCodec::BufferInfo::DumpSurfaceBuffer(const std::string& prefix, uint64_t cnt) const
{
    int w = surfaceBuffer->GetWidth(); int h = surfaceBuffer->GetHeight();
    int byteStride = surfaceBuffer->GetStride();
    // YUV420: suffix="yuv", alignedH = planes[1].offset / byteStride
    // RGBA: suffix="rgba", totalSize = byteStride * h
    sprintf_s(name, "%s/%s_%dx%d..._%s.yuv", DUMP_PATH, prefix.c_str(), ...);
    ofs.write(va, totalSize);
}
```
BUILD_ENG_VERSION 保护，按 PixelFormat 选择 YUV420/RGBA/other 三种转储格式，文件名含 w×h/stride/pts。

### E19: DecideDumpInfo YUV420 对齐高度计算 (hcodec_dfx.cpp L448-465)
```cpp
void HCodec::BufferInfo::DecideDumpInfo(...) const
{
    case GRAPHIC_PIXEL_FMT_YCBCR_420_P:
    case GRAPHIC_PIXEL_FMT_YCRCB_420_SP:
    case GRAPHIC_PIXEL_FMT_YCBCR_420_SP:
    case GRAPHIC_PIXEL_FMT_YCBCR_P010:
    case GRAPHIC_PIXEL_FMT_YCRCB_P010: {
        alignedH = static_cast<int32_t>(static_cast<int64_t>(planes->planes[1].offset) / byteStride);
        totalSize = GetYuv420Size(byteStride, alignedH);
        suffix = "yuv"; break;
    }
}
```
通过 planes[1].offset 计算 YUV420 的实际对齐高度，CbCr 平面偏移/stride。

### E20: PrintAllCaller 全局实例统计 (hcodec.cpp L1270-1285)
```cpp
void HCodec::PrintAllCaller()
{
    for (const auto& [app, vec] : g_decCallers) {
        LOGI("[pid %d][%s] hold %zu decoders", app.pid, app.processName.c_str(), vec.size());
    }
}
```
g_decCallers 全局 map追踪所有实例，按 pid/processName 分组，用于监控活跃解码器数量。

## Summary

S236 探索 HCodec DFX 模块（hcodec_dfx.cpp 513行 + hcodec_dfx.h 34行），生成 20 条行号级 evidence。

核心发现：
1. **FUNC_TRACKER() RAII 追踪器**：构造 `>>` / 析构 `<<`，配合 SCOPED_TRACE() 宏，在 hcodec.cpp 关键路径（Init/Start/Stop/Flush/Release）全面部署
2. **HiSysEvent FAULT 上报**：FaultEventWrite(HISYSEVENT_DOMAIN_HCODEC, "FAULT")，MODULE=HardwareDecoder
3. **BufferOwner 四方持有者追踪**：OWNED_BY_US/USER/OMX/SURFACE，ChangeOwner() 切换时触发 UpdateHoldCnt/UpdateHoldTime 累加
4. **TotalEvent 累加统计**：eventCnt事件次数 + eventSum 时长×数量，用于计算平均持有时长/平均持有数
5. **IntervalAverage区间统计**：fps + mbps + 四方平均持有时长ms，通过 CalculateInterval()周期性计算
6. **Buffer循环停止检测**：lastOwnerChangeTime 不变则判定 circulateHasStopped_，触发 PrintAllBufferInfo
7. **YUV420/RGBA 转储**：BUILD_ENG_VERSION 保护，planes[1].offset/stride 计算对齐高度
8. **PrintAllCaller 全局实例追踪**：g_decCallers 全局 map，按 pid/processName 分组统计活跃解码器数量

## Associations
S57 (HDecoder/HEncoder OMX 组件架构) / S160 (HDecoder/HEncoder 后台管理 FreezeBuffers/DMA-BUF Swap) / S82/S200/S213 (AVCodec DFX 通用框架)

## Status
draft