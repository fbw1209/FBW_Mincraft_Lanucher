# FBW Minecraft Launcher (FML)

一个面向 Windows 的轻量 Minecraft 启动器，使用 Python + CustomTkinter 构建，浅色 Google 风格界面。

> 仓库：<https://github.com/fbw1209/FBW_Mincraft_Lanucher>
> 当前版本：1.1.0
> 支持平台：Windows 10 / 11

## 功能

- 浅色、简洁的 Google Material 风格界面
- 使用 Windows 原生列表控件，版本列表滚动更流畅
- 获取 Mojang 官方版本列表，支持 BMCLAPI 镜像回退
- 下载原版 Minecraft，并选择安装 Fabric / Forge / NeoForge / OptiFine
- 加载器版本按 PCL 命名规则合并为单个版本文件夹，例如：
  - `26.3-Fabric 0.20.1`
  - `1.12.2-Forge_14.23.5.2859`
  - `1.20.1-OptiFine_HD_U_I6`
- 合并版本自动创建 PCL 风格的目录：`mods`、`config`、`saves`、`resourcepacks`、`shaderpacks`、`logs`、`crash-reports`
- Fabric 安装或首次启动时自动补充 Fabric API
- 从 Modrinth / CurseForge 搜索并下载模组、光影、资源包、整合包
- 资源列表显示来自 Modrinth / CurseForge 的项目图片
- 版本管理：查看/删除存档，启用/禁用/删除模组
- 从列表隐藏版本、恢复隐藏版本、彻底删除版本文件
- 导出 `.bat` 启动脚本；参数过长时自动配套生成 `.ps1`
- 从版本文件夹、版本压缩包或其他游戏目录导入已有版本
- PCL 风格多关键词模糊搜索
- 自动检测本机 Java，并按游戏版本选择合适的大版本
- 缺少 Java 时自动下载 Mojang 官方运行时（包含 Java 8）
- 离线账户登录，自动生成离线 UUID
- 处理旧版资源映射、natives 解压、版本继承与启动参数
- 实时游戏日志窗口与启动器错误日志

## 下载与运行

### 单文件便携版

仓库中的 [`dist/FML.exe`](./dist/FML.exe) 是单文件便携版：

1. 将 `FML.exe` 放到一个**可写目录**（桌面、D 盘文件夹、U 盘等）
2. 双击运行
3. 首次运行会在 EXE 同级创建 `data/` 目录，用于配置、缓存、日志和自动下载的 Java

单文件版不需要安装 Python，但每次启动会先解压运行时，因此启动速度比源码运行稍慢。

### 从源码运行

```powershell
python -m pip install -r requirements.txt
python main.pyw
```

也可以双击 `启动器.bat`。该脚本会优先运行 `dist\FML.exe`，不存在时再运行源码。

## 使用流程

1. 打开“下载”页面，选中一个 Minecraft 版本
2. 点击“安装 / 选择加载器”
3. 选择原版、Fabric、Forge、NeoForge 或 OptiFine
4. 安装完成后在主页点击“开始游戏”

Fabric 会自动安装 Fabric API；Forge / NeoForge / OptiFine 会调用官方安装器。

## 数据位置

- 启动器配置：`data/config.json`
- 版本列表缓存：`data/cache/`
- 启动器日志：`data/logs/launcher.log`
- 自动下载的 Java：`data/runtime/`
- 默认游戏目录：`%APPDATA%\.minecraft`（可在设置中修改）
- 版本目录：`<游戏目录>/versions/<版本名>/`
- 版本隔离目录：`mods`、`saves`、`resourcepacks`、`shaderpacks` 等位于对应版本文件夹内

`data/` 不会提交到 Git 仓库，避免把个人配置上传。

## 构建单文件 EXE

```powershell
.\build.ps1
```

脚本会安装依赖和 PyInstaller，并生成：

```text
dist/FML.exe
```

手动构建：

```powershell
python -m PyInstaller --noconfirm --clean --onefile --windowed `
  --name FML `
  --icon "assets\icon.ico" `
  --add-data "assets;assets" `
  --collect-all customtkinter `
  "main.pyw"
```

## 项目结构

```text
FBW_Mincraft_Lanucher/
├─ main.pyw                  程序入口
├─ 启动器.bat                启动 EXE / 源码
├─ build.ps1                 单文件 EXE 构建脚本
├─ requirements.txt
├─ assets/
│  ├─ icon.ico
│  └─ icon.png
├─ launcher/
│  ├─ config.py              配置读写
│  ├─ net.py                 网络请求与多线程下载
│  ├─ version.py             版本列表、继承合并、规则与资源解析
│  ├─ installer.py           原版 / Fabric 安装与版本合并
│  ├─ loaders.py             Forge / NeoForge / OptiFine 安装
│  ├─ resources.py           Modrinth / CurseForge 搜索、下载与 Fabric API
│  ├─ importer.py            版本导入
│  ├─ java.py                Java 检测、选择与运行时下载
│  ├─ launch.py              启动参数、natives、实例目录与进程管理
│  ├─ paths.py               路径与常量
│  └─ ui/
│     ├─ app.py              主窗口、页面调度、任务队列
│     ├─ pages.py            主页 / 版本 / 下载 / 资源 / 设置
│     ├─ widgets.py          卡片、列表与状态组件
│     ├─ dialogs.py          加载器选择、版本管理、导入、日志窗口
│     └─ theme.py            浅色主题、原生列表样式与 HiDPI 图标
├─ tests/
│  └─ test_core.py           核心逻辑单元测试
└─ dist/
   └─ FML.exe                单文件便携版
```

## 测试

```powershell
python -m unittest discover -s tests -v
```

当前测试覆盖离线 UUID、Maven 路径、规则判断、版本继承、启动参数构建、合成版本安装和版本隔离目录识别。

已实际验证：

- Minecraft 1.0 + Java 8：安装并进入游戏
- Minecraft 26.3 + Java 25：安装并启动
- Minecraft 26.3 + Fabric Loader 0.20.1：安装并启动
- Minecraft 1.12.2 + Forge 14.23.5.2859：安装并启动
- Minecraft 1.12.2 + OptiFine HD_U_G5：安装成功
- 从其他游戏目录导入 1.12.2 / Forge / OptiFine 版本
- Modrinth / CurseForge 搜索、文件获取与下载

## 已知限制

- 仅支持离线账户，暂不支持 Microsoft 正版登录
- 整合包目前会下载到 `modpacks/`，不会自动创建独立实例
- NeoForge 安装需要能够访问 `maven.neoforged.net`；网络不可达时会提示
- CurseForge 使用公共镜像接口，镜像不可用时搜索会失败
- Quilt 自动安装尚未实现
- 单文件版需要在有写入权限的目录运行

## 说明

- 游戏文件来自 Mojang 官方服务器，镜像仅作为下载加速回退
- 本项目与 Mojang、Microsoft、PCL 无隶属关系
- 请仅下载和游玩你拥有合法授权的游戏

## License

MIT，见 [LICENSE](./LICENSE)。
