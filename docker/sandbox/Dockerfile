# 使用官方沙盒镜像作为基础
FROM enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest

# 设置工作目录
WORKDIR /app

# 1. 配置 pip 镜像源（清华源）以加速下载，防止网络超时
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 2. 安装 Python 依赖
# 分层构建：先安装依赖，再安装 Playwright，方便利用缓存
RUN pip install crawl4ai pandas numpy scipy openpyxl yfinance requests tushare akshare PyYAML Pillow python-pptx

# 3. 安装 Playwright 浏览器环境
# --with-deps 会尝试安装系统依赖，如果基础镜像非 root 用户可能需要 sudo，但通常容器内默认为 root
RUN playwright install --with-deps chromium

# 预创建缓存目录
RUN mkdir -p /root/.cache/pip
