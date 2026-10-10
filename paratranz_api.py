import os
import time
from datetime import datetime

import requests
import yaml
from pathlib import Path
from typing import Optional, Dict, Union


class ParaTranzAPI:
    max_wait_seconds = 300  # 最大等待时间（5 分钟）
    poll_interval = 5       # 轮询间隔（秒）

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
        """根据文件名和路径查找文件ID"""
        url = f"{self.base_url}/projects/{self.project_id}/files"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()

        files = response.json()

        for f in files:
            remote_path = os.path.dirname(f['name']).replace('\\', '/').strip('/')
            local_path = target_path.replace('\\', '/').strip('/')

            if os.path.basename(f['name']) == file_name and remote_path == local_path:
                return f['id']

        return None

    def _update_config_id(self, project: str, version: str, file_id: int):
        """更新配置文件中的paratranz_id"""
        config = self._load_config()

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
        """智能上传文件（自动处理ID查找和配置更新）"""
        config = self._load_config()
        project_cfg = config['projects'][project]
        version_cfg = project_cfg['versions'][version]

        file_id = version_cfg.get('paratranz_id')
        file_name = os.path.basename(local_file_path)

        if not file_id:
            file_id = self._find_file_id(file_name, target_path)

            if file_id:
                print(f"🔄️️️ 发现已有文件ID: {file_id}")
                self._update_config_id(project, version, file_id)
            else:
                print("🆕️ 未找到已有文件，将创建新文件")

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
        """增强版上传方法（保持原有功能）"""
        local_file = Path(file_path)
        if not local_file.exists():
            raise FileNotFoundError(f"本地文件不存在: {local_file}")

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

        files = {'file': (local_file.name, open(local_file, 'rb'))}
        data = {}

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
            files['file'][1].close()

    # ------------------------------------------------------------------ #
    # Artifacts
    # ------------------------------------------------------------------ #
    def get_artifact(self) -> Optional[dict]:
        """获取导出结果列表（返回分页对象，results 为数组）"""
        try:
            url = f"{self.base_url}/projects/{self.project_id}/artifacts"
            response = requests.get(url, headers=self.headers, timeout=30)
            if response.status_code == 200:
                return response.json()
            print(f"错误：请求失败，状态码 {response.status_code}")
            print("响应内容:", response.text)
        except requests.exceptions.RequestException as e:
            print("请求异常:", e)
        return None

    @staticmethod
    def _artifact_results(data) -> list:
        """从分页响应里取出 results 数组，兼容直接返回 list 的情况"""
        if isinstance(data, dict):
            results = data.get("results")
            if isinstance(results, list):
                return results
        if isinstance(data, list):
            return data
        return []

    def generate_artifact(self):
        """触发导出并等待新 artifact 生成完成。

        修复点：
          1. GET /artifacts 返回的是分页对象，createdAt 在 results[i] 里
          2. POST /artifacts 返回的是 Job，不是 Artifact
          3. 轮询时以“新出现的 artifact id”为准，不再拿顶层 createdAt
        """
        # 1. 记录触发前的 artifact id 集合
        before_data = self.get_artifact()
        before_ids = {
            a.get("id")
            for a in self._artifact_results(before_data)
            if isinstance(a, dict)
        }

        # 2. 触发导出
        try:
            url = f"{self.base_url}/projects/{self.project_id}/artifacts"
            response = requests.post(url, headers=self.headers, timeout=30)
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"触发导出请求异常: {e}") from e

        if response.status_code == 403:
            raise RuntimeError("没有权限触发导出，请检查 API Token 或用户权限")
        if response.status_code != 200:
            raise RuntimeError(
                f"触发导出失败，状态码 {response.status_code}: {response.text}"
            )
        print("✅️ 导出任务已成功触发！")

        # 3. 轮询等待新 artifact 出现
        try_time = 0
        last_seen = None
        while try_time < self.max_wait_seconds:
            time.sleep(self.poll_interval)
            try_time += self.poll_interval

            data = self.get_artifact()
            results = self._artifact_results(data)
            last_seen = results

            new_ready = [
                a for a in results
                if isinstance(a, dict)
                and a.get("id") not in before_ids
                and a.get("createdAt")
            ]

            if new_ready:
                latest = max(new_ready, key=lambda x: x.get("id") or 0)
                created_at = latest.get("createdAt")
                try:
                    artifact_time = datetime.fromisoformat(
                        created_at.replace("Z", "+00:00")
                    )
                    print(f"✅️ 导出任务已成功完成！artifact_time={artifact_time}")
                except Exception:
                    print(f"✅️ 导出任务已成功完成！createdAt={created_at}")
                return latest

            print(f"🛑️️️ 时间：{try_time}s，导出任务尚未完成")

        raise RuntimeError(
            f"导出任务超时（{self.max_wait_seconds}s），最后一次 results: {last_seen}"
        )

    def download_artifact(self):
        """下载导出结果（302 会由 requests 自动跟随）"""
        url = self.base_url + f"/projects/{self.project_id}/artifacts/download"
        for attempt in range(3):
            try:
                response = requests.get(url, headers=self.headers, timeout=30)
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
