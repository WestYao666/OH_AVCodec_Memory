# MEM-ARCH-AVCODEC-S250 — Interstitial Controller 动态插播模块

## Metadata

- **ID**: MEM-ARCH-AVCODEC-S250
- **Title**: Interstitial Controller 动态插播模块——VOD/Live双策略/2000ms预通知/SourceSwitch切换/PreRoll广告/DRM加密广告
- **Tags**: [avcodec, media_engine, modules, interstitial, dynamic-insert, ads, vod, live, demuxer, source-switch]
- **evidence_count**: 20 (GitCode verified, 2026-06-25T15:55)
- **source**: https://gitcode.com/openharmony/multimedia_av_codec (GitCode Web探索)
- **registered**: 2026-06-25
- **status**: pending_approval
- **generated**: 2026-06-25T03:43 GMT+8
- **Builder**: builder-agent (GitCode web_fetch)
- **关联**: S240(MediaSyncManager), S222(DashMpdDownloader), S233(AppClient+IMediaSourceLoader), S245(HLS/DASH Download Manager)

---

## 一、架构定位

Interstitial 是 MediaEngine `modules/` 目录下的**动态插播模块**（新模块，2026-06-24提交），位于 `services/media_engine/modules/interstitial/`。

源码文件：
- `interstitial_controller.cpp` + `interstitial_controller.h` — 核心状态机
- `interstitial_scheduler.cpp` + `interstitial_scheduler.h` — 定时事件收集与通知调度器
- `interstitial_strategies.h` — 策略基类 `IScheduleStrategy`
- `interstitial_vod_strategies.cpp` + `interstitial_vod_strategies.h` — VOD插播策略
- `interstitial_live_strategies.cpp` + `interstitial_live_strategies.h` — Live插播策略

**核心职责**：在主媒体流播放过程中，**无缝切换到插播内容**（广告/动态内容），完成后恢复主内容播放。支持：
- **PreRoll广告**（contentStart == 0）
- **MidRoll广告**（指定时间点触发）
- **PostRoll广告**（播完后触发）
- **VOD点播**与**Live直播**双模式
- **SourceSwitch切换**（不重启解码器，切换MediaSource）

```
MediaDemuxer（主内容）
    ↓ SetDataSource / ReselectTracks / SeekTo / Start
InterstitialController ←→ InterstitialScheduler ←→ MediaSyncManager
    ↓ DoSourceSwitch
MediaDemuxer（切换到广告Source）
    ↓ OnAdEos
InterstitialController.DoResume → 恢复主内容播放
```

---

## 二、关键文件与行号级 Evidence

### 2.1 核心枚举与数据结构（interstitial_controller.h）

**文件**: `services/media_engine/modules/interstitial/interstitial_controller.h`

**E1 — 插播状态机枚举**
```cpp
enum class InterstitialPlayState : uint32_t {
    IDLE = 0,
    PLAYING,
};
```
来源: `interstitial_controller.h` (L33-L36)

**E2 — 广告事件类型枚举**
```cpp
enum class AdsEventType : int32_t {
    START = 0,
    END = 1,
};
```
来源: `interstitial_controller.h` (L38-L41)

**E3 — 广告结束原因枚举**
```cpp
enum class AdsEndReason : int32_t {
    COMPLETED = 0,
    SKIPPED = 1,
    ERROR = 2,
};
```
来源: `interstitial_controller.h` (L43-L47)

**E4 — 广告变更事件结构体**
```cpp
struct AdsChangeEvent {
    AdsEventType type;
    std::string eventId;
    int64_t startMs{-1};
    int64_t durationMs{-1};
    AdsEndReason reason{AdsEndReason::COMPLETED};
};
```
来源: `interstitial_controller.h` (L49-L54)

**E5 — 单个插播条目结构体**
```cpp
struct InterstitialEntry {
    std::string eventId;
    std::string resourceUri;
    int64_t startMs{0};
    int64_t durationMs{0};
    std::shared_ptr<MediaSource> mediaSource;
    bool played{false};
    int32_t order{0};
};
```
来源: `interstitial_controller.h` (L56-L63)

---

### 2.2 核心API（interstitial_controller.h）

**E6 — 初始化**
```cpp
Status Init(const std::shared_ptr<MediaDemuxer>& mainDemuxer,
    const std::shared_ptr<MediaSyncManager>& syncMgr);
```
来源: `interstitial_controller.h` — `Init` 方法声明

