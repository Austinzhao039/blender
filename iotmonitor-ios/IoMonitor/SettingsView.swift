//
//  SettingsView.swift
//  环境监测 iOS 客户端
//
//  这一页存在的唯一原因：服务器地址和设备 ID 不能写死在代码里。
//  换一台服务器 / 换一块板子，在手机上改两个字段就行，不用重新打包。
//

import SwiftUI

struct SettingsView: View {

    @Environment(\.dismiss) private var dismiss

    @AppStorage(Prefs.baseUrlKey) private var baseUrl = Prefs.defaultBase
    @AppStorage(Prefs.deviceIdKey) private var deviceId = Prefs.defaultDevice
    @AppStorage(Prefs.pollKey) private var pollSeconds = 5
    @AppStorage("autoRefresh") private var autoRefresh = true

    @State private var testing = false
    @State private var testResult: String?
    @State private var testOK = false

    var body: some View {
        Form {
            Section {
                TextField("https://iot.austin666.top", text: $baseUrl)
                    .keyboardType(.URL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .onSubmit { normalize() }

                TextField("board01", text: $deviceId)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()

                Button {
                    testConnection()
                } label: {
                    HStack {
                        Text("测试连接")
                        Spacer()
                        if testing { ProgressView().controlSize(.small) }
                        else if let r = testResult {
                            Text(r)
                                .font(.caption)
                                .foregroundStyle(testOK ? Brand.ok : Brand.temp)
                        }
                    }
                }
                .disabled(testing)
            } header: {
                Text("服务器")
            } footer: {
                Text("必须是能直接访问到后端的地址。局域网调试可以用 http://192.168.x.x:8000（App 已允许明文 HTTP）。")
            }

            Section {
                Toggle("自动刷新", isOn: $autoRefresh)
                    .tint(Brand.teal)

                HStack {
                    Text("刷新间隔")
                    Spacer()
                    Text("\(pollSeconds) 秒")
                        .foregroundStyle(.secondary)
                    Stepper("", value: $pollSeconds, in: 1...120, step: 1)
                        .labelsHidden()
                }
            } header: {
                Text("刷新")
            } footer: {
                Text("板子默认 5 秒上报一次，App 跟它对齐就够；调太密只是多耗流量。")
            }

            Section {
                Button("恢复默认设置") {
                    baseUrl = Prefs.defaultBase
                    deviceId = Prefs.defaultDevice
                    pollSeconds = 5
                    autoRefresh = true
                    testResult = nil
                }
                .foregroundStyle(Brand.temp)
            }

            Section {
                LabeledContent("当前地址", value: Prefs.baseUrl)
                LabeledContent("当前设备", value: Prefs.deviceId)
                LabeledContent("版本", value: appVersion)
            } header: {
                Text("关于")
            } footer: {
                Text("环境监测 · 掌控板 + MQTT + FastAPI 自建链路。数据全部存在你自己服务器上的 SQLite 里，没有第三方云。")
            }
        }
        .navigationTitle("设置")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                Button("完成") {
                    normalize()
                    dismiss()
                }
                .fontWeight(.semibold)
            }
        }
    }

    private var appVersion: String {
        let v = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0"
        let b = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "1"
        return "\(v) (\(b))"
    }

    /// 去掉首尾空格和结尾的 "/"，否则拼出来会变成 //api/devices
    private func normalize() {
        var u = baseUrl.trimmingCharacters(in: .whitespacesAndNewlines)
        while u.hasSuffix("/") { u = String(u.dropLast()) }
        if u.isEmpty { u = Prefs.defaultBase }
        baseUrl = u

        let d = deviceId.trimmingCharacters(in: .whitespacesAndNewlines)
        deviceId = d.isEmpty ? Prefs.defaultDevice : d
    }

    private func testConnection() {
        normalize()
        testing = true
        testResult = nil
        Task {
            do {
                let r = try await Api().ping()
                testOK = true
                if let first = r.device {
                    testResult = "通 · \(r.count) 台 · \(r.ms)ms"
                    // 只填过一次默认值的话，顺手指向第一台真设备
                    if deviceId == Prefs.defaultDevice && first != Prefs.defaultDevice {
                        deviceId = first
                    }
                } else {
                    testResult = "通 · 但还没有设备上报过"
                }
            } catch {
                testOK = false
                testResult = "不通：\(error.localizedDescription)"
            }
            testing = false
        }
    }
}
