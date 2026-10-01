FROM python:3.12-slim

WORKDIR /app

# curl 供 HEALTHCHECK;playwright chromium 系统依赖在镜像构建时装齐
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install-deps chromium \
    && playwright install chromium

# 运行期收尾从 scripts/ 导入(article_img_decrypt/thumbs_backfill)
COPY collector/ collector/
COPY server/ server/
COPY web/ web/
COPY config/ config/
COPY scripts/article_img_decrypt.py scripts/
COPY scripts/thumbs_backfill.py scripts/
COPY docker-entrypoint.sh .
RUN chmod +x docker-entrypoint.sh

# 数据(SQLite + 对象文件)全部落在挂载卷,容器无状态
ENV MELON_DATA_DIR=/data
# 容器内浏览器后端:无头 Chromium(过 CF 托管挑战,docs/lessons/headless-browser-pass-cf.md);
# 宿主机开发时改 MELON_BROWSER_BACKEND=webbridge 走 kimi-webbridge 扩展
ENV MELON_BROWSER_BACKEND=playwright
# 容器日志时间戳用上海时区;调度时区由代码内 zoneinfo(MELON_TZ,默认 Asia/Shanghai)决定
ENV TZ=Asia/Shanghai
VOLUME /data
EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
    CMD curl -sf http://127.0.0.1:8787/api/sources || exit 1

CMD ["./docker-entrypoint.sh"]
