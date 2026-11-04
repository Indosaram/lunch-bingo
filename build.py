#!/usr/bin/env python3
"""점심 빙고 빌드.

k-skill 잇플 스킬(bccard-eatpl-search)의 검색 API를 동네별로 호출해
'점심에 문 여는 매출 상위 식당 24곳'을 고르고, 화면에 표시할 값만 담은
site/data/<동네>.json 과 정적 파일을 site/ 에 만든다.

- 원본 응답은 저장하지 않는다 (공모전 약관 제9조의2: 원본 축적 금지).
- merUrl 은 받은 그대로 쓰며 서버에서 호출하지 않는다.
"""
import json, os, re, shutil, sys, time, urllib.parse, urllib.request, hashlib, datetime

PROXY = os.environ.get("EATPL_PROXY", "https://k-skill-proxy.nomadamas.org/v1/bccard-eatpl/search")
ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(ROOT, "site")
GAP = float(os.environ.get("EATPL_GAP", "3.5"))  # seconds between calls (proxy rate-limits bursts)

NOT_LUNCH = {"카페", "호프", "기타주점", "바(bar)", "이자카야", "요리주점", "와인바", "칵테일바",
             "빵/도넛", "기타베이커리", "제과점", "아이스크림", "디저트", "떡/한과", "뷔페", "편의점"}
MER_PREFIX = "https://web.paybooc.ai/"

def fetch(loc, tries=5):
    url = PROXY + "?" + urllib.parse.urlencode({"location": loc})
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"user-agent": "lunch-bingo-build/1.0 (+https://indosaram.github.io/lunch-bingo/)"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r).get("items", []) or []
        except urllib.error.HTTPError as e:
            wait = 20 * (i + 1) if e.code == 429 else 5 * (i + 1)
            print(f"  {loc}: HTTP {e.code}, retry in {wait}s", file=sys.stderr)
            time.sleep(wait)
        except Exception as e:  # network
            print(f"  {loc}: {e}, retry", file=sys.stderr)
            time.sleep(5 * (i + 1))
    raise RuntimeError(f"failed: {loc}")

def hm(s):
    s = str(s or "")
    return int(s[:2]) * 60 + int(s[2:4]) if re.fullmatch(r"\d{4}", s) else None

def open_at_lunch(it):
    a, b = hm(it.get("srtTime")), hm(it.get("endTime"))
    if a is None or b is None:
        return False
    if b < a:  # overnight
        b += 24 * 60
    return a <= 11 * 60 + 30 and b >= 13 * 60 + 30

def hours(it):
    a, b = it.get("srtTime"), it.get("endTime")
    if not (a and b and len(a) == 4 and len(b) == 4):
        return None
    t = f"{a[:2]}:{a[2:]}–{'익일 ' if b < a else ''}{b[:2]}:{b[2:]}"
    return t

def short_name(n):
    n = re.sub(r"\(주\)|㈜|주식회사|\(유\)|유한회사", "", n).strip()
    n = re.sub(r"\s*\([^)]*\)\s*$", "", n).strip()  # trailing (지점)
    m = re.match(r"^(.{2,}?)\s+\S*점$", n)  # '역전우동 판교역점' -> '역전우동'
    if m:
        n = m.group(1).strip()
    return n or "이름 없음"

def pick(items):
    seen, out = set(), []
    for it in items:
        u = it.get("merUrl") or ""
        if not u.startswith(MER_PREFIX) or u in seen:
            continue
        if (it.get("merTpbuzNm") or "") in NOT_LUNCH or not open_at_lunch(it):
            continue
        seen.add(u)
        out.append(it)
    def num(v):
        try: return float(v)
        except Exception: return 999.0
    out.sort(key=lambda x: (num(x.get("allSaleRnk")), num(x.get("ccgSaleRnk"))))
    return out

def view(it):
    cust = it.get("vistCstmrRnkList") or {}
    return {
        "n": it.get("merNm"), "s": short_name(it.get("merNm") or ""),
        "c": it.get("merTpbuzNm"), "a": it.get("merAddr"),
        "r": it.get("allSaleRnk"), "g": it.get("ccgSaleRnk"),
        "h": hours(it),
        "bd": it.get("congestionDwk"), "bt": it.get("congestionTizn"),
        "cu": [cust[k] for k in sorted(cust) if cust.get(k)][:3],
        "lo": bool(it.get("loclPrsnPpltYn")), "gr": bool(it.get("empyVsitYn")),
        "fr": bool(it.get("frnrVsitYn")),
        "u": it.get("merUrl"),
    }

def board_order(area_id, stores, month):
    # 같은 달에는 같은 동네 사람 모두 같은 판을 보도록 (동네+월) 시드로 섞는다.
    def k(s):
        return hashlib.sha1(f"{area_id}:{month}:{s['u']}".encode()).hexdigest()
    return sorted(stores, key=k)

def main():
    areas = json.load(open(os.path.join(ROOT, "areas.json"), encoding="utf-8"))
    only = set(sys.argv[1:])
    if os.path.isdir(SITE):
        shutil.rmtree(SITE)
    shutil.copytree(os.path.join(ROOT, "src"), SITE)
    os.makedirs(os.path.join(SITE, "data"), exist_ok=True)
    kst = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)
    month = kst.strftime("%Y-%m")
    index = []
    first = True
    for ar in areas:
        if only and ar["id"] not in only:
            continue
        items = []
        for loc in ar["q"]:
            if not first:
                time.sleep(GAP)
            first = False
            got = fetch(loc)
            print(f"{ar['id']} / {loc}: {len(got)}", file=sys.stderr)
            items.extend(got)
        chosen = [view(x) for x in pick(items)[:24]]
        if len(chosen) < 24:
            print(f"!! {ar['id']}: only {len(chosen)} lunch spots, skipping", file=sys.stderr)
            continue
        board = board_order(ar["id"], chosen, month)
        bid = hashlib.sha1("|".join(s["u"] for s in board).encode()).hexdigest()[:8]
        out = {"id": ar["id"], "name": ar["name"], "sub": ar["sub"], "board": bid,
               "updated": kst.strftime("%Y-%m-%d"), "stores": board}
        with open(os.path.join(SITE, "data", f"{ar['id']}.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
        index.append({"id": ar["id"], "name": ar["name"], "sub": ar["sub"]})
    with open(os.path.join(SITE, "data", "areas.json"), "w", encoding="utf-8") as f:
        json.dump({"updated": kst.strftime("%Y-%m-%d"), "areas": index}, f, ensure_ascii=False)
    print(f"built {len(index)} areas -> {SITE}", file=sys.stderr)
    if not index:
        sys.exit(1)

if __name__ == "__main__":
    main()
