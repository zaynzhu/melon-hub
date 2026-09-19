FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY collector/ collector/
COPY server/ server/
COPY web/ web/
COPY config/ config/
COPY docker-entrypoint.sh .
RUN chmod +x docker-entrypoint.sh

# 数据(SQLite + 对象文件)全部落在挂载卷,容器无状态
ENV MELON_DATA_DIR=/data
VOLUME /data
EXPOSE 8787

CMD ["./docker-entrypoint.sh"]
