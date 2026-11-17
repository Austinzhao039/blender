//
//  ContentView.swift
//  环境监测 iOS 客户端
//
//  结构跟安卓端完全对齐：4 个 tab（总览 / 曲线 / 报警 / 控制）+ 右上角齿轮进设置。
//  iOS 16 起用 NavigationStack（不是老的 NavigationView）。
//

import SwiftUI

struct ContentView: View {

    @StateObject private var state = MonitorState()
    @State private var showSettings = false

    @Environment(\.scenePhase) private var scenePhase

    @AppStorage("autoRefresh") private var autoRefresh = true
    @AppStorage(Prefs.pollKey) private var pollSeconds = 5

    /// 轮询的"节拍"：autoRefresh 或间隔一变就要重启那个 while 循环
    private var pollKey: String { "\(autoRefresh)-\(pollSeconds)" }

    var body: some View {
        TabView {
            NavigationStack {
                OverviewView(state: state, openSettings: { showSettings = true })
            }
            .tabItem { Label("总览", systemImage: "house.fill") }

            NavigationStack {
                ChartsView(state: state, openSettings: { showSettings = true })
            }
            .tabItem { Label("曲线", systemImage: "chart.xyaxis.line") }

            NavigationStack {
                AlertsView(state: state, openSettings: { showSettings = true })
            }
            .tabItem { Label("报警", systemImage: "bell.fill") }

            NavigationStack {
                ControlView(state: state, openSettings: { showSettings = true })
            }
            .tabItem { Label("控制", systemImage: "slider.horizontal.3") }
        }
        .tint(Brand.teal)
        .sheet(isPresented: $showSettings) {
            NavigationStack {
                SettingsView()
            }
        }
        // 进后台再回来立刻刷一次，别让用户盯着几小时前的旧数据
        .onChange(of: scenePhase) { phase in
            if phase == .active { Task { await state.refresh() } }
        }
        .task(id: pollKey) {
            await state.refresh()
            guard autoRefresh, pollSeconds > 0 else { return }
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: UInt64(pollSeconds) * 1_000_000_000)
                if Task.isCancelled { break }
                await state.refresh()
            }
        }
    }

}

// MARK: - 右上角齿轮

/// 四个页面都要放同一个齿轮，抽成 modifier，省得抄四遍
private struct GearToolbar: ViewModifier {
    let action: () -> Void

    func body(content: Content) -> some View {
        content.toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                Button(action: action) {
                    Image(systemName: "gearshape")
                }
                .accessibilityLabel("设置")
            }
        }
    }
}

extension View {
    func gearToolbar(_ action: @escaping () -> Void) -> some View {
        modifier(GearToolbar(action: action))
    }
}
