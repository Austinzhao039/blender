//
//  MonitorState.swift
//  环境监测 iOS 客户端
//
//  整个 App 就一个状态对象：设备 + 曲线 + 报警 + 时间窗。
//
//  ★ 故意不加 @MainActor：
//    给类标 @MainActor 后，init 就变成 MainActor 隔离的，而 `@StateObject var state = MonitorState()`
//    里的初始化表达式是在非隔离上下文里求值的，严格并发下会报
//    "call to main actor-isolated initializer in a synchronous nonisolated context"。
//    这里改成"网络请求随便哪个线程跑，写状态一律 await MainActor.run"：
//    既保证 @Published 在主线程更新（否则 Xcode 会刷紫色警告），也不挑编译器版本。
//

import Foundation
import SwiftUI

final class MonitorState: ObservableObject, @unchecked Sendable {

    @Published var device: DeviceInfo?
    @Published var samples: [Sample] = []
    @Published var alerts: [Alert] = []

    @Published var error: String?
    @Published var loading = false
    @Published var updatedAt: Date?

    @Published var window: TimeWindow = .m10

    private let api = Api()

    /// 设备 ID 以设置页为准
    var deviceId: String { Prefs.deviceId }

    /// 最新一条采样：优先用设备列表里的 latest，取不到退到曲线最后一条
    var latest: Sample? {
        device?.latest ?? samples.last
    }

    /// 最近 30 秒内有数据就算在线
    var online: Bool { device?.online() ?? false }

    func value(_ m: Metric) -> Double? {
        latest?.value(m)
    }

    // MARK: - 刷新

    private func fetchDevices() async -> [DeviceInfo]? { try? await api.devices() }

    private func fetchSamples(_ id: String, _ limit: Int) async -> [Sample]? {
        try? await api.telemetry(deviceId: id, limit: limit)
    }

    private func fetchAlerts() async -> [Alert]? { try? await api.alerts(limit: 40) }

    /// 三个请求并发发出去。某个失败只记 error，不清空已经拿到的数据
    /// —— 网络抖一下不该把整屏变空白。
    func refresh() async {
        let alreadyLoading = await MainActor.run { () -> Bool in
            if loading { return true }
            loading = true
            return false
        }
        if alreadyLoading { return }

        let devId = Prefs.deviceId
        let lim = await MainActor.run { window.limit() }

        async let devicesTask = fetchDevices()
        async let samplesTask = fetchSamples(devId, lim)
        async let alertsTask = fetchAlerts()

        let devList = await devicesTask
        let sampleList = await samplesTask
        let alertList = await alertsTask

        await MainActor.run {
            var firstError: String?

            if let devList {
                // 选中的设备不在列表里也照常显示（可能刚换过 id），只是状态给离线
                if let hit = devList.first(where: { $0.deviceId == devId }) {
                    device = hit
                } else {
                    device = devList.first
                }
            } else {
                firstError = "设备列表拉取失败"
            }

            if let sampleList {
                samples = sampleList
            } else if firstError == nil {
                firstError = "曲线数据拉取失败"
            }

            if let alertList {
                alerts = alertList
            }

            error = firstError
            if firstError == nil { updatedAt = Date() }
            loading = false
        }
    }

    func changeWindow(_ w: TimeWindow) async {
        let same = await MainActor.run { () -> Bool in
            if w == window { return true }
            window = w
            samples = []       // 先清掉，别让旧窗口的数据顶着新标题显示
            return false
        }
        if same { return }
        await refresh()
    }

    // MARK: - 下行指令

    func sendLed(r: Int, g: Int, b: Int, brightness: Int) async -> Result<String, Error> {
        do {
            let sent = try await api.led(deviceId: Prefs.deviceId, r: r, g: g, b: b, brightness: brightness)
            return .success(sent)
        } catch {
            return .failure(error)
        }
    }

    func sendSensor(enabled: Bool) async -> Result<String, Error> {
        do {
            let sent = try await api.sensor(deviceId: Prefs.deviceId, enabled: enabled)
            // 服务端会顺手把 config 改掉，本地也同步一份，省一次请求
            await MainActor.run {
                if let d = device {
                    device = d.with(config: d.config.with(sensorEnabled: enabled))
                }
            }
            return .success(sent)
        } catch {
            return .failure(error)
        }
    }

    func sendInterval(seconds: Int) async -> Result<String, Error> {
        do {
            let sent = try await api.interval(deviceId: Prefs.deviceId, seconds: seconds)
            await MainActor.run {
                if let d = device {
                    device = d.with(config: d.config.with(intervalSeconds: seconds))
                }
            }
            return .success(sent)
        } catch {
            return .failure(error)
        }
    }
}
