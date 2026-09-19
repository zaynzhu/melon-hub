"""加载 config/sites.yaml(项目根由 collector 包位置推导,避免依赖 cwd)。"""
import os

import yaml

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_config = None


def project_root():
    return _ROOT


def data_dir():
    return os.environ.get('MELON_DATA_DIR') or os.path.join(_ROOT, 'data')


def load_config():
    global _config
    if _config is None:
        path = os.path.join(_ROOT, 'config', 'sites.yaml')
        with open(path, encoding='utf-8') as f:
            _config = yaml.safe_load(f)
    return _config
