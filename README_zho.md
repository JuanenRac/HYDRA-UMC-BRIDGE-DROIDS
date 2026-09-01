<!-- =============================================================================
HYDRA-UMC-BRIDGE-DROIDS - 有腿式/人形机器人双向协调桥接
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
============================================================================= -->

<p align="center">
  <img src="images/HYDRA_UMC_BANNER.svg" alt="HYDRA-UMC-BRIDGE-DROIDS 横幅" width="100%">
</p>

# 🤖 HYDRA-UMC-BRIDGE-DROIDS

<p align="center"><a href="README.md">🇺🇸 English</a> | <a href="README_spa.md">🇪🇸 Español</a> | <a href="README_fra.md">🇫🇷 Français</a> | <a href="README_ita.md">🇮🇹 Italiano</a> | <a href="README_deu.md">🇩🇪 Deutsch</a> | 🇨🇳 <b>简体中文</b> | <a href="README_jpn.md">🇯🇵 日本語</a></p>

### 🔗 HYDRA-UMC 与有腿式/人形机器人之间无依赖的协调边界

<p align="left">
  <img src="https://img.shields.io/badge/许可证-GPL%203.0-blue.svg" alt="GPL 3.0">
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB.svg" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/Safety-Fails%20Closed-red.svg" alt="故障安全">
</p>

---

## 1. 🛠️ 技术概览

**HYDRA-UMC-BRIDGE-DROIDS** 是 HYDRA-UMC 与有腿式或人形机器人平台之间双向的高层协调边界,可通过 Wi-Fi、蓝牙或蜂窝(4G/5G)链路访问。它从不计算步态、平衡或关节轨迹:它校验并转发一套小型的、具名的全身动作触发器词汇(`WALK_TO`、`PICK_OBJECT`、`PLACE_OBJECT`、`RETURN_HOME`、`HOLD_POSITION`),每一个都有自己真实的必填参数契约。它不是一个电机控制节点,也不能绕过 HYDRA-UMC-SERVER、MCU 限位、看门狗或急停(E-STOP)。

它与 `HYDRA-UMC-BRIDGE-AMR` 和 `HYDRA-UMC-BRIDGE-UAV` 同属 **Mobile & Autonomous Bridges** 家族,并与固定式的 **External Automation Bridges**(CNC、LASER、OPENPNP、PRINTER3D、ROS2)共享同一个 `HYDRA-UMC-SDK` 任务与安全契约——因此无论是移动式还是固定式,任何一个桥接都不能自行发明"可以安全工作"的定义。

### 核心特性:
* ✅ **真实的无依赖协调核心:** `coordinator.py` 中的 `DroidCoordinator` 完全没有导入任何传输相关模块(既无 socket,也无厂商 SDK)——它刻意保持为纯 Python,可以在任何主机上测试,无需连接真实的机器人。*(已实现,并在 `tests/test_coordinator.py` 中测试)*
* ✅ **真实的具名动作触发器词汇:** `WALK_TO`、`PICK_OBJECT`、`PLACE_OBJECT`、`RETURN_HOME`、`HOLD_POSITION`——绝不是原始关节指令。全身步态、平衡和关节级控制仍然是机器人自身板载控制器(Jetson 级或同等水平)的专属权限。*(已实现)*
* ✅ **真实的按动作参数校验:** 每个动作触发器都有自己真实的、最小化的必填参数契约(例如 `WALK_TO` 需要 `x`/`y`),在任务被转发之前就会进行检查——缺少其对应动作所需参数的请求会在本地被拒绝,而不会被悄悄传递到下游。*(已实现,已测试)*
* ✅ **真实的共享安全门控:** 每个通过 `DroidCoordinator.dispatch()` 派发的任务都会由 `HYDRA-UMC-SDK` 的 `bridge_contract` 中的 `evaluate_job()` 评估,这与所有兄弟桥接以及 HYDRA-UMC-SERVER 使用的是同一个门控;生产性阶段需要外部机器处于 `IDLE` 且 HYDRA-UMC 单元处于 `READY`,而 `HOLD_POSITION`(从 `ABORT` 映射而来)在故障期间仍可请求。*(已实现)*
* ✅ **安全拒绝的阶段路由与静态证据:** 未知的未来 SDK 阶段会被拒绝,而不是被猜测处理。`inspect_action_plan.py` 会输出静态模式 `1.0` 的动作计划,且不会打开任何传输通道。*(已实现,已测试)*
* ✅ **非变更式构建/测试:** `build-test.bat`/`.sh` 编译源码并运行确定性单元测试,不改变版本或 CHANGELOG。*(已实现,见下方"构建与运行")*
* 🔜 **真实的 Wi-Fi/BT/4G-5G 传输适配器,以及有文档记录的机器人命令接口**——只有在选定并测试了真实平台之后才会引入。*(计划中)*

