# -*- coding: utf-8 -*-
# GitHub Actions自动更新直播源脚本（从橙子IPTV两个源采集，检测有效性）

import urllib.request
import urllib.parse
import re
import concurrent.futures
import ssl

# 橙子IPTV的两个源
SOURCES = [
    "https://v6.gh-proxy.org/https://raw.githubusercontent.com/OrangeWay520/my-iptv/master/my_channels.m3u",
    "https://live.zbds.top/tv/iptv4.m3u",
]

# 超时时间（秒）
TIMEOUT = 10

# 并发数
CONCURRENCY = 20

# 忽略 SSL 证书验证
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE


def fetch_url(url):
    """下载 URL 内容"""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        resp = urllib.request.urlopen(req, timeout=TIMEOUT, context=ssl_ctx)
        return resp.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"  下载失败: {url} - {e}")
        return None


def parse_m3u(content):
    """解析 m3u 内容，返回 {频道名: [URL列表]}"""
    channels = {}
    lines = content.split('\n')
    current_name = None

    for line in lines:
        line = line.strip()
        if line.startswith('#EXTINF:'):
            # 解析频道名
            match = re.search(r',(.+)$', line)
            if match:
                current_name = match.group(1).strip()
        elif line and not line.startswith('#') and current_name:
            # 这是一个 URL
            if current_name not in channels:
                channels[current_name] = []
            channels[current_name].append(line)
            current_name = None

    return channels


def check_url_valid(url):
    """检测 URL 是否有效（返回 200，且是有效的 m3u8，不是报错 json）"""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        resp = urllib.request.urlopen(req, timeout=TIMEOUT, context=ssl_ctx)

        # 先读前 2KB，看看是不是有效的 m3u8
        content = resp.read(2048).decode('utf-8', errors='ignore')

        # 有效的 m3u8 应该包含 #EXTM3U 或 #EXTINF
        if '#EXTM3U' in content or '#EXTINF' in content:
            return True
        else:
            return False

    except Exception as e:
        return False


def normalize_name(name):
    """归一化频道名，去掉横杠、空格等差异"""
    # 去掉所有空格和横杠
    name = name.replace(' ', '').replace('-', '')
    # 统一转大写
    name = name.upper()
    return name


def main():
    print("=== 从橙子IPTV两个源采集直播源 ===\n", flush=True)

    # 1. 从两个源拉取 m3u 内容
    all_channels = {}  # {归一化后的频道名: {"original_name": 原始名, "urls": [URL列表]}}

    for i, source_url in enumerate(SOURCES):
        print(f"[{i+1}/{len(SOURCES)}] 拉取: {source_url}", flush=True)
        content = fetch_url(source_url)
        if content:
            channels = parse_m3u(content)
            print(f"  解析出 {len(channels)} 个频道\n", flush=True)

            # 合并到 all_channels
            for name, urls in channels.items():
                norm_name = normalize_name(name)
                if norm_name not in all_channels:
                    all_channels[norm_name] = {"original_name": name, "urls": []}
                # 如果当前的原始名更规范（有横杠），就用它
                if '-' in name and '-' not in all_channels[norm_name]["original_name"]:
                    all_channels[norm_name]["original_name"] = name
                for url in urls:
                    if url not in all_channels[norm_name]["urls"]:
                        all_channels[norm_name]["urls"].append(url)

    print(f"总共采集到 {len(all_channels)} 个频道（归一化后）\n", flush=True)

    # 2. 检测每个频道的 URL 有效性
    print("=== 检测 URL 有效性 ===\n", flush=True)

    valid_channels = {}  # {归一化后的频道名: {"original_name": 原始名, "urls": [有效URL列表]}}

    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        futures = {}
        for norm_name, channel_info in all_channels.items():
            for url in channel_info["urls"]:
                future = executor.submit(check_url_valid, url)
                futures[future] = (norm_name, url, channel_info["original_name"])

        for future in concurrent.futures.as_completed(futures):
            norm_name, url, original_name = futures[future]
            is_valid = future.result()
            if is_valid:
                if norm_name not in valid_channels:
                    valid_channels[norm_name] = {"original_name": original_name, "urls": []}
                valid_channels[norm_name]["urls"].append(url)

    print(f"\n有效频道: {len(valid_channels)} 个\n", flush=True)

    # 3. 生成 live_channels.txt
    print("=== 生成 live_channels.txt ===\n", flush=True)

    # 央视频道的固定顺序
    CCTV_ORDER = [
        "CCTV-1", "CCTV-2", "CCTV-3", "CCTV-4", "CCTV-5", "CCTV-6",
        "CCTV-7", "CCTV-8", "CCTV-9", "CCTV-10", "CCTV-11", "CCTV-12",
        "CCTV-13", "CCTV-14", "CCTV-15", "CCTV-16", "CCTV-17"
    ]

    # 卫视频道的固定顺序
    SAT_ORDER = [
        "湖南卫视", "浙江卫视", "东方卫视", "江苏卫视", "北京卫视",
        "广东卫视", "深圳卫视", "黑龙江卫视", "安徽卫视", "东南卫视",
        "河南卫视", "江西卫视", "辽宁卫视", "甘肃卫视", "内蒙古卫视",
        "青海卫视", "山西卫视", "西藏卫视", "新疆卫视", "天津卫视",
        "重庆卫视", "四川卫视", "山东卫视", "湖北卫视"
    ]

    with open("live_channels.txt", "w", encoding="utf-8") as f:
        f.write("央视频道,#genre#\n")

        # 先写央视频道，按固定顺序
        cctv_channels = {k: v for k, v in valid_channels.items() if 'CCTV' in k}
        cctv_order_norm = [normalize_name(n) for n in CCTV_ORDER]

        for cctv_name in CCTV_ORDER:
            norm_name = normalize_name(cctv_name)
            if norm_name in cctv_channels:
                f.write(f"{cctv_name},{'#'.join(cctv_channels[norm_name]['urls'])}\n")

        # 再写其他央视频道（付费频道等）
        other_cctv = {k: v for k, v in cctv_channels.items() if k not in cctv_order_norm}
        for norm_name, channel_info in other_cctv.items():
            f.write(f"{channel_info['original_name']},{'#'.join(channel_info['urls'])}\n")

        f.write("\n卫视频道,#genre#\n")

        # 再写卫视频道，按固定顺序
        sat_channels = {k: v for k, v in valid_channels.items() if '卫视' in v["original_name"]}
        sat_order_norm = [normalize_name(n) for n in SAT_ORDER]

        for sat_name in SAT_ORDER:
            norm_name = normalize_name(sat_name)
            if norm_name in sat_channels:
                f.write(f"{sat_name},{'#'.join(sat_channels[norm_name]['urls'])}\n")

        # 再写其他卫视频道
        other_sat = {k: v for k, v in sat_channels.items() if k not in sat_order_norm}
        for norm_name, channel_info in other_sat.items():
            f.write(f"{channel_info['original_name']},{'#'.join(channel_info['urls'])}\n")

        f.write("\n地方频道,#genre#\n")

        # 最后写其他频道
        other_channels = {k: v for k, v in valid_channels.items() if k not in cctv_channels and k not in sat_channels}
        for norm_name, channel_info in other_channels.items():
            f.write(f"{channel_info['original_name']},{'#'.join(channel_info['urls'])}\n")

    print(f"完成！生成 live_channels.txt，共 {len(valid_channels)} 个频道", flush=True)


if __name__ == "__main__":
    main()
