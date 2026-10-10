import io
import os
import time
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

import requests


class ParaTranzError(RuntimeError):
    """ParaTranz 相关错误统一异常类型。"""


class ParaTranzAPI:
    """ParaTranz API 客户端。

    参数:
        api_key:    ParaTranz 个人令牌（从环境变量 PARATRANZ_KEY 读取亦可）。
        project_id: 项目 ID。若不传则尝试从环境变量 PARATRANZ_PROJECT_ID 读取。
        base_url:   自定义 API 根地址，默认为 https://paratranz.cn/api。
        timeout:    单次 HTTP 请求超时（秒）。
    """

    BASE_URL = "https://paratranz.cn/api"

    def __init__(
        self,
        api_key: str,
        project_id: Optional[int] = None,
        base_url: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        if not api_key:
            raise ValueError("未找到 ParaTranz API 密钥")

        self.api_key = api_key
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self.timeout = timeout

        # project_id 允许通过参数或环境变量提供
        if project_id is None:
            env_id = os.environ.get("PARATRANZ_PROJECT_ID")
            if env_id:
                try:
                    project_id = int(env_id)
                except ValueError:
                    raise ValueError(
                        f"PARATRANZ_PROJECT_ID 不是合法整数: {env_id!r}"
                    )
        self.project_id: Optional[int] = project_id

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": self.api_key,
                "Accept": "application/json",
                "User-Agent": "gtceu-chinese-translation/1.0",
            }
        )

        # 记录最近一次生成的 artifact，download_artifact() 默认复用它
        self._last_artifact: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------ #
    # 内部工具
    # ------------------------------------------------------------------ #
    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        resp = self.session.request(method, self._url(path), **kwargs)
        if not resp.ok:
            raise ParaTranzError(
                f"[{method} {path}] HTTP {resp.status_code}: {resp.text[:500]}"
            )
        return resp

    def _require_project_id(self) -> int:
        if not self.project_id:
            raise ParaTranzError(
                "未配置 project_id，请通过构造参数或环境变量 "
                "PARATRANZ_PROJECT_ID 指定"
            )
        return self.project_id

    # ------------------------------------------------------------------ #
    # artifact 查询 / 状态判断
    # ------------------------------------------------------------------ #
    def _list_artifacts(self) -> List[Dict[str, Any]]:
        """拉取项目的 artifact 列表，兼容多种返回结构。"""
        pid = self._require_project_id()
        resp = self._request("GET", f"/projects/{pid}/artifacts")
        try:
            data = resp.json()
        except ValueError:
            return []

        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("artifacts", "data", "items", "results"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
        return []

    @staticmethod
    def _artifact_ready(artifact: Any) -> bool:
        """判断一个 artifact 是否已经生成完成、可以下载。"""
        if not isinstance(artifact, dict):
            return False
        # 关键：必须有 createdAt，否则就是刚入队还没生成
        if not artifact.get("createdAt"):
            return False
        status = str(artifact.get("status", "")).lower()
        if status in {"pending", "processing", "running", "queued", "waiting"}:
            return False
        return True

    @staticmethod
    def _artifact_sort_key(artifact: Dict[str, Any]) -> str:
        # createdAt 是 ISO8601 字符串，直接按字典序倒排即可
        return artifact.get("createdAt") or ""

    # ------------------------------------------------------------------ #
    # 对外接口
    # ------------------------------------------------------------------ #
    def generate_artifact(
        self,
        timeout: int = 600,
        interval: float = 3.0,
        expected_count: int = 1,
    ) -> Dict[str, Any]:
        """触发一次导出任务，并轮询等待 artifact 就绪。

        参数:
            timeout:        最长等待时间（秒）。
            interval:       轮询间隔（秒）。
            expected_count: 期望生成多少个 artifact（一般 1 个即可）。

        返回:
            最新的 artifact 字典（含 id / createdAt 等字段）。
        """
        pid = self._require_project_id()

        # 记录触发前已有的 artifact id，用于识别“本次新生成的”
        try:
            before_ids = {a.get("id") for a in self._list_artifacts()}
        except ParaTranzError:
            before_ids = set()

        # 1. 触发导出
        self._request("POST", f"/projects/{pid}/artifacts")
        print("✅️ 导出任务已成功触发！")

        # 2. 轮询等待新 artifact 出现并进入 ready 状态
        deadline = time.time() + timeout
        last_seen: Optional[Dict[str, Any]] = None

        while time.time() < deadline:
            artifacts = self._list_artifacts()
            new_artifacts = [
                a for a in artifacts
                if isinstance(a, dict) and a.get("id") not in before_ids
            ]
            ready_new = [a for a in new_artifacts if self._artifact_ready(a)]

            if ready_new:
                latest = sorted(
                    ready_new, key=self._artifact_sort_key, reverse=True
                )[0]
                created_at = latest.get("createdAt")

                # 防御式解析时间戳（核心修复点）
                artifact_time: Any
                try:
                    artifact_time = datetime.fromisoformat(
                        created_at.replace("Z", "+00:00")
                    )
                except Exception:  # noqa: BLE001
                    artifact_time = created_at

                print(f"✅️ 导出完成，artifact 时间: {artifact_time}")
                self._last_artifact = latest
                return latest

            # 用于超时时的诊断信息
            if new_artifacts:
                last_seen = sorted(
                    new_artifacts, key=self._artifact_sort_key, reverse=True
                )[0]

            print("⏳ 等待导出任务完成...")
            time.sleep(interval)

        raise ParaTranzError(
            f"导出任务超时（{timeout}s），最后一次 artifact 状态: {last_seen}"
        )

    def download_artifact(
        self,
        artifact: Optional[Union[int, Dict[str, Any]]] = None,
        retries: int = 3,
        interval: float = 3.0,
    ) -> bytes:
        """下载导出 zip 的二进制内容。

        参数:
            artifact: 可以是 artifact id（int）、artifact 字典，或 None。
                      为 None 时优先复用 generate_artifact() 的结果，
                      再退化为“列表里最新的 ready artifact”。
            retries:  下载失败重试次数。
            interval: 重试间隔（秒）。

        返回:
            zip 文件的 bytes。
        """
        pid = self._require_project_id()

        # ---- 1. 解析 artifact id ----
        artifact_id: Optional[int] = None
        if isinstance(artifact, dict):
            artifact_id = artifact.get("id")
        elif isinstance(artifact, int):
            artifact_id = artifact
        elif artifact is None and self._last_artifact is not None:
            artifact_id = self._last_artifact.get("id")

        if artifact_id is None:
            artifacts = self._list_artifacts()
            ready = [a for a in artifacts if self._artifact_ready(a)]
            if not ready:
                raise ParaTranzError("找不到可下载的 artifact")
            artifact_id = sorted(
                ready, key=self._artifact_sort_key, reverse=True
            )[0].get("id")

        if artifact_id is None:
            raise ParaTranzError("无法确定 artifact id")

        # ---- 2. 下载 ----
        last_err: Optional[Exception] = None
        for attempt in range(1, retries + 1):
            try:
                resp = self._request(
                    "GET",
                    f"/projects/{pid}/artifacts/{artifact_id}/download",
                )
                data = resp.content
                if not data:
                    raise ParaTranzError("下载返回内容为空")

                # 简单校验是不是真的 zip（PK 头）
                if not data.startswith(b"PK"):
                    preview = data[:200]
                    raise ParaTranzError(
                        f"下载内容不是 zip，前 200 字节: {preview!r}"
                    )
                return data
            except Exception as e:  # noqa: BLE001
                last_err = e
                print(f"⚠️ 下载失败 (第 {attempt}/{retries} 次): {e}")
                if attempt < retries:
                    time.sleep(interval)

        raise ParaTranzError(
            f"下载 artifact {artifact_id} 失败: {last_err}"
        )


# ---------------------------------------------------------------------- #
# 本地自测
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    key = os.environ.get("PARATRANZ_KEY")
    if not key:
        raise SystemExit("请先设置环境变量 PARATRANZ_KEY")

    api = ParaTranzAPI(api_key=key)
    artifact_info = api.generate_artifact()
    zip_bytes = api.download_artifact(artifact_info)

    print(f"📦 下载完成，共 {len(zip_bytes)} 字节")
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        print(f"📂 zip 内包含 {len(names)} 个文件，前 10 项:")
        for n in names[:10]:
            print("   ", n)