---

## 2. 🔄 机器人协调流程

```mermaid
flowchart LR
    DROID["有腿式/人形机器人<br/>(Wi-Fi / BT / 4G-5G)"] -- "动作触发器" --> BRIDGE["BRIDGE-DROIDS<br/>DroidCoordinator.dispatch()"]
    BRIDGE -- BridgeJob --> SDK["HYDRA-UMC-SDK<br/>evaluate_job()"]
    SDK -- GateDecision --> SERVER["HYDRA-UMC-SERVER"]
    SERVER -- "任务 / 中止" --> MCU["MCU 安全"]
```

---

## 3. 🧱 架构与设计决策

* **为什么核心从不计算步态或平衡。** 机器人自身的板载计算单元(Jetson 级或同等水平)已经运行着一个真实的、针对具体硬件的全身控制器——在这里重新推导这一套要么会拙劣地重复它,要么会与它产生冲突。只发送具名的目的地/动作触发器(`WALK_TO x y`、`PICK_OBJECT object_id`)让 HYDRA-UMC 的角色始终停留在协调层面,这与本项目起步时所依据的架构笔记一致:"不要在核心中计算机器人的步态"。
* **为什么每个动作触发器都有自己明确的必填参数列表。** 没有 `x`/`y` 的 `WALK_TO`,或没有 `object_id` 的 `PICK_OBJECT`,是一种真实的、可被捕获的请求格式错误——在任何传输发生之前就在这里拒绝它,严格优于转发一条不完整的指令然后寄望于机器人自身的固件也能安全地拒绝它。
* **为什么 `DroidCoordinator.dispatch()` 仍然让每个任务都经过共享的 `evaluate_job()` 门控。** 机器人只是使用与 CNC、LASER、OPENPNP、PRINTER3D 和 ROS2 相同的 `bridge_contract` 的又一个客户端——它不会获得任何绕过所有其他桥接和 HYDRA-UMC-SERVER 所执行的 IDLE/READY 逻辑的特殊待遇。
* **为什么 `HOLD_POSITION`(源自 `ABORT`)在故障期间仍可请求。** 门控的生产性阶段要求(`IDLE` + `READY`)被刻意地不以同样的方式应用于中止请求——操作员必须始终能够要求机器人原地静止,即使正处于故障中,而不是继续执行它正在做的事情。
* **为什么传输适配器和具体的命令接口尚未加入本仓库。** 在选定并测试某个具体机器人平台的真实 Wi-Fi/BT/4G-5G 命令协议之前就对其做出承诺,会有引入这个本地无依赖核心无法验证的假设的风险。
* **它如何融入整个生态系统。** BRIDGE-DROIDS 位于真实机器人与 `HYDRA-UMC-SDK` → `HYDRA-UMC-SERVER` → MCU 安全之间——它是一个协调边界,绝不是电机控制节点,也不能绕过 HYDRA-UMC-SERVER、MCU 限位、看门狗或急停。

---

## 📂 目录结构

```text
HYDRA-UMC-BRIDGE-DROIDS/
├── src/
│   └── hydra_umc_bridge_droids/
│       ├── __init__.py
│       └── coordinator.py       # DroidCoordinator:无依赖的动作触发器门控
├── tests/
│   └── test_coordinator.py      # 协调核心的确定性单元测试
├── tools/
│   ├── build_test.py            # 非变更式编译 + 测试运行器 (build-test.bat/.sh)
│   ├── bump_version.py          # 同步 pyproject.toml、清单和 CHANGELOG.md
│   └── inspect_action_plan.py   # 打印静态动作计划(不打开传输通道)
├── docs/
│   └── BRIDGE_GUIDE.md          # 范围、兼容平台、脚本、硬件验收门控
├── build-test.bat / build-test.sh  # 仅验证,绝不修改仓库
├── build.bat / build.sh            # 先验证,成功后才更新版本 + CHANGELOG
├── pyproject.toml               # 包元数据;依赖 HYDRA-UMC-SDK (git)
├── hydra-umc.project.json       # 生态系统清单(版本、成熟度、家族)
├── CHANGELOG.md
├── CODE_OF_CONDUCT.md / CONTRIBUTING.md / SECURITY.md / SUPPORT.md
├── LICENSE / LICENSE.md
└── README.md / README_*.md      # 本文件及其 6 种译文
```

---

## 4. ⚙️ 构建与运行

需要 Python 3.11+。`tools/build_test.py` 期望 `HYDRA-UMC-SDK` 作为兄弟目录被检出(`../HYDRA-UMC-SDK`),或通过环境变量 `HYDRA_UMC_SDK_ROOT` 指定。

