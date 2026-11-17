//
//  Theme.swift
//  环境监测 iOS 客户端
//
//  颜色统一在这里，跟着 App 图标的主色（青 #0E9AA7）走，
//  四路指标各一个色，网页面板 / 安卓 / iOS 三端颜色一致，看着是一套东西。
//

import SwiftUI

enum Brand {
    /// App 图标底色
    static let teal = Color(red: 0x0E / 255.0, green: 0x9A / 255.0, blue: 0xA7 / 255.0)
    static let tealDeep = Color(red: 0x0A / 255.0, green: 0x6E / 255.0, blue: 0x78 / 255.0)

    static let temp = Color(red: 0xE4 / 255.0, green: 0x5A / 255.0, blue: 0x4C / 255.0)
    static let humi = Color(red: 0x3E / 255.0, green: 0x8E / 255.0, blue: 0xD8 / 255.0)
    static let light = Color(red: 0xE8 / 255.0, green: 0xA5 / 255.0, blue: 0x2B / 255.0)
    static let soil = Color(red: 0x8A / 255.0, green: 0x6D / 255.0, blue: 0x3B / 255.0)

    static let ok = Color(red: 0x2F / 255.0, green: 0xB3 / 255.0, blue: 0x6A / 255.0)
    static let off = Color(red: 0x9A / 255.0, green: 0x9A / 255.0, blue: 0x9A / 255.0)
}

extension Metric {
    var color: Color {
        switch self {
        case .temp:  return Brand.temp
        case .humi:  return Brand.humi
        case .light: return Brand.light
        case .soil:  return Brand.soil
        }
    }

    var icon: String {
        switch self {
        case .temp:  return "thermometer.medium"
        case .humi:  return "drop.fill"
        case .light: return "sun.max.fill"
        case .soil:  return "leaf.fill"
        }
    }
}

extension Alert {
    /// 报警文案里有"过高/过低/离线"，靠关键词上色就够了，不必让后端加字段
    var isDanger: Bool {
        message.contains("过高") || message.contains("过低") || message.contains("离线")
    }

    var color: Color { isDanger ? Brand.temp : Brand.teal }
}

/// 卡片统一圆角 + 细边，深色模式下也不会糊成一片
struct CardBackground: ViewModifier {
    var tint: Color = Brand.teal

    func body(content: Content) -> some View {
        content
            .padding(14)
            .background(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(Color(.secondarySystemGroupedBackground))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .stroke(tint.opacity(0.18), lineWidth: 1)
            )
    }
}

extension View {
    func cardStyle(_ tint: Color = Brand.teal) -> some View {
        modifier(CardBackground(tint: tint))
    }
}
