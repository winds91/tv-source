# -*- coding: utf-8 -*-
# GitHub Actions自动更新直播源脚本（纯央视听yangshipin.cn官方源 + Playwright async并发）
# 用 async_playwright 真正并发抓页面，避免 sync API 跨线程问题

import asyncio
import re
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# (pid, 显示名, 分组)
YANGSHIPIN_CHANNELS = [
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
    (600001809, "CCTV-14 少儿",       "cctv"),
    (600001815, "CCTV-15 音乐",      "cctv"),
    (600098637, "CCTV-16 奥林匹克",  "cctv"),
    (600001810, "CCTV-17 农业农村",  "cctv"),
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
]

LOCAL_FILE = "live_channels.txt"
TIMEOUT = 10
CONCURRENCY = 5   # 同时开5个page
WAIT_MS = 10000    # 每个页面等10秒

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


async def fetch_one(context, task, sem):
    """单个频道抓取（async并发）"""
    pid, display, group = task
    page_url = f"https://www.yangshipin.cn/tv/home?pid={pid}"
    m3u8_urls = []

    async with sem:
        page = await context.new_page()
        try:
            def on_response(resp):
                if ".m3u8" in resp.url and "favicon" not in resp.url:
                    m3u8_urls.append(resp.url)
            page.on("response", on_response)

            await page.goto(page_url, wait_until="load", timeout=30000)

            # 注入JS：主动查找video元素并触发播放
            # 解决yangshipin播放器不自动播放导致抓不到m3u8的问题
            play_js = """
            (function() {
                function triggerPlay(video) {
                    video.muted = false;
                    video.controls = false;
                    if (video.paused) {
                        var p = video.play();
                        if (p !== undefined && p !== null) {
                            p.catch(function() {
                                video.muted = true;
                                video.play().then(function() {
                                    setTimeout(function() { video.muted = false; }, 200);
                                }).catch(function() {});
                            });
                        }
                    }
                }
                function checkVideo() {
                    var videos = document.getElementsByTagName('video');
                    for (var i = 0; i < videos.length; i++) {
                        triggerPlay(videos[i]);
                    }
                }
                checkVideo();
                setInterval(checkVideo, 1000);
            })();
            """
            await page.evaluate(play_js)

            # 模拟点击页面中央触发播放（体育频道等需要用户点击才会加载m3u8）
            await page.wait_for_timeout(2000)  # 等播放器初始化
            await page.mouse.click(640, 360)   # 点击页面中央

            # 智能等待：最多等30秒，每1秒检查一次m3u8是否出现
            # 出现后再等2秒让其他码率线路也加载完
            # 如果前10秒没抓到，第11秒补一次点击
            for i in range(30):
                await page.wait_for_timeout(1000)
                if m3u8_urls:
                    await page.wait_for_timeout(2000)
                    break
                # 第10秒还没抓到，补一次点击
                if i == 9 and not m3u8_urls:
                    await page.mouse.click(640, 360)
        except Exception as e:
            print(f"  [{display}] err: {e}")
        finally:
            await page.close()

    # 去重
    seen = set()
    result = []
    for u in m3u8_urls:
        key = u.split("#")[0]
        if key not in seen:
            seen.add(key)
            result.append(u)
    return (display, group, result)


async def fetch_all(tasks):
    from playwright.async_api import async_playwright

    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--autoplay-policy=no-user-gesture-required",  # 放开自动播放限制
                "--mute-audio",  # headless模式下静音，避免播放被阻止
            ],
        )
        context = await browser.new_context(
            user_agent=HEADERS["User-Agent"],
            extra_http_headers={"Referer": "https://www.yangshipin.cn/"},
        )
        sem = asyncio.Semaphore(CONCURRENCY)
        print(f"并发抓取 {len(tasks)} 个频道（concurrency={CONCURRENCY}）...")
        coros = [fetch_one(context, t, sem) for t in tasks]
        done = 0
        for coro in asyncio.as_completed(coros):
            display, group, urls = await coro
            done += 1
            if urls:
                print(f"  [{done}/{len(tasks)}] {display} -> {len(urls)} 条")
            else:
                print(f"  [{done}/{len(tasks)}] {display} -> 未抓到")
            results.append((display, group, urls))
        await browser.close()
    return results


def test_url(url):
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
    print("=== 开始更新直播源 ===")
    results = asyncio.run(fetch_all(YANGSHIPIN_CHANNELS))

    cctv_channels, plus_channels, sat_channels = {}, {}, {}
    for display, group, urls in results:
        if not urls:
            continue
        if group == "cctv":
            cctv_channels[display] = urls
        elif group == "plus":
            plus_channels[display] = urls
        else:
            sat_channels[display] = urls

    # 批量检测URL
    print("\n批量检测m3u8可用性...")
    all_urls = set()
    for d in (cctv_channels, plus_channels, sat_channels):
        for urls in d.values():
            all_urls.update(urls)

    alive = set()
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
                alive.add(u)
            else:
                dead += 1
    print(f"  可用 {len(alive)}, 失效 {dead}")

    def sort_key(display):
        """频道排序key：CCTV按编号，CGTN/付费排后，卫视按名称"""
        m = re.match(r'CCTV-(\d+)(.*)', display)
        if m:
            num = int(m.group(1))
            suffix = m.group(2)
            if '+' in suffix:
                return (0, num, 1, display)  # 5+ 排在5后面
            return (0, num, 0, display)
        if display.startswith('CGTN'):
            return (1, 0, 0, display)
        if display.startswith('CCTV '):
            return (2, 0, 0, display)  # 付费频道排在最后
        return (3, 0, 0, display)

    def filter_out(d):
        out = []
        for display, urls in d.items():
            good = [u for u in urls if u in alive]
            if good:
                out.append((display, f"{display},{'#'.join(good)}"))
        out.sort(key=lambda x: sort_key(x[0]))
        return [line for _, line in out]

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
    print(f"央视精品: {len(plus_out)} 个")
    print(f"卫视: {len(sat_out)} 个")


if __name__ == "__main__":
    main()
