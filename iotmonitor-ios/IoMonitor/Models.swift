//
//  Models.swift
//  环境监测 iOS 客户端
//
//  字段照抄 https://iot.austin666.top 的真实返回（esp32/server/app/routers/telemetry.py）：
//    GET /api/devices                -> { devices: [ {device_id, display, last_seen, samples, latest, config} ] }
//    GET /api/devices/{id}/telemetry -> { items: [ {ts, temperature, humidity, light, soil} ] }
//    GET /api/alerts                 -> { items: [ {ts, type, message} ] }
//  数值可能是 null（老固件只发 T/H 时 L/S 存 NULL），所以全部用 Double? 接。
//

import Foundation

// MARK: - JSON 取值helper

/// JSONSerialization 出来的数字是 NSNumber；null 是 NSNull。
/// 统一走这一层，避免每处都写 `as? Double` 然后被 NSNumber 坑。
///
/// 这里不显式判 NSNull：它不是 NSNumber 也不是 String，落到最后 return nil 正好。
/// （这么写还有个好处：Foundation 在非 Darwin 平台上没有 NSNull，代码能直接编译）
func jnum(_ any: Any?) -> Double? {
    guard let any else { return nil }          // 键根本不存在
    if let d = any as? Double { return d }
    if let n = any as? NSNumber { return n.doubleValue }
    if let s = any as? String { return Double(s) }
    return nil
}

func jint(_ any: Any?) -> Int? {
    guard let d = jnum(any) else { return nil }
    return Int(d)
}

func jstr(_ any: Any?) -> String {
    if let s = any as? String { return s }
    if let n = any as? NSNumber { return n.stringValue }
    if any is NSNull { return "" }
    return ""
}

func jbool(_ any: Any?) -> Bool? {
    if let b = any as? Bool { return b }
    if let n = any as? NSNumber { return n.intValue != 0 }
    return nil
}

// MARK: - 一条采样

struct Sample: Identifiable {
    /// 服务端 ts 是 Unix 秒（浮点）
    let ts: Double
    let temperature: Double?
    let humidity: Double?
    let light: Double?
    let soil: Double?

    var id: Double { ts }
    var date: Date { Date(timeIntervalSince1970: ts) }

    func value(_ m: Metric) -> Double? {
        switch m {
        case .temp:  return temperature
        case .humi:  return humidity
        case .light: return light
        case .soil:  return soil
        }
    }

    static func parse(_ o: [String: Any]) -> Sample {
        Sample(
            ts: jnum(o["ts"]) ?? 0,
            temperature: jnum(o["temperature"]),
            humidity: jnum(o["humidity"]),
            light: jnum(o["light"]),
            soil: jnum(o["soil"])
        )
    }
}

// MARK: - 四路指标

/// 四路数据统一成枚举：卡片标题、单位、小数位、图表颜色都从这里取，
/// 免得四张卡片写四遍几乎一样的代码。
///
/// 小数位是 0 —— 用户明确要求面板和板子上都不显示小数点，App 跟网页保持一致。
enum Metric: String, CaseIterable, Identifiable {
    case temp, humi, light, soil

    var id: String { rawValue }

    var label: String {
        switch self {
        case .temp:  return "温度"
        case .humi:  return "湿度"
        case .light: return "光照"
        case .soil:  return "土壤"
        }
    }

    var unit: String {
        switch self {
        case .temp:  return "℃"
        case .humi, .soil: return "%"
        case .light: return ""
        }
    }

    var decimals: Int { 0 }

    /// 没有数据时显示破折号，别显示 0 —— 0 会被误当成"真的读到 0"。
    /// （光照本来就是 0，这种时候只有 updatedAt / 在线状态能说明问题）
    func format(_ v: Double?) -> String {
        guard let v else { return "—" }
        return String(format: "%.\(decimals)f", v)
    }
}

// MARK: - 设备

struct DeviceConfig {
    var intervalSeconds: Int = 5
    var sensorEnabled: Bool = true
    var tempMax: Double?
    var tempMin: Double?
    var humiMax: Double?
    var humiMin: Double?
    var soilMin: Double?

