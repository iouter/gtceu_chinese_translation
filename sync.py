import os
from urllib.parse import urlparse

import yaml
import json
import requests
from pathlib import Path

from paratranz_api import ParaTranzAPI

with open("config.yaml", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

paratranz_api = os.environ.get("PARATRANZ_KEY")
if not paratranz_api:
    raise ValueError("未找到 ParaTranz API 密钥")

def main():
    for project in CONFIG["projects"]:
        proj_cfg = CONFIG["projects"][project]
        versions = list(proj_cfg["versions"].keys())

        # 优先处理基础版本
        if "base" in proj_cfg:
            base_ver = proj_cfg["base"]
            if base_ver in versions:
                process_version(project, base_ver)
                versions.remove(base_ver)

        # 处理其他版本
        for ver in versions:
            process_version(project, ver, proj_cfg.get("base"))


def download_source(project: str, version: str, url: str, save_path: str):
    """
    从GitHub下载指定版本的原文文件
    """

    # 确定本地保存路径
    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    # 执行下载（带重试机制）
    print(f"⬇️ 开始下载 {project}-{version}")
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()

            with open(save_path, "wb") as f:
                f.write(response.content)

            print(f"✅️ 下载成功 {project}-{version}")

        except requests.exceptions.RequestException as e:
            if attempt == 2:
                raise RuntimeError(
                    f"下载失败 [{project}-{version}]\n"
                    f"URL: {url}\n"
                    f"错误: {str(e)}"
                )
            print(f"⚠️ 重试中 ({attempt + 1}/3) {url}")


def extract_file_extension(url: str) -> str:
    """从URL路径中提取文件扩展名"""
    parsed = urlparse(url)
    filename = parsed.path.split("/")[-1]

    if "." not in filename:
        return ""

    # 处理多扩展名情况（如file.min.json）
    return filename.split(".")[-1].lower()


def convert_file(project: str, version: str, file_extension: str, delta_path: str) -> str:
    print(f"⏩️ 转换为Paratranz格式 {project}-{version}")
    input_path = f"{project}/{version}/original/en_us.{file_extension}"
    if delta_path is not None:
        input_path = delta_path
    paratranz_name = CONFIG["projects"][project]["paratranz_name"]
    output_path = input_path.replace("original", "paratranz").replace(f"en_us.{file_extension}", paratranz_name)
    if file_extension == "lang":
        with open(input_path, 'r', encoding='utf-8') as f:
            original_texts = f.readlines()
        serial = 0
        context = "类型" + str(serial)
        translate_list = []
        for text in original_texts:
            text = text.strip()
            if text == "":
                serial += 1
                context = "类型" + str(serial)
            if "#" in text:
                context = context + "：" + text[1:].strip()
            if "=" in text:
                key, original = text.split("=", 1)
                translate_list.append({'key': key, 'original': original, 'context': context})
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(translate_list, f, sort_keys=True, separators=(',', ':'), ensure_ascii=False, indent=4)
    elif file_extension == "json":
        with open(input_path, "r", encoding="utf-8") as f:
            original = json.load(f)
        with open(output_path, "w", encoding="utf-8") as f:
            translate_list = []
            for key in original:
                transdict = {'key': key, 'original': original[key]}
                translate_list.append(transdict)
            json.dump(translate_list, f, sort_keys=True, separators=(',', ':'), ensure_ascii=False, indent=4)
    print(f"✅️ 转换成功 {project}-{version}")
    return output_path


def upload_files(project, version, paratranz_path):
    print(f"⬆️ 正在上传至Paratranz {project}-{version}")
    api = ParaTranzAPI(api_key=paratranz_api)
    target_path = f"{project}/{version}/"
    api.smart_upload(project, version, paratranz_path, target_path)
    print(f"✅️ 更新成功 {project}-{version}")


def process_version(project: str, version: str, base_ver: str = None):
    print(f"{project.upper()} {version}".center(40))

    try:
        # Step 1: 下载原文
        url = build_source_url(project, version)
        file_extension = extract_file_extension(url)
        original_path = f"{project}/{version}/original/en_us.{file_extension}"
        download_source(project, version, url, original_path)

        # Step 2: 生成差异
        delta_path = None
        if base_ver and version != base_ver:
            base_file = f"{project}/{base_ver}/original/en_us.{file_extension}"
            if file_extension == "json":
                delta_path = generate_delta_json(base_file, original_path, project, version)

        # Step 3: 转换格式
        paratranz_path = convert_file(project, version, file_extension, delta_path)

        # Step 4: 上传文件
        upload_files(project, version, paratranz_path)

    except Exception as e:
        print(f"! 流程中断: {str(e)}")
        exit(1)


def generate_delta_json(base_file: str, new_file: str, project: str, version: str) -> str:
    """生成仅包含新增键的差异文件"""
    with open(base_file, encoding="utf-8") as f:
        base_data = json.load(f)

    with open(new_file, encoding="utf-8") as f:
        new_data = json.load(f)

    delta = {k: v for k, v in new_data.items() if k not in set(base_data.keys()) or v != base_data.get(k)}

    output_path = f"{project}/{version}/original/en_us_{version}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(delta, f, indent=2)

    return output_path


def build_source_url(project: str, version: str) -> str:
    """生成GitHub raw文件地址"""
    repo = CONFIG["projects"][project]["repo"].replace("github.com", "raw.githubusercontent.com")
    branch = CONFIG["projects"][project]["versions"][version]["branch"]
    file_path = CONFIG["projects"][project]["file_path"]
    return f"{repo}/{branch}/{file_path}"


if __name__ == "__main__":
    main()