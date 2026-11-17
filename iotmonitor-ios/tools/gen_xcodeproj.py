#!/usr/bin/env python3
"""生成 IoMonitor.xcodeproj（project.pbxproj + 共享 scheme）。

为什么要脚本：pbxproj 里每个对象都得有一个全局唯一的 24 位十六进制 ID，
手写一处拼错，Xcode 打开就是一句 "The project is damaged"。脚本按固定规则发 ID，
结果是确定性的 —— 重跑不会产生 diff。

用法：
    python3 tools/gen_xcodeproj.py            # 就地生成
    python3 tools/gen_xcodeproj.py --check    # 只校验现有 pbxproj 里引用是否都能对上

加源文件：把文件名加到下面 SOURCES 里，重跑一次即可（Xcode 里手动加组也行）。
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # esp32/apps/ios
PROJ_DIR = os.path.join(ROOT, "IoMonitor.xcodeproj")
APP_DIR = os.path.join(ROOT, "IoMonitor")

TARGET_NAME = "IoMonitor"
BUNDLE_ID = "top.austin666.iotmonitor"
DEPLOY_TARGET = "16.0"

SOURCES = [
    "IoMonitorApp.swift",
    "ContentView.swift",
    "Models.swift",
    "Api.swift",
    "Theme.swift",
    "MonitorState.swift",
    "OverviewView.swift",
    "ChartsView.swift",
    "AlertsView.swift",
    "ControlView.swift",
    "SettingsView.swift",
]

RESOURCES = ["Assets.xcassets"]
PLIST = "Info.plist"


def oid(n: int) -> str:
    """确定性 ID：20 位固定前缀 + 4 位序号，正好 24 个十六进制字符。

    Xcode 只要求"24 位十六进制、全局唯一"，不要求是随机 UUID。
    固定前缀的好处是重跑脚本不会改 ID，git diff 里看不出噪音。
    """
    return "0A5710000000000000%06X" % n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验，不写文件")
    args = ap.parse_args()

    if args.check:
        return check()

    # ---- 发号 ----
    n = 1
    ids = {}

    def take(key):
        nonlocal n
        ids[key] = oid(n)
        n += 1
        return ids[key]

    project_id = take("project")
    target_id = take("target")
    product_id = take("product")
    main_group = take("group.root")
    app_group = take("group.app")
    products_group = take("group.products")
    sources_phase = take("phase.sources")
    frameworks_phase = take("phase.frameworks")
    resources_phase = take("phase.resources")
    proj_cfg_list = take("cfglist.project")
    target_cfg_list = take("cfglist.target")
    proj_debug = take("cfg.project.debug")
    proj_release = take("cfg.project.release")
    target_debug = take("cfg.target.debug")
    target_release = take("cfg.target.release")

    file_refs = {}
    build_files = {}
    for f in SOURCES:
        file_refs[f] = take("file." + f)
        build_files[f] = take("build." + f)
    for f in RESOURCES:
        file_refs[f] = take("file." + f)
        build_files[f] = take("build." + f)
    file_refs[PLIST] = take("file." + PLIST)

    # ---- 片段 ----
    build_file_lines = []
    for f in SOURCES:
        build_file_lines.append(
            "\t\t%s /* %s in Sources */ = {isa = PBXBuildFile; fileRef = %s /* %s */; };"
            % (build_files[f], f, file_refs[f], f)
        )
    for f in RESOURCES:
        build_file_lines.append(
            "\t\t%s /* %s in Resources */ = {isa = PBXBuildFile; fileRef = %s /* %s */; };"
            % (build_files[f], f, file_refs[f], f)
        )

    file_ref_lines = [
        "\t\t%s /* %s.app */ = {isa = PBXFileReference; explicitFileType = wrapper.application; "
        "includeInIndex = 0; path = %s.app; sourceTree = BUILT_PRODUCTS_DIR; };"
        % (product_id, TARGET_NAME, TARGET_NAME)
    ]
    for f in SOURCES:
        file_ref_lines.append(
            "\t\t%s /* %s */ = {isa = PBXFileReference; lastKnownFileType = sourcecode.swift; "
            "path = %s; sourceTree = \"<group>\"; };"
            % (file_refs[f], f, f)
        )
    for f in RESOURCES:
        if f.endswith(".xcassets"):
            kind = "folder.assetcatalog"
        elif f.endswith(".storyboard"):
            kind = "file.storyboard"
        else:
            kind = "folder"
        file_ref_lines.append(
            "\t\t%s /* %s */ = {isa = PBXFileReference; lastKnownFileType = %s; "
            "path = %s; sourceTree = \"<group>\"; };"
            % (file_refs[f], f, kind, f)
        )
    file_ref_lines.append(
        "\t\t%s /* %s */ = {isa = PBXFileReference; lastKnownFileType = text.plist.xml; "
        "path = %s; sourceTree = \"<group>\"; };"
        % (file_refs[PLIST], PLIST, PLIST)
    )

    app_group_children = SOURCES + RESOURCES + [PLIST]
    app_group_children_txt = "\n".join(
        "\t\t\t\t%s /* %s */," % (file_refs[f], f) for f in app_group_children
    )

    src_children_txt = "\n".join(
        "\t\t\t\t%s /* %s in Sources */," % (build_files[f], f) for f in SOURCES
    )
    res_children_txt = "\n".join(
        "\t\t\t\t%s /* %s in Resources */," % (build_files[f], f) for f in RESOURCES
    )

    pbx = """// !$*UTF8*$!
{{
	archiveVersion = 1;
	classes = {{
	}};
	objectVersion = 56;
	objects = {{

/* Begin PBXBuildFile section */
{build_files}
/* End PBXBuildFile section */

/* Begin PBXFileReference section */
{file_refs}
/* End PBXFileReference section */

/* Begin PBXFrameworksBuildPhase section */
		{frameworks_phase} /* Frameworks */ = {{
			isa = PBXFrameworksBuildPhase;
			buildActionMask = 2147483647;
			files = (
			);
			runOnlyForDeploymentPostprocessing = 0;
		}};
/* End PBXFrameworksBuildPhase section */

/* Begin PBXGroup section */
		{main_group} = {{
			isa = PBXGroup;
			children = (
				{app_group} /* {target_name} */,
				{products_group} /* Products */,
			);
			sourceTree = "<group>";
		}};
		{app_group} /* {target_name} */ = {{
			isa = PBXGroup;
			children = (
{app_children}
			);
			path = {target_name};
			sourceTree = "<group>";
		}};
		{products_group} /* Products */ = {{
			isa = PBXGroup;
			children = (
				{product_id} /* {target_name}.app */,
			);
			name = Products;
			sourceTree = "<group>";
		}};
/* End PBXGroup section */

/* Begin PBXNativeTarget section */
		{target_id} /* {target_name} */ = {{
			isa = PBXNativeTarget;
			buildConfigurationList = {target_cfg_list} /* Build configuration list for PBXNativeTarget "{target_name}" */;
			buildPhases = (
				{sources_phase} /* Sources */,
				{frameworks_phase} /* Frameworks */,
				{resources_phase} /* Resources */,
			);
			buildRules = (
			);
			dependencies = (
			);
			name = {target_name};
			productName = {target_name};
			productReference = {product_id} /* {target_name}.app */;
			productType = "com.apple.product-type.application";
		}};
/* End PBXNativeTarget section */

/* Begin PBXProject section */
		{project_id} /* Project object */ = {{
			isa = PBXProject;
			attributes = {{
				BuildIndependentTargetsInParallel = 1;
				LastSwiftUpdateCheck = 1500;
				LastUpgradeCheck = 1500;
				TargetAttributes = {{
					{target_id} = {{
						CreatedOnToolsVersion = 15.0;
					}};
				}};
			}};
			buildConfigurationList = {proj_cfg_list} /* Build configuration list for PBXProject "{target_name}" */;
			compatibilityVersion = "Xcode 14.0";
			developmentRegion = en;
			hasScannedForEncodings = 0;
			knownRegions = (
				en,
				Base,
				"zh-Hans",
			);
			mainGroup = {main_group};
			productRefGroup = {products_group} /* Products */;
			projectDirPath = "";
			projectRoot = "";
			targets = (
				{target_id} /* {target_name} */,
			);
		}};
/* End PBXProject section */

/* Begin PBXResourcesBuildPhase section */
		{resources_phase} /* Resources */ = {{
			isa = PBXResourcesBuildPhase;
			buildActionMask = 2147483647;
			files = (
{res_children}
			);
			runOnlyForDeploymentPostprocessing = 0;
		}};
/* End PBXResourcesBuildPhase section */

/* Begin PBXSourcesBuildPhase section */
		{sources_phase} /* Sources */ = {{
			isa = PBXSourcesBuildPhase;
			buildActionMask = 2147483647;
			files = (
{src_children}
			);
			runOnlyForDeploymentPostprocessing = 0;
		}};
/* End PBXSourcesBuildPhase section */

/* Begin XCBuildConfiguration section */
		{proj_debug} /* Debug */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
				ALWAYS_SEARCH_USER_PATHS = NO;
				ASSETCATALOG_COMPILER_GENERATE_SWIFT_ASSET_SYMBOL_EXTENSIONS = YES;
				CLANG_ANALYZER_NONNULL = YES;
				CLANG_ENABLE_MODULES = YES;
				CLANG_ENABLE_OBJC_ARC = YES;
				CLANG_WARN_BOOL_CONVERSION = YES;
				CLANG_WARN_DOCUMENTATION_COMMENTS = YES;
				CLANG_WARN_EMPTY_BODY = YES;
				CLANG_WARN_UNREACHABLE_CODE = YES;
				COPY_PHASE_STRIP = NO;
				DEBUG_INFORMATION_FORMAT = dwarf;
				ENABLE_STRICT_OBJC_MSGSEND = YES;
				ENABLE_TESTABILITY = YES;
				ENABLE_USER_SCRIPT_SANDBOXING = YES;
				GCC_C_LANGUAGE_STANDARD = gnu17;
				GCC_DYNAMIC_NO_PIC = NO;
				GCC_NO_COMMON_BLOCKS = YES;
				GCC_OPTIMIZATION_LEVEL = 0;
				GCC_PREPROCESSOR_DEFINITIONS = (
					"DEBUG=1",
					"$(inherited)",
				);
				GCC_WARN_UNDECLARED_SELECTOR = YES;
				GCC_WARN_UNINITIALIZED_AUTOS = YES_AGGRESSIVE;
				GCC_WARN_UNUSED_FUNCTION = YES;
				GCC_WARN_UNUSED_VARIABLE = YES;
				IPHONEOS_DEPLOYMENT_TARGET = {deploy};
				LOCALIZATION_PREFERS_STRING_CATALOGS = YES;
				MTL_ENABLE_DEBUG_INFO = INCLUDE_SOURCE;
				MTL_FAST_MATH = YES;
				ONLY_ACTIVE_ARCH = YES;
				SDKROOT = iphoneos;
				SWIFT_ACTIVE_COMPILATION_CONDITIONS = "DEBUG $(inherited)";
				SWIFT_OPTIMIZATION_LEVEL = "-Onone";
			}};
			name = Debug;
		}};
		{proj_release} /* Release */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
				ALWAYS_SEARCH_USER_PATHS = NO;
				ASSETCATALOG_COMPILER_GENERATE_SWIFT_ASSET_SYMBOL_EXTENSIONS = YES;
				CLANG_ANALYZER_NONNULL = YES;
				CLANG_ENABLE_MODULES = YES;
				CLANG_ENABLE_OBJC_ARC = YES;
				CLANG_WARN_BOOL_CONVERSION = YES;
				CLANG_WARN_DOCUMENTATION_COMMENTS = YES;
				CLANG_WARN_EMPTY_BODY = YES;
				CLANG_WARN_UNREACHABLE_CODE = YES;
				COPY_PHASE_STRIP = NO;
				DEBUG_INFORMATION_FORMAT = "dwarf-with-dsym";
				ENABLE_NS_ASSERTIONS = NO;
				ENABLE_STRICT_OBJC_MSGSEND = YES;
				ENABLE_USER_SCRIPT_SANDBOXING = YES;
				GCC_C_LANGUAGE_STANDARD = gnu17;
				GCC_NO_COMMON_BLOCKS = YES;
				GCC_WARN_UNDECLARED_SELECTOR = YES;
				GCC_WARN_UNINITIALIZED_AUTOS = YES_AGGRESSIVE;
				GCC_WARN_UNUSED_FUNCTION = YES;
				GCC_WARN_UNUSED_VARIABLE = YES;
				IPHONEOS_DEPLOYMENT_TARGET = {deploy};
				LOCALIZATION_PREFERS_STRING_CATALOGS = YES;
				MTL_ENABLE_DEBUG_INFO = NO;
				MTL_FAST_MATH = YES;
				SDKROOT = iphoneos;
				SWIFT_COMPILATION_MODE = wholemodule;
				VALIDATE_PRODUCT = YES;
			}};
			name = Release;
		}};
		{target_debug} /* Debug */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
				ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon;
				ASSETCATALOG_COMPILER_GLOBAL_ACCENT_COLOR_NAME = AccentColor;
				CODE_SIGN_STYLE = Automatic;
				CURRENT_PROJECT_VERSION = 1;
				DEVELOPMENT_TEAM = "";
				ENABLE_PREVIEWS = YES;
				GENERATE_INFOPLIST_FILE = NO;
				INFOPLIST_FILE = "{target_name}/{plist}";
				LD_RUNPATH_SEARCH_PATHS = (
					"$(inherited)",
					"@executable_path/Frameworks",
				);
				MARKETING_VERSION = 1.0;
				PRODUCT_BUNDLE_IDENTIFIER = {bundle_id};
				PRODUCT_NAME = "$(TARGET_NAME)";
				SWIFT_EMIT_LOC_STRINGS = YES;
				SWIFT_VERSION = 5.0;
				TARGETED_DEVICE_FAMILY = "1,2";
			}};
			name = Debug;
		}};
		{target_release} /* Release */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
				ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon;
				ASSETCATALOG_COMPILER_GLOBAL_ACCENT_COLOR_NAME = AccentColor;
				CODE_SIGN_STYLE = Automatic;
				CURRENT_PROJECT_VERSION = 1;
				DEVELOPMENT_TEAM = "";
				ENABLE_PREVIEWS = YES;
				GENERATE_INFOPLIST_FILE = NO;
				INFOPLIST_FILE = "{target_name}/{plist}";
				LD_RUNPATH_SEARCH_PATHS = (
					"$(inherited)",
					"@executable_path/Frameworks",
				);
				MARKETING_VERSION = 1.0;
				PRODUCT_BUNDLE_IDENTIFIER = {bundle_id};
				PRODUCT_NAME = "$(TARGET_NAME)";
				SWIFT_EMIT_LOC_STRINGS = YES;
				SWIFT_VERSION = 5.0;
				TARGETED_DEVICE_FAMILY = "1,2";
			}};
			name = Release;
		}};
