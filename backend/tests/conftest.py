"""pytest 配置：把 backend/ 加入 sys.path"""
import os
import sys

# 让 app.* 能被导入
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)
