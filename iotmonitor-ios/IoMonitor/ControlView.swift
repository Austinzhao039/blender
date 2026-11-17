//
//  ControlView.swift
//  环境监测 iOS 客户端
//
//  所有按钮都是 POST /api/devices/{id}/cmd，服务端再转成 MQTT 报文：
//      RGB:R,G,B,Brightness     → 板子调 WS2812（四段缺一不可）
//      SENSOR:ON | SENSOR:OFF   → 停/开采集
//      INTERVAL:N               → 改上报间隔（秒）
//  接口会把这行报文原样回传（"sent"），所以发送后直接把回显贴出来 ——
//  点了没反应时，能立刻分清是"命令没发出去"还是"板子没收到"。
//

import SwiftUI

struct ControlView: View {

    @ObservedObject var state: MonitorState
    var openSettings: () -> Void

    // 用 Double 存，Slider 只吃 Double；发送时再取整
    @State private var r: Double = 255
    @State private var g: Double = 90
    @State private var b: Double = 0
    @State private var brightness: Double = 80

    @State private var sensorOn = true
    /// 服务端当前已知的采集状态。用来挡掉"进页面时初始化赋值也算一次变更"
    /// 导致的假下发 —— 那样一进控制页就会往板子发一条 SENSOR:ON。
    @State private var lastSensor = true
    @State private var interval: Int = 5

    @State private var busy = false
    @State private var toast: String?
    @State private var toastBad = false

    private let presets: [Preset] = [
        Preset(name: "红", r: 255, g: 0, b: 0),
        Preset(name: "绿", r: 0, g: 255, b: 0),
        Preset(name: "蓝", r: 0, g: 0, b: 255),
        Preset(name: "白", r: 255, g: 255, b: 255),
        Preset(name: "暖黄", r: 255, g: 150, b: 40),
        Preset(name: "青", r: 14, g: 154, b: 167),
    ]