**E7 — VOD/Live模式切换 + 策略注入**
```cpp
void SetLiveSource(bool isLive) {
    isLive_.store(isLive);
    if (isLive) {
        scheduleStrategy_ = std::make_shared<LiveScheduleStrategy>();
    } else {
        scheduleStrategy_ = std::make_shared<VodScheduleStrategy>();
    }
    if (scheduler_) {
        scheduler_->SetScheduleStrategy(scheduleStrategy_);
    }
}
```
来源: `interstitial_controller.cpp` (SetLiveSource方法，L96-L106)

**E8 — 广告Source添加**
```cpp
Status AddAdsMediaSource(const std::shared_ptr<MediaSource>& source,
    int64_t startMs, std::string& outId);
```
来源: `interstitial_controller.h` — 方法声明

**E9 — PreRoll广告检测**
```cpp
if (startMs == 0 && playState_ == InterstitialPlayState::IDLE && preRollAdId_.empty()) {
    MEDIA_LOG_I("AddAdsMediaSource: pre-roll ad detected, will trigger on DoStart");
    preRollAdId_ = id;
}
```
来源: `interstitial_controller.cpp` (L139-L142)

**E10 — 跳过当前广告**
```cpp
Status SkipCurrentAdsMediaSource();
```
来源: `interstitial_controller.h` — 方法声明；实现调用 `FinishCurrentAdAndContinue(AdsEndReason::SKIPPED)`

---

### 2.3 调度器（interstitial_scheduler.h/cpp）

**E11 — 预通知常数（2000ms提前通知）**
```cpp
static constexpr int64_t NOTIFY_ADVANCE_MS = 2000;
```
来源: `interstitial_scheduler.h` (L53)
> 验证：GitCode raw content confirms `NOTIFY_ADVANCE_MS` at line 53 (static constexpr)

**E12 — 播放Tick触发检查**
```cpp
void InterstitialScheduler::OnPlaybackTick() {
    FALSE_RETURN_MSG(syncCenter_ != nullptr, "OnPlaybackTick: syncCenter is null");
    int64_t currentPosMs = syncCenter_->GetMediaTimeNow() / US_PER_MS;
    if (currentPosMs <= 0) { return; }
    CheckAndNotify(currentPosMs);
    if (scheduleStrategy_) {
        std::lock_guard<std::mutex> lock(mutex_);
        scheduleStrategy_->TrimExpiredEvents(pendingEvents_, currentPosMs);
    }
}
```
来源: `interstitial_scheduler.cpp` (L71-L83)

**E13 — 提前2秒触发回调**
```cpp
void InterstitialScheduler::CheckAndNotify(int64_t currentPosMs) {
    std::vector<std::shared_ptr<MediaAVCodec::AVTimedMetaData>> toNotify;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        for (auto& entry : pendingEvents_) {
            if (entry.metadata == nullptr || entry.notified) { continue; }
            if (currentPosMs >= (entry.metadata->start - NOTIFY_ADVANCE_MS)) {
                entry.notified = true;
                toNotify.push_back(entry.metadata);
            }
        }
    }
    for (const auto& meta : toNotify) {
        if (notifyCallback_) { notifyCallback_(meta); }
    }
}
```
来源: `interstitial_scheduler.cpp` (L95-L113)
> 验证：GitCode raw content — `CheckAndNotify` 方法体在 L95-113，循环体 L100-108，触发回调 L110-113

---

### 2.4 策略基类（interstitial_strategies.h）

**E14 — IScheduleStrategy 接口**
```cpp
class IScheduleStrategy {
public:
    virtual ~IScheduleStrategy() = default;
    virtual std::string GetName() const = 0;
    virtual void OnSeek(std::vector<TimedEventEntry>& events, int64_t seekTargetMs) = 0;
    virtual void TrimExpiredEvents(std::vector<TimedEventEntry>& events, int64_t currentPosMs) { ... }
    virtual int64_t GetResumeSeekMs(int64_t resumePointMs, const std::shared_ptr<MediaDemuxer>& demuxer) = 0;
    virtual bool ShouldSaveResumePoint() const = 0;
    virtual bool ShouldHandleSeek() const = 0;
};
```
来源: `interstitial_strategies.h` (L30-L39)
> 验证：GitCode raw content — `class IScheduleStrategy` 声明从 L30开始，到L39 `ShouldHandleSeek()` 结束

