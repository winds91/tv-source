# -*- coding: utf-8 -*-
# GitHub Actions自动更新直播源脚本
# 功能：拉取橙子主源+备用源，合并当前仓库的频道，批量检测失效URL，写回live_channels.txt

import re
import os
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# 橙子IPTV源
ORANGE_MAIN_URL = "https://raw.githubusercontent.com/OrangeWay520/my-iptv/master/my_channels.m3u"
ORANGE_BACKUP_URL = "https://live.zbds.top/tv/iptv4.m3u"

# 当前仓库的文件
LOCAL_FILE = "live_channels.txt"

# 检测超时（秒）
TIMEOUT = 5

def fetch_url(url):
    """下载URL内容"""
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            return r.text
    except Exception as e:
        print(f"下载失败 {url}: {e}")
    return None

def parse_m3u(content):
    """解析m3u文件，返回 {频道名: [urls]}"""
    channels = {}
    lines = content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF:"):
            # 提取频道名
            m = re.search(r'tvg-name="([^"]*)"', line)
            if m:
                name = m.group(1).strip()
            else:
                parts = line.split(",")
                name = parts[-1].strip() if len(parts) > 1 else f"channel_{i}"
            
            # 下一行是URL
            if i + 1 < len(lines):
                url = lines[i+1].strip()
                if url.startswith("http") or url.startswith("rtsp"):
                    # 简化频道名
                    clean_name = name.replace("HD", "").replace("高清", "").strip()
                    if clean_name not in channels:
                        channels[clean_name] = []
                    if url not in channels[clean_name]:
                        channels[clean_name].append(url)
            i += 2
        else:
            i += 1
    return channels

def parse_txt(content):
    """解析txt格式（内置源格式），返回 {频道名: [urls]}"""
    channels = {}
    for line in content.split("\n"):
        line = line.strip()
        if not line or line.endswith("#genre#") or line.startswith("#"):
            continue
        if "," not in line:
            continue
        parts = line.split(",", 1)
        name = parts[0].strip()
        urls_str = parts[1].strip()
        urls = [u.strip() for u in urls_str.split("#") if u.strip().startswith("http") or u.strip().startswith("rtsp")]
        if urls:
            channels[name] = urls
    return channels

def test_url(url):
    """检测URL是否可用，返回 (url, is_alive)"""
    try:
        r = requests.get(url, timeout=TIMEOUT, stream=True)
        if r.status_code == 200:
            # 读前100字节验证是不是m3u8
            content = next(r.iter_content(100), b"").decode("utf-8", errors="ignore")
            if "#EXTM3U" in content or "#EXT" in content or r.headers.get("content-type", "").startswith("application/vnd.apple.mpegurl"):
                return (url, True)
            # 有些m3u8不返回EXTM3U头，但状态码200也算可用
            return (url, True)
        return (url, False)
    except:
        return (url, False)

def main():
    print("=== 开始更新直播源 ===")
    
    # 1. 读取当前仓库的live_channels.txt
    existing_channels = {}
    if os.path.exists(LOCAL_FILE):
        with open(LOCAL_FILE, "r", encoding="utf-8") as f:
            existing_channels = parse_txt(f.read())
        print(f"当前仓库频道数: {len(existing_channels)}")
    
    # 2. 拉取橙子主源
    print("\n拉取橙子主源...")
    main_content = fetch_url(ORANGE_MAIN_URL)
    main_channels = {}
    if main_content:
        main_channels = parse_m3u(main_content)
        print(f"橙子主源频道数: {len(main_channels)}")
    
    # 3. 拉取橙子备用源
    print("\n拉取橙子备用源...")
    backup_content = fetch_url(ORANGE_BACKUP_URL)
    backup_channels = {}
    if backup_content:
        backup_channels = parse_m3u(backup_content)
        print(f"橙子备用源频道数: {len(backup_channels)}")
    
    # 4. 合并所有频道
    all_channels = dict(existing_channels)  # 先放已有的
    for name, urls in main_channels.items():
        if name not in all_channels:
            all_channels[name] = []
        for u in urls:
            if u not in all_channels[name]:
                all_channels[name].append(u)
    for name, urls in backup_channels.items():
        if name not in all_channels:
            all_channels[name] = []
        for u in urls:
            if u not in all_channels[name]:
                all_channels[name].append(u)
    
    print(f"\n合并后总频道数: {len(all_channels)}")
    
    # 5. 收集所有唯一URL
    all_urls = set()
    for urls in all_channels.values():
        for u in urls:
            all_urls.add(u)
    print(f"唯一URL数: {len(all_urls)}")
    
    # 6. 批量检测
    print("\n开始批量检测...")
    alive_urls = set()
    dead_count = 0
    
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(test_url, url): url for url in all_urls}
        done = 0
        for future in as_completed(futures):
            url, is_alive = future.result()
            done += 1
            if done % 50 == 0:
                print(f"  进度: {done}/{len(all_urls)}")
            if is_alive:
                alive_urls.add(url)
            else:
                dead_count += 1
    
    print(f"\n检测完成: 可用 {len(alive_urls)}, 失效 {dead_count}")
    
    # 7. 过滤失效URL，删除所有源都失效的频道
    final_channels = {}
    for name, urls in all_channels.items():
        good_urls = [u for u in urls if u in alive_urls]
        if good_urls:
            final_channels[name] = good_urls
    
    print(f"最终频道数: {len(final_channels)}")
    
    # 8. 按分组输出
    cctv = sorted([n for n in final_channels if n.startswith("CCTV") or "央视" in n or "CGTN" in n])
    satellite = sorted([n for n in final_channels if "卫视" in n])
    local = sorted([n for n in final_channels if n not in cctv and n not in satellite])
    
    # 9. 写回文件
    with open(LOCAL_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write("央视频道,#genre#\n")
        for name in cctv:
            f.write(f"{name},{'#'.join(final_channels[name])}\n")
        f.write("\n卫视频道,#genre#\n")
        for name in satellite:
            f.write(f"{name},{'#'.join(final_channels[name])}\n")
        f.write("\n地方频道,#genre#\n")
        for name in local:
            f.write(f"{name},{'#'.join(final_channels[name])}\n")
    
    print(f"\n=== 更新完成 ===")
    print(f"央视: {len(cctv)}, 卫视: {len(satellite)}, 地方: {len(local)}")
    print(f"输出文件: {LOCAL_FILE}")

if __name__ == "__main__":
    main()