```bash
# Windows
build-test.bat      # 仅验证 —— 不改变版本/CHANGELOG
build.bat            # 先验证,成功后更新版本 + CHANGELOG

# Linux/macOS
bash build-test.sh
bash build.sh
```

`build-test` 使用 `py_compile` 编译 `src/` 下的每个模块,并运行完整的 `unittest` 套件(`tests/test_coordinator.py`)——以确定性的方式进行,没有真实机器人连接,没有网络,也不会改变版本/CHANGELOG。`build` 会先运行同样的验证,只有成功后才调用 `tools/bump_version.py`,在 `pyproject.toml`、`hydra-umc.project.json` 和 `CHANGELOG.md` 之间同步版本号。目前尚无真正的硬件 `run` 命令——这需要经过验证的传输适配器和真实的机器人平台。

---

## ✅ 当前状态与后续步骤

**目前真实的部分:** 版本 `0.0.1`,作为一个无依赖协调核心(`DroidCoordinator`)是功能齐备的,配有真实的按动作参数校验、安全拒绝的阶段路由、静态 `plan-only` 动作模式,以及已接入 CI 并带 SDK 检出的非变更式 build-test 脚本。

**集成边界:** 本桥接只是一个协调边界——它不是电机控制节点,也不能绕过 HYDRA-UMC-SERVER、MCU 限位、看门狗或急停;每个被派发的任务仍然要经过所有兄弟桥接使用的同一个共享门控。

**仍待完成:** 尚未验证任何真实传输方式(Wi-Fi/BT/4G-5G)或物理机器人——真实的传输适配器和有文档记录的机器人命令接口只会在选定并测试了具体平台之后才会引入。

---

## 🔗 相关项目

本项目是同一作者(JuanenRac / Electro Hobby 3D)更大的机器人生态系统的一部分,涵盖固件、控制软件、AI 节点和车队工具。了解这一点很有必要,因为某个请求实际上可能与这些项目之一有关,而不是与本仓库有关。

### 直接相关

- **[HYDRA-UMC-SDK](https://github.com/JuanenRac/HYDRA-UMC-SDK)** —— 共享的任务与安全契约,本桥接(以及所有其他桥接)都通过它评估任务。
- **[HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER)** —— 本桥接汇报的经过身份验证的生态系统边界。
- **[HYDRA-UMC-BRIDGE-AMR](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-AMR)** —— 面向 AGV/AMR 车队的兄弟移动桥接。
- **[HYDRA-UMC-BRIDGE-UAV](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-UAV)** —— 面向无人机的兄弟移动桥接。

### 生态系统的其余部分

**HYDRA-UMC 平台** —— 本桥接为其协调辅助功能的多机器人微工厂
- **[HYDRA-UMC](https://github.com/JuanenRac/HYDRA-UMC)** —— 协调多达 8 条机械臂的 CM5 + STM32H745 主板。
- **[HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER)** —— 每个控制客户端和桥接都会对接的 Express/WebSocket 后端。
- **[HYDRA-UMC-STUDIO](https://github.com/JuanenRac/HYDRA-UMC-STUDIO)** —— 基于网页的控制仪表盘,多机器人 3D 可视化。

**External Automation Bridges** —— 共享同一个 `HYDRA-UMC-SDK` 任务门控的兄弟仓库
- **[HYDRA-UMC-BRIDGE-CNC](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-CNC)** —— CNC 单元协调桥接。
- **[HYDRA-UMC-BRIDGE-LASER](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-LASER)** —— 激光单元协调桥接。
- **[HYDRA-UMC-BRIDGE-OPENPNP](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-OPENPNP)** —— 面向 OpenPnP 的板级流程桥接。
- **[HYDRA-UMC-BRIDGE-PRINTER3D](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-PRINTER3D)** —— 面向开源 3D 打印软件的协调桥接。
- **[HYDRA-UMC-BRIDGE-ROS2](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-ROS2)** —— 面向任意 ROS 2 平台的通用协调桥接。

**安全与集成证据**
- **[HYDRA-UMC-SAFETY-ZONES](https://github.com/JuanenRac/HYDRA-UMC-SAFETY-ZONES)** —— 整个桥接家族共用的单元区域安全证据。
- **[HYDRA-UMC-HIL-BRIDGE](https://github.com/JuanenRac/HYDRA-UMC-HIL-BRIDGE)** —— 硬件在环测试证据。

## 👤 作者
**JuanenRac** (Electro Hobby 3D)
📧 electrohobby3d@gmail.com
📺 [youtube.com/@electrohobby3d](https://youtube.com/@electrohobby3d)

## 📜 许可证
GPL-3.0 - 详见 LICENSE。
