# GitDiffHelper (GD)

GD 是一款面向开发者和 Tech Lead 的命令行工具，通过 GitLab API 快速审计多个私有代码仓的分支差异，并提供一键创建同步 MR 的功能，解决微服务架构下代码同步状态难追踪、发布流程繁琐的问题。

## 功能特性

### 核心功能
- **配置管理与继承**：支持全局配置、分组管理和配置继承
- **仓库与状态扫描**：支持仓库搜索、完整性检查和状态快照
- **自动化流水线操作**：自动创建 MR、检查存量 MR、打 Tag 功能
- **可视化反馈**：使用颜色标识同步、领先、落后等风险状态

### 命令列表

#### 基础管理
| 命令 | 说明 |
| --- | --- |
| `gd search <key>` | 搜索远端所有可访问仓库及 ID |
| `gd add <id> [-g group]` | 将仓库加入本地配置，可选指定分组 |
| `gd list` | 查看当前配置的所有分组及仓库架构 |

#### 审计与状态
| 命令 | 说明 |
| --- | --- |
| `gd verify` | 检查配置仓库的权限和分支有效性 |
| `gd status` | 全局总览：所有仓库的 Diff 简报（颜色标记） |
| `gd status <id>` | 交互式详情：查看特定仓的 Commit 列表、作者及内容 |

#### 同步操作
| 命令 | 说明 |
| --- | --- |
| `gd sync <id> --to-master` | 创建开发到主干的 MR（发布预览） |
| `gd sync <id> --to-dev` | 创建主干到开发的 MR（回流同步） |
| `gd tag <id> <version>` | 在指定仓库打上新 Tag |

## 环境要求

- Python 3.7+
- GitLab API 访问权限（需要 api 作用域的访问令牌）

## 安装

### 1. 克隆代码
```bash
git clone <repository-url>
cd git_diff_helper
```

### 2. 安装依赖
```bash
pip install -r requirements.txt
```

### 3. 配置环境变量
复制 `.env.example` 文件为 `.env` 并填写配置：

```bash
cp .env.example .env
# 编辑 .env 文件，填写 GitLab URL 和 Token
```

### 4. 配置别名（可选）
为了方便使用，可以在 `~/.bashrc` 或 `~/.zshrc` 中添加别名：

```bash
alias gd="python3 /path/to/git_diff_helper/gd.py"
```

## 快速开始

### 1. 搜索仓库
```bash
gd search <关键词>
```

### 2. 添加仓库
```bash
# 添加仓库到默认分组
gd add <仓库ID>

# 添加仓库到指定分组
gd add <仓库ID> -g <分组名>
```

### 3. 查看仓库列表
```bash
gd list
```

### 4. 验证仓库权限
```bash
gd verify
```

### 5. 查看仓库状态
```bash
# 查看所有仓库状态
gd status

# 查看单个仓库详细状态
gd status <仓库ID>
```

### 6. 同步仓库并创建 MR
```bash
# 从 develop 同步到 master
gd sync <仓库ID> --to-master

# 从 master 同步到 develop
gd sync <仓库ID> --to-dev
```

### 7. 创建标签
```bash
gd tag <仓库ID> <版本号>
```

## 配置文件结构

配置文件存储在 `~/.gd/config.yaml`，结构如下：

```yaml
global:
  gitlab_url: "https://gitlab.example.com"
  token: "your-token"
  default_branch: "master"
groups:
  group1:
    # 组级配置
repos:
  "123":
    name: "project-name"
    path: "namespace/project-name"
    group: "group1"
    # 仓库级配置（会覆盖组和全局配置）
```

## 注意事项

1. **API 限制**：频繁调用 GitLab API 可能会触发速率限制，建议合理使用
2. **权限问题**：确保你的 GitLab Token 具有足够的权限（需要 api 作用域）
3. **安全性**：Token 存储在本地，请确保文件权限设置为 600（仅当前用户读写）
4. **分支命名**：默认使用 `develop` 和 `master` 分支，如需修改请在配置文件中设置

## 故障排查

### 常见问题

1. **API 请求失败**：检查 GitLab URL 和 Token 是否正确，网络连接是否正常
2. **权限不足**：确保 Token 具有 api 作用域，并且对目标仓库有访问权限
3. **分支不存在**：确保仓库中存在 `develop` 和 `master` 分支

### 日志

工具会在执行过程中输出详细的日志信息，如遇到问题，请查看终端输出的错误信息。

## 开发与扩展

### 开发流程

1. **环境初始化**：实现 `~/.gd/` 目录的自动创建和 `config.yaml` 的读写逻辑
2. **继承逻辑实现**：编写配置解析器，确保 Repo 能够正确继承 Group 或 Global 的分支配置
3. **GitLab 客户端封装**：基于 `requests` 封装基础 API（Projects, Commits, Compare）
4. **只读审计功能**：实现 `gd search` 和 `gd status` 命令
5. **写操作与 MR 自动化**：实现 `gd sync` 和 `gd tag` 命令
6. **优化与分发**：添加本地缓存，使用 `PyInstaller` 打包成独立二进制文件

### 扩展建议

- 添加支持 GitHub 的适配器
- 实现更复杂的分组策略
- 添加 Web 界面
- 集成 CI/CD 流程

## 许可证

[MIT License](LICENSE)
