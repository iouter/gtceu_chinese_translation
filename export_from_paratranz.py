import os
import yaml
from paratranz_api import ParaTranzAPI

with open("config.yaml", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

paratranz_api = os.environ.get("PARATRANZ_KEY")
if not paratranz_api:
    raise ValueError("未找到 ParaTranz API 密钥")
api = ParaTranzAPI(api_key=paratranz_api)


def main():
    pass


def generate_artifact():
    pass


if __name__ == "__main__":
    main()