//
//  OverviewView.swift
//  环境监测 iOS 客户端
//
//  一眼看全的状态页：设备在线点 + 2×2 四个指标 + 上报参数。
//  离线时数字仍然显示（最后一次取到的值），但会把"多久之前"标红 —— 这比直接显示"—"
//  有用得多：0 和"没数据"是两件事，前者是传感器真实读数。
//

import SwiftUI

struct OverviewView: View {

    @ObservedObject var state: MonitorState
    var openSettings: () -> Void

    private let columns = [
        GridItem(.flexible(), spacing: 12),
        GridItem(.flexible(), spacing: 12),
    ]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {

                headerCard

                if let err = state.error {
                    banner(err)
                }

                LazyVGrid(columns: columns, spacing: 12) {
                    ForEach(Metric.allCases) { m in
                        MetricCard(metric: m, value: state.value(m))
                    }
                }

                infoCard

                Text("数据来自 \(Prefs.baseUrl)")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                    .frame(maxWidth: .infinity, alignment: .center)
                    .padding(.top, 4)
            }
            .padding(.horizontal, 14)
            .padding(.bottom, 24)
        }
        .background(Color(.systemGroupedBackground))
        .navigationTitle("环境监测")
        .navigationBarTitleDisplayMode(.inline)
        .gearToolbar(openSettings)
        .refreshable { await state.refresh() }
    }

    // MARK: - 顶部设备卡

    private var headerCard: some View {
        HStack(alignment: .top, spacing: 12) {
            Circle()
                .fill(state.online ? Brand.ok : Brand.off)
                .frame(width: 10, height: 10)
                .padding(.top, 6)

            VStack(alignment: .leading, spacing: 4) {
                Text(state.device?.display ?? Prefs.deviceId)
                    .font(.headline)

                HStack(spacing: 6) {
                    Text(state.online ? "在线" : "离线")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(state.online ? Brand.ok : Brand.off)

                    if let d = state.device {
                        Text("· 最后数据 \(Fmt.ago(d.lastSeen))")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                if let u = state.updatedAt {
                    Text("本机刷新于 \(Fmt.clock(u))")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
            }

            Spacer()

            if state.loading {
                ProgressView().controlSize(.small)
            }
        }
        .cardStyle()
    }

    // MARK: - 错误条

    private func banner(_ text: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(Brand.light)
            Text(text)
                .font(.footnote)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .padding(10)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(Brand.light.opacity(0.12))
        )
    }

    // MARK: - 上报参数

    private var infoCard: some View {
        VStack(spacing: 0) {
            InfoRow(label: "设备 ID", value: state.device?.deviceId ?? Prefs.deviceId)
            Divider()
            InfoRow(label: "上报间隔", value: "\(state.device?.config.intervalSeconds ?? 5) 秒")
            Divider()
            InfoRow(label: "采集状态", value: (state.device?.config.sensorEnabled ?? true) ? "开启" : "已停止")
            Divider()
            InfoRow(label: "累计样本", value: "\(state.device?.samples ?? 0) 条")
        }
        .cardStyle()
    }
}

// MARK: - 指标卡

struct MetricCard: View {
    let metric: Metric
    let value: Double?

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                Image(systemName: metric.icon)
                    .font(.footnote)
                    .foregroundStyle(metric.color)
                Text(metric.label)
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(.secondary)
                Spacer(minLength: 0)
            }

            HStack(alignment: .firstTextBaseline, spacing: 2) {
                Text(metric.format(value))
                    .font(.system(size: 34, weight: .semibold, design: .rounded))
                    .foregroundStyle(metric.color)
                    .minimumScaleFactor(0.6)
                    .lineLimit(1)
                Text(metric.unit)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .cardStyle(metric.color)
    }
}

// MARK: - 一行键值

struct InfoRow: View {
    let label: String
    let value: String

    var body: some View {
        HStack {
            Text(label)
                .font(.footnote)
                .foregroundStyle(.secondary)
            Spacer()
            Text(value)
                .font(.footnote.weight(.medium))
                .foregroundStyle(.primary)
        }
        .padding(.vertical, 9)
    }
}
