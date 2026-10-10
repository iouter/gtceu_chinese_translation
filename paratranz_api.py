import os
import time
from datetime import datetime

import requests
import yaml
from pathlib import Path
from typing import Optional, Dict, Union


class ParaTranzAPI:
    max_wait_seconds = 300  # 最大等待时间（10分钟）
    poll_interval = 5  # 轮询间隔（秒）

    def __init__(self, api_key: str, config_path: str = "config.yaml"):
        self.api_key = api_key
        self.config_path = config_path
        self.base_url = "https://paratranz.cn/api"
        self.project_id = self._load_config()['paratranz_id']
        self.headers = {
            "Authorization": api_key,
            "accept": "application/json"
        }

    def _load_config(self) -> Dict:
        """加载配置文件"""
        with open(self.config_path) as f:
            return yaml.safe_load(f) or {}

    def _save_config(self, config: Dict):
        """保存配置文件"""
        with open(self.config_path, 'w') as f:
            yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)

    def _find_file_id(self, file_name: str, target_path: str) -> Optional[int]:
        """
        根据文件名和路径查找文件ID
        """
        url = f"{self.base_url}/projects/{self.project_id}/files"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()

        files = response.json()

        for f in files:
            # 标准化路径比较
            remote_path = os.path.dirname(f['name']).replace('\\', '/').strip('/')
            local_path = target_path.replace('\\', '/').strip('/')

            if os.path.basename(f['name']) == file_name and remote_path == local_path:
                return f['id']

        return None

    def _update_config_id(self, project: str, version: str, file_id: int):
        """更新配置文件中的paratranz_id"""
        config = self._load_config()

        # 定位到对应的版本配置
        versions = config['projects'][project]['versions']
        for ver, cfg in versions.items():
            if ver == version:
                cfg['paratranz_id'] = file_id
                break
        else:
            raise KeyError(f"版本 {version} 未找到配置")

        self._save_config(config)

    def smart_upload(
            self,
            project: str,
            version: str,
            local_file_path: str,
            target_path: str = ""
    ) -> dict:
        """
        智能上传文件（自动处理ID查找和配置更新）
        """
        # 获取项目配置
        config = self._load_config()
        project_cfg = config['projects'][project]
        version_cfg = project_cfg['versions'][version]

        # 尝试从配置获取已有ID
        file_id = version_cfg.get('paratranz_id')
        file_name = os.path.basename(local_file_path)

        # 如果未找到ID，尝试查询已有文件
        if not file_id:
            file_id = self._find_file_id(file_name, target_path)

            if file_id:
                print(f"🔄️️️ 发现已有文件ID: {file_id}")
                self._update_config_id(project, version, file_id)
            else:
                print("🆕️ 未找到已有文件，将创建新文件")

        # 执行上传操作
        if file_id:
            print(f"⬆️ 开始更新文件（ID: {file_id}）")
            result = self.upload_files(
                project_id=self.project_id,
                file_path=local_file_path,
                paratranz_id=file_id,
                is_update=True
            )
        else:
            print(f"🆕️ 开始创建新文件到路径: {target_path}")
            result = self.upload_files(
                project_id=self.project_id,
                file_path=local_file_path,
                target_path=target_path
            )
            new_id = result['file']['id']
            self._update_config_id(project, version, new_id)
            print(f"✅ 新建文件ID已保存: {new_id}")

        return result

    def upload_files(self, project_id: int, file_path: Union[str, Path],
                     target_path: str = "", paratranz_id: Optional[int] = None,
                     is_update: bool = False, is_translation: bool = False,
                     force: bool = False) -> dict:
        """
        增强版上传方法（保持原有功能）
        上传文件到Paratranz平台

        :param project_id: 项目ID
        :param file_path: 本地文件路径
        :param target_path: 在项目中的存储路径（仅创建时需要）
        :param paratranz_id: 需要更新的文件ID（更新时必需）
        :param is_update: 是否是更新操作
        :param is_translation: 是否是翻译文件（更新翻译时使用）
        :param force: 是否强制覆盖已有翻译
        :return: API响应结果
        """
        # 转换路径对象并验证文件存在
        local_file = Path(file_path)
        if not local_file.exists():
            raise FileNotFoundError(f"本地文件不存在: {local_file}")

        # 构造API端点
        if is_translation:
            if not paratranz_id:
                raise ValueError("更新翻译需要提供文件ID")
            url = f"{self.base_url}/projects/{project_id}/files/{paratranz_id}/translation"
        elif is_update:
            if not paratranz_id:
                raise ValueError("更新文件需要提供文件ID")
            url = f"{self.base_url}/projects/{project_id}/files/{paratranz_id}"
        else:
            url = f"{self.base_url}/projects/{project_id}/files"

        # 准备请求数据
        files = {'file': (local_file.name, open(local_file, 'rb'))}
        data = {}

        # 添加额外参数
        if not is_update and target_path:
            data['path'] = target_path.strip('/')
        if is_translation:
            data['force'] = str(force).lower()

        try:
            response = requests.post(
                url,
                headers=self.headers,
                files=files,
                data=data,
                timeout=30
            )
            response.raise_for_status()
            return response.json()

        except requests.exceptions.HTTPError as e:
            error_info = f"HTTP错误 {response.status_code}"
            if response.content:
                try:
                    error_data = response.json()
                    error_info += f": {error_data.get('message', '未知错误')}"
                    if 'code' in error_data:
                        error_info += f" (代码: {error_data['code']})"
                except:
                    error_info += f": {response.text}"
            raise RuntimeError(f"上传失败 - {error_info}") from e

        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"网络连接错误: {str(e)}") from e

        finally:
            files['file'][1].close()  # 确保关闭文件句柄

    def generate_artifact(self):
        try:
            url = self.base_url + f"/projects/{self.project_id}/artifacts"
            response = requests.post(url, headers=self.headers)
            if response.status_code == 200:
                print("✅️ 导出任务已成功触发！")

                # ★ 改动1：POST 响应可能没有 createdAt，做个兜底
                start_created = response.json().get('createdAt')
                if start_created:
                    start_artifact_time = datetime.fromisoformat(
                        start_created.replace("Z", "+00:00")
                    )
                else:
                    start_artifact_time = datetime.now().astimezone()

                try_time = 0
                while try_time < self.max_wait_seconds:
                    try_time += self.poll_interval
                    time.sleep(self.poll_interval)
                    artifact_status = self.get_artifact()

                    # ★ 改动2：get_artifact 失败会返回 None
                    if not artifact_status:
                        print(f"🛑️️️ 时间：{try_time}s，获取导出状态失败")
                        continue

                    # ★ 改动3（关键）：任务未完成时 createdAt 是 None，
                    #   原来这行就是 .get('createdAt').replace(...) 直接爆掉
                    created_at = artifact_status.get('createdAt')
                    if not created_at:
                        print(f"🛑️️️ 时间：{try_time}s，导出任务尚未完成")
                        continue

                    artifact_time = datetime.fromisoformat(
                        created_at.replace("Z", "+00:00")
                    )
                    if artifact_time >= start_artifact_time:
                        print("✅️ 导出任务已成功完成！")
                        return
                    print(f"🛑️️️ 时间：{try_time}s，导出任务尚未完成")
            elif response.status_code == 403:
                print("错误：没有权限，请检查API Token或用户权限。")
            else:
                print(f"错误：请求失败，状态码 {response.status_code}")
                print("响应内容:", response.text)
        except requests.exceptions.RequestException as e:
            print("请求异常:", e)

    def get_artifact(self):
        try:
            url = self.base_url + f"/projects/{self.project_id}/artifacts"
            response = requests.get(url, headers=self.headers)
            if response.status_code == 200:
                job_info = response.json()
                return job_info
            else:
                print(f"错误：请求失败，状态码 {response.status_code}")
                print("响应内容:", response.text)
        except requests.exceptions.RequestException as e:
            print("请求异常:", e)

    def download_artifact(self):
        url = self.base_url + f"/projects/{self.project_id}/artifacts/download"
        for attempt in range(3):
            try:
                response = requests.get(url, headers=self.headers, timeout=10)
                response.raise_for_status()
                print(f"✅️ 下载导出结果成功 ")
                return response.content
            except requests.exceptions.RequestException as e:
                if attempt == 2:
                    raise RuntimeError(
                        f"下载导出结果失败\n"
                        f"URL: {url}\n"
                        f"错误: {str(e)}"
                    )
                print(f"⚠️ 重试中 ({attempt + 1}/3) {url}")
