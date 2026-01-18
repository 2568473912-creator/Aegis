import json
import os

CONFIG_FILE = "config.json"

# 默认配置 (当配置文件不存在或读取出错时使用)
DEFAULT_CONFIG = {
    "effective_bits_idx": 0,
    "channel_count_idx": 0,
    "use_robust": True,

    "thresh_global_h": 20,
    "thresh_global_v": 20,
    "thresh_part_h": 10,
    "thresh_part_v": 10,
    "block_qty": 10,

    "strip_h": 0,
    "strip_v": 0,
    "edge_gain": 1.0,

    "vis_pad": 5,
    "crop_pad": 20,

    "last_folder": ""
}


class ConfigManager:
    @staticmethod
    def load_config():
        """加载配置，返回字典。如果文件不存在则返回默认值。"""
        if not os.path.exists(CONFIG_FILE):
            return DEFAULT_CONFIG.copy()

        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # 合并默认配置，防止旧版配置文件缺少新字段
                config = DEFAULT_CONFIG.copy()
                config.update(data)
                return config
        except Exception as e:
            print(f"Error loading config: {e}")
            return DEFAULT_CONFIG.copy()

    @staticmethod
    def save_config(data):
        """保存配置到文件"""
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"Error saving config: {e}")