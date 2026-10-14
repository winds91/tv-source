# -*- coding: utf-8 -*-
# GitHub Actions自动更新直播源脚本
# 功能：拉取橙子主源+备用源，合并当前仓库的频道，智能合并同名频道，批量检测失效URL，写回live_channels.txt

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

def normalize_name(name):
    """
    规范化频道名，用于合并同名频道
    例如：CCTV-1、CCTV1、CCTV1HD、CCTV1综合 -> 都归一为 cctv1
    """
    n = name.strip().upper()
    # 去掉横杠、空格
    n = n.replace("-", "").replace(" ", "").replace("　", "")
    # 去掉常见后缀
    for suffix in ["HD", "高清", "标清", "1080P", "720P", "1080", "720", "PLUS", "+"]:
        n = n.replace(suffix, "")
    # 去掉中文后缀（综合、财经、综艺等），只保留数字编号
    # CCTV1综合 -> CCTV1
    n = re.sub(r"(CCTV\d+).*$", r"\1", n)
    return n

def display_name(name):
    """生成显示用的频道名（用短名，去掉中文后缀）"""
    n = name.strip()
    # CCTV1综合 -> CCTV-1
    m = re.match(r"CCTV(\d+).*", n)
    if m:
        return f"CCTV-{m.group(1)}"
    # CCTV1 -> CCTV-1
    m = re.match(r"^CCTV(\d+)$", n)
    if m:
        return f"CCTV-{m.group(1)}"
    return n

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
    """解析m3u文件，返回 {规范化名: [原始名, urls]}"""
    channels = {}
    lines = content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF:"):
            m = re.search(r'tvg-name="([^"]*)"', line)
            if m:
                name = m.group(1).strip()
            else:
                parts = line.split(",")
                name = parts[-1].strip() if len(parts) > 1 else f"channel_{i}"
            
            if i + 1 < len(lines):
                url = lines[i+1].strip()
                if url.startswith("http") or url.startswith("rtsp"):
                    norm = normalize_name(name)
                    if norm not in channels:
                        channels[norm] = {"display": name, "urls": []}
                    if url not in channels[norm]["urls"]:
                        channels[norm]["urls"].append(url)
            i += 2
        else:
            i += 1
    return channels

def parse_txt(content):
    """解析txt格式，返回 {规范化名: [原始名, urls]}"""
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
            norm = normalize_name(name)
            if norm not in channels:
                channels[norm] = {"display": name, "urls": []}
            for u in urls:
                if u not in channels[norm]["urls"]:
                    channels[norm]["urls"].append(u)
    return channels

def test_url(url):
    """检测URL是否可用"""
    try:
        r = requests.get(url, timeout=TIMEOUT, stream=True)
        if r.status_code == 200:
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
    
    # 4. 合并所有频道（按规范化名合并）
    all_channels = dict(existing_channels)
    for norm, data in main_channels.items():
        if norm not in all_channels:
            all_channels[norm] = data
        else:
            # 合并URL
            existing_urls = set(all_channels[norm]["urls"])
            for u in data["urls"]:
                if u not in existing_urls:
                    all_channels[norm]["urls"].append(u)
                    existing_urls.add(u)
    
    for norm, data in backup_channels.items():
        if norm not in all_channels:
            all_channels[norm] = data
        else:
            existing_urls = set(all_channels[norm]["urls"])
            for u in data["urls"]:
                if u not in existing_urls:
                    all_channels[norm]["urls"].append(u)
                    existing_urls.add(u)
    
    print(f"\n合并后总频道数: {len(all_channels)}")
    
    # 5. 收集所有唯一URL
    all_urls = set()
    for data in all_channels.values():
        for u in data["urls"]:
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
    
    # 7. 过滤失效URL
    final_channels = {}
    for norm, data in all_channels.items():
        good_urls = [u for u in data["urls"] if u in alive_urls]
        if good_urls:
            final_channels[norm] = {"display": display_name(data["display"]), "urls": good_urls}
    
    print(f"最终频道数: {len(final_channels)}")
    
    # 8. 按分组分类
    cctv = []
    satellite = []
    local = []
    
    for norm, data in final_channels.items():
        name = data["display"]
        if norm.startswith("CCTV") or "CGTN" in norm:
            cctv.append((norm, name, data["urls"]))
        elif "卫视" in name:
            satellite.append((norm, name, data["urls"]))
        else:
            local.append((norm, name, data["urls"]))
    
    # 排序
    def sort_key(item):
        norm = item[0]
        # CCTV按数字排序
        m = re.match(r"CCTV(\d+)", norm)
        if m:
            return (0, int(m.group(1)), norm)
        return (1, norm)
    
    cctv.sort(key=sort_key)
    satellite.sort(key=lambda x: x[1])
    local.sort(key=lambda x: x[1])
    
    # 9. 写回文件
    with open(LOCAL_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write("央视频道,#genre#\n")
        for norm, name, urls in cctv:
            f.write(f"{name},{'#'.join(urls)}\n")
        
        f.write("\n卫视频道,#genre#\n")
        for norm, name, urls in satellite:
            f.write(f"{name},{'#'.join(urls)}\n")
        
        f.write("\n地方频道,#genre#\n")
        for norm, name, urls in local:
            f.write(f"{name},{'#'.join(urls)}\n")
    
    print(f"\n=== 更新完成 ===")
    print(f"央视: {len(cctv)}, 卫视: {len(satellite)}, 地方: {len(local)}")
    print(f"输出文件: {LOCAL_FILE}")

if __name__ == "__main__":
    main()
