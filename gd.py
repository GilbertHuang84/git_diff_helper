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
                return config
        # 创建默认配置
        default_config = {
            'global': {
                'gitlab_url': '',
                'token': '',
                'default_branch': 'master'
            },
            'groups': {},
            'repos': {}
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
        project = client.get_project(repo_id)
        
        if not project:
            console.print(f"[red]错误: 无法获取仓库ID {repo_id} 的信息[/red]")
            return
        
        if 'repos' not in self.config_manager.config:
            self.config_manager.config['repos'] = {}
        
        self.config_manager.config['repos'][repo_id] = {
            'name': project['name'],
            'path': project['path_with_namespace']
        }
        
        if group:
            self.config_manager.config['repos'][repo_id]['group'] = group
            # 确保组存在
            if 'groups' not in self.config_manager.config:
                self.config_manager.config['groups'] = {}
            if group not in self.config_manager.config['groups']:
                self.config_manager.config['groups'][group] = {}
        
        self.config_manager.save()
        console.print(f"[green]成功添加仓库: {project['name']} (ID: {repo_id})[/green]")
    
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
        
        # 检查develop和master分支的差异
        compare_result = client.compare_branches(repo_id, 'develop', default_branch)
        
        if not compare_result:
            return repo_id, repo_info.get('name', '未知'), "[red]🔴 无法获取状态[/red]"
        
        ahead = compare_result.get('ahead_count', 0)
        behind = compare_result.get('behind_count', 0)
        
        if ahead > 0 and behind > 0:
            status = "[yellow]🟡 分歧[/yellow]"
        elif ahead > 0:
            status = "[blue]🔵 领先[/blue]"
        elif behind > 0:
            status = "[red]🔴 落后[/red]"
        else:
            status = "[green]🟢 同步[/green]"
        
        return repo_id, repo_info.get('name', '未知'), status
    
    async def status(self, repo_id=None):
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
            
            # 获取差异
            compare_result = client.compare_branches(repo_id, 'develop', default_branch)
            
            if not compare_result:
                console.print(f"[red]错误: 无法获取仓库 {repo_id} 的状态[/red]")
                return
            
            console.print(f"[bold]仓库:[/bold] {repo_info.get('name', '未知')} (ID: {repo_id})")
            console.print(f"[bold]默认分支:[/bold] {default_branch}")
            console.print(f"[bold]Develop 领先:[/bold] {compare_result.get('ahead_count', 0)} 个提交")
            console.print(f"[bold]Develop 落后:[/bold] {compare_result.get('behind_count', 0)} 个提交")
            
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
            
            if not repos:
                console.print("[yellow]暂无配置的仓库[/yellow]")
                return
            
            tasks = []
            for repo_id, repo_info in repos.items():
                tasks.append(self._check_repo_status(repo_id, repo_info, client))
            
            results = await asyncio.gather(*tasks)
            
            table = Table(title="仓库状态总览")
            table.add_column("ID", style="cyan")
            table.add_column("名称", style="green")
            table.add_column("状态", style="bold")
            
            for result in results:
                table.add_row(result[0], result[1], result[2])
            
            console.print(table)
    
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
    
    def tag(self, repo_id, version):
        """创建标签"""
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
        
        # 创建标签
        tag = client.create_tag(repo_id, version, default_branch, f"Release version {version}")
        
        if tag:
            console.print(f"[green]成功创建标签:[/green] {version}")
        else:
            console.print("[red]创建标签失败[/red]")
    
    def rm(self, repo_id):
        """删除仓库"""
        repos = self.config_manager.config.get('repos', {})
        
        if repo_id not in repos:
            console.print(f"[red]错误: 仓库ID {repo_id} 未配置[/red]")
            return
        
        repo_name = repos[repo_id].get('name', '未知')
        del self.config_manager.config['repos'][repo_id]
        self.config_manager.save()
        
        console.print(f"[green]成功删除仓库: {repo_name} (ID: {repo_id})[/green]")
    
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
        
        if not groups:
            console.print("[yellow]暂无配置的分组[/yellow]")
            return
        
        table = Table(title="分组列表")
        table.add_column("名称", style="cyan")
        table.add_column("仓库数量", style="green")
        
        for group_name in groups:
            # 统计分组中的仓库数量
            repo_count = 0
            for repo_info in self.config_manager.config.get('repos', {}).values():
                if repo_info.get('group') == group_name:
                    repo_count += 1
            
            table.add_row(group_name, str(repo_count))
        
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
    parser = argparse.ArgumentParser(description='GitDiffHelper (GD) - 多仓库Git差异管理工具')
    subparsers = parser.add_subparsers(dest='command', help='子命令')
    
    # search命令
    search_parser = subparsers.add_parser('search', help='搜索远端仓库')
    search_parser.add_argument('key', help='搜索关键词')
    
    # add命令
    add_parser = subparsers.add_parser('add', help='添加仓库')
    add_parser.add_argument('id', help='仓库ID')
    add_parser.add_argument('-g', '--group', help='分组名称')
    
    # list命令
    subparsers.add_parser('list', help='查看配置的仓库')
    
    # verify命令
    subparsers.add_parser('verify', help='验证仓库权限')
    
    # status命令
    status_parser = subparsers.add_parser('status', help='查看仓库状态')
    status_parser.add_argument('id', nargs='?', help='仓库ID，不指定则查看所有')
    
    # sync命令
    sync_parser = subparsers.add_parser('sync', help='同步仓库并创建MR')
    sync_parser.add_argument('id', help='仓库ID')
    sync_parser.add_argument('--to-master', action='store_true', default=True, help='同步到master分支')
    sync_parser.add_argument('--to-dev', action='store_false', dest='to_master', help='同步到develop分支')
    
    # tag命令
    tag_parser = subparsers.add_parser('tag', help='创建标签')
    tag_parser.add_argument('id', help='仓库ID')
    tag_parser.add_argument('version', help='标签版本')
    
    # rm命令
    rm_parser = subparsers.add_parser('rm', help='删除仓库')
    rm_parser.add_argument('id', help='仓库ID')
    
    # group命令
    group_parser = subparsers.add_parser('group', help='分组管理')
    group_subparsers = group_parser.add_subparsers(dest='group_command', help='分组子命令')
    
    # group add命令
    group_add_parser = group_subparsers.add_parser('add', help='创建分组')
    group_add_parser.add_argument('name', help='分组名称')
    
    # group list命令
    group_subparsers.add_parser('list', help='列出所有分组')
    
    # group rm命令
    group_rm_parser = group_subparsers.add_parser('rm', help='删除分组')
    group_rm_parser.add_argument('name', help='分组名称')
    
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
        asyncio.run(helper.status(args.id))
    elif args.command == 'sync':
        helper.sync(args.id, args.to_master)
    elif args.command == 'tag':
        helper.tag(args.id, args.version)
    elif args.command == 'rm':
        helper.rm(args.id)
    elif args.command == 'group':
        if args.group_command == 'add':
            helper.group_add(args.name)
        elif args.group_command == 'list':
            helper.group_list()
        elif args.group_command == 'rm':
            helper.group_rm(args.name)
        else:
            group_parser.print_help()
    else:
        parser.print_help()

if __name__ == '__main__':
    main()
