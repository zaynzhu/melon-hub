"""正文密文图批量解密:RustFS 密文对象 → 本地 AES-CBC 解密 → 同 key 原地覆盖。

原理与踩坑详见 docs/image-decrypt-playbook.md,要点:
  - 三站正文图 CDN 对所有 HTTP 客户端返回 AES-CBC 密文,密钥/IV 硬编码在
    站内 usr/plugins/ai/common/image.*.js(字符码拼接,见坑 14)。
  - 密文对象采集时已全部落 RustFS(2026-09-29 盘点 2788 张零缺失),
    批量解密全程内网,不访问外站,不受频率限制约束。
  - 对象 key 与 images_json 不变,仅覆盖对象字节;DB 零写入。

三阶段(备份是覆盖的硬闸门):
  1. 盘点:images_json 建对象清单,逐个验魔数分类(明文跳过/密文待解)。
  2. 备份:全部密文备份到 data/backup_cipher/<key>,逐个校验大小一致,
     未 100% 完成不进入覆盖阶段。
  3. 解密:pycryptodome AES-128-CBC + PKCS7,解出后验魔数,失败单篇保留
     密文并计入失败清单。首张即失败视为密钥错误,整体中止。

密钥不硬编码(仓库推送 GitHub,不能公开站方密钥):运行时从 JS 文件提取。
用法:
  .venv/bin/python scripts/article_img_decrypt.py --js-file /tmp/mh_hl365_image.js
  .venv/bin/python scripts/article_img_decrypt.py --js-file a.js --limit 12   # 小批量
  .venv/bin/python scripts/article_img_decrypt.py --dry-run                   # 只盘点
"""
import argparse
import base64
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Crypto.Cipher import AES  # noqa: E402

from collector.store import Database, ObjectStore  # noqa: E402

_BACKUP_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'data', 'backup_cipher')


def _kind(raw):
    """魔数判图:curl 200 / 扩展名校验发现不了密文。"""
    if raw[:2] == b'\xff\xd8':
        return 'jpg'
    if raw[:3] == b'GIF':
        return 'gif'
    if raw[:4] == b'\x89PNG':
        return 'png'
    if raw[:4] == b'RIFF':
        return 'webp'
    return None


def _collect_keys(db):
    """images_json 里的对象 key 全集(跨文章可能共用同一图,需去重)。"""
    with db.conn.cursor() as cur:
        cur.execute(
            "select source, images_json from articles "
            "where images_json is not null and images_json != '[]' and images_json != ''")
    keys = set()
    for row in cur.fetchall():
        for im in json.loads(row['images_json']):
            if im.get('key'):
                keys.add(im['key'])
    return sorted(keys)


def _backup_path(key):
    return os.path.join(_BACKUP_ROOT, key)


def _extract_keyiv(js_text):
    """从站内混淆 JS 提取 AES 密钥/IV(字符码下划线串)。

    主模式:cc("102_53_...") —— 站方当前混淆器的拼接函数名;失效时回退到
    AES.decrypt 调用点附近任意字符码串。候选必须恰好 2 个,多了少了都人工
    确认,不猜。
    """
    candidates = re.findall(r'cc\("([0-9_]+)"\)', js_text)
    if not candidates:
        window = ''
        for m in re.finditer(r'AES\.decrypt', js_text):
            window += js_text[max(0, m.start() - 800):m.end() + 800]
        candidates = re.findall(r'"([0-9]+(?:_[0-9]+)+)"', window)

    decoded = []
    seen = set()
    for c in candidates:
        s = ''.join(chr(int(x)) for x in c.split('_'))
        if len(s) == 16 and s.isprintable() and s not in seen:
            seen.add(s)
            decoded.append(s)
    if len(decoded) != 2:
        raise SystemExit(f'密钥提取异常:期望恰好 2 个 16 字符候选,实得 {len(decoded)}: {decoded};'
                         '请人工核对 JS 后改代码,不要猜')
    return decoded[0].encode(), decoded[1].encode()  # 代码顺序:key 在前,iv 在后


def _decrypt_one(cipher, key, iv):
    """AES-128-CBC + PKCS7。填充不合法视为失败,不做宽松去填充。"""
    if len(cipher) % 16 != 0:
        return None
    pt = AES.new(key, AES.MODE_CBC, iv).decrypt(cipher)
    pad = pt[-1]
    if not (1 <= pad <= 16) or pt[-pad:] != bytes([pad]) * pad:
        return None
    return pt[:-pad]


def _load_keyiv(js_files):
    """依次尝试多个 JS 提取密钥,返回 (key, iv);全失败抛 SystemExit。"""
    for path in js_files:
        with open(path, encoding='utf-8', errors='replace') as f:
            try:
                return _extract_keyiv(f.read())
            except SystemExit:
                continue
    raise SystemExit(f'所有 JS 均未提取到密钥: {js_files}')


