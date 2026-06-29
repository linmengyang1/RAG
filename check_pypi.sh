#!/bin/bash
# 检查 pip 配置和 PyPI 连通性
echo "=== pip 配置 ==="
cat /etc/pip.conf 2>/dev/null || echo "  无 /etc/pip.conf"
pip config list 2>&1

echo
echo "=== PyPI 连通性 ==="
curl -sS -o /dev/null -w "pypi.org: %{http_code} (%{time_total}s)\n" --connect-timeout 5 https://pypi.org 2>&1
curl -sS -o /dev/null -w "pypi.tuna: %{http_code} (%{time_total}s)\n" --connect-timeout 5 https://pypi.tuna.tsinghua.edu.cn 2>&1
curl -sS -o /dev/null -w "mirrors.aliyun: %{http_code} (%{time_total}s)\n" --connect-timeout 5 https://mirrors.aliyun.com/pypi/simple/ 2>&1

echo
echo "=== 尝试安装 transformers 4.57.6（清华源）==="
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple "transformers==4.57.6" 2>&1 | tail -20

echo
echo "=== 安装后版本 ==="
python -c "import transformers; print(f'transformers: {transformers.__version__}')"