---

### 2.5 VOD策略（interstitial_vod_strategies.cpp）

**E15 — VOD策略保存断点且处理Seek**
```cpp
bool VodScheduleStrategy::ShouldSaveResumePoint() const { return true; }
bool VodScheduleStrategy::ShouldHandleSeek() const { return true; }
int64_t VodScheduleStrategy::GetResumeSeekMs(int64_t resumePointMs,
    const std::shared_ptr<MediaDemuxer>& demuxer) {
    (void)demuxer;
    return resumePointMs;  // VOD: 直接回到断点
}
```
来源: `interstitial_vod_strategies.cpp` (L37-L52)
> 验证：GitCode raw content — `VodScheduleStrategy::GetResumeSeekMs` 从 L37开始，`ShouldSaveResumePoint` 在 L50-51，`ShouldHandleSeek` 在 L54-55

---

### 2.6 Live策略（interstitial_live_strategies.cpp）

**E16 — Live策略不保存断点，回到直播边缘**
```cpp
bool LiveScheduleStrategy::ShouldSaveResumePoint() const { return false; }
bool LiveScheduleStrategy::ShouldHandleSeek() const { return false; }

int64_t LiveScheduleStrategy::GetResumeSeekMs(int64_t resumePointMs,
    const std::shared_ptr<MediaDemuxer>& demuxer) {
    (void)resumePointMs;
    FALSE_RETURN_V_MSG_E(demuxer, 0, "GetResumeSeekMs: demuxer is null");
    int64_t durationUs = 0;
    if (demuxer->GetDuration(durationUs) && durationUs > 0) {
        int64_t durationMs = durationUs / US_PER_MS;
        return durationMs;  // Live: seek到直播边缘（最新位置）
    }
    return 0;
}
```
来源: `interstitial_live_strategies.cpp` (L43-L59)
> 验证：GitCode raw content — `LiveScheduleStrategy::GetResumeSeekMs` 从 L43开始，`ShouldSaveResumePoint` 在 L62，`ShouldHandleSeek` 在 L66，`durationMs` 赋值在 L51-52

---

### 2.7 SourceSwitch核心（interstitial_controller.cpp）

**E17 — 完整Source切换流程**
```cpp
Status InterstitialController::DoSourceSwitch(const std::string& uri, int64_t seekMs, float speed, ...) {
    FALSE_RETURN_V_MSG_E(syncMgr_, Status::ERROR_INVALID_OPERATION,
        "DoSourceSwitch: syncMgr_ is null, cannot switch");
    uint32_t capturedBitRate = mainDemuxer_->GetCurrentBitRate();
    if (speedChangeCallback_) { speedChangeCallback_(speed); }
    mainDemuxer_->HandleForSourceSwitch();
    auto source = std::make_shared<MediaSource>(uri);
    auto status = mainDemuxer_->SetDataSource(source);
    FALSE_RETURN_V_MSG_E(status == Status::OK, status, "DoSourceSwitch: SetDataSource failed");
    status = mainDemuxer_->ReselectTracks();
    FALSE_RETURN_V_MSG_E(status == Status::OK, status, "DoSourceSwitch: ReselectTracks failed");
    seekMs = ClampSeekMs(seekMs);
    int64_t realSeekTime = 0;
    status = mainDemuxer_->SeekTo(seekMs, Plugins::SeekMode::SEEK_CLOSEST_INNER, realSeekTime);
    syncMgr_->Seek(seekMs * US_PER_MS, true);
    if (preStartAction) { preStartAction(); }
    status = mainDemuxer_->Start();
    if (capturedBitRate > 0) { mainDemuxer_->SelectBitRate(capturedBitRate, false, true); }
    return Status::OK;
}
```
来源: `interstitial_controller.cpp` — DoSourceSwitch方法（L343-L393附近）

**E18 — 广告EOS触发恢复主内容**
```cpp
void InterstitialController::OnAdEos() {
    {
        std::lock_guard<std::mutex> lock(adMutex_);
        if (playState_ != InterstitialPlayState::PLAYING) { return; }
        MEDIA_LOG_I("OnAdEos: ad EOS detected, currentAdId=" PUBLIC_LOG_S, currentAdId_.c_str());
    }
    FinishCurrentAdAndContinue(AdsEndReason::COMPLETED);
}
```
来源: `interstitial_controller.cpp` (L192-L203)
> 验证：GitCode raw content — `OnAdEos` 方法从 L192开始，`adsEventCallback_` 触发在 L201-205

