#!/usr/bin/env python3
"""Venture Board stats collector. Runs on GitHub Actions (free, open network).
Reads config.json (slug -> store ids), pulls public store stats + Polar sales, writes stats.json.
Every source is optional: a failure is recorded in "errors" and the rest still runs."""
import json, os, sys, urllib.request, urllib.parse, datetime
UA = {"User-Agent": "venture-board-collector/1.0", "Accept": "application/json"}
def get(url, headers=None, data=None, method=None):
    h = dict(UA); h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode("utf-8"))
cfg = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")))
out, errors = {}, []
def put(slug, **kw):
    d = out.setdefault(slug, {})
    for k, v in kw.items():
        if v is not None: d[k] = v
def num(x):
    try: return float(x)
    except Exception: return None

for slug, src in cfg["products"].items():
    try:
        if src.get("vscode"):
            body = json.dumps({"filters": [{"criteria": [{"filterType": 7, "value": src["vscode"]}]}], "flags": 914}).encode()
            r = get("https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery", {"Content-Type": "application/json", "Accept": "application/json;api-version=7.2-preview.1"}, body, "POST")
            ext = r["results"][0]["extensions"][0]; st = {s["statisticName"]: s["value"] for s in ext.get("statistics", [])}
            put(slug, installs=int(st.get("install", 0)), rating=round(st["averagerating"], 2) if st.get("ratingcount") else None, reviews=int(st.get("ratingcount", 0)), version=ext["versions"][0]["version"], vscodeStatus="live")
    except Exception as e: errors.append(f"{slug} vscode: {e}")
    try:
        if src.get("openvsx"):
            r = get("https://open-vsx.org/api/" + src["openvsx"])
            put(slug, openvsxDownloads=r.get("downloadCount"), openvsxStatus="live" if r.get("version") else "pending")
    except urllib.error.HTTPError as e:
        put(slug, openvsxStatus="not public yet") if e.code == 404 else errors.append(f"{slug} openvsx: {e}")
    except Exception as e: errors.append(f"{slug} openvsx: {e}")
    try:
        if src.get("edge"):
            r = get("https://microsoftedge.microsoft.com/addons/getproductdetailsbycrxid/" + src["edge"])
            put(slug, edgeUsers=r.get("activeInstallCount"), rating=num(r.get("averageRating")) or None, reviews=r.get("ratingCount"), edgeVersion=r.get("version"))
    except Exception as e: errors.append(f"{slug} edge: {e}")
    try:
        if src.get("amo"):
            r = get("https://addons.mozilla.org/api/v5/addons/addon/%s/" % src["amo"])
            put(slug, firefoxUsers=r.get("average_daily_users"), firefoxStatus=r.get("status"), firefoxRating=(r.get("ratings") or {}).get("average"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404): put(slug, firefoxStatus="not public yet")
        else: errors.append(f"{slug} amo: {e}")
    except Exception as e: errors.append(f"{slug} amo: {e}")
    try:
        if src.get("wporg"):
            q = urllib.parse.urlencode({"action": "plugin_information", "request[slug]": src["wporg"], "request[fields][active_installs]": 1})
            r = get("https://api.wordpress.org/plugins/info/1.2/?" + q)
            if r.get("error"): put(slug, wporgStatus="not public yet")
            else: put(slug, installs=r.get("active_installs"), rating=round(r["rating"] / 20, 2) if r.get("num_ratings") else None, reviews=r.get("num_ratings"), wporgStatus="live")
    except urllib.error.HTTPError as e:
        put(slug, wporgStatus="not public yet") if e.code == 404 else errors.append(f"{slug} wporg: {e}")
    except Exception as e: errors.append(f"{slug} wporg: {e}")
    try:
        if src.get("atlassian"):
            r = get("https://marketplace.atlassian.com/rest/2/addons/" + src["atlassian"])
            dist = r.get("distribution") or {}; rev = r.get("reviews") or {}
            put(slug, installs=dist.get("totalInstalls"), activeUsers=dist.get("totalUsers"), rating=rev.get("averageStars"), reviews=rev.get("count"), atlassianStatus="live")
    except urllib.error.HTTPError as e:
        put(slug, atlassianStatus="not public yet") if e.code == 404 else errors.append(f"{slug} atlassian: {e}")
    except Exception as e: errors.append(f"{slug} atlassian: {e}")
    # combine store user counts into installs when a product has several stores
    d = out.get(slug, {})
    parts = [d.get(k) for k in ("edgeUsers", "firefoxUsers", "openvsxDownloads") if isinstance(d.get(k), (int, float))]
    if parts and not src.get("vscode") and not src.get("wporg") and not src.get("atlassian"): d["installs"] = int(sum(parts))

# Polar sales: orders + active subscriptions, per product id
tok = os.environ.get("POLAR_TOKEN")
if tok:
    pid2slug = {pid: slug for slug, src in cfg["products"].items() for pid in src.get("polar", [])}
    H = {"Authorization": "Bearer " + tok}
    try:
        page = 1
        while True:
            r = get(f"https://api.polar.sh/v1/orders/?limit=100&page={page}", H)
            for o in r.get("items", []):
                slug = pid2slug.get(o.get("product_id"))
                if not slug or o.get("status") not in ("paid", "refunded", "partially_refunded"): continue
                d = out.setdefault(slug, {})
                cents = o.get("net_amount", o.get("subtotal_amount", o.get("amount", 0))) or 0
                refunded = o.get("refunded_amount", 0) or 0
                d["grossUsd"] = round(d.get("grossUsd", 0) + (cents - refunded) / 100, 2)
                if cents > 0: d["sales"] = d.get("sales", 0) + 1
                if refunded: d["refunds"] = d.get("refunds", 0) + 1
                # $0 orders (100% discount codes, owner test buys) are not paying customers
                if cents > 0: d.setdefault("_customers", set()).add(o.get("customer_id"))
                else: d["freeOrders"] = d.get("freeOrders", 0) + 1
            pg = r.get("pagination") or {}
            if page >= (pg.get("max_page") or 1): break
            page += 1
        for slug in set(pid2slug.values()):
            d = out.setdefault(slug, {})
            d["payingCustomers"] = len(d.pop("_customers", set()) - {None})
            d.setdefault("grossUsd", 0); d.setdefault("sales", 0); d.setdefault("refunds", 0)
    except Exception as e: errors.append(f"polar orders: {e}")
    try:
        page = 1; subs = {}
        while True:
            r = get(f"https://api.polar.sh/v1/subscriptions/?active=true&limit=100&page={page}", H)
            for s in r.get("items", []):
                slug = pid2slug.get(s.get("product_id"))
                if slug and (s.get("amount") or 0) > 0: subs[slug] = subs.get(slug, 0) + 1
            pg = r.get("pagination") or {}
            if page >= (pg.get("max_page") or 1): break
            page += 1
        for slug in set(pid2slug.values()): out.setdefault(slug, {})["paidUsers"] = subs.get(slug, 0)
    except Exception as e: errors.append(f"polar subscriptions: {e}")
else:
    errors.append("POLAR_TOKEN not set")

for d in out.values(): d.pop("_customers", None)
now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
json.dump({"fetchedAt": now, "products": out, "errors": errors}, open("stats.json", "w"), indent=1, default=list)
print(json.dumps({"fetchedAt": now, "products": len(out), "errors": errors}))
