#!/bin/sh
# melon-hub 容器入口:启动即采集一次 hl365,此后每小时增量;主进程为 API 服务。
# 51吃瓜/每日大赛采集依赖宿主机真实浏览器(kimi-webbridge 过 CF),不在容器内跑;
# 宿主机采集时把 MELON_DATA_DIR 指向本容器的 /data 卷即可共用数据。
set -e

echo "[entrypoint] 首次 hl365 采集..."
python -m collector.hl365 --pages 1 || echo "[entrypoint] 首次采集失败,服务照常启动"

(
  while true; do
    sleep 3600
    echo "[entrypoint] 定时 hl365 增量采集..."
    python -m collector.hl365 --pages 1 || true
  done
) &

exec python -m uvicorn server.app:app --host 0.0.0.0 --port 8787
