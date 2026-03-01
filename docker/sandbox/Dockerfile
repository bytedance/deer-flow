# 使用官方沙盒镜像作为基础
FROM enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest

# 设置工作目录
WORKDIR /app

# 安装 crawl4ai 及其依赖
# 注意：crawl4ai 需要 playwright，playwright 需要安装浏览器二进制文件
# 我们同时安装其他常用的数据分析库，以便其他 Skill 使用
RUN pip install crawl4ai pandas numpy scipy openpyxl yfinance requests tushare akshare PyYAML Pillow python-pptx && \
    playwright install --with-deps chromium

# 预创建缓存目录以加速后续可能的动态安装
RUN mkdir -p /root/.cache/pip
