# GitDiffHelper 配置指南

## 配置命令

GitDiffHelper 提供了 `config` 命令来管理配置，支持以下子命令：

- `config set <key> <value>`: 设置配置
- `config get <key>`: 获取配置

## 配置项清单

### 1. 全局配置 (global.*)

| 配置项 | 说明 | 默认值 | 示例 |
|--------|------|--------|------|
| global.gitlab_url | GitLab 服务器 URL | 空字符串 | `https://git.example.com` |
| global.token | GitLab 访问令牌 | 空字符串 | `your_private_token` |
| global.default_branch | 默认分支名称 | master | `main` |
| global.test_branch | 测试分支名称 | develop | `dev` |
| global.prod_branch | 生产分支名称 | master | `main` |

### 2. 分组配置 (groups.<group_name>.*)

| 配置项 | 说明 | 默认值 | 示例 |
|--------|------|--------|------|
| groups.<group_name>.default_branch | 分组默认分支 | 继承全局配置 | `main` |
| groups.<group_name>.test_branch | 分组测试分支 | 继承全局配置 | `dev` |
| groups.<group_name>.prod_branch | 分组生产分支 | 继承全局配置 | `main` |

### 3. 仓库配置 (repos.<repo_id>.*)

| 配置项 | 说明 | 默认值 | 示例 |
|--------|------|--------|------|
| repos.<repo_id>.name | 仓库名称 | 无 | `My Project` |
| repos.<repo_id>.path | 仓库路径 | 无 | `namespace/project` |
| repos.<repo_id>.group | 所属分组 | 无 | `my_group` |
| repos.<repo_id>.default_branch | 仓库默认分支 | 继承分组或全局配置 | `main` |
| repos.<repo_id>.test_branch | 仓库测试分支 | 继承分组或全局配置 | `dev` |
| repos.<repo_id>.prod_branch | 仓库生产分支 | 继承分组或全局配置 | `main` |

## 配置优先级

配置遵循以下优先级（从高到低）：
1. 仓库级别的配置
2. 分组级别的配置
3. 全局配置
4. 硬编码的默认值

## 示例

### 设置全局默认分支
```bash
gd config set global.default_branch main
```

### 获取全局GitLab URL
```bash
gd config get global.gitlab_url
```

### 设置分组的测试分支
```bash
gd config set groups.integration.test_branch develop
```

### 设置仓库的生产分支
```bash
gd config set repos.1234.prod_branch main
```