# -*- coding: utf-8 -*-
# GitHub Actions自动更新直播源脚本（纯央视听yangshipin.cn官方源 + Playwright无头浏览器）
# 原理：用Playwright打开yangshipin.cn每个pid对应的直播页，监听真实m3u8网络响应
# 数据来源：my-tv-1项目解密得到的pid列表，覆盖央视高清镜像 + CGTN + 付费频道 + 全国卫视

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# 央视听yangshipin.cn频道列表
# (pid, 统一频道显示名, 分组)
#   cctv = 央视频道组（CCTV-1~17高清镜像）
#   plus = 央视精品组（CGTN/付费/CCTV-4K，不能播的会被test_url自动过滤）
#   sat  = 卫视频道组
YANGSHIPIN_CHANNELS = [
    # 央视频道（高清镜像）
    (600001859, "CCTV-1 综合",       "cctv"),
    (600001800, "CCTV-2 财经",       "cctv"),
    (600001801, "CCTV-3 综艺",       "cctv"),
    (600001814, "CCTV-4 中文国际",   "cctv"),
    (600001818, "CCTV-5 体育",       "cctv"),
    (600001817, "CCTV-5+ 体育赛事",  "cctv"),
    (600108442, "CCTV-6 电影",       "cctv"),
    (600004092, "CCTV-7 国防军事",   "cctv"),
    (600001803, "CCTV-8 电视剧",     "cctv"),
    (600004078, "CCTV-9 纪录",       "cctv"),
    (600001805, "CCTV-10 科教",      "cctv"),
    (600001806, "CCTV-11 戏曲",      "cctv"),
    (600001807, "CCTV-12 社会与法",  "cctv"),
    (600001811, "CCTV-13 新闻",      "cctv"),
    (600001809, "CCTV-14 少儿",      "cctv"),
    (600001815, "CCTV-15 音乐",      "cctv"),
    (600098637, "CCTV-16 奥林匹克",  "cctv"),
    (600001810, "CCTV-17 农业农村",  "cctv"),
    # 央视精品（CGTN + 付费频道 + 4K；不能播的自动过滤）
    (600002264, "CCTV-4K 超高清",    "plus"),
    (600014550, "CGTN",              "plus"),
    (600084704, "CGTN 法语",         "plus"),
    (600084758, "CGTN 俄语",         "plus"),
    (600084782, "CGTN 阿拉伯语",     "plus"),
    (600084744, "CGTN 西班牙语",     "plus"),
    (600084781, "CGTN 外语记录",     "plus"),
    (600099658, "CCTV 风云剧场",     "plus"),
    (600099655, "CCTV 第一剧场",     "plus"),
    (600099620, "CCTV 怀旧剧场",     "plus"),
    (600099637, "CCTV 世界地理",     "plus"),
    (600099660, "CCTV 风云音乐",     "plus"),
    (600099649, "CCTV 兵器科技",     "plus"),
    (600099636, "CCTV 风雨足球",     "plus"),
    (600099659, "CCTV 高尔夫网球",   "plus"),
    (600099650, "CCTV 女性时尚",     "plus"),
    (600099653, "CCTV 文化精品",     "plus"),
    (600099652, "CCTV 央视台球",     "plus"),
    (600099656, "CCTV 电视指南",     "plus"),
    (600099651, "CCTV 卫生健康",     "plus"),
    # 全国卫视
    (600002309, "北京卫视",          "sat"),
    (600002521, "江苏卫视",          "sat"),
    (600002483, "东方卫视",          "sat"),
    (600002520, "浙江卫视",          "sat"),
    (600002475, "湖南卫视",          "sat"),
    (600002508, "湖北卫视",          "sat"),
    (600002485, "广东卫视",          "sat"),
    (600002509, "广西卫视",          "sat"),
    (600002498, "黑龙江卫视",        "sat"),
    (600002506, "海南卫视",          "sat"),
    (600002531, "重庆卫视",          "sat"),
    (600002481, "深圳卫视",          "sat"),
    (600002516, "四川卫视",          "sat"),
    (600002525, "河南卫视",          "sat"),
    (600002484, "东南卫视",          "sat"),
    (600002490, "贵州卫视",          "sat"),
    (600002503, "江西卫视",          "sat"),
    (600002505, "辽宁卫视",          "sat"),
    (600002532, "安徽卫视",          "sat"),
    (600002493, "河北卫视",          "sat"),
    (600002513, "山东卫视",          "sat"),
    (600152137, "天津卫视",          "sat"),
    (600190405, "吉林卫视",          "sat"),
    (600190400, "陕西卫视",          "sat"),
    (600190408, "甘肃卫视",          "sat"),
    (600190737, "宁夏卫视",          "sat"),
    (600190401, "内蒙古卫视",        "sat"),
    (600190402, "云南卫视",          "sat"),
    (600190407, "山西卫视",          "sat"),
    (600190406, "青海卫视",          "sat"),
    (600190403, "西藏卫视",          "sat"),
    (600171827, "中国教育",          "sat"),
    (600193252, "兵团卫视",          "sat"),
]

LOCAL_FILE = "live_channels.txt"
TIMEOUT = 10
PARALLEL_FETCH = 5  # 并发抓页面数（yangshipin并发限制内）

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def grab_m3u8_one(task):
    """单个频道抓m3u8，每次调用独立开playwright实例（线程安全）"""
    pid, display, group = task
    from playwright.sync_api import sync_playwright

    page_url = f"https://www.yangshipin.cn/tv/home?pid={pid}"
    m3u8_urls = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                extra_http_headers={"Referer": "https://www.yangshipin.cn/"},
            )
            page = context.new_page()

            def handle_response(response):
                url = response.url
                if ".m3u8" in url and "favicon" not in url:
                    m3u8_urls.append(url)

            page.on("response", handle_response)
            page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(10000)
            browser.close()
    except Exception as e:
        print(f"  [{display}] 抓取异常: {e}")

    # 按路径去重
    seen = set()
    result = []
    for u in m3u8_urls:
        key = u.split("#")[0]
        if key not in seen:
            seen.add(key)
            result.append(u)
    return (display, group, result)


def test_url(url):
    """检测m3u8是否真能播放：200 + 返回内容是EXTM3U"""
    try:
        r = requests.get(
            url,
            headers={**HEADERS, "Referer": "https://www.yangshipin.cn/"},
            timeout=TIMEOUT,
            stream=True,
        )
        if r.status_code != 200:
            return (url, False)
        content = next(r.iter_content(800), b"")
        text = content.decode("utf-8", errors="ignore")
        if "#EXTM3U" in text or "#EXT-X-STREAM" in text or "#EXTINF" in text:
            return (url, True)
        ct = r.headers.get("content-type", "")
        if "mpegurl" in ct:
            return (url, True)
        return (url, False)
    except Exception:
        return (url, False)


def main():
    print("=== 开始更新直播源（纯央视听yangshipin + Playwright） ===")

    cctv_channels = {}
    plus_channels = {}
    sat_channels = {}

    # 并发抓所有yangshipin频道
    print(f"\n并发抓取 {len(YANGSHIPIN_CHANNELS)} 个频道（并发数={PARALLEL_FETCH}）...")
    tasks = list(YANGSHIPIN_CHANNELS)
    done_count = 0
    with ThreadPoolExecutor(max_workers=PARALLEL_FETCH) as ex:
        futures = {ex.submit(grab_m3u8_one, t): t for t in tasks}
        for fut in as_completed(futures):
            display, group, urls = fut.result()
            done_count += 1
            if not urls:
                print(f"  [{done_count}/{len(tasks)}] {display} -> 未抓到m3u8")
                continue
            print(f"  [{done_count}/{len(tasks)}] {display} -> {len(urls)} 条")
            if group == "cctv":
                cctv_channels[display] = urls
            elif group == "plus":
                plus_channels[display] = urls
            else:
                sat_channels[display] = urls

    # 批量检测
    print(f"\n批量检测m3u8可用性...")
    all_urls = set()
    for d in (cctv_channels, plus_channels, sat_channels):
        for urls in d.values():
            all_urls.update(urls)

    alive_urls = set()
    dead = 0
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(test_url, u): u for u in all_urls}
        done = 0
        for fut in as_completed(futures):
            u, ok = fut.result()
            done += 1
            if done % 20 == 0:
                print(f"  进度 {done}/{len(all_urls)}")
            if ok:
                alive_urls.add(u)
            else:
                dead += 1

    print(f"  可用 {len(alive_urls)}, 失效 {dead}")

    # 写文件
    def filter_out(d):
        out = []
        for display, urls in d.items():
            good = [u for u in urls if u in alive_urls]
            if good:
                out.append(f"{display},{'#'.join(good)}")
        return out

    cctv_out = filter_out(cctv_channels)
    plus_out = filter_out(plus_channels)
    sat_out = filter_out(sat_channels)

    with open(LOCAL_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write("央视频道,#genre#\n")
        for line in cctv_out:
            f.write(line + "\n")
        if plus_out:
            f.write("\n央视精品,#genre#\n")
            for line in plus_out:
                f.write(line + "\n")
        f.write("\n卫视频道,#genre#\n")
        for line in sat_out:
            f.write(line + "\n")

    print(f"\n=== 完成 ===")
    print(f"央视: {len(cctv_out)} 个")
    print(f"央视精品(CGTN/付费/4K): {len(plus_out)} 个")
    print(f"卫视: {len(sat_out)} 个")
    print(f"输出: {LOCAL_FILE}")


if __name__ == "__main__":
    main()
