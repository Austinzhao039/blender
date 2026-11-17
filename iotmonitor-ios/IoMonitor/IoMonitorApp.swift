//
//  IoMonitorApp.swift
//  环境监测 iOS 客户端
//
//  SwiftUI 生命周期（不用 AppDelegate / SceneDelegate）。
//  微信、支付宝那种"单例 + 路由"的写法在这里完全没必要 —— 四个 tab 就是全部导航。
//

import SwiftUI

@main
struct IoMonitorApp: App {

    init() {
        // 第一次启动把默认服务器地址写进去，否则 @AppStorage 是空字符串，
        // 界面上的输入框会空白，用户会以为坏了。
        if (UserDefaults.standard.string(forKey: Prefs.baseUrlKey) ?? "").isEmpty {
            UserDefaults.standard.set(Prefs.defaultBase, forKey: Prefs.baseUrlKey)
        }
        if (UserDefaults.standard.string(forKey: Prefs.deviceIdKey) ?? "").isEmpty {
            UserDefaults.standard.set(Prefs.defaultDevice, forKey: Prefs.deviceIdKey)
        }
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}
