//
//  AlertsView.swift
//  环境监测 iOS 客户端
//
//  报警按时间倒序（后端 /api/alerts 就是 desc）。
//  阈值在服务端改（temp_max / humi_max / soil_min），App 这边只负责显示，
//  不在手机上判阈值 —— 否则 App 和服务器会给出两套不一样的报警。
//

import SwiftUI

struct AlertsView: View {

    @ObservedObject var state: MonitorState
    var openSettings: () -> Void

    var body: some View {
        Group {
            if state.alerts.isEmpty {
                empty
            } else {
                List {
                    ForEach(state.alerts) { a in
                        row(a)
                            .listRowBackground(Color(.secondarySystemGroupedBackground))
                    }
                }
                .listStyle(.insetGrouped)
            }
        }
        .navigationTitle("报警")
        .navigationBarTitleDisplayMode(.inline)
        .gearToolbar(openSettings)
        .refreshable { await state.refresh() }
    }

    private var empty: some View {
        VStack(spacing: 10) {
            Image(systemName: "checkmark.shield.fill")
                .font(.system(size: 34))
                .foregroundStyle(Brand.ok.opacity(0.6))
            Text("没有报警记录")
                .font(.footnote)
                .foregroundStyle(.secondary)
            Text("超过阈值（温度/湿度上下限、土壤下限）才会记一条")
                .font(.caption2)
                .foregroundStyle(.tertiary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 40)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(.systemGroupedBackground))
    }

    private func row(_ a: Alert) -> some View {
        HStack(alignment: .top, spacing: 10) {
            RoundedRectangle(cornerRadius: 2)
                .fill(a.color)
                .frame(width: 3)
                .padding(.vertical, 2)

            VStack(alignment: .leading, spacing: 4) {
                Text(a.message)
                    .font(.footnote)
                    .fixedSize(horizontal: false, vertical: true)

                HStack(spacing: 6) {
                    Text(Fmt.stamp(a.date))
                    Text("·")
                    Text(Fmt.ago(a.ts))
                }
                .font(.caption2)
                .foregroundStyle(.tertiary)
            }

            Spacer(minLength: 0)
        }
        .padding(.vertical, 4)
    }
}