/* End XCBuildConfiguration section */

/* Begin XCConfigurationList section */
		{proj_cfg_list} /* Build configuration list for PBXProject "{target_name}" */ = {{
			isa = XCConfigurationList;
			buildConfigurations = (
				{proj_debug} /* Debug */,
				{proj_release} /* Release */,
			);
			defaultConfigurationIsVisible = 0;
			defaultConfigurationName = Release;
		}};
		{target_cfg_list} /* Build configuration list for PBXNativeTarget "{target_name}" */ = {{
			isa = XCConfigurationList;
			buildConfigurations = (
				{target_debug} /* Debug */,
				{target_release} /* Release */,
			);
			defaultConfigurationIsVisible = 0;
			defaultConfigurationName = Release;
		}};
/* End XCConfigurationList section */
	}};
	rootObject = {project_id} /* Project object */;
}}
""".format(
        build_files="\n".join(build_file_lines),
        file_refs="\n".join(file_ref_lines),
        frameworks_phase=frameworks_phase,
        main_group=main_group,
        app_group=app_group,
        products_group=products_group,
        app_children=app_group_children_txt,
        product_id=product_id,
        target_id=target_id,
        target_name=TARGET_NAME,
        sources_phase=sources_phase,
        resources_phase=resources_phase,
        res_children=res_children_txt,
        src_children=src_children_txt,
        project_id=project_id,
        proj_cfg_list=proj_cfg_list,
        target_cfg_list=target_cfg_list,
        proj_debug=proj_debug,
        proj_release=proj_release,
        target_debug=target_debug,
        target_release=target_release,
        deploy=DEPLOY_TARGET,
        plist=PLIST,
        bundle_id=BUNDLE_ID,
    )

    scheme = """<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion = "1500" version = "1.7">
   <BuildAction parallelizeBuildables = "YES" buildImplicitDependencies = "YES">
      <BuildActionEntries>
         <BuildActionEntry buildForTesting = "YES" buildForRunning = "YES" buildForProfiling = "YES" buildForArchiving = "YES" buildForAnalyzing = "YES">
            <BuildableReference
               BuildableIdentifier = "primary"
               BlueprintIdentifier = "{target_id}"
               BuildableName = "{target_name}.app"
               BlueprintName = "{target_name}"
               ReferencedContainer = "container:{target_name}.xcodeproj">
            </BuildableReference>
         </BuildActionEntry>
      </BuildActionEntries>
   </BuildAction>
   <TestAction buildConfiguration = "Debug" selectedDebuggerIdentifier = "Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier = "Xcode.DebuggerFoundation.Launcher.LLDB" shouldUseLaunchSchemeArgsEnv = "YES">
      <Testables>
      </Testables>
   </TestAction>
   <LaunchAction buildConfiguration = "Debug" selectedDebuggerIdentifier = "Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier = "Xcode.DebuggerFoundation.Launcher.LLDB" launchStyle = "0" useCustomWorkingDirectory = "NO" ignoresPersistentStateOnLaunch = "NO" debugDocumentVersioning = "YES" debugServiceExtension = "internal" allowLocationSimulation = "YES">
      <BuildableProductRunnable runnableDebuggingMode = "0">
         <BuildableReference
            BuildableIdentifier = "primary"
            BlueprintIdentifier = "{target_id}"
            BuildableName = "{target_name}.app"
            BlueprintName = "{target_name}"
            ReferencedContainer = "container:{target_name}.xcodeproj">
         </BuildableReference>
      </BuildableProductRunnable>
   </LaunchAction>
   <ProfileAction buildConfiguration = "Release" shouldUseLaunchSchemeArgsEnv = "YES" savedToolIdentifier = "" useCustomWorkingDirectory = "NO" debugDocumentVersioning = "YES">
      <BuildableProductRunnable runnableDebuggingMode = "0">
         <BuildableReference
            BuildableIdentifier = "primary"
            BlueprintIdentifier = "{target_id}"
            BuildableName = "{target_name}.app"
            BlueprintName = "{target_name}"
            ReferencedContainer = "container:{target_name}.xcodeproj">
         </BuildableReference>
      </BuildableProductRunnable>
   </ProfileAction>
   <AnalyzeAction buildConfiguration = "Debug">
   </AnalyzeAction>
   <ArchiveAction buildConfiguration = "Release" revealArchiveInOrganizer = "YES">
   </ArchiveAction>
