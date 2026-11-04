"""Build the bundled place data (``data/places.tsv.gz``) from a GeoNames dump.

Run once when the data should be refreshed (it is checked into the repository)::

    python -m lumen.geo.build D:\\GeoNames

Missing source files are downloaded into that folder from download.geonames.org
(cities1000.zip, alternateNamesV2.zip ~200 MB, admin1CodesASCII.txt, countryInfo.txt).
GeoNames data is licensed under CC BY 4.0.

Output (gzip, UTF-8, tab separated, one record per line)::

    #<version>
    C  <country code>  <name>  <zh>  <fr>
    A  <country>.<admin1>  <name>  <zh>  <fr>
    P  <geonameid>  <lat>  <lon>  <country>  <admin1>  <population>  <name>  <zh>  <fr>

``zh`` and ``fr`` are empty when they equal ``name``.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import math
import sys
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path

BASE_URL = "https://download.geonames.org/export/dump/"
SOURCES = ("cities1000.zip", "alternateNamesV2.zip", "admin1CodesASCII.txt", "countryInfo.txt")
OUTPUT = Path(__file__).parent / "data" / "places.tsv.gz"

# Sections of a city, historical, abandoned or destroyed places are not useful as names.
SKIP_FEATURES = {"PPLX", "PPLH", "PPLQ", "PPLW", "PPLCH"}
# Parts of a city within this distance of it are left out (see _without_districts), so
# that their photos are given to the city.
DISTRICT_KM = 25.0
# Common Traditional -> Simplified characters (place names tagged plain "zh" are often
# Traditional; "zh-CN" / "zh-Hans" are preferred when they exist).
_HANT = """
萊莱 諾诺 維维 爾尔 亞亚 蘭兰 倫伦 頓顿 達达 蘇苏 濟济 華华 馬马 納纳 羅罗 賽赛 歐欧 區区 縣县 鎮镇
島岛 灣湾 門门 東东 陽阳 雲云 龍龙 廣广 寧宁 齊齐 興兴 慶庆 漢汉 關关 開开 嶺岭 澤泽 豐丰 鄉乡 莊庄
橋桥 際际 灘滩 濱滨 峽峡 衛卫 陸陆 勞劳 夢梦 盧卢 魯鲁 薩萨 聖圣 奧奥 樂乐 熱热 茲兹 瓊琼 貝贝 圖图
偉伟 麥麦 費费 紐纽 約约 臺台 傑杰 遜逊 蓋盖 韋韦 內内 瑪玛 麗丽 漁渔 爭争 軍军 隊队 鐵铁 線线 場场
廠厂 園园 館馆 庫库 劍剑 舊旧 堯尧 瀋沈 遼辽 黃黄 嶼屿 礦矿 塢坞 壩坝 圍围 蕭萧 劉刘 張张 陳陈 楊杨
趙赵 吳吴 鄭郑 謝谢 許许 鄧邓 馮冯 韓韩 葉叶 蔣蒋 鍾钟 邁迈 烏乌 別别 頭头 條条 鳳凤 鳥鸟 魚鱼 鶴鹤
鷹鹰 獅狮 鹽盐 義义 臨临 濰潍 錫锡 蘆芦 蘿萝 葦苇 歷历 壽寿 喬乔 萬万 寶宝 貴贵 賀贺 資资 贊赞 輪轮
轉转 運运 進进 連连 遠远 選选 邊边 鄰邻 醫医 銀银 錦锦 鏡镜 長长 閣阁 間间 陰阴 隴陇 隱隐 雙双 雞鸡
離离 靈灵 靜静 須须 領领 額额 風风 飛飞 餘余 驛驿 絲丝 經经 緬缅 總总 織织 綠绿 網网 聯联 聲声 臘腊
藝艺 號号 蝦虾 補补 裝装 見见 規规 視视 觀观 詩诗 誠诚 語语 說说 調调 談谈 論论 諸诸 證证 譯译 護护
讓让 賓宾 車车 軒轩 輝辉 農农 鄒邹 鋼钢 錢钱 鎖锁 閘闸 陣阵 階阶 險险 電电 霧雾 響响 頂顶 順顺 題题
顏颜 願愿 類类 顧顾 騎骑 驗验 體体 鬆松 鮑鲍 鴨鸭 鵝鹅 麵面 點点 黨党 塊块 夾夹 學学 實实 寫写 專专
將将 對对 屬属 岡冈 崗岗 嶽岳 廟庙 廳厅 彎弯 從从 復复 徵征 憶忆 應应 戰战 擊击 斷断 時时 晉晋 曉晓
會会 業业 極极 樓楼 標标 樹树 橫横 權权 歡欢 歸归 氣气 滬沪 滿满 潛潜 潤润 澗涧 濕湿 瀏浏 瀘泸 為为
無无 煙烟 爐炉 牆墙 獨独 環环 瑤瑶 產产 畫画 當当 疊叠 發发 盤盘 眾众 確确 碼码 磚砖 禮礼 禪禅 種种
穩稳 窩窝 競竞 筆笔 築筑 簡简 糧粮 紀纪 紅红 級级 純纯 紙纸 細细 終终 組组 結结 給给 統统 繼继 續续
習习 聞闻 肅肃 脈脉 艙舱 蓮莲 蔥葱 薑姜 藍蓝 蘋苹 處处 蟲虫 蠶蚕 衝冲 裏里 製制 複复 覺觉 記记 設设
評评 詞词 認认 誌志 請请 識识 讀读 變变 讚赞 貢贡 貨货 購购 賣卖 賴赖 贏赢 跡迹 躍跃 軟软 載载 輕轻
辦办 邏逻 釀酿 針针 鋒锋 錄录 鐘钟 閱阅 隸隶 難难 韻韵 頻频 顯显 飄飘 飲饮 飾饰 養养 馳驰 駐驻 驅驱
驚惊 鬱郁 鮮鲜 鳴鸣 鴻鸿 鵬鹏 鷗鸥 麼么 齋斋 墾垦 堅坚 壯壮 寬宽 嶠峤 巒峦 帥帅 帶带 敘叙
錶表 濤涛 瀾澜 癒愈 礎础
"""
SIMPLIFY = str.maketrans(
    {pair[0]: pair[1] for pair in _HANT.split() if len(pair) == 2 and pair[0] != pair[1]}
)
# Preferred language tags, best first.
LANGUAGES = {"zh": ("zh-CN", "zh-Hans", "zh"), "fr": ("fr",)}


def _download(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name in SOURCES:
        target = folder / name
        if not target.exists():
            print(f"downloading {name}…", flush=True)
            urllib.request.urlretrieve(BASE_URL + name, target)


def _lines(path: Path, member: str | None = None) -> io.TextIOWrapper:
    if member is None:
        return open(path, encoding="utf-8", newline="")
    archive = zipfile.ZipFile(path)
    return io.TextIOWrapper(archive.open(member), encoding="utf-8", newline="")


def _clean(text: str) -> str:
    return text.replace("\t", " ").strip()


def build(folder: Path, output: Path = OUTPUT) -> dict[str, int]:
    _download(folder)

    countries: dict[str, list[str]] = {}  # code -> [geonameid, name]
    with _lines(folder / "countryInfo.txt") as handle:
        for line in handle:
            if line.startswith("#") or not line.strip():
                continue
            cols = line.rstrip("\n").split("\t")
            countries[cols[0]] = [cols[16], _clean(cols[4])]

    admin1: dict[str, list[str]] = {}  # "FR.11" -> [geonameid, name]
    with _lines(folder / "admin1CodesASCII.txt") as handle:
        for line in handle:
            cols = line.rstrip("\n").split("\t")
            if len(cols) >= 4:
                admin1[cols[0]] = [cols[3], _clean(cols[1])]

    places: list[list[str]] = []
    communes: dict[str, str] = {}  # geonameid -> finest administrative code (e.g. a commune)
    with _lines(folder / "cities1000.zip", "cities1000.txt") as handle:
        for line in handle:
            cols = line.rstrip("\n").split("\t")
            if cols[6] != "P" or cols[7] in SKIP_FEATURES:
                continue
            places.append(
                [cols[0], f"{float(cols[4]):.4f}", f"{float(cols[5]):.4f}", cols[8], cols[10],
                 cols[14] or "0", _clean(cols[1])]
            )  # fmt: skip
            communes[cols[0]] = f"{cols[8]}.{cols[10]}.{cols[11]}.{cols[12]}.{cols[13]}"
    places = _without_districts(places, communes)

    wanted = {p[0] for p in places} | {a[0] for a in admin1.values()}
    wanted |= {c[0] for c in countries.values()}
    # geonameid -> lang -> (rank, name)
    names: dict[str, dict[str, tuple[tuple[int, int, int], str]]] = {}
    tags = {tag: (lang, rank) for lang, tags in LANGUAGES.items() for rank, tag in enumerate(tags)}
    with _lines(folder / "alternateNamesV2.zip", "alternateNamesV2.txt") as handle:
        for row in csv.reader(handle, delimiter="\t", quoting=csv.QUOTE_NONE):
            if len(row) < 8 or row[1] not in wanted or row[2] not in tags:
                continue
            if row[6] == "1" or row[7] == "1":  # colloquial or historic
                continue
            lang, rank = tags[row[2]]
            key = (rank, 0 if row[4] == "1" else 1, 0 if row[5] == "1" else 1)
            best = names.setdefault(row[1], {}).get(lang)
            if best is None or key < best[0]:
                text = _clean(row[3])
                names[row[1]][lang] = (key, text.translate(SIMPLIFY) if lang == "zh" else text)

    def translations(geonameid: str, name: str) -> list[str]:
        found = names.get(geonameid, {})
        out = []
        for lang in LANGUAGES:
            value = found[lang][1] if lang in found else ""
            out.append("" if value == name else value)
        return out

    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        *(["C", code, name, *translations(gid, name)] for code, (gid, name) in sorted(countries.items())),  # noqa: E501
        *(["A", code, name, *translations(gid, name)] for code, (gid, name) in sorted(admin1.items())),  # noqa: E501
        *(["P", *place, *translations(place[0], place[-1])] for place in places),
    ]  # fmt: skip
    body = "".join("\t".join(line) + "\n" for line in lines)
    # The version changes with the content, so that assets are named again.
    digest = hashlib.sha1(body.encode("utf-8")).hexdigest()[:8]
    version = datetime.now(UTC).strftime(f"geonames-%Y%m%d-{digest}")
    with gzip.open(output, "wt", encoding="utf-8", newline="\n", compresslevel=9) as out:
        out.write(f"#{version}\n{body}")
    return {"countries": len(countries), "regions": len(admin1), "places": len(places)}


def _without_districts(places: list[list[str]], communes: dict[str, str]) -> list[list[str]]:
    """Leave out parts of a city: places named after a bigger place nearby ("Paris 15
    Vaugirard") and smaller places in the same commune ("Gare", a quarter of Paris)."""
    by_name: dict[tuple[str, str], list[list[str]]] = {}
    biggest: dict[str, list[str]] = {}
    for place in places:
        by_name.setdefault((place[3], place[6]), []).append(place)
        commune = communes[place[0]]
        if not commune.endswith(".") and (
            commune not in biggest or int(place[5]) > int(biggest[commune][5])
        ):
            biggest[commune] = place

    def district(place: list[str]) -> bool:
        city = biggest.get(communes[place[0]])
        if city is not None and city is not place and _km(city, place) <= DISTRICT_KM:
            return True
        words = place[6].split(" ")
        for count in range(1, len(words)):
            for city in by_name.get((place[3], " ".join(words[:count])), []):
                if int(city[5]) > int(place[5]) and _km(city, place) <= DISTRICT_KM:
                    return True
        return False

    return [place for place in places if not district(place)]


def _km(a: list[str], b: list[str]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, map(float, (a[1], a[2], b[1], b[2])))
    h = math.sin((lat2 - lat1) / 2) ** 2
    h += math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(h)))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("source", type=Path, help="Folder with (or for) the GeoNames files")
    args = parser.parse_args(argv)
    counts = build(args.source)
    size = OUTPUT.stat().st_size / 1e6
    print(f"wrote {OUTPUT} ({size:.1f} MB): {counts}")


if __name__ == "__main__":
    main(sys.argv[1:])
