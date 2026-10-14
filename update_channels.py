# -*- coding: utf-8 -*-
# GitHub Actions自动更新直播源脚本（纯央视网官方源 + Playwright无头浏览器）
# 功能：用Playwright打开央视网每个频道的直播页，等待JS执行完，提取真实的m3u8视频地址

import re
import os
import json
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# 所有央视频道列表（频道路径, 显示名）
CCTV_CHANNELS = [
    ("cctv1", "CCTV-1 综合"),
    ("cctv2", "CCTV-2 财经"),
    ("cctv3", "CCTV-3 综艺"),
    ("cctv4", "CCTV-4 中文国际"),
    ("cctv5", "CCTV-5 体育"),
    ("cctv6", "CCTV-6 电影"),
    ("cctv7", "CCTV-7 国防军事"),
    ("cctv8", "CCTV-8 电视剧"),
    ("cctv9", "CCTV-9 纪录"),
    ("cctv10", "CCTV-10 科教"),
    ("cctv11", "CCTV-11 戏曲"),
    ("cctv12", "CCTV-12 社会与法"),
    ("cctv13", "CCTV-13 新闻"),
    ("cctv15", "CCTV-15 音乐"),
    ("cctv16", "CCTV-16 奥林匹克"),
    ("cctv17", "CCTV-17 农业农村"),
]

# 当前仓库的文件
LOCAL_FILE = "live_channels.txt"

# 检测超时（秒）
TIMEOUT = 8

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://tv.cctv.com/"
}

def fetch_with_playwright(channel_path):
    """
    用Playwright打开央视网直播页，提取真实的m3u8视频地址
    返回: [m3u8_url1, m3u8_url2, ...]
    """
    from playwright.sync_api import sync_playwright
    
    url = f"https://tv.cctv.com/live/{channel_path}/"
    m3u8_urls = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            extra_http_headers={"Referer": "https://tv.cctv.com/"}
        )
        page = context.new_page()
        
        # 监听所有网络请求，找m3u8
        def handle_response(response):
            if ".m3u8" in response.url:
                m3u8_urls.append(response.url)
        
        page.on("response", handle_response)
        
        try:
            # 打开页面，等待网络空闲
            page.goto(url, wait_until="networkidle", timeout=30000)
            # 再等5秒让JS完全执行
            page.wait_for_timeout(5000)
        except Exception as e:
            print(f"  {channel_path}: 页面加载超时 {e}")
        
        browser.close()
    
    return list(set(m3u8_urls))

def fetch_vdn_api(channel_name):
    """
    备用方案：调用央视网VDN API，获取音频地址
    """
    vdn_url = "https://vdn.live.cntv.cn/api2/liveHtml5.do"
    params = {
        "channel": f"pa://cctv_p2p_hd{channel_name}",
        "client": "html5"
    }
    try:
        r = requests.get(vdn_url, params=params, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        
        text = r.text
        m = re.search(r"var\s+html5VideoData\s*=\s*'(\{.*?\})';", text)
        if not m:
            return []
        
        json_str = m.group(1).replace("\\'", "'")
        data = json.loads(json_str)
        
        if data.get("ack") != "yes":
            return []
        
        hls_urls = data.get("hls_url", {})
        m3u8_list = []
        for key, value in hls_urls.items():
            if value and isinstance(value, str) and ".m3u8" in value:
                m3u8_list.append(value)
        
        return m3u8_list
    except Exception as e:
        print(f"  {channel_name}: VDN API失败 {e}")
        return []

def test_url(url):
    """检测URL是否真正可用（状态码200 + 返回内容是m3u8）"""
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, stream=True)
        if r.status_code != 200:
            return (url, False)
        
        content = next(r.iter_content(500), b"")
        try:
            text = content.decode("utf-8", errors="ignore")
        except:
            return (url, False)
        
        if "#EXTM3U" in text or "#EXT-X-STREAM" in text or "#EXTINF" in text:
            return (url, True)
        
        content_type = r.headers.get("content-type", "")
        if "mpegurl" in content_type or "octet-stream" in content_type:
            return (url, True)
        
        if text.strip().startswith("{") and "error" in text.lower():
            return (url, False)
        if "错误" in text or "没有配置" in text:
            return (url, False)
        
        return (url, False)
    except:
        return (url, False)

def main():
    print("=== 开始更新直播源（纯央视网官方源 + Playwright） ===")
    
    all_channels = {}  # {频道名: {display: 显示名, urls: [url1, url2]}}
    
    # 方案1：先用Playwright抓真实视频地址
    print("\n用Playwright抓视频地址...")
    for channel_path, display_name in CCTV_CHANNELS:
        print(f"抓取 {channel_path} ({display_name})...")
        try:
            m3u8_list = fetch_with_playwright(channel_path)
            if m3u8_list:
                all_channels[channel_path] = {
                    "display": display_name,
                    "urls": m3u8_list
                }
                print(f"  找到 {len(m3u8_list)} 个视频地址")
            else:
                print(f"  未找到视频地址，尝试VDN API...")
                # 备用方案：用VDN API
                backup_urls = fetch_vdn_api(channel_path)
                if backup_urls:
                    all_channels[channel_path] = {
                        "display": display_name,
                        "urls": backup_urls
                    }
                    print(f"  VDN API 找到 {len(backup_urls)} 个地址")
                else:
                    print(f"  未找到任何地址")
        except Exception as e:
            print(f"  Playwright失败: {e}")
            # 备用方案：用VDN API
            backup_urls = fetch_vdn_api(channel_path)
            if backup_urls:
                all_channels[channel_path] = {
                    "display": display_name,
                    "urls": backup_urls
                }
                print(f"  VDN API 找到 {len(backup_urls)} 个地址")
    
    print(f"\n获取到 {len(all_channels)} 个频道")
    
    # 收集所有唯一URL
    all_urls = set()
    for data in all_channels.values():
        for u in data["urls"]:
            all_urls.add(u)
    print(f"唯一URL数: {len(all_urls)}")
    
    # 批量检测
    print("\n开始批量检测...")
    alive_urls = set()
    dead_count = 0
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(test_url, url): url for url in all_urls}
        done = 0
        for future in as_completed(futures):
            url, is_alive = future.result()
            done += 1
            if done % 10 == 0:
                print(f"  进度: {done}/{len(all_urls)}")
            if is_alive:
                alive_urls.add(url)
            else:
                dead_count += 1
    
    print(f"\n检测完成: 可用 {len(alive_urls)}, 失效 {dead_count}")
    
    # 过滤失效URL
    final_channels = {}
    for channel_name, data in all_channels.items():
        good_urls = [u for u in data["urls"] if u in alive_urls]
        if good_urls:
            final_channels[channel_name] = {
                "display": data["display"],
                "urls": good_urls
            }
    
    print(f"最终频道数: {len(final_channels)}")
    
    # 写回文件
    with open(LOCAL_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write("央视频道,#genre#\n")
        for channel_name, data in final_channels.items():
            f.write(f"{data['display']},{'#'.join(data['urls'])}\n")
    
    print(f"\n=== 更新完成 ===")
    print(f"频道数: {len(final_channels)}")
    print(f"输出文件: {LOCAL_FILE}")

if __name__ == "__main__":
    main()