</Scheme>
""".format(target_id=target_id, target_name=TARGET_NAME)

    os.makedirs(os.path.join(PROJ_DIR, "xcshareddata", "xcschemes"), exist_ok=True)
    with open(os.path.join(PROJ_DIR, "project.pbxproj"), "w", encoding="utf-8") as fh:
        fh.write(pbx)
    scheme_path = os.path.join(PROJ_DIR, "xcshareddata", "xcschemes", TARGET_NAME + ".xcscheme")
    with open(scheme_path, "w", encoding="utf-8") as fh:
        fh.write(scheme)

    print("wrote %s" % os.path.join(PROJ_DIR, "project.pbxproj"))
    print("wrote %s" % scheme_path)
    print("sources=%d resources=%d" % (len(SOURCES), len(RESOURCES)))
    return 0


def check() -> int:
    """不依赖 Xcode 的自检：括号平衡 + 每个被引用的 ID 都有定义 + 文件都在磁盘上。"""
    path = os.path.join(PROJ_DIR, "project.pbxproj")
    if not os.path.exists(path):
        print("缺少 %s" % path)
        return 1
    text = open(path, encoding="utf-8").read()

    bad = 0
    for left, right in (("{", "}"), ("(", ")")):
        if text.count(left) != text.count(right):
            print("括号不配对：%s=%d %s=%d" % (left, text.count(left), right, text.count(right)))
            bad += 1

    defined = set(re.findall(r"^\t\t([0-9A-F]{24}) ", text, re.M))
    used = set(re.findall(r"([0-9A-F]{24})", text))
    missing = used - defined
    if missing:
        print("被引用但没有定义：%s" % ", ".join(sorted(missing)))
        bad += 1

    for name in SOURCES + RESOURCES + [PLIST]:
        if not os.path.exists(os.path.join(APP_DIR, name)):
            print("磁盘上不存在：IoMonitor/%s" % name)
            bad += 1

    # 每个源文件都得出现在 Sources 阶段
    for name in SOURCES:
        if ("/* %s in Sources */" % name) not in text:
            print("没进 Sources 阶段：%s" % name)
            bad += 1

    print("objects=%d" % len(defined))
    print("FAIL" if bad else "OK")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