    static func parse(_ o: [String: Any]?) -> DeviceConfig {
        let o = o ?? [:]
        return DeviceConfig(
            intervalSeconds: jint(o["interval_seconds"]) ?? 5,
            sensorEnabled: (jint(o["sensor_enabled"]) ?? 1) != 0,
            tempMax: jnum(o["temp_max"]),
            tempMin: jnum(o["temp_min"]),
            humiMax: jnum(o["humi_max"]),
            humiMin: jnum(o["humi_min"]),
            soilMin: jnum(o["soil_min"])
        )
    }

    /// 改单个字段要重建整个结构，写个 with 省得到处抄 7 个参数
    func with(sensorEnabled v: Bool) -> DeviceConfig {
        var c = self
        c.sensorEnabled = v
        return c
    }

    func with(intervalSeconds v: Int) -> DeviceConfig {
        var c = self
        c.intervalSeconds = v
        return c
    }
}

struct DeviceInfo: Identifiable {
    let deviceId: String
    let display: String
    let lastSeen: Double
    let samples: Int
    let latest: Sample?
    let config: DeviceConfig

    var id: String { deviceId }

    /// 板子每 5 秒一条；超过 30 秒没数据就当离线（跟网页面板的判据一致）
    func online(now: Double = Date().timeIntervalSince1970) -> Bool {
        now - lastSeen < 30
    }

    var lastSeenDate: Date { Date(timeIntervalSince1970: lastSeen) }

    static func parse(_ o: [String: Any]) -> DeviceInfo {
        let id = jstr(o["device_id"])
        let disp = jstr(o["display"])
        return DeviceInfo(
            deviceId: id,
            display: disp.isEmpty ? id : disp,
            lastSeen: jnum(o["last_seen"]) ?? 0,
            samples: jint(o["samples"]) ?? 0,
            latest: (o["latest"] as? [String: Any]).map { Sample.parse($0) },
            config: DeviceConfig.parse(o["config"] as? [String: Any])
        )
    }

    func with(config: DeviceConfig) -> DeviceInfo {
        DeviceInfo(
            deviceId: deviceId,
            display: display,
            lastSeen: lastSeen,
            samples: samples,
            latest: latest,
            config: config
        )
    }
}

// MARK: - 报警

struct Alert: Identifiable {
    let ts: Double
    let type: String
    let message: String

    var id: String { "\(ts)-\(type)-\(message)" }
    var date: Date { Date(timeIntervalSince1970: ts) }

    static func parse(_ o: [String: Any]) -> Alert {
        Alert(ts: jnum(o["ts"]) ?? 0, type: jstr(o["type"]), message: jstr(o["message"]))
    }
}

// MARK: - 时间窗

/// 曲线页顶部那排按钮。
/// 取点数量 = 窗口秒数 / 上报间隔(5s)，上限 5000（后端 limit 的硬上限）。
enum TimeWindow: String, CaseIterable, Identifiable {
    case m10, h1, h6, d1

    var id: String { rawValue }

    var label: String {
        switch self {
        case .m10: return "10 分钟"
        case .h1:  return "1 小时"
        case .h6:  return "6 小时"
        case .d1:  return "24 小时"
        }
    }

    var seconds: Int {
        switch self {
        case .m10: return 600
        case .h1:  return 3600
        case .h6:  return 21_600
        case .d1:  return 86_400
        }
    }

    func limit() -> Int {
        min(max(seconds / 5, 120), 5000)
    }
}

// MARK: - 时间格式化

enum Fmt {
    private static let clockFmt: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "HH:mm:ss"
        return f
    }()

    private static let dayFmt: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "MM-dd HH:mm"
        return f
    }()

    private static let stampFmt: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "MM-dd HH:mm:ss"
        return f
    }()

    static func clock(_ date: Date) -> String { clockFmt.string(from: date) }
    static func day(_ date: Date) -> String { dayFmt.string(from: date) }
    static func stamp(_ date: Date) -> String { stampFmt.string(from: date) }

    /// "3 秒前" / "2 分钟前" —— 离线判定比绝对时间好读
    static func ago(_ ts: Double) -> String {
        guard ts > 0 else { return "从未" }
        let d = Date().timeIntervalSince1970 - ts
        if d < 5 { return "刚刚" }
        if d < 60 { return "\(Int(d)) 秒前" }
        if d < 3600 { return "\(Int(d / 60)) 分钟前" }
        if d < 86_400 { return "\(Int(d / 3600)) 小时前" }
        return "\(Int(d / 86_400)) 天前"
    }
}
