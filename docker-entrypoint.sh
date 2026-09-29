#!/bin/sh
# melon-hub 容器入口:定时采集由应用内调度器(server/sync.py)负责,
# 配置存数据库、设置页可视化修改,与本地启动行为完全一致。
# 51吃瓜/每日大赛采集依赖宿主机真实浏览器(kimi-webbridge 过 CF),不在容器内跑;
# 宿主机采集时把 MELON_DATA_DIR 指向本容器的 /data 卷即可共用数据。
set -e

exec python -m uvicorn server.app:app --host 0.0.0.0 --port 8787