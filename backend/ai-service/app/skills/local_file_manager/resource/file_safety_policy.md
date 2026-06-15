# Local File Manager — 文件安全操作策略

本文档是 Local File Manager Skill 的核心资源文档，定义了 AI 操作本地文件系统时必须遵守的安全底线、系统默认路径参考以及用户自定义的快速路径映射和白名单路径。

---

## 一、系统默认路径快照

以下为宿主机核心用户目录的绝对路径映射，AI 在涉及路径推断时优先参考此映射，禁止凭空猜测。

### Windows

| 目录名 | 典型绝对路径 | 说明 |
|--------|-------------|------|
| Desktop | `C:/Users/Xie/Desktop` | 桌面目录 |
| Downloads | `C:/Users/Xie/Downloads` | 下载目录 |
| Documents | `C:/Users/Xie/Documents` | 文档目录 |
| Pictures | `C:/Users/Xie/Pictures` | 图片目录 |
| Music | `C:/Users/Xie/Music` | 音乐目录 |
| Videos | `C:/Users/Xie/Videos` | 视频目录 |
| AppData\Local | `C:/Users/Xie/AppData/Local` | 本地应用数据 |
| AppData\Roaming | `C:/Users/Xie/AppData/Roaming` | 漫游应用数据 |

---

## 二、用户自定义快速路径映射

```yaml
当前项目所在的文件夹: "F:\YilenaCode\Luna-AI"
应用软件数据存放的盘: "D:\" 
跟学校相关的资料存放的文件夹: "E:\AAAAAA学校相关\"
跟就业相关的资料存放的文件夹: "E:\AAAAA就业相关\"
用户代码项目ma的文件夹: "F:\YilenaCode"
```

## 三、用户自定义白名单路径

```yaml
allowed_safe_zone:
    - "D:/"
    - "E:/"
    - "F:/"
```

---

## 四、文件安全操作策略

### 4.1 绝对禁止操作的系统保护目录（Windows）

| 目录 | 原因 |
|------|------|
| `C:/Windows` | 操作系统核心文件 |
| `C:/Windows/System32` | 系统关键二进制文件 |
| `C:/Windows/System` | 系统关键文件 |
| `C:/Program Files` | 已安装程序目录 |
| `C:/Program Files (x86)` | 已安装 32 位程序目录 |
| `C:/ProgramData` | 应用程序共享数据 |
| `C:/System Volume Information` | 系统卷信息（影子存储） |
| `C:/$Recycle.Bin` | 回收站 |
| `C:/Boot` | 引导文件 |
| `C:/Users/Default` | 默认用户配置文件模板 |

### 4.2 绝对禁止操作的系统保护目录（macOS/Linux）

| 目录 | 原因 |
|------|------|
| `/System` (macOS) | 操作系统核心文件 |
| `/bin` | 系统二进制文件 |
| `/sbin` | 系统管理二进制文件 |
| `/etc` | 系统配置文件 |
| `/var` | 可变数据（日志、数据库） |
| `/usr` | Unix 系统资源 |
| `/boot` | 引导文件 |
| `/dev` | 设备文件 |
| `/proc` | 进程文件系统 |
| `/root` | root 用户主目录 |
| `/private` (macOS) | macOS 私有系统文件 |

### 4.3 高危操作安全规程

| 操作 | 风险等级 | 安全规程 |
|------|---------|---------|
| 删除文件/目录 | L3 | 路径必须确认 → 非保护路径 → 用户 Gating 强警告确认 → 审计日志 |
| 写入/覆盖文件 | L2 | 覆盖前预警 → 禁止写入保护目录 → 超 10MB 拒绝 |
| 移动/重命名 | L2 | 源路径必须存在 → 目标父目录必须存在 → 禁止穿越保护区 |
| 全局搜索 | L0 | 60 秒超时 → 8 层深度限制 → 自动排除系统目录 |
| 列出目录 | L0 | 路径校验 → 无副作用直接放行 |
| 读取元数据 | L0 | 路径校验 → 无副作用直接放行 |

---

## 五、风险等级映射

| 工具名 | 风险等级 | 是否需要 Gating |
|--------|---------|----------------|
| `list_directory` | L0 | 否 |
| `read_file_metadata` | L0 | 否 |
| `search_files_global` | L0 | 否 |
| `move_or_rename_file` | L2 | 是（中度确认） |
| `create_or_write_file` | L2 | 是（中度确认） |
| `delete_local_file` | L3 | 是（强警告） |

---

## 六、文件搜索策略

### 搜索范围选择

| 场景 | 推荐策略 | 说明 |
|------|---------|------|
| 知道具体路径 | 直接使用 `list_directory` | 最快速 |
| 只知道文件名 | 使用 `search_files_global` | 指定 pattern |
| 不确定位置 | 先 `list_directory` 常用目录 | 缩小范围后全局搜索 |

### 搜索模式技巧

| 模式 | 匹配规则 | 示例 |
|------|---------|------|
| `*.pdf` | 所有 PDF 文件 | `*.pdf` → report.pdf |
| `report_*` | 以 report_ 开头 | `report_*` → report_2024.docx |
| `*重要*` | 文件名包含"重要" | `*重要*` → 重要通知.txt |
| 精确文件名 | 完全匹配 | `report.docx` → 只匹配 report.docx |

### 搜索性能

- **深度限制**：搜索深度不超过 8 层目录
- **超时控制**：60 秒超时返回部分结果
- **排除目录**：自动排除 `$Recycle.Bin`、`System Volume Information`、`.git`、`node_modules` 等

---

## 七、错误处理与降级策略

| 现象 | 可能原因 | 处理建议 |
|------|---------|---------|
| 路径不存在 | 用户提供的路径有误 | 使用 `list_directory` 或 `search_files_global` 确认 |
| 权限不足 | 进程无权限访问目标 | 建议以管理员身份运行 |
| 文件被占用 | 其他进程正在使用该文件 | 关闭相关程序后重试 |
| 磁盘空间不足 | 写入时磁盘已满 | 清理磁盘空间后重试 |
| 路径名过长 | Windows 路径超过 260 字符 | 将文件移至较浅目录层次 |

**降级策略**：
1. 第一级：返回具体错误信息和建议操作
2. 第二级：路径不存在 → 建议搜索正确路径
3. 第三级：权限不足 → 建议管理员模式或切换目录

---

## 八、隐私与安全注意事项

1. **路径脱敏**：日志输出时必须对用户名路径进行脱敏处理，替换为 `[REDACTED]`
2. **禁止漫游**：禁止 AI 在没有用户明确指示的情况下自动扫描非用户数据目录
3. **删除可追溯**：所有删除操作必须记录完整审计日志
4. **写入限制**：禁止 AI 主动向系统敏感路径写入任何文件
5. **用户数据边界**：操作范围应限制在用户个人目录内

---

## 九、工具参数快速参考

| 工具名 | 风险等级 | 必填参数 | 可选参数 | 说明 |
|--------|---------|---------|---------|------|
| `list_directory` | L0 | `path` | — | 列出目录内容 |
| `read_file_metadata` | L0 | `path` | — | 读取文件元数据 |
| `search_files_global` | L0 | `pattern` | `drive` | 全局文件搜索 |
| `move_or_rename_file` | L2 | `source_path`, `destination_path` | `overwrite` | 移动/重命名 |
| `create_or_write_file` | L2 | `path`, `content` | `mode` | 写入/创建文件 |
| `delete_local_file` | L3 | `path` | `recursive` | 删除文件/目录 |
