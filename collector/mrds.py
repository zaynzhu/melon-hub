"""每日大赛(mrds)采集入口。

用法:.venv/bin/python -m collector.mrds [--list-only] [--limit N]
"""
import argparse

from collector import browser_fetch, typecho_collector

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--list-only', action='store_true', help='只拉列表不抓正文')
    parser.add_argument('--thumbs', action='store_true', help='只补抓列表缩略图')
    parser.add_argument('--backfill', action='store_true', help='全量补齐:逐页入库+缩略图')
    parser.add_argument('--pages', type=int, default=3, help='backfill 翻页数')
    parser.add_argument('--limit', type=int, default=12, help='单次抓取正文篇数')
    args = parser.parse_args()
    browser_fetch.ensure_ready()
    if args.backfill:
        typecho_collector.backfill('mrds', pages=args.pages)
    elif args.thumbs:
        typecho_collector.collect_thumbs('mrds')
    else:
        typecho_collector.collect_list('mrds')
        if not args.list_only:
            typecho_collector.collect_articles('mrds', args.limit)
    browser_fetch.close_session()