def auto_decrypt_new(js_files=None, keys=None):
    """采集后自动校验+解密新落的密文图(供 sync 调度/手动同步收尾调用)。

    与 main() 的差异:只处理本次指定的 keys(不扫全库),静默成功、
    显式返回统计;无密文时零开销。备份硬闸门与 main() 同规则。
    返回 {'checked': n, 'cipher': n, 'ok': n, 'failed': [keys]}。
    """
    store = ObjectStore()
    db = Database()
    checked = keys if keys is not None else _collect_keys(db)
    plain, cipher = [], []
    for k in checked:
        try:
            raw = store.get_bytes(k)
        except FileNotFoundError:
            continue  # 缺失不入库,重抓归 thumbs_backfill
        (plain if _kind(raw) else cipher).append((k, raw))
    stats = {'checked': len(checked), 'cipher': len(cipher), 'ok': 0, 'failed': []}
    if not cipher:
        return stats
    if js_files is None:
        js_files = [p for p in os.environ.get('MELON_DECRYPT_JS', '').split(',') if p]
    if not js_files:
        stats['failed'] = [k for k, _ in cipher]
        print(f'[img-check] 发现 {len(cipher)} 张密文但未配 MELON_DECRYPT_JS,'
              '未解密(密文保留)', file=sys.stderr)
        return stats
    key, iv = _load_keyiv(js_files)
    # 备份硬闸门:全量备份校验通过才覆盖
    for k, raw in cipher:
        path = _backup_path(k)
        if os.path.exists(path) and os.path.getsize(path) == len(raw):
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(raw)
    bad = [k for k, raw in cipher
           if not (os.path.exists(_backup_path(k))
                   and os.path.getsize(_backup_path(k)) == len(raw))]
    if bad:
        stats['failed'] = [k for k, _ in cipher]
        print(f'[img-check] 备份校验失败 {len(bad)} 个,本次跳过解密', file=sys.stderr)
        return stats
    for k, raw in cipher:
        pt = _decrypt_one(raw, key, iv)
        if pt and _kind(pt):
            store.put(k, pt)
            stats['ok'] += 1
        else:
            stats['failed'].append(k)
    print(f'[img-check] 密文图自动解密:{stats["ok"]}/{len(cipher)},'
          f'失败 {len(stats["failed"])}(密文保留)')
    return stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--js-file', action='append', required=True,
                        help='站内 image.*.js 本地路径,可多次传入;用于运行时提取密钥')
    parser.add_argument('--limit', type=int, default=0, help='最多解密张数,0 不限')
    parser.add_argument('--dry-run', action='store_true', help='只盘点不备份不覆盖')
    args = parser.parse_args()

    store = ObjectStore()
    db = Database()

    # 阶段 1:盘点
    keys = _collect_keys(db)
    plain, cipher, missing = [], [], []
    for k in keys:
        try:
            raw = store.get_bytes(k)
        except FileNotFoundError:
            missing.append(k)
            continue
        (plain if _kind(raw) else cipher).append((k, raw))
    print(f'盘点:对象 {len(keys)} = 明文 {len(plain)}(跳过) + 密文 {len(cipher)}(待解)'
          f' + 缺失 {len(missing)}')
    if missing:
        print(f'[warn] 缺失对象(不入库不处理,需从 source_url 重抓): {missing[:5]}'
              f'{"..." if len(missing) > 5 else ""}')
    if args.dry_run:
        return
    if not cipher:
        print('无密文待解,完成')
        return
    if args.limit:
        cipher = cipher[:args.limit]
        print(f'--limit 生效:本次处理 {len(cipher)} 张')

    # 阶段 2:备份(覆盖的硬闸门)
    print(f'备份 {len(cipher)} 张密文 → {_BACKUP_ROOT}')
    for k, raw in cipher:
        path = _backup_path(k)
        if os.path.exists(path) and os.path.getsize(path) == len(raw):
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(raw)
    bad = [k for k, raw in cipher
           if not (os.path.exists(_backup_path(k))
                   and os.path.getsize(_backup_path(k)) == len(raw))]
    if bad:
        raise SystemExit(f'备份校验失败 {len(bad)} 个(如 {bad[0]}),中止,未覆盖任何对象')
    print('备份校验通过,进入解密')

    # 阶段 3:解密
    key, iv = _load_keyiv(args.js_file)
    print(f'密钥提取 OK(首个 JS 命中): key/IV 已从 JS 提取,首张试解验证')

    ok, failed = 0, []
    for idx, (k, raw) in enumerate(cipher, 1):
        pt = _decrypt_one(raw, key, iv)
        ext = _kind(pt) if pt else None
        if not ext:
            failed.append(k)
            if idx == 1:
                raise SystemExit(f'首张 {k} 解密失败(魔数/填充不对),判定密钥错误,整体中止')
            continue
        for attempt in range(3):
            try:
                store.put(k, pt)
                ok += 1
                break
            except Exception as exc:  # noqa: BLE001 上传重试,失败保留密文
                if attempt == 2:
                    failed.append(k)
                    print(f'[fail] {k} 上传重试耗尽: {exc}', file=sys.stderr)
        if idx % 100 == 0:
            print(f'  进度 {idx}/{len(cipher)},成功 {ok},失败 {len(failed)}')
    print(f'完成:解密 {ok}/{len(cipher)},失败 {len(failed)}')
    if failed:
        print('失败清单(密文已保留,可人工排查):')
        for k in failed:
            print(f'  {k}')


if __name__ == '__main__':
    main()
