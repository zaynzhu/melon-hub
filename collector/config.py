"""加载 .env(存在则注入环境变量,不覆盖已有值)与 config/sites.yaml。"""
import os

import yaml

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_config = None


def project_root():
    return _ROOT


def data_dir():
    return os.environ.get('MELON_DATA_DIR') or os.path.join(_ROOT, 'data')


def load_env():
    env_path = os.path.join(_ROOT, '.env')
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, value = line.partition('=')
            os.environ.setdefault(key.strip(), value.strip())


load_env()


def load_config():
    global _config
    if _config is None:
        path = os.path.join(_ROOT, 'config', 'sites.yaml')
        with open(path, encoding='utf-8') as f:
            _config = yaml.safe_load(f)
    return _config