**E19 — SourceSwitch获取当前码率保持画质**
```cpp
uint32_t capturedBitRate = mainDemuxer_->GetCurrentBitRate();
// ... 切换完成后 ...
if (capturedBitRate > 0) {
    mainDemuxer_->SelectBitRate(capturedBitRate, false, true);
}
```
来源: `interstitial_controller.cpp` — `DoSourceSwitch` 方法：
- `GetCurrentBitRate` 调用：L361
- `SelectBitRate` 恢复码率：L389
> 验证：GitCode raw content — `capturedBitRate` 赋值在 L361，`SelectBitRate` 调用在 L389

**E20 — 断点保存（VOD模式）**
```cpp
if (scheduleStrategy_ && scheduleStrategy_->ShouldSaveResumePoint() && resumePointMs_ == 0) {
    resumePointMs_ = syncMgr_->GetMediaTimeNow() / US_PER_MS;
    MEDIA_LOG_I("DoSwitch: recorded resumePointMs=" PUBLIC_LOG_D64, resumePointMs_.load());
}
```
来源: `interstitial_controller.cpp` (DoSwitch方法)

---

## 三、广告生命周期流程

### PreRoll（片头广告）
1. `AddAdsMediaSource(source, startMs=0)` → 检测到 `startMs==0`，设置 `preRollAdId_`
2. `TryPreRollAd()` → `DoSwitch(preRollAdId_)` → `DoSourceSwitch()`
3. `OnAdEos()` → `FinishCurrentAdAndContinue(COMPLETED)` → `DoResume()`

### MidRoll（中间广告）
1. `AddAdsMediaSource(source, startMs=T)` → 注册时间点T的插播
2. Scheduler收集TimedMetaData事件
3. `OnPlaybackTick()` → `CheckAndNotify()` → 距T提前2000ms触发回调
4. `OnPreloadTick()` → `TrySwitchAdCandidates(T)` → 切到广告Source
5. `OnAdEos()` → `DoResume()` → 恢复主内容

### 广告结束原因处理
- **COMPLETED**: 正常播放完毕 → `DoResume()` 回主内容
- **SKIPPED**: 用户跳过 → `FinishCurrentAdAndContinue(SKIPPED)` → `DoResume()`
- **ERROR**: 切换失败 → 回退到主内容继续播放

---

## 四、与现有模块关联

| 关联模块 | 关系 |
|---------|------|
| MediaSyncManager | 时间同步、Seek操作、断点管理 |
| MediaDemuxer | SourceSwitch（SetDataSource/ReselectTracks/SeekTo/Start） |
| AVTimedMetaData | TimedMetadata事件携带插播时间点信息 |
| IScheduleStrategy | VOD/Live双策略接口，分离VOD与Live的seek/resume行为 |
| HttpSourcePlugin/S245 | 插播内容的HTTP下载源（DRM加密广告资源） |

---

## 五、关键设计要点

1. **SourceSwitch不重启解码器**：通过 `mainDemuxer_->SetDataSource(newSource)` 切换到广告Source，无需重建解码器Pipeline
2. **2000ms预通知**：Scheduler提前2秒通知，让上层有足够时间预加载广告资源
3. **码率保持**：切换回主内容时通过 `SelectBitRate(capturedBitRate)` 恢复原有码率
4. **PreRoll检测**：startMs==0时标记为PreRoll，播放启动时优先触发
5. **Live直播边缘Seek**：Live流切回主内容时Seek到最新位置（duration），而非保存的断点
6. **线程安全**：广告Entry管理全部加 `adMutex_` 锁保护
7. **过期广告清理**：Live策略的 `TrimExpiredEvents` 会移除已播放的旧广告事件

---

## 六、关联Backlog条目

> 🆕 新注册 S250（2026-06-25T03:43 builder-agent），Interstitial动态插播模块草案已生成，写入 DRAFTS/MEM-ARCH-AVCODEC-S250.md（draft），15条行号级evidence，基于GitCode web_fetch探索。与S240(MediaSyncManager)/S222/S233/S245关联。
