#!/usr/bin/env python3
"""점심 빙고 빌드.

k-skill 잇플 스킬(bccard-eatpl-search)의 검색 API를 동네별로 호출해
'점심에 문 여는 매출 상위 식당 24곳'을 고르고, 화면에 표시할 값만 담은
site/data/<동네>.json 과 정적 파일을 site/ 에 만든다.

- 원본 응답은 저장하지 않는다 (공모전 약관 제9조의2: 원본 축적 금지).
- merUrl 은 받은 그대로 쓰며 서버에서 호출하지 않는다.
"""
import json, os, re, shutil, sys, time, urllib.parse, urllib.request, urllib.error, hashlib, datetime, math, tempfile

PROXY = os.environ.get("EATPL_PROXY", "https://k-skill-proxy.nomadamas.org/v1/bccard-eatpl/search")
ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(ROOT, "site")
GAP = float(os.environ.get("EATPL_GAP", "3.5"))  # seconds between calls (proxy rate-limits bursts)
PREVIOUS_SITE = os.environ.get("EATPL_PREVIOUS_SITE", "https://indosaram.github.io/lunch-bingo").rstrip("/")

NOT_LUNCH = {"카페", "호프", "기타주점", "바(bar)", "이자카야", "요리주점", "와인바", "칵테일바",
             "빵/도넛", "기타베이커리", "제과점", "아이스크림", "아이스크림/요거트/빙수",
             "디저트", "떡/한과", "뷔페", "편의점"}
MER_PREFIX = "https://web.paybooc.ai/"
CITY_ALIASES = {"서울특별시": "서울", "서울시": "서울", "경기도": "경기"}

def in_locality(address, area):
    """검색은 부분 일치이므로 주소의 시/도와 시/구를 별도로 검증한다."""
    parts = str(address or "").split()
    if not parts:
        return False
    parts[0] = CITY_ALIASES.get(parts[0], parts[0])
    return any(parts[:len(prefix)] == prefix for prefix in area["localities"])

def fetch(loc, tries=5):
    url = PROXY + "?" + urllib.parse.urlencode({"location": loc})
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"user-agent": "lunch-bingo-build/1.0 (+https://indosaram.github.io/lunch-bingo/)"})
            with urllib.request.urlopen(req, timeout=40) as r:
                payload = json.load(r)
            if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
                raise ValueError("search response must contain an items array")
            if not all(isinstance(item, dict) for item in payload["items"]):
                raise ValueError("search items must be objects")
            return payload["items"]
        except ValueError:
            raise  # Do not treat a changed/error schema as an empty search result.
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

def pick(items, area):
    seen, out = set(), []
    for it in items:
        u = it.get("merUrl") or ""
        if not u.startswith(MER_PREFIX) or u in seen:
            continue
        if not in_locality(it.get("merAddr"), area):
            continue
        if (it.get("merTpbuzNm") or "") in NOT_LUNCH or not open_at_lunch(it):
            continue
        seen.add(u)
        out.append(it)
    def num(v):
        try:
            n = float(v)
            return n if math.isfinite(n) else 999.0
        except Exception: return 999.0
    out.sort(key=lambda x: (num(x.get("allSaleRnk")), num(x.get("ccgSaleRnk")), x["merUrl"]))
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

def load_previous(area_id):
    """Read only the current public display artifact, never raw API history.

    Fail on unreadable existing data rather than silently replacing a monthly
    board. A 404 means this area has not been published yet.
    """
    path = os.path.join(SITE, "data", f"{area_id}.json")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    if not PREVIOUS_SITE:  # explicit first/local build without an existing site
        return None
    url = f"{PREVIOUS_SITE}/data/{urllib.parse.quote(area_id, safe='')}.json"
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "user-agent": "lunch-bingo-build/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=40) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise

