# Desktop Operation Skill 策略文档

## 概述

Desktop Operation Skill 提供桌面自动化能力，包含屏幕截图、应用启动/关闭、鼠标控制、键盘控制等工具。所有操作均在本地执行，遵循本地优先原则。

## 屏幕坐标系说明

### 坐标原点
- 屏幕左上角为坐标原点 `(0, 0)`。
- X 轴向右递增，Y 轴向下递增。

### 多屏场景
- 主显示器索引为 `0`，副显示器索引递增。
- 多屏时坐标空间为虚拟屏幕空间，副屏坐标可能为负值（位于主屏左侧或上方时）。
- 使用 `screen_index` 参数指定目标显示器。

### DPI 缩放
- 系统会自动检测 DPI 缩放比例（如 125%、150%、200%）。
- 坐标始终使用物理像素值，无需手动换算。
- 截图返回的图片尺寸为物理像素尺寸。

## 常见应用路径映射

### Windows 系统
| 应用名称 | 进程名 | 常见安装路径 |
|---------|--------|-------------|
| 记事本 | notepad.exe | C:\Windows\System32\notepad.exe |
| 计算器 | calc.exe | C:\Windows\System32\calc.exe |
| 画图 | mspaint.exe | C:\Windows\System32\mspaint.exe |
| 命令提示符 | cmd.exe | C:\Windows\System32\cmd.exe |
| 任务管理器 | taskmgr.exe | C:\Windows\System32\taskmgr.exe |
| 资源管理器 | explorer.exe | C:\Windows\explorer.exe |
| Chrome | chrome.exe | C:\Program Files\Google\Chrome\Application\chrome.exe |
| Firefox | firefox.exe | C:\Program Files\Mozilla Firefox\firefox.exe |
| Edge | msedge.exe | C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe |
| VS Code | code.exe | C:\Users\{user}\AppData\Local\Programs\Microsoft VS Code\Code.exe |

### macOS 系统
| 应用名称 | 进程名 | 常见安装路径 |
|---------|--------|-------------|
| 文本编辑 | TextEdit | /Applications/TextEdit.app |
| 计算器 | Calculator | /Applications/Calculator.app |
| 终端 | Terminal | /Applications/Utilities/Terminal.app |
| 活动监视器 | Activity Monitor | /Applications/Utilities/Activity Monitor.app |
| 访达 | Finder | /System/Library/CoreServices/Finder.app |
| Safari | Safari | /Applications/Safari.app |
| Chrome | Google Chrome | /Applications/Google Chrome.app |

## 安全操作规范

### 风险等级说明

| 等级 | 含义 | 工具 | 是否需要用户确认 |
|-----|------|------|----------------|
| L0 | 低危，只读操作 | screenshot | 不需要 |
| L1 | 低危，有副作用但通常可逆 | open_application, mouse_control, keyboard_control | 不需要 |
| L2 | 中危，可能导致数据丢失 | close_application | 需要（前端 Gating） |

### 禁止操作清单

#### 禁止强制终止的系统关键进程
- **Windows**: `explorer.exe`, `svchost.exe`, `lsass.exe`, `csrss.exe`, `smss.exe`, `wininit.exe`, `winlogon.exe`, `services.exe`, `system`
- **数据库服务**: `postgres.exe`, `redis-server.exe`, `mysqld.exe`, `mongod.exe`
- **安全软件**: `MsMpEng.exe`（Windows Defender）

#### 禁止执行的鼠标操作
- 点击涉及金融交易、密码输入、删除确认等敏感按钮（未经用户明确授权）。
- 在未知弹窗上点击"确定"或"是"。

#### 禁止执行的键盘操作
- 输入用户密码、银行卡号等敏感信息（未经用户明确授权）。
- 触发系统级危险快捷键（如 `Ctrl+Alt+Delete` 后选择"关机"）。

## 错误处理与降级策略

### 截图失败
- **原因**: 权限不足、显示器断开、DPI 变更。
- **处理**: 返回错误信息，建议检查显示设置。

### 应用启动失败
- **原因**: 应用未安装、路径错误、权限不足。
- **处理**: 返回错误信息，建议提供完整路径或确认安装状态。

### 坐标越界
- **原因**: 坐标超出屏幕范围、多屏配置变更。
- **处理**: 返回有效坐标范围，建议重新获取屏幕信息。

### 进程关闭失败
- **原因**: 进程不存在、权限不足、进程受保护。
- **处理**: 返回错误信息，建议使用任务管理器手动处理。

## 隐私安全注意事项

1. **截图隐私**: 截图可能包含敏感信息（密码、个人信息、机密文档），返回前应提醒用户。
2. **键盘记录**: 键盘输入内容不会被记录到日志，但会在审计日志中记录操作事件。
3. **进程信息**: 进程列表可能包含用户正在运行的应用信息，仅在必要时获取。
4. **本地执行**: 所有操作均在本地执行，不会将屏幕内容或输入数据上传到云端。

## 工具参数快速参考

### screenshot
```
region: {left, top, width, height}  # 可选，不传则全屏
screen_index: 0                      # 可选，默认主屏
output_format: "png" | "jpeg"       # 可选，默认 png
save_path: "..."                     # 可选，不传则返回 base64
```

### open_application
```
app_name: "notepad"                  # 必填，应用名或路径
arguments: ["--new-window"]          # 可选，启动参数
working_directory: "C:\\"            # 可选，工作目录
wait_for_start: false                # 可选，是否等待启动
```

### mouse_control
```
action: "move" | "click" | "double_click" | "drag" | "scroll"
x, y: 坐标                           # move/click/double_click/drag 必填
button: "left" | "right" | "middle"  # 可选，默认 left
end_x, end_y: 拖拽终点               # action=drag 时必填
scroll_direction: "up" | "down"      # action=scroll 时必填
scroll_steps: 3                      # 可选，默认 3
duration: 0.1                        # 可选，移动动画时长
```

### keyboard_control
```
action: "type_text" | "press_key" | "release_key" | "hotkey"
text: "..."                          # action=type_text 时必填
key: "enter"                         # action=press_key/release_key 时必填
keys: ["ctrl", "c"]                  # action=hotkey 时必填
interval: 0.01                       # 可选，字符间隔
press_duration: 0.05                 # 可选，按键按下时长
```

### close_application
```
pid: 1234                            # 可选，与 process_name 二选一
process_name: "notepad.exe"          # 可选，与 pid 二选一
force: false                         # 可选，默认 false
timeout: 5.0                         # 可选，优雅退出超时
```
