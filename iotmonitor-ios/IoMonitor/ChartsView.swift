//
//  ChartsView.swift
//  环境监测 iOS 客户端
//
//  四张图，一张一条线 —— 不搞双 Y 轴。
//  理由：四路量纲差太远（温度 20 上下、光照 0~800），塞一张图里必然有一条被压成直线。
//
//  折线自己用 Path 画，不引 Swift Charts：
//    ① 想控制"末端圆点 + 渐变面积 + 3 条虚线网格"这些细节，Charts 反而绕；
//    ② Swift Charts 是 iOS 16 的框架，自己画就没有版本门槛。
//

import SwiftUI

struct ChartsView: View {

    @ObservedObject var state: MonitorState
    var openSettings: () -> Void

    var body: some View {
        ScrollView {
            VStack(spacing: 14) {
                windowPicker

                if state.samples.isEmpty {
                    emptyHint
                } else {
                    ForEach(Metric.allCases) { m in
                        MetricChartCard(
                            metric: m,
                            samples: state.samples
                        )
                    }
                }

                Text("时间刻度按上报间隔（约 5 秒）等距绘制；中间断线说明那段时间没收到数据。")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.horizontal, 14)
            .padding(.bottom, 24)
        }
        .background(Color(.systemGroupedBackground))
        .navigationTitle("曲线")
        .navigationBarTitleDisplayMode(.inline)
        .gearToolbar(openSettings)
        .refreshable { await state.refresh() }
    }

    private var windowPicker: some View {
        HStack(spacing: 8) {
            ForEach(TimeWindow.allCases) { w in
                chip(w)
            }
        }
    }

    private func chip(_ w: TimeWindow) -> some View {
        let on = (state.window == w)
        return Button {
            Task { await state.changeWindow(w) }
        } label: {
            Text(w.label)
                .font(.footnote.weight(.medium))
                .padding(.vertical, 7)
                .frame(maxWidth: .infinity)
                .background(
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .fill(on ? Brand.teal : Color(.secondarySystemGroupedBackground))
                )
                .foregroundStyle(on ? Color.white : Color.primary)
        }
        .buttonStyle(.plain)
    }

    private var emptyHint: some View {
        VStack(spacing: 8) {
            Image(systemName: "waveform.path.ecg")
                .font(.system(size: 30))
                .foregroundStyle(.tertiary)
            Text("这个时间窗里还没有数据")
                .font(.footnote)
                .foregroundStyle(.secondary)
            Text("板子每 5 秒上报一条，或下拉刷新试试")
                .font(.caption2)
                .foregroundStyle(.tertiary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 60)
    }
}

// MARK: - 单指标图表卡

struct MetricChartCard: View {

    let metric: Metric
    let samples: [Sample]

    private var values: [Double] {
        samples.compactMap { $0.value(metric) }
    }

    private var stats: (min: Double, max: Double, last: Double)? {
        let v = values
        guard let lo = v.min(), let hi = v.max(), let last = v.last else { return nil }
        return (lo, hi, last)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 6) {
                Image(systemName: metric.icon)
                    .font(.footnote)
                    .foregroundStyle(metric.color)
                Text(metric.label)
                    .font(.subheadline.weight(.semibold))

                Spacer()

                if let s = stats {
                    Text("低 \(metric.format(s.min)) · 高 \(metric.format(s.max)) · 现 \(metric.format(s.last))\(metric.unit)")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }

            LineChart(values: values, color: metric.color)

            if let f = samples.first, let l = samples.last {
                HStack {
                    Text(Fmt.clock(f.date))
                    Spacer()
                    Text("\(values.count) 点 / \(spanText)")
                    Spacer()
                    Text(Fmt.clock(l.date))
                }
                .font(.caption2)
                .foregroundStyle(.tertiary)
            }
        }
        .cardStyle(metric.color)
    }

    private var spanText: String {
        guard let f = samples.first, let l = samples.last, l.ts > f.ts else { return "—" }
        let sec = Int(l.ts - f.ts)
        if sec < 60 { return "\(sec) 秒" }
        if sec < 3600 { return "\(sec / 60) 分钟" }
        return String(format: "%.1f 小时", Double(sec) / 3600)
    }
}

// MARK: - 折线

struct LineChart: View {

    let values: [Double]
    let color: Color

    private let height: CGFloat = 132
    /// 画出边界留白，免得描边被裁掉一半
    private let inset: CGFloat = 5

    var body: some View {
        GeometryReader { geo in
            let size = geo.size
            let pts = points(in: size)

            ZStack(alignment: .topLeading) {
                grid(size)

                if pts.count >= 2 {
                    areaPath(pts, size)
                        .fill(
                            LinearGradient(
                                colors: [color.opacity(0.26), color.opacity(0.02)],
                                startPoint: .top,
                                endPoint: .bottom
                            )
                        )

                    linePath(pts)
                        .stroke(
                            color,
                            style: StrokeStyle(lineWidth: 2, lineCap: .round, lineJoin: .round)
                        )

                    Circle()
                        .fill(color)
                        .frame(width: 5, height: 5)
                        .position(pts[pts.count - 1])
                } else {
                    Text("数据不足")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                        .frame(width: size.width, height: size.height)
                }
            }
        }
        .frame(height: height)
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(Color(.tertiarySystemFill).opacity(0.30))
        )
    }

    // MARK: 坐标换算

    /// Y 轴上下各放 12% 余量（至少 0.6），否则一条几乎水平的线会贴在边框上
    private func points(in size: CGSize) -> [CGPoint] {
        guard values.count >= 2 else { return [] }
        guard let lo0 = values.min(), let hi0 = values.max() else { return [] }

        let pad = max((hi0 - lo0) * 0.12, 0.6)
        let lo = lo0 - pad
        let hi = hi0 + pad
        let span = hi - lo
        guard span > 0 else { return [] }

        let w = size.width - inset * 2
        let h = size.height - inset * 2
        let step = w / CGFloat(values.count - 1)

        return values.enumerated().map { i, v in
            let x = inset + CGFloat(i) * step
            let ratio = (v - lo) / span
            let y = inset + h - CGFloat(ratio) * h
            return CGPoint(x: x, y: min(max(y, inset), inset + h))
        }
    }

    private func linePath(_ pts: [CGPoint]) -> Path {
        var p = Path()
        p.move(to: pts[0])
        for pt in pts.dropFirst() { p.addLine(to: pt) }
        return p
    }

    private func areaPath(_ pts: [CGPoint], _ size: CGSize) -> Path {
        var p = Path()
        let bottom = size.height - inset
        p.move(to: CGPoint(x: pts[0].x, y: bottom))
        for pt in pts { p.addLine(to: pt) }
        p.addLine(to: CGPoint(x: pts[pts.count - 1].x, y: bottom))
        p.closeSubpath()
        return p
    }

    private func grid(_ size: CGSize) -> some View {
        Path { p in
            for i in 0...3 {
                let y = inset + (size.height - inset * 2) * CGFloat(i) / 3
                p.move(to: CGPoint(x: 0, y: y))
                p.addLine(to: CGPoint(x: size.width, y: y))
            }
        }
        .stroke(Color.primary.opacity(0.07), style: StrokeStyle(lineWidth: 1, dash: [3, 4]))
    }
}
