//
//  Api.swift
//  环境监测 iOS 客户端
//
//  只打 5 个接口，全部用 URLSession + JSONSerialization，不引任何第三方库
//  （Alamofire / Moya 都不需要），保证别人 clone 下来直接能编译。
//

import Foundation

// MARK: - 本地设置

/// 服务器地址 / 设备 ID / 轮询间隔。
/// 直接用 UserDefaults + @AppStorage，设置页改完立刻生效，不用重启 App。
enum Prefs {
    static let baseUrlKey = "baseUrl"
    static let deviceIdKey = "deviceId"
    static let pollKey = "pollSeconds"

    static let defaultBase = "https://iot.austin666.top"
    static let defaultDevice = "board01"

    static var baseUrl: String {
        get {
            let v = (UserDefaults.standard.string(forKey: baseUrlKey) ?? "").trimmingCharacters(in: .whitespaces)
            let t = v.hasSuffix("/") ? String(v.dropLast()) : v
            return t.isEmpty ? defaultBase : t
        }
        set {
            var v = newValue.trimmingCharacters(in: .whitespaces)
            while v.hasSuffix("/") { v = String(v.dropLast()) }
            UserDefaults.standard.set(v, forKey: baseUrlKey)
        }
    }

    static var deviceId: String {
        get {
            let v = (UserDefaults.standard.string(forKey: deviceIdKey) ?? "").trimmingCharacters(in: .whitespaces)
            return v.isEmpty ? defaultDevice : v
        }
        set {
            let v = newValue.trimmingCharacters(in: .whitespaces)
            UserDefaults.standard.set(v, forKey: deviceIdKey)
        }
    }

    /// 0 表示关掉自动轮询，只在下拉刷新时请求
    static var pollSeconds: Int {
        get {
            let v = UserDefaults.standard.integer(forKey: pollKey)
            return v == 0 ? 5 : v
        }
        set { UserDefaults.standard.set(newValue, forKey: pollKey) }
    }
}

// MARK: - 错误

enum ApiError: LocalizedError {
    case badUrl(String)
    case http(Int, String)
    case decode(String)

    var errorDescription: String? {
        switch self {
        case .badUrl(let s):
            return "地址不合法：\(s)"
        case .http(let code, let body):
            return "HTTP \(code) \(body)"
        case .decode(let body):
            return "返回格式不对：\(body)"
        }
    }
}

// MARK: - 客户端

struct Api {

    private var session: URLSession {
        let cfg = URLSessionConfiguration.ephemeral
        cfg.timeoutIntervalForRequest = 8
        cfg.timeoutIntervalForResource = 12
        // 面板数据一秒都不能缓存，否则下拉刷新看到旧值
        cfg.requestCachePolicy = .reloadIgnoringLocalCacheData
        return URLSession(configuration: cfg)
    }

    private func send(_ path: String, method: String = "GET", body: [String: Any]? = nil) async throws -> [String: Any] {
        let full = Prefs.baseUrl + path
        guard let url = URL(string: full) else { throw ApiError.badUrl(full) }

        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body {
            req.httpBody = try JSONSerialization.data(withJSONObject: body)
            req.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        }

        let (data, resp) = try await session.data(for: req)
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        let text = String(data: data, encoding: .utf8) ?? ""

        guard (200..<300).contains(code) else {
            throw ApiError.http(code, String(text.prefix(160)))
        }
        if text.isEmpty { return [:] }
        guard let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw ApiError.decode(String(text.prefix(160)))
        }
        return obj
    }

    /// 设备列表。App 只用第一台（选中的 deviceId），但列表接口顺便能判断设备在不在。
    func devices() async throws -> [DeviceInfo] {
        let o = try await send("/api/devices")
        let arr = o["devices"] as? [[String: Any]] ?? []
        return arr.map { DeviceInfo.parse($0) }
    }

    /// 历史曲线。
    /// ★ order=desc 不能省：后端语义是"按这个方向排序后取前 N 条"，
    ///   传 asc 拿到的是**最早**的 N 条（等于永远是几小时前的数据）。
    ///   拉下来再 reversed() 给图表用升序。
    func telemetry(deviceId: String, limit: Int) async throws -> [Sample] {
        let o = try await send("/api/devices/\(deviceId)/telemetry?limit=\(limit)&order=desc")
        let arr = o["items"] as? [[String: Any]] ?? []
        // .reversed() 返回的是 ReversedCollection 不是 Array，这里必须转回来
        return Array(arr.map { Sample.parse($0) }.reversed())
    }

    func alerts(limit: Int = 40) async throws -> [Alert] {
        let o = try await send("/api/alerts?limit=\(limit)")
        let arr = o["items"] as? [[String: Any]] ?? []
        return arr.map { Alert.parse($0) }
    }

    // MARK: 下行指令（POST /api/devices/{id}/cmd，服务端再转 MQTT）

    /// 返回值就是真正发到板子上的那条报文，比如 "RGB:255,0,0,80"，
    /// 显示出来方便排查"点了没反应到底是没发出去还是板子没收到"。
    @discardableResult
    func led(deviceId: String, r: Int, g: Int, b: Int, brightness: Int) async throws -> String {
        let body: [String: Any] = ["type": "led", "r": r, "g": g, "b": b, "brightness": brightness]
        let o = try await send("/api/devices/\(deviceId)/cmd", method: "POST", body: body)
        return jstr(o["sent"])
    }

    @discardableResult
    func sensor(deviceId: String, enabled: Bool) async throws -> String {
        let body: [String: Any] = ["type": "sensor", "enabled": enabled]
        let o = try await send("/api/devices/\(deviceId)/cmd", method: "POST", body: body)
        return jstr(o["sent"])
    }

    @discardableResult
    func interval(deviceId: String, seconds: Int) async throws -> String {
        let body: [String: Any] = ["type": "interval", "seconds": seconds]
        let o = try await send("/api/devices/\(deviceId)/cmd", method: "POST", body: body)
        return jstr(o["sent"])
    }

    /// 设置页的"测试连接"用：拉一次设备列表，顺便把耗时一起回显
    func ping() async throws -> (count: Int, device: String?, ms: Int) {
        let t0 = Date()
        let list = try await devices()
        let ms = Int(Date().timeIntervalSince(t0) * 1000)
        return (list.count, list.first?.deviceId, ms)
    }
}
