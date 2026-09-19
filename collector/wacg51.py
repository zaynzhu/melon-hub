"""51吃瓜(wacg51)采集入口。

用法:.venv/bin/python -m collector.wacg51 [--list-only] [--limit N]
"""
import argparse

from collector import browser_fetch, typecho_collector

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--list-only', action='store_true', help='只拉列表不抓正文')
    parser.add_argument('--thumbs', action='store_true', help='只补抓列表缩略图')
    parser.add_argument('--limit', type=int, default=12, help='单次抓取正文篇数')
    args = parser.parse_args()
    browser_fetch.ensure_ready()
    if args.thumbs:
        typecho_collector.collect_thumbs('wacg51')
    else:
        typecho_collector.collect_list('wacg51')
        if not args.list_only:
            typecho_collector.collect_articles('wacg51', args.limit)
    browser_fetch.close_session()