def make_board(area, items, month, updated, previous=None):
    eligible = pick(items, area)
    if not eligible:
        raise ValueError(f"{area['id']}: no verified lunch data; keep the previous deployment")
    fresh = {it["merUrl"]: {**view(it), "updated": updated} for it in eligible}
    candidates = list(fresh.values())
    old_month = None
    if previous is not None:
        old_month = previous.get("month") or str(previous.get("updated", ""))[:7]
        if previous.get("id") != area["id"] or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", old_month):
            raise ValueError(f"invalid previous board: {area['id']}")
        if old_month > month:
            raise ValueError(f"previous board is from the future: {area['id']}")
    if previous is not None and old_month == month:
        old_stores = previous.get("stores")
        if not isinstance(old_stores, list) or len(old_stores) != 24:
            raise ValueError(f"invalid previous stores: {area['id']}")
        seen, board = set(), []
        # Returned but no longer eligible is a correction, not a ranking change.
        returned = {it.get("merUrl") for it in items}
        for old in old_stores:
            u = old.get("u", "")
            valid = (isinstance(u, str) and u.startswith(MER_PREFIX) and u not in seen
                     and in_locality(old.get("a"), area) and old.get("c") not in NOT_LUNCH
                     and (u not in returned or u in fresh))
            if valid:
                seen.add(u)
                board.append(fresh.get(u) or {**old, "updated": old.get("updated") or previous["updated"]})
            else:
                board.append(None)
        replacements = iter(s for s in candidates if s["u"] not in seen)
        board = [s if s is not None else next(replacements, None) for s in board]
        if any(s is None for s in board):
            raise ValueError(f"{area['id']}: not enough verified lunch spots to repair board")
    else:
        if len(candidates) < 24:
            raise ValueError(f"{area['id']}: only {len(candidates)} verified lunch spots; need 24")
        board = board_order(area["id"], candidates[:24], month)
    identity = f"{area['id']}:{month}:" + "|".join(s["u"] for s in board)
    bid = hashlib.sha1(identity.encode()).hexdigest()[:8]
    # 'updated' describes displayed data, not merely a successful build attempt.
    display_updated = max(s["updated"] for s in board)
    return {"id": area["id"], "name": area["name"], "sub": area["sub"], "board": bid,
            "month": month, "updated": display_updated, "stores": board}

def build_site(areas, month, updated):
    # Publish the new directory only after every requested area is valid.
    # A query failure/shortage must not silently remove a neighborhood.
    with tempfile.TemporaryDirectory(prefix=".build-", dir=ROOT) as temp:
        stage = os.path.join(temp, "site")
        shutil.copytree(os.path.join(ROOT, "src"), stage)
        os.makedirs(os.path.join(stage, "data"), exist_ok=True)
        index = []
        first = True
        for ar in areas:
            previous = load_previous(ar["id"])
            items = []
            for loc in ar["q"]:
                if not first:
                    time.sleep(GAP)
                first = False
                got = fetch(loc)
                print(f"{ar['id']} / {loc}: {len(got)}", file=sys.stderr)
                items.extend(got)
            out = make_board(ar, items, month, updated, previous)
            with open(os.path.join(stage, "data", f"{ar['id']}.json"), "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
            index.append({"id": ar["id"], "name": ar["name"], "sub": ar["sub"]})
        if not index:
            raise ValueError("no areas requested")
        with open(os.path.join(stage, "data", "areas.json"), "w", encoding="utf-8") as f:
            json.dump({"updated": updated, "areas": index}, f, ensure_ascii=False)
        if os.path.isdir(SITE):
            shutil.rmtree(SITE)
        shutil.move(stage, SITE)
    return index


def main():
    with open(os.path.join(ROOT, "areas.json"), encoding="utf-8") as f:
        areas = json.load(f)
    only = set(sys.argv[1:])
    unknown = only - {a["id"] for a in areas}
    if unknown:
        raise ValueError(f"unknown areas: {', '.join(sorted(unknown))}")
    if only:
        areas = [a for a in areas if a["id"] in only]
    kst = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)
    index = build_site(areas, kst.strftime("%Y-%m"), kst.strftime("%Y-%m-%d"))
    print(f"built {len(index)} areas -> {SITE}", file=sys.stderr)

if __name__ == "__main__":
    main()
