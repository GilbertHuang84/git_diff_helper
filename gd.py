#!/usr/bin/env python3
"""GitDiffHelper (GD) - 多仓库Git差异管理工具"""

import os
import sys
import yaml
import asyncio
import argparse
import requests
from rich.console import Console
from rich.table import Table
from rich.progress import Progress

# 加载.env文件
if os.path.exists('.env'):
    with open('.env', 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                key, value = line.split('=', 1)
                os.environ[key] = value

# 全局变量
CONFIG_DIR = os.path.expanduser('~/.gd')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config.yaml')
CACHE_DIR = os.path.join(CONFIG_DIR, 'cache')

# 确保控制台输出正常
console = Console(force_terminal=True)

class ConfigManager:
    """配置管理类"""
    def __init__(self):
        self._ensure_config_dir()
        self.config = self._load_config()
        self._load_env_vars()
        # 保存加载了环境变量的配置
        self.save()
    
    def _ensure_config_dir(self):
        """确保配置目录存在"""
        if not os.path.exists(CONFIG_DIR):
            os.makedirs(CONFIG_DIR)
        if not os.path.exists(CACHE_DIR):
            os.makedirs(CACHE_DIR)
    
    def _load_config(self):
        """加载配置文件"""
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
                # 确保配置结构完整
                if 'global' not in config:
                    config['global'] = {
                        'gitlab_url': '',
                        'token': '',
                        'default_branch': 'master'
                    }
                if 'groups' not in config:
                    config['groups'] = {}
                if 'repos' not in config:
                    config['repos'] = {}
                if 'current_group' not in config:
                    config['current_group'] = ''
                return config
        # 创建默认配置
        default_config = {
            'global': {
                'gitlab_url': '',
                'token': '',
                'default_branch': 'master'
            },
            'groups': {},
            'repos': {},
            'current_group': ''
        }
        # 保存默认配置到文件
        self.save_config(default_config)
        return default_config
    
    def save_config(self, config):
        """保存配置到文件"""
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
    
    def _load_env_vars(self):
        """从环境变量加载配置"""
        if os.environ.get('GITLAB_TOKEN'):
            self.config['global']['token'] = os.environ['GITLAB_TOKEN']
        if os.environ.get('GITLAB_URL'):
            self.config['global']['gitlab_url'] = os.environ['GITLAB_URL']
    
    def save(self):
        """保存配置文件"""
        self.save_config(self.config)
    
    def get_repo_config(self, repo_id):
        """获取仓库配置，支持继承"""
        repo_config = self.config.get('repos', {}).get(repo_id, {})
        group_id = repo_config.get('group')
        
        # 继承组配置
        if group_id and group_id in self.config.get('groups', {}):
            group_config = self.config['groups'][group_id]
            for key, value in group_config.items():
                if key not in repo_config:
                    repo_config[key] = value
        
        # 继承全局配置
        for key, value in self.config['global'].items():
            if key not in repo_config:
                repo_config[key] = value
        
        return repo_config

class GitLabClient:
    """GitLab API客户端"""
    def __init__(self, config):
        self.url = config['gitlab_url'].rstrip('/')
        self.token = config['token']
        self.timeout = int(os.environ.get('GITLAB_TIMEOUT', 30))
        self.verify = os.environ.get('GITLAB_HTTP_VERIFY', 'True').lower() == 'true'
        self.headers = {
            'Private-Token': self.token,
            'Content-Type': 'application/json'
        }
    
    def _request(self, method, endpoint, **kwargs):
        """发送API请求"""
        url = f"{self.url}/api/v4{endpoint}"
        kwargs.setdefault('headers', self.headers)
        kwargs.setdefault('timeout', self.timeout)
        kwargs.setdefault('verify', self.verify)
        
        try:
            response = requests.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            console.print(f"[red]API请求失败: {e}[/red]")
            return None
    
    def search_projects(self, query):
        """搜索项目"""
        return self._request('GET', f'/projects', params={'search': query, 'per_page': 100})
    
    def get_project(self, project_id):
        """获取项目信息"""
        return self._request('GET', f'/projects/{project_id}')
    
    def compare_branches(self, project_id, source_branch, target_branch):
        """比较分支差异"""
        return self._request('GET', f'/projects/{project_id}/repository/compare', 
                          params={'from': source_branch, 'to': target_branch})
    
    def get_merge_requests(self, project_id, source_branch, target_branch):
        """获取合并请求"""
        return self._request('GET', f'/projects/{project_id}/merge_requests', 
                          params={'source_branch': source_branch, 'target_branch': target_branch, 'state': 'opened'})
    
    def create_merge_request(self, project_id, source_branch, target_branch, title, description):
        """创建合并请求"""
        data = {
            'source_branch': source_branch,
            'target_branch': target_branch,
            'title': title,
            'description': description
        }
        return self._request('POST', f'/projects/{project_id}/merge_requests', json=data)
    
    def create_tag(self, project_id, tag_name, ref, message):
        """创建标签"""
        data = {
            'tag_name': tag_name,
            'ref': ref,
            'message': message
        }
        return self._request('POST', f'/projects/{project_id}/repository/tags', json=data)
    
    def get_tags(self, project_id):
        """获取标签列表"""
        return self._request('GET', f'/projects/{project_id}/repository/tags', params={'per_page': 100})
    
    def get_branches(self, project_id):
        """获取分支列表"""
        return self._request('GET', f'/projects/{project_id}/repository/branches', params={'per_page': 100})

class GitDiffHelper:
    """GitDiffHelper主类"""
    def __init__(self):
        self.config_manager = ConfigManager()
    
    def search(self, query):
        """搜索仓库"""
        config = self.config_manager.config['global']
        if not config.get('token') or not config.get('gitlab_url'):
            console.print("[red]错误: 请先配置GitLab URL和Token[/red]")
            return
        
        client = GitLabClient(config)
        projects = client.search_projects(query)
        
        if not projects:
            console.print("[yellow]未找到匹配的项目[/yellow]")
            return
        
        table = Table(title="搜索结果")
        table.add_column("ID", style="cyan")
        table.add_column("名称", style="green")
        table.add_column("路径", style="blue")
        
        for project in projects:
            table.add_row(str(project['id']), project['name'], project['path_with_namespace'])
        
        console.print(table)
    
    def add(self, repo_id, group=None):
        """添加仓库"""
        config = self.config_manager.config['global']
        if not config.get('token') or not config.get('gitlab_url'):
            console.print("[red]错误: 请先配置GitLab URL和Token[/red]")
            return
        
        client = GitLabClient(config)
        
        # 检查输入是否为数字ID
        if repo_id.isdigit():
            # 通过ID获取仓库
            project = client.get_project(repo_id)
            
            if not project:
                console.print(f"[red]错误: 无法获取仓库ID {repo_id} 的信息[/red]")
                return
            
            selected_project = project
        else:
            # 通过名称搜索仓库
            projects = client.search_projects(repo_id)
            
            if not projects:
                console.print(f"[red]错误: 未找到名称包含 '{repo_id}' 的仓库[/red]")
                return
            
            # 如果只有一个结果，直接使用
            if len(projects) == 1:
                selected_project = projects[0]
            else:
                # 列出多个结果让用户选择
                console.print("[blue]找到多个匹配的仓库，请选择:[/blue]")
                for i, project in enumerate(projects, 1):
                    console.print(f"{i}. {project['name']} (ID: {project['id']}) - {project['path_with_namespace']}")
                
                # 获取用户选择
                while True:
                    try:
                        choice = int(input("请输入序号: "))
                        if 1 <= choice <= len(projects):
                            selected_project = projects[choice - 1]
                            break
                        else:
                            console.print("[yellow]输入无效，请输入正确的序号[/yellow]")
                    except ValueError:
                        console.print("[yellow]输入无效，请输入数字[/yellow]")
        
        if 'repos' not in self.config_manager.config:
            self.config_manager.config['repos'] = {}
        
        # 如果没有指定分组，使用当前分组
        if not group:
            group = self.config_manager.config.get('current_group', '')
        
        project_id = str(selected_project['id'])
        self.config_manager.config['repos'][project_id] = {
            'name': selected_project['name'],
            'path': selected_project['path_with_namespace']
        }
        
        if group:
            self.config_manager.config['repos'][project_id]['group'] = group
            # 确保组存在
            if 'groups' not in self.config_manager.config:
                self.config_manager.config['groups'] = {}
            if group not in self.config_manager.config['groups']:
                self.config_manager.config['groups'][group] = {}
        
        self.config_manager.save()
        console.print(f"[green]成功添加仓库: {selected_project['name']} (ID: {project_id})[/green]")
    
    def group_set(self, group_name):
        """设置当前分组"""
        groups = self.config_manager.config.get('groups', {})
        
        if group_name not in groups:
            console.print(f"[red]错误: 分组 {group_name} 不存在[/red]")
            return
        
        self.config_manager.config['current_group'] = group_name
        self.config_manager.save()
        
        console.print(f"[green]成功设置当前分组: {group_name}[/green]")
    
    def group_current(self):
        """查看当前分组"""
        current_group = self.config_manager.config.get('current_group', '')
        
        if current_group:
            console.print(f"[green]当前分组: {current_group}[/green]")
        else:
            console.print("[yellow]未设置当前分组[/yellow]")
    
    def list(self):
        """列出所有仓库"""
        config = self.config_manager.config
        
        if not config.get('repos'):
            console.print("[yellow]暂无配置的仓库[/yellow]")
            return
        
        table = Table(title="仓库列表")
        table.add_column("ID", style="cyan")
        table.add_column("名称", style="green")
        table.add_column("路径", style="blue")
        table.add_column("分组", style="magenta")
        
        for repo_id, repo_info in config['repos'].items():
            table.add_row(
                repo_id,
                repo_info.get('name', '未知'),
                repo_info.get('path', '未知'),
                repo_info.get('group', '无')
            )
        
        console.print(table)
    
    def verify(self):
        """验证仓库权限"""
        global_config = self.config_manager.config['global']
        if not global_config.get('token') or not global_config.get('gitlab_url'):
            console.print("[red]错误: 请先配置GitLab URL和Token[/red]")
            return
        
        client = GitLabClient(global_config)
        repos = self.config_manager.config.get('repos', {})
        
        if not repos:
            console.print("[yellow]暂无配置的仓库[/yellow]")
            return
        
        table = Table(title="验证结果")
        table.add_column("ID", style="cyan")
        table.add_column("名称", style="green")
        table.add_column("状态", style="bold")
        
        for repo_id, repo_info in repos.items():
            project = client.get_project(repo_id)
            if project:
                status = "[green]🟢 正常[/green]"
            else:
                status = "[red]🔴 失败[/red]"
            
            table.add_row(repo_id, repo_info.get('name', '未知'), status)
        
        console.print(table)
    
    async def _check_repo_status(self, repo_id, repo_info, client):
        """检查单个仓库状态"""
        repo_config = self.config_manager.get_repo_config(repo_id)
        default_branch = repo_config.get('default_branch', 'master')
        test_branch = repo_config.get('test_branch', 'develop')
        prod_branch = repo_config.get('prod_branch', 'master')
        
        # 获取仓库的实际分支
        branches = client.get_branches(repo_id)
        if not branches:
            return repo_id, repo_info.get('name', '未知'), "[red]🔴 无法获取分支信息[/red]", "N/A", "N/A", "N/A"
        
        # 提取分支名称列表
        branch_names = [branch['name'] for branch in branches]
        
        # 获取测试分支和生产分支的commit id
        test_commit = "N/A"
        prod_commit = "N/A"
        
        if test_branch in branch_names:
            test_branch_info = next((b for b in branches if b['name'] == test_branch), None)
            if test_branch_info:
                test_commit = test_branch_info.get('commit', {}).get('id', 'N/A')[:7]
        
        if prod_branch in branch_names:
            prod_branch_info = next((b for b in branches if b['name'] == prod_branch), None)
            if prod_branch_info:
                prod_commit = prod_branch_info.get('commit', {}).get('id', 'N/A')[:7]
        
        # 获取最新tag的commit id
        latest_tag_commit = "N/A"
        tags = client.get_tags(repo_id)
        if tags and len(tags) > 0:
            latest_tag = tags[0]  # GitLab API按创建时间降序返回
            latest_tag_commit = latest_tag.get('commit', {}).get('id', 'N/A')[:7]
        
        # 常见的开发分支名称
        dev_branches = ['develop', 'dev', 'development', 'feature']
        # 常见的主分支名称
        main_branches = ['master', 'main', 'prod', 'production']
        
        # 找出所有开发分支和主分支
        found_dev_branches = [b for b in branch_names if b in dev_branches]
        found_main_branches = [b for b in branch_names if b in main_branches]
        
        # 如果没有找到开发分支或主分支，使用第一个分支作为主分支
        if not found_dev_branches:
            if branch_names:
                found_dev_branches = [branch_names[0]]
            else:
                return repo_id, repo_info.get('name', '未知'), "[red]🔴 缺少必要的分支[/red]", test_commit, prod_commit, latest_tag_commit
        
        if not found_main_branches:
            if branch_names:
                # 选择不是开发分支的第一个分支作为主分支
                for b in branch_names:
                    if b not in dev_branches:
                        found_main_branches = [b]
                        break
                # 如果所有分支都是开发分支，使用第一个作为主分支
                if not found_main_branches:
                    found_main_branches = [branch_names[0]]
            else:
                return repo_id, repo_info.get('name', '未知'), "[red]🔴 缺少必要的分支[/red]", test_commit, prod_commit, latest_tag_commit
        
        # 选择第一个开发分支和第一个主分支进行比较
        source_branch = found_dev_branches[0]
        target_branch = found_main_branches[0]
        
        # 比较分支差异
        compare_result = client.compare_branches(repo_id, source_branch, target_branch)
        
        if not compare_result:
            # 尝试反向比较
            compare_result = client.compare_branches(repo_id, target_branch, source_branch)
            if not compare_result:
                return repo_id, repo_info.get('name', '未知'), "[red]🔴 无法获取状态[/red]", test_commit, prod_commit, latest_tag_commit
            # 交换分支名称，因为我们是反向比较的
            source_branch, target_branch = target_branch, source_branch
        
        # 确保ahead_count和behind_count存在
        ahead = compare_result.get('ahead_count', 0)
        behind = compare_result.get('behind_count', 0)
        
        if ahead > 0 and behind > 0:
            status = "[yellow]🟡 分歧[/yellow]"
        elif ahead > 0:
            status = f"[blue]🔵 {source_branch}领先{target_branch} {ahead}个提交[/blue]"
        elif behind > 0:
            status = f"[red]🔴 {source_branch}落后{target_branch} {behind}个提交[/red]"
        else:
            status = "[green]🟢 同步[/green]"
        
        return repo_id, repo_info.get('name', '未知'), status, test_commit, prod_commit, latest_tag_commit
    
    async def status(self, repo_id=None, verbose=False):
        """查看仓库状态"""
        global_config = self.config_manager.config['global']
        if not global_config.get('token') or not global_config.get('gitlab_url'):
            console.print("[red]错误: 请先配置GitLab URL和Token[/red]")
            return
        
        client = GitLabClient(global_config)
        
        if repo_id:
            # 查看单个仓库详情
            repo_info = self.config_manager.config.get('repos', {}).get(repo_id)
            if not repo_info:
                console.print(f"[red]错误: 仓库ID {repo_id} 未配置[/red]")
                return
            
            repo_config = self.config_manager.get_repo_config(repo_id)
            default_branch = repo_config.get('default_branch', 'master')
            
            # 获取仓库的实际分支
            branches = client.get_branches(repo_id)
            if not branches:
                console.print(f"[red]错误: 无法获取仓库 {repo_id} 的分支信息[/red]")
                return
            
            # 提取分支名称列表
            branch_names = [branch['name'] for branch in branches]
            
            # 显示详细信息
            if verbose:
                console.print(f"[bold]仓库信息:[/bold]")
                console.print(f"  名称: {repo_info.get('name', '未知')}")
                console.print(f"  ID: {repo_id}")
                console.print(f"  路径: {repo_info.get('path', '未知')}")
                console.print(f"  分组: {repo_info.get('group', '无')}")
                console.print(f"  默认分支: {default_branch}")
                console.print(f"  所有分支: {', '.join(branch_names)}")
                console.print()
            
            # 确定要比较的分支
            source_branch = 'develop' if 'develop' in branch_names else None
            target_branch = default_branch if default_branch in branch_names else None
            
            # 如果没有找到develop分支，尝试其他常见的开发分支名称
            if not source_branch:
                for branch_name in ['dev', 'development', 'feature']:
                    if branch_name in branch_names:
                        source_branch = branch_name
                        break
            
            # 如果没有找到默认分支，尝试main分支
            if not target_branch:
                if 'main' in branch_names:
                    target_branch = 'main'
                elif branch_names:
                    # 使用第一个分支作为目标分支
                    target_branch = branch_names[0]
            
            # 如果仍然没有找到合适的分支，返回错误
            if not source_branch or not target_branch:
                console.print(f"[red]错误: 仓库 {repo_id} 缺少必要的分支[/red]")
                return
            
            # 比较分支差异
            compare_result = client.compare_branches(repo_id, source_branch, target_branch)
            
            if not compare_result:
                # 尝试反向比较
                compare_result = client.compare_branches(repo_id, target_branch, source_branch)
                if not compare_result:
                    console.print(f"[red]错误: 无法获取仓库 {repo_id} 的状态[/red]")
                    return
                # 交换分支名称，因为我们是反向比较的
                source_branch, target_branch = target_branch, source_branch
            
            # 确保ahead_count和behind_count存在
            ahead = compare_result.get('ahead_count', 0)
            behind = compare_result.get('behind_count', 0)
            
            console.print(f"[bold]仓库:[/bold] {repo_info.get('name', '未知')} (ID: {repo_id})")
            console.print(f"[bold]默认分支:[/bold] {default_branch}")
            console.print(f"[bold]比较分支:[/bold] {source_branch} → {target_branch}")
            console.print(f"[bold]{source_branch} 领先:[/bold] {ahead} 个提交")
            console.print(f"[bold]{source_branch} 落后:[/bold] {behind} 个提交")
            
            # 显示提交列表
            if compare_result.get('commits'):
                console.print("\n[bold]提交列表:[/bold]")
                table = Table()
                table.add_column("Hash", style="cyan")
                table.add_column("作者", style="green")
                table.add_column("日期", style="blue")
                table.add_column("消息", style="white")
                
                for commit in compare_result['commits'][:10]:  # 只显示最近10个
                    table.add_row(
                        commit['id'][:7],
                        commit['author_name'],
                        commit['created_at'][:10],
                        commit['message'].split('\n')[0]
                    )
                
                console.print(table)
        else:
            # 查看所有仓库状态
            repos = self.config_manager.config.get('repos', {})
            current_group = self.config_manager.config.get('current_group', '')
            
            # 过滤出当前分组下的仓库
            filtered_repos = {}
            for repo_id, repo_info in repos.items():
                if not current_group or repo_info.get('group') == current_group:
                    filtered_repos[repo_id] = repo_info
            
            if not filtered_repos:
                if current_group:
                    console.print(f"[yellow]当前分组 '{current_group}' 下暂无配置的仓库[/yellow]")
                else:
                    console.print("[yellow]暂无配置的仓库[/yellow]")
                return
            
            tasks = []
            for repo_id, repo_info in filtered_repos.items():
                tasks.append(self._check_repo_status(repo_id, repo_info, client))
            
            results = await asyncio.gather(*tasks)
            
            title = "仓库状态总览"
            if current_group:
                title = f"当前分组 '{current_group}' 的仓库状态"
            
            table = Table(title=title)
            table.add_column("ID", style="cyan")
            table.add_column("名称", style="green")
            table.add_column("状态", style="bold")
            table.add_column("测试分支", style="yellow")
            table.add_column("生产分支", style="yellow")
            table.add_column("最新Tag", style="yellow")
            
            for result in results:
                table.add_row(result[0], result[1], result[2], result[3], result[4], result[5])
            
            console.print(table)
            
            # 显示详细信息
            if verbose:
                console.print("\n[bold]详细信息:[/bold]")
                for repo_id, repo_info in filtered_repos.items():
                    repo_config = self.config_manager.get_repo_config(repo_id)
                    default_branch = repo_config.get('default_branch', 'master')
                    console.print(f"\n[bold]{repo_info.get('name', '未知')} (ID: {repo_id})[/bold]")
                    console.print(f"  路径: {repo_info.get('path', '未知')}")
                    console.print(f"  分组: {repo_info.get('group', '无')}")
                    console.print(f"  默认分支: {default_branch}")
                    
                    # 获取仓库的实际分支
                    branches = client.get_branches(repo_id)
                    if branches:
                        branch_names = [branch['name'] for branch in branches]
                        console.print(f"  分支数量: {len(branch_names)}")
                        if len(branch_names) <= 10:
                            console.print(f"  分支: {', '.join(branch_names)}")
                        else:
                            console.print(f"  分支: {', '.join(branch_names[:5])}... 等 {len(branch_names)} 个分支")
                    
                    # 显示测试分支和生产分支的配置及commit id
                    console.print("  分支配置:")
                    
                    # 从配置文件中获取分支配置
                    repo_config = self.config_manager.get_repo_config(repo_id)
                    test_branch = repo_config.get('test_branch', 'develop')
                    prod_branch = repo_config.get('prod_branch', 'master')
                    
                    # 优先使用配置文件中设置的分支
                    branch_types = {
                        '测试分支': test_branch,
                        '生产分支': prod_branch
                    }
                    
                    for branch_type, config_branch in branch_types.items():
                        # 检查配置的分支是否存在
                        if config_branch in branch_names:
                            # 获取分支的最新commit id
                            branch_info = next((b for b in branches if b['name'] == config_branch), None)
                            if branch_info:
                                commit_id = branch_info.get('commit', {}).get('id', 'N/A')[:7]
                                console.print(f"    {branch_type}: {config_branch} (commit: {commit_id})")
                        else:
                            # 如果配置的分支不存在，尝试其他常见分支
                            common_branches = []
                            if branch_type == '测试分支':
                                common_branches = ['develop', 'dev', 'development', 'feature']
                            else:  # 生产分支
                                common_branches = ['master', 'main', 'prod', 'production']
                            
                            # 找到第一个存在的常见分支
                            found_branch = None
                            for branch in common_branches:
                                if branch in branch_names:
                                    found_branch = branch
                                    break
                            
                            if found_branch:
                                branch_info = next((b for b in branches if b['name'] == found_branch), None)
                                if branch_info:
                                    commit_id = branch_info.get('commit', {}).get('id', 'N/A')[:7]
                                    console.print(f"    {branch_type}: {found_branch} (commit: {commit_id}) (使用默认分支)")
                            else:
                                console.print(f"    {branch_type}: 无")
    
    def sync(self, repo_id, to_master=True):
        """同步仓库并创建MR"""
        global_config = self.config_manager.config['global']
        if not global_config.get('token') or not global_config.get('gitlab_url'):
            console.print("[red]错误: 请先配置GitLab URL和Token[/red]")
            return
        
        client = GitLabClient(global_config)
        repo_info = self.config_manager.config.get('repos', {}).get(repo_id)
        
        if not repo_info:
            console.print(f"[red]错误: 仓库ID {repo_id} 未配置[/red]")
            return
        
        repo_config = self.config_manager.get_repo_config(repo_id)
        default_branch = repo_config.get('default_branch', 'master')
        
        if to_master:
            source_branch = 'develop'
            target_branch = default_branch
        else:
            source_branch = default_branch
            target_branch = 'develop'
        
        # 检查是否存在未关闭的MR
        mrs = client.get_merge_requests(repo_id, source_branch, target_branch)
        
        if mrs and len(mrs) > 0:
            console.print(f"[yellow]已存在未关闭的MR:[/yellow] {mrs[0]['web_url']}")
            return
        
        # 检查分支差异
        compare_result = client.compare_branches(repo_id, source_branch, target_branch)
        
        if not compare_result:
            console.print(f"[red]错误: 无法获取分支差异[/red]")
            return
        
        ahead = compare_result.get('ahead_count', 0)
        
        if ahead == 0:
            console.print("[green]分支已经同步，无需创建MR[/green]")
            return
        
        # 生成MR描述
        description = "## 自动创建的同步MR\n\n"
        description += f"- 源分支: {source_branch}\n"
        description += f"- 目标分支: {target_branch}\n"
        description += f"- 提交数量: {ahead}\n\n"
        description += "## 提交列表\n"
        
        for commit in compare_result.get('commits', [])[:10]:
            message = commit['message'].split('\n')[0]
            description += f"- [{commit['id'][:7]}] {message} (by {commit['author_name']})\n"
        
        # 创建MR
        title = f"Sync: {source_branch} → {target_branch}"
        mr = client.create_merge_request(repo_id, source_branch, target_branch, title, description)
        
        if mr:
            console.print(f"[green]成功创建MR:[/green] {mr['web_url']}")
        else:
            console.print("[red]创建MR失败[/red]")
    
    def _get_repo_id_by_name(self, repo_name):
        """通过仓库名称获取仓库ID"""
        repos = self.config_manager.config.get('repos', {})
        matching_repos = []
        
        for r_id, r_info in repos.items():
            if repo_name.lower() in r_info.get('name', '').lower():
                matching_repos.append((r_id, r_info))
        
        if not matching_repos:
            return None
        elif len(matching_repos) == 1:
            return matching_repos[0][0]
        else:
            # 列出多个结果让用户选择
            console.print("[blue]找到多个匹配的仓库，请选择:[/blue]")
            for i, (r_id, r_info) in enumerate(matching_repos, 1):
                console.print(f"{i}. {r_info.get('name', '未知')} (ID: {r_id}) - {r_info.get('path', '未知')}")
            
            # 获取用户选择
            while True:
                try:
                    choice = int(input("请输入序号: "))
                    if 1 <= choice <= len(matching_repos):
                        return matching_repos[choice - 1][0]
                    else:
                        console.print("[yellow]输入无效，请输入正确的序号[/yellow]")
                except ValueError:
                    console.print("[yellow]输入无效，请输入数字[/yellow]")
    
    def tag_create(self, repo_id, version):
        """创建标签"""
        # 检查输入是否为数字ID
        if not repo_id.isdigit():
            # 通过名称获取仓库ID
            repo_id = self._get_repo_id_by_name(repo_id)
            if not repo_id:
                console.print(f"[red]错误: 未找到名称包含 '{repo_id}' 的仓库[/red]")
                return
        
        global_config = self.config_manager.config['global']
        if not global_config.get('token') or not global_config.get('gitlab_url'):
            console.print("[red]错误: 请先配置GitLab URL和Token[/red]")
            return
        
        client = GitLabClient(global_config)
        repo_info = self.config_manager.config.get('repos', {}).get(repo_id)
        
        if not repo_info:
            console.print(f"[red]错误: 仓库ID {repo_id} 未配置[/red]")
            return
        
        # 获取仓库信息，确认默认分支存在
        project = client.get_project(repo_id)
        if not project:
            console.print(f"[red]错误: 无法获取仓库 {repo_id} 的信息[/red]")
            return
        
        default_branch = project.get('default_branch', 'master')
        console.print(f"[blue]使用默认分支:[/blue] {default_branch}")
        
        # 创建标签
        tag = client.create_tag(repo_id, version, default_branch, f"Release version {version}")
        
        if tag:
            console.print(f"[green]成功创建标签:[/green] {version}")
        else:
            console.print("[red]创建标签失败，请检查标签名称是否符合要求[/red]")
    
    def tag_list(self, repo_id, show_all=False):
        """列出标签"""
        # 检查输入是否为数字ID
        if not repo_id.isdigit():
            # 通过名称获取仓库ID
            repo_id = self._get_repo_id_by_name(repo_id)
            if not repo_id:
                console.print(f"[red]错误: 未找到名称包含 '{repo_id}' 的仓库[/red]")
                return
        
        global_config = self.config_manager.config['global']
        if not global_config.get('token') or not global_config.get('gitlab_url'):
            console.print("[red]错误: 请先配置GitLab URL和Token[/red]")
            return
        
        client = GitLabClient(global_config)
        repo_info = self.config_manager.config.get('repos', {}).get(repo_id)
        
        if not repo_info:
            console.print(f"[red]错误: 仓库ID {repo_id} 未配置[/red]")
            return
        
        # 获取标签列表
        tags = client.get_tags(repo_id)
        
        if not tags:
            console.print(f"[yellow]仓库 {repo_info.get('name', '未知')} 暂无标签[/yellow]")
            return
        
        # 确定要显示的标签数量
        total_tags = len(tags)
        display_tags = tags
        if not show_all and total_tags > 10:
            display_tags = tags[:10]
        
        table = Table(title=f"{repo_info.get('name', '未知')} 的标签列表")
        table.add_column("标签名称", style="cyan")
        table.add_column("提交", style="green")
        table.add_column("创建时间", style="blue")
        
        for tag in display_tags:
            # 从commit对象中获取创建时间
            created_at = '未知'
            commit = tag.get('commit', {})
            if commit:
                for field in ['created_at', 'authored_date', 'committed_date']:
                    if field in commit:
                        created_at = commit[field]
                        break
            
            if created_at != '未知':
                created_at = created_at[:10]
            
            table.add_row(
                tag.get('name', '未知'),
                tag.get('commit', {}).get('id', 'N/A')[:7],
                created_at
            )
        
        console.print(table)
        
        # 显示剩余标签数量
        if not show_all and total_tags > 10:
            remaining = total_tags - 10
            console.print(f"[yellow]显示了前10个标签，还有 {remaining} 个标签未显示。使用 --all 选项查看所有标签。[/yellow]")
    
    def rm(self, repo_id):
        """删除仓库"""
        repos = self.config_manager.config.get('repos', {})
        
        # 检查输入是否为数字ID
        if repo_id.isdigit():
            # 通过ID删除仓库
            if repo_id not in repos:
                console.print(f"[red]错误: 仓库ID {repo_id} 未配置[/red]")
                return
            
            selected_repo_id = repo_id
            repo_name = repos[selected_repo_id].get('name', '未知')
        else:
            # 通过名称搜索仓库
            matching_repos = []
            for r_id, r_info in repos.items():
                if repo_id.lower() in r_info.get('name', '').lower():
                    matching_repos.append((r_id, r_info))
            
            if not matching_repos:
                console.print(f"[red]错误: 未找到名称包含 '{repo_id}' 的仓库[/red]")
                return
            
            # 如果只有一个结果，直接使用
            if len(matching_repos) == 1:
                selected_repo_id, repo_info = matching_repos[0]
                repo_name = repo_info.get('name', '未知')
            else:
                # 列出多个结果让用户选择
                console.print("[blue]找到多个匹配的仓库，请选择:[/blue]")
                for i, (r_id, r_info) in enumerate(matching_repos, 1):
                    console.print(f"{i}. {r_info.get('name', '未知')} (ID: {r_id}) - {r_info.get('path', '未知')}")
                
                # 获取用户选择
                while True:
                    try:
                        choice = int(input("请输入序号: "))
                        if 1 <= choice <= len(matching_repos):
                            selected_repo_id, repo_info = matching_repos[choice - 1]
                            repo_name = repo_info.get('name', '未知')
                            break
                        else:
                            console.print("[yellow]输入无效，请输入正确的序号[/yellow]")
                    except ValueError:
                        console.print("[yellow]输入无效，请输入数字[/yellow]")
        
        # 要求用户确认
        confirm = input(f"确定要删除仓库 {repo_name} (ID: {selected_repo_id}) 吗？(y/n): ")
        if confirm.lower() != 'y':
            console.print("[yellow]取消删除操作[/yellow]")
            return
        
        del self.config_manager.config['repos'][selected_repo_id]
        self.config_manager.save()
        
        console.print(f"[green]成功删除仓库: {repo_name} (ID: {selected_repo_id})[/green]")
    
    def group_add(self, group_name):
        """创建分组"""
        if 'groups' not in self.config_manager.config:
            self.config_manager.config['groups'] = {}
        
        if group_name in self.config_manager.config['groups']:
            console.print(f"[yellow]分组 {group_name} 已存在[/yellow]")
            return
        
        self.config_manager.config['groups'][group_name] = {}
        self.config_manager.save()
        
        console.print(f"[green]成功创建分组: {group_name}[/green]")
    
    def group_list(self):
        """列出所有分组"""
        groups = self.config_manager.config.get('groups', {})
        repos = self.config_manager.config.get('repos', {})
        
        if not groups:
            console.print("[yellow]暂无配置的分组[/yellow]")
            return
        
        # 先统计每个分组的仓库
        group_repos = {}
        for group_name in groups:
            group_repos[group_name] = []
        
        # 遍历所有仓库，分配到对应的分组
        for repo_id, repo_info in repos.items():
            group_name = repo_info.get('group')
            if group_name and group_name in groups:
                group_repos[group_name].append((repo_id, repo_info))
        
        # 显示分组列表
        table = Table(title="分组列表")
        table.add_column("名称", style="cyan")
        table.add_column("仓库数量", style="green")
        table.add_column("仓库列表", style="blue")
        
        for group_name in groups:
            repo_list = group_repos.get(group_name, [])
            repo_count = len(repo_list)
            
            # 构建仓库列表字符串
            repo_names = []
            for repo_id, repo_info in repo_list:
                repo_names.append(f"{repo_info.get('name', '未知')} ({repo_id})")
            
            repo_list_str = ", ".join(repo_names) if repo_names else "无"
            
            table.add_row(group_name, str(repo_count), repo_list_str)
        
        console.print(table)
    
    def group_rm(self, group_name):
        """删除分组"""
        groups = self.config_manager.config.get('groups', {})
        
        if group_name not in groups:
            console.print(f"[red]错误: 分组 {group_name} 不存在[/red]")
            return
        
        # 检查分组中是否有仓库
        repo_count = 0
        for repo_info in self.config_manager.config.get('repos', {}).values():
            if repo_info.get('group') == group_name:
                repo_count += 1
        
        if repo_count > 0:
            console.print(f"[yellow]警告: 分组 {group_name} 中还有 {repo_count} 个仓库，删除分组后这些仓库将变为无分组状态[/yellow]")
        
        # 要求用户确认
        confirm = input(f"确定要删除分组 {group_name} 吗？(y/n): ")
        if confirm.lower() != 'y':
            console.print("[yellow]取消删除操作[/yellow]")
            return
        
        # 删除分组
        del self.config_manager.config['groups'][group_name]
        
        # 移除仓库中的分组信息
        for repo_id, repo_info in self.config_manager.config.get('repos', {}).items():
            if repo_info.get('group') == group_name:
                del repo_info['group']
        
        self.config_manager.save()
        
        console.print(f"[green]成功删除分组: {group_name}[/green]")

def main():
    """主函数"""
    # 命令别名映射
    command_aliases = {
        's': 'search',
        'a': 'add',
        'ls': 'list',
        'v': 'verify',
        'st': 'status',
        'sy': 'sync',
        't': 'tag',
        'r': 'rm',
        'g': 'group',
        'cfg': 'config'
    }
    
    # 分组子命令别名映射
    group_command_aliases = {
        'a': 'add',
        'ls': 'list',
        'r': 'rm',
        's': 'set',
        'c': 'current'
    }
    
    # 配置子命令别名映射
    config_command_aliases = {
        's': 'set',
        'g': 'get',
        'l': 'list'
    }
    
    # 标签子命令别名映射
    tag_command_aliases = {
        'c': 'create',
        'l': 'list',
        'll': 'll'
    }
    
    # 处理命令行参数
    if len(sys.argv) > 1:
        # 处理主命令别名
        if sys.argv[1] in command_aliases:
            sys.argv[1] = command_aliases[sys.argv[1]]
        
        # 处理分组子命令别名
        if len(sys.argv) > 2 and sys.argv[1] == 'group' and sys.argv[2] in group_command_aliases:
            sys.argv[2] = group_command_aliases[sys.argv[2]]
        
        # 处理配置子命令别名
        if len(sys.argv) > 2 and sys.argv[1] == 'config' and sys.argv[2] in config_command_aliases:
            sys.argv[2] = config_command_aliases[sys.argv[2]]
        
        # 处理标签子命令别名
        if len(sys.argv) > 2 and sys.argv[1] == 'tag' and sys.argv[2] in tag_command_aliases:
            sys.argv[2] = tag_command_aliases[sys.argv[2]]
    
    parser = argparse.ArgumentParser(description='GitDiffHelper (GD) - 多仓库Git差异管理工具')
    subparsers = parser.add_subparsers(dest='command', help='子命令', required=False)
    
    # search命令
    search_parser = subparsers.add_parser('search', help='搜索远端仓库 (缩写: s)')
    search_parser.add_argument('key', help='搜索关键词')
    
    # add命令
    add_parser = subparsers.add_parser('add', help='添加仓库 (缩写: a)')
    add_parser.add_argument('id', help='仓库ID')
    add_parser.add_argument('-g', '--group', help='分组名称')
    
    # list命令
    subparsers.add_parser('list', help='查看配置的仓库 (缩写: ls)')
    
    # verify命令
    subparsers.add_parser('verify', help='验证仓库权限 (缩写: v)')
    
    # status命令
    status_parser = subparsers.add_parser('status', help='查看仓库状态 (缩写: st)')
    status_parser.add_argument('id', nargs='?', help='仓库ID，不指定则查看所有')
    status_parser.add_argument('--verbose', '-v', action='store_true', help='显示详细信息')
    
    # sync命令
    sync_parser = subparsers.add_parser('sync', help='同步仓库并创建MR (缩写: sy)')
    sync_parser.add_argument('id', help='仓库ID')
    sync_parser.add_argument('--to-master', action='store_true', default=True, help='同步到master分支')
    sync_parser.add_argument('--to-dev', action='store_false', dest='to_master', help='同步到develop分支')
    
    # tag命令
    tag_parser = subparsers.add_parser('tag', help='标签管理 (缩写: t)')
    tag_subparsers = tag_parser.add_subparsers(dest='tag_command', help='标签子命令 (缩写: c=create, l=list, ll=ll)')
    
    # tag create命令
    tag_create_parser = tag_subparsers.add_parser('create', help='在默认分支上创建标签 (缩写: c)')
    tag_create_parser.add_argument('id', help='仓库ID或名称')
    tag_create_parser.add_argument('version', help='标签版本')
    # 添加命令级别的帮助信息
    tag_create_parser.epilog = "注意: 标签是在仓库的默认分支上创建的。可以通过 'gd config get/set repos.<仓库ID>.default_branch' 查看或修改默认分支。"
    
    # tag list命令
    tag_list_parser = tag_subparsers.add_parser('list', help='列出标签 (缩写: l)')
    tag_list_parser.add_argument('id', help='仓库ID或名称')
    tag_list_parser.add_argument('--all', '-a', '-all', action='store_true', help='显示所有标签')
    
    # tag ll命令
    tag_ll_parser = tag_subparsers.add_parser('ll', help='快速显示所有标签 (缩写: ll)')
    tag_ll_parser.add_argument('id', help='仓库ID或名称')
    
    # rm命令
    rm_parser = subparsers.add_parser('rm', help='删除仓库 (缩写: r)')
    rm_parser.add_argument('id', help='仓库ID')
    
    # group命令
    group_parser = subparsers.add_parser('group', help='分组管理 (缩写: g)')
    group_subparsers = group_subparsers = group_parser.add_subparsers(dest='group_command', help='分组子命令')
    
    # group add命令
    group_add_parser = group_subparsers.add_parser('add', help='创建分组 (缩写: a)')
    group_add_parser.add_argument('name', help='分组名称')
    
    # group list命令
    group_subparsers.add_parser('list', help='列出所有分组 (缩写: ls)')
    
    # group rm命令
    group_rm_parser = group_subparsers.add_parser('rm', help='删除分组 (缩写: r)')
    group_rm_parser.add_argument('name', help='分组名称')
    
    # group set命令
    group_set_parser = group_subparsers.add_parser('set', help='设置当前分组 (缩写: s)')
    group_set_parser.add_argument('name', help='分组名称')
    
    # group current命令
    group_subparsers.add_parser('current', help='查看当前分组 (缩写: c)')
    
    # config命令
    config_parser = subparsers.add_parser('config', help='配置管理 (缩写: cfg)')
    config_subparsers = config_parser.add_subparsers(dest='config_command', help='配置子命令')
    
    # config set命令
    config_set_parser = config_subparsers.add_parser('set', help='设置配置 (缩写: s)')
    config_set_parser.add_argument('key', help='配置键，支持 global.default_branch, repos.<repo_id>.default_branch, groups.<group_name>.default_branch')
    config_set_parser.add_argument('value', help='配置值')
    
    # config get命令
    config_get_parser = config_subparsers.add_parser('get', help='获取配置 (缩写: g)')
    config_get_parser.add_argument('key', help='配置键，支持 global.default_branch, repos.<repo_id>.default_branch, groups.<group_name>.default_branch')
    
    # config list命令
    config_list_parser = config_subparsers.add_parser('list', help='列出所有配置 (缩写: l)')
    
    args = parser.parse_args()
    
    helper = GitDiffHelper()
    
    if args.command == 'search':
        helper.search(args.key)
    elif args.command == 'add':
        helper.add(args.id, args.group)
    elif args.command == 'list':
        helper.list()
    elif args.command == 'verify':
        helper.verify()
    elif args.command == 'status':
            asyncio.run(helper.status(args.id, args.verbose))
    elif args.command == 'sync':
        helper.sync(args.id, args.to_master)
    elif args.command == 'tag':
        if args.tag_command == 'create':
            helper.tag_create(args.id, args.version)
        elif args.tag_command == 'list':
            helper.tag_list(args.id, args.all)
        elif args.tag_command == 'll':
            helper.tag_list(args.id, True)
        else:
            tag_parser.print_help()
    elif args.command == 'rm':
        helper.rm(args.id)
    elif args.command == 'group':
        if args.group_command == 'add':
            helper.group_add(args.name)
        elif args.group_command == 'list':
            helper.group_list()
        elif args.group_command == 'rm':
            helper.group_rm(args.name)
        elif args.group_command == 'set':
            helper.group_set(args.name)
        elif args.group_command == 'current':
            helper.group_current()
        else:
            group_parser.print_help()
    elif args.command == 'config':
        if args.config_command == 'set':
            # 解析配置键
            parts = args.key.split('.')
            if len(parts) < 2:
                console.print("[red]错误: 配置键格式不正确，应为 section.key 或 section.id.key[/red]")
                return
            
            section = parts[0]
            key = parts[-1]
            
            # 设置配置
            if section == 'global':
                if len(parts) != 2:
                    console.print("[red]错误: 全局配置键格式应为 global.key[/red]")
                    return
                if 'global' not in helper.config_manager.config:
                    helper.config_manager.config['global'] = {}
                helper.config_manager.config['global'][key] = args.value
            elif section == 'repos':
                if len(parts) != 3:
                    console.print("[red]错误: 仓库配置键格式应为 repos.<repo_id>.key[/red]")
                    return
                repo_id = parts[1]
                if 'repos' not in helper.config_manager.config:
                    helper.config_manager.config['repos'] = {}
                if repo_id not in helper.config_manager.config['repos']:
                    console.print(f"[red]错误: 仓库ID {repo_id} 未配置[/red]")
                    return
                helper.config_manager.config['repos'][repo_id][key] = args.value
            elif section == 'groups':
                if len(parts) != 3:
                    console.print("[red]错误: 分组配置键格式应为 groups.<group_name>.key[/red]")
                    return
                group_name = parts[1]
                if 'groups' not in helper.config_manager.config:
                    helper.config_manager.config['groups'] = {}
                if group_name not in helper.config_manager.config['groups']:
                    console.print(f"[red]错误: 分组 {group_name} 不存在[/red]")
                    return
                helper.config_manager.config['groups'][group_name][key] = args.value
            else:
                console.print(f"[red]错误: 未知的配置 section: {section}[/red]")
                return
            
            # 保存配置
            helper.config_manager.save()
            console.print(f"[green]成功设置配置: {args.key} = {args.value}[/green]")
        elif args.config_command == 'get':
            # 解析配置键
            parts = args.key.split('.')
            if len(parts) < 2:
                console.print("[red]错误: 配置键格式不正确，应为 section.key 或 section.id.key[/red]")
                return
            
            section = parts[0]
            key = parts[-1]
            
            # 获取配置
            value = None
            if section == 'global':
                if len(parts) != 2:
                    console.print("[red]错误: 全局配置键格式应为 global.key[/red]")
                    return
                value = helper.config_manager.config.get('global', {}).get(key)
            elif section == 'repos':
                if len(parts) != 3:
                    console.print("[red]错误: 仓库配置键格式应为 repos.<repo_id>.key[/red]")
                    return
                repo_id = parts[1]
                value = helper.config_manager.config.get('repos', {}).get(repo_id, {}).get(key)
            elif section == 'groups':
                if len(parts) != 3:
                    console.print("[red]错误: 分组配置键格式应为 groups.<group_name>.key[/red]")
                    return
                group_name = parts[1]
                value = helper.config_manager.config.get('groups', {}).get(group_name, {}).get(key)
            else:
                console.print(f"[red]错误: 未知的配置 section: {section}[/red]")
                return
            
            if value is not None:
                console.print(f"[green]{args.key} = {value}[/green]")
            else:
                console.print(f"[yellow]配置 {args.key} 未设置[/yellow]")
        elif args.config_command == 'list':
            # 列出所有配置
            config = helper.config_manager.config
            
            console.print("[bold]全局配置:[/bold]")
            global_config = config.get('global', {})
            if global_config:
                for key, value in global_config.items():
                    console.print(f"  global.{key} = {value}")
            else:
                console.print("  无")
            
            console.print("\n[bold]分组配置:[/bold]")
            groups_config = config.get('groups', {})
            if groups_config:
                for group_name, group_settings in groups_config.items():
                    console.print(f"  [blue]{group_name}:[/blue]")
                    if group_settings:
                        for key, value in group_settings.items():
                            console.print(f"    groups.{group_name}.{key} = {value}")
                    else:
                        console.print("    无")
            else:
                console.print("  无")
            
            console.print("\n[bold]仓库配置:[/bold]")
            repos_config = config.get('repos', {})
            if repos_config:
                for repo_id, repo_settings in repos_config.items():
                    console.print(f"  [blue]{repo_id} ({repo_settings.get('name', '未知')}):[/blue]")
                    if repo_settings:
                        for key, value in repo_settings.items():
                            if key not in ['name', 'path', 'group']:
                                console.print(f"    repos.{repo_id}.{key} = {value}")
                    else:
                        console.print("    无")
            else:
                console.print("  无")
        else:
            config_parser.print_help()
    else:
        parser.print_help()

if __name__ == '__main__':
    main()