    private var preview: Color {
        Color(red: r / 255, green: g / 255, blue: b / 255)
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 14) {
                ledCard
                sensorCard
                intervalCard
                if let t = toast { toastView(t) }
                Text("指令经服务器转成 MQTT 下发，板子收到才会变；没变先看串口有没有 [cmd] 那一行。")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.horizontal, 14)
            .padding(.bottom, 24)
        }
        .background(Color(.systemGroupedBackground))
        .navigationTitle("控制")
        .navigationBarTitleDisplayMode(.inline)
        .gearToolbar(openSettings)
        .onAppear {
            if let c = state.device?.config {
                sensorOn = c.sensorEnabled
                lastSensor = c.sensorEnabled
                interval = c.intervalSeconds
            }
        }
    }

    // MARK: - 灯

    private var ledCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(preview)
                    .frame(width: 46, height: 46)
                    .overlay(
                        RoundedRectangle(cornerRadius: 10, style: .continuous)
                            .stroke(Color.primary.opacity(0.12), lineWidth: 1)
                    )

                VStack(alignment: .leading, spacing: 2) {
                    Text("板载 RGB 灯")
                        .font(.subheadline.weight(.semibold))
                    Text("R\(Int(r)) G\(Int(g)) B\(Int(b)) · 亮度 \(Int(brightness))")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                Spacer()
            }

            channel("R", value: $r, tint: .red)
            channel("G", value: $g, tint: .green)
            channel("B", value: $b, tint: .blue)
            channel("亮度", value: $brightness, tint: Brand.teal)

            HStack(spacing: 8) {
                ForEach(presets) { p in
                    Button {
                        r = p.r; g = p.g; b = p.b
                    } label: {
                        Circle()
                            .fill(Color(red: p.r / 255, green: p.g / 255, blue: p.b / 255))
                            .frame(width: 30, height: 30)
                            .overlay(Circle().stroke(Color.primary.opacity(0.12), lineWidth: 1))
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(p.name)
                }
                Spacer()
            }

            Button {
                sendLed()
            } label: {
                Text(busy ? "发送中…" : "应用到板子")
                    .font(.subheadline.weight(.semibold))
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 11)
                    .background(
                        RoundedRectangle(cornerRadius: 12, style: .continuous)
                            .fill(Brand.teal)
                    )
                    .foregroundStyle(.white)
            }
            .buttonStyle(.plain)
            .disabled(busy)
        }
        .cardStyle()
    }

    private func channel(_ name: String, value: Binding<Double>, tint: Color) -> some View {
        HStack(spacing: 10) {
            Text(name)
                .font(.caption.weight(.semibold))
                .foregroundStyle(tint)
                .frame(width: 28, alignment: .leading)

            Slider(value: value, in: 0...255, step: 1)
                .tint(tint)

            Text("\(Int(value.wrappedValue))")
                .font(.caption2.monospacedDigit())
                .foregroundStyle(.secondary)
                .frame(width: 30, alignment: .trailing)
        }
    }

    // MARK: - 采集开关

    private var sensorCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Toggle(isOn: $sensorOn) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("采集开关")
                        .font(.subheadline.weight(.semibold))
                    Text(sensorOn ? "板子正在上报数据" : "已停止上报（省电 / 暂停实验）")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
            .tint(Brand.teal)
            .onChange(of: sensorOn) { v in
                guard v != lastSensor else { return }
                lastSensor = v
                sendSensor(v)
            }
        }
        .cardStyle()
    }

    // MARK: - 上报间隔

    private var intervalCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("上报间隔")
                        .font(.subheadline.weight(.semibold))
                    Text("1~60 秒；越小越实时，也越费流量和电")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Stepper("\(interval) 秒", value: $interval, in: 1...60)
                    .labelsHidden()
                Text("\(interval) 秒")
                    .font(.subheadline.monospacedDigit())
                    .frame(width: 52, alignment: .trailing)
            }

            Button {
                sendInterval()
            } label: {
                Text("下发间隔")
                    .font(.footnote.weight(.semibold))
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 9)
                    .background(
                        RoundedRectangle(cornerRadius: 10, style: .continuous)
                            .fill(Brand.teal.opacity(0.12))
                    )
                    .foregroundStyle(Brand.teal)
            }
            .buttonStyle(.plain)
        }
        .cardStyle()
    }

    // MARK: - 提示条

    private func toastView(_ text: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: toastBad ? "xmark.circle.fill" : "checkmark.circle.fill")
                .foregroundStyle(toastBad ? Brand.temp : Brand.ok)
            Text(text)
                .font(.caption)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .padding(10)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill((toastBad ? Brand.temp : Brand.ok).opacity(0.12))
        )
    }

    // MARK: - 动作

    private func sendLed() {
        busy = true
        Task {
            let res = await state.sendLed(
                r: Int(r), g: Int(g), b: Int(b), brightness: Int(brightness)
            )
            busy = false
            switch res {
            case .success(let p):
                toast = "已下发 \(p)"
                toastBad = false
            case .failure(let e):
                toast = "下发失败：\(e.localizedDescription)"
                toastBad = true
            }
        }
    }

    private func sendSensor(_ v: Bool) {
        Task {
            switch await state.sendSensor(enabled: v) {
            case .success(let p):
                toast = "已下发 \(p)"
                toastBad = false
            case .failure(let e):
                toast = "下发失败：\(e.localizedDescription)"
                toastBad = true
                sensorOn = !v      // 发失败就把开关拨回去，别让界面骗人
                lastSensor = !v
            }
        }
    }

    private func sendInterval() {
        Task {
            switch await state.sendInterval(seconds: interval) {
            case .success(let p):
                toast = "已下发 \(p)"
                toastBad = false
            case .failure(let e):
                toast = "下发失败：\(e.localizedDescription)"
                toastBad = true
            }
        }
    }
}

/// 预设色。
/// 写成结构体而不是元组，是因为 Swift 的 KeyPath 取不到元组元素
/// （`ForEach(presets, id: \.0)` 会直接编译不过）。
struct Preset: Identifiable {
    let name: String
    let r: Double
    let g: Double
    let b: Double

    var id: String { name }
}
