import io
import json
import os
import zipfile
from pathlib import Path

import yaml
from paratranz_api import ParaTranzAPI

with open("config.yaml", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

paratranz_api = os.environ.get("PARATRANZ_KEY")
if not paratranz_api:
    raise ValueError("未找到 ParaTranz API 密钥")
api = ParaTranzAPI(api_key=paratranz_api)


def unzip_files(project, version, zip_ref, base_ver: str = None):
    print(f"⏪️ 开始解压 {project}-{version}")
    file_name = CONFIG["projects"][project]["paratranz_name"]
    save_path = f"{project}/{version}/paratranz_output"
    zip_path = f"utf8/{project}/{version}/{file_name}"

    if base_ver is not None:
        file_name = file_name.replace(".json", f"_{version}.json")
        zip_path = f"utf8/{project}/{version}/{file_name}"

    Path(save_path).mkdir(parents=True, exist_ok=True)
    source = zip_ref.open(zip_path)
    target = open(os.path.join(save_path, file_name), "wb")
    with source, target:
        target.write(source.read())
    print(f"✅️ 解压完成 {project}-{version}")
    return


def convert_files(project: str, version: str, base_ver: str = None):
    print(f"⬅️ 开始转回minencraft格式 {project}-{version}")
    paratranz_name = CONFIG["projects"][project]["paratranz_name"]
    translated_name = CONFIG["projects"][project]["tranlated_name"]
    translated_path = f"{project}/{version}/translation/{translated_name}"
    file_extension = translated_name.split(".")[-1].lower()
    original_path = f"{project}/{version}/original/en_us.{file_extension}"
    if base_ver is not None:
        base_path = f"{project}/{base_ver}/paratranz_output/{paratranz_name}"
        delta_name = paratranz_name.replace(".json", f"_{version}.json")
        delta_path = f"{project}/{version}/paratranz_output/{delta_name}"
        if file_extension == "json":
            with open(base_path, "r", encoding="utf-8") as o:
                base = json.load(o)
            with open(delta_path, 'r', encoding="utf-8") as d:
                delta = json.load(d)
            with open(original_path, 'r', encoding="utf-8") as o:
                original = json.load(o)
            with open(translated_path, "w", encoding="utf-8") as f:
                translate_dict = {}
                for trans in base + delta:
                    key = trans['key']
                    if key in original.keys():
                        if len(trans['translation']) == 0:
                            translate_dict[key] = trans['original']
                        else:
                            translate_dict[key] = trans['translation']
                json.dump(translate_dict, f, sort_keys=True, separators=(',', ':'), ensure_ascii=False, indent=4)
    else:
        input_path = f"{project}/{version}/paratranz_output/{paratranz_name}"
        if file_extension == "json":
            with open(input_path, "r", encoding="utf-8") as o:
                original = json.load(o)
            with open(translated_path, "w", encoding="utf-8") as f:
                translate_dict = {}
                for trans in original:
                    if len(trans['translation']) == 0:
                        translate_dict[trans['key']] = trans['original']
                    else:
                        translate_dict[trans['key']] = trans['translation']
                json.dump(translate_dict, f, sort_keys=True, separators=(',', ':'), ensure_ascii=False, indent=4)
        elif file_extension == "lang":
            with open(original_path, "r", encoding="utf-8") as p:
                text = p.read()
            with open(input_path, 'r', encoding='utf-8') as o:
                translate_list = json.load(o)
            for translate_dict in translate_list:
                if translate_dict.get('translation') is not None:
                    old = "{}={}".format(translate_dict['key'], translate_dict['original'])
                    new = "{}={}".format(translate_dict['key'], translate_dict['translation'])
                    text = text.replace(old, new, 1)
            with open(translated_path, "w", encoding="utf-8") as t:
                t.write(text)
    print(f"✅️ 转换完成 {project}-{version}")
    return


def process_version(project: str, version: str, zip_ref, base_ver: str = None):
    print(f"{project.upper()} {version}".center(40))
    try:
        # 步骤1：解压
        unzip_files(project, version, zip_ref, base_ver)
        # 步骤2：转换
        convert_files(project, version, base_ver)
    except Exception as e:
        print(f"! 流程中断: {str(e)}")
        exit(1)


def main():
    api.generate_artifact()
    zip_data = api.download_artifact()
    zip_buffer = io.BytesIO(zip_data)

    with zipfile.ZipFile(zip_buffer, 'r') as zip_ref:
        for project in CONFIG["projects"]:
            proj_cfg = CONFIG["projects"][project]
            versions = list(proj_cfg["versions"].keys())

            # 优先处理基础版本
            if "base" in proj_cfg:
                base_ver = proj_cfg["base"]
                if base_ver in versions:
                    process_version(project, base_ver, zip_ref)
                    versions.remove(base_ver)

            # 处理其他版本
            for ver in versions:
                process_version(project, ver, zip_ref, proj_cfg.get("base"))


if __name__ == "__main__":
    main()
