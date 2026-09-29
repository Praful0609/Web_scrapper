"""
review_scraper.py  — Universal E-commerce Review Scraper
=========================================================
Supports: Amazon, Flipkart, Books.ToScrape (free test site), Generic pages.

Usage examples:
  python scraper.py --demo
  python scraper.py --url "https://books.toscrape.com" --site books --pages 1
  python scraper.py --url "https://www.amazon.in/dp/B09G3HRMVB" --site amazon --pages 3
  python scraper.py --url "https://www.flipkart.com/..." --site flipkart --pages 2
  python scraper.py --url "https://example.com/product" --site generic --debug

Outputs: reviews_output.json  +  reviews_output.csv
"""

import argparse
import json
import csv
import time
import random
import re
import sys
from datetime import datetime
from dataclasses import dataclass, asdict, field
from typing import Optional, List
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup


# ─────────────────────────────────────────────
#  DATA MODEL
# ─────────────────────────────────────────────

@dataclass
class Review:
    customer_name: str = "Anonymous"
    rating: Optional[float] = None
    title: str = ""
    body: str = ""
    tags: List[str] = field(default_factory=list)
    date: str = ""
    verified: bool = False
    helpful_votes: int = 0
    source_url: str = ""
    scraped_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ─────────────────────────────────────────────
#  HTTP HELPERS
# ─────────────────────────────────────────────

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3_1) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]

def make_headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Cache-Control": "max-age=0",
    }

def fetch(url: str, session: requests.Session, debug: bool = False,
          retries: int = 3) -> Optional[BeautifulSoup]:
    for attempt in range(1, retries + 1):
        try:
            time.sleep(random.uniform(1.5, 3.0))
            resp = session.get(url, headers=make_headers(), timeout=20, allow_redirects=True)

            if debug:
                print(f"  [DEBUG] Status={resp.status_code}  URL={resp.url}")
                print(f"  [DEBUG] Content-Type: {resp.headers.get('Content-Type','?')}")
                print(f"  [DEBUG] Response length: {len(resp.text)} chars")

            if resp.status_code == 503:
                print(f"  [!] 503 Service Unavailable (bot-blocked?). Retry {attempt}/{retries}...")
                time.sleep(5 * attempt)
                continue

            if resp.status_code == 404:
                print(f"  [!] 404 Not Found: {url}")
                return None

            resp.raise_for_status()

            lower = resp.text.lower()
            if any(kw in lower for kw in ["captcha", "robot check", "are you a human",
                                           "verify you're human", "access denied"]):
                print("  [!] Bot/CAPTCHA page detected. The site is blocking automated access.")
                print("      Try: --site generic  or use --demo to see sample output.")
                return None

            return BeautifulSoup(resp.text, "lxml")

        except requests.RequestException as exc:
            print(f"  [!] Request error (attempt {attempt}/{retries}): {exc}")
            if attempt < retries:
                time.sleep(3 * attempt)

    return None

def clean(text: str) -> str:
    return " ".join((text or "").strip().split())


# ─────────────────────────────────────────────
#  AMAZON SCRAPER
# ─────────────────────────────────────────────

def amazon_reviews_url(product_url: str, page: int = 1) -> str:
    parsed = urlparse(product_url)
    m = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", product_url)
    if not m:
        raise ValueError(
            "Could not extract ASIN from URL.\n"
            "Make sure the URL contains /dp/XXXXXXXXXX  (10-char ASIN).\n"
            f"Your URL: {product_url}"
        )
    asin = m.group(1)
    base = f"{parsed.scheme}://{parsed.netloc}"
    return (f"{base}/product-reviews/{asin}"
            f"?pageNumber={page}&sortBy=recent&reviewerType=all_reviews"
            f"&formatType=current_format")

def parse_amazon(soup: BeautifulSoup, url: str, debug: bool) -> List[Review]:
    reviews = []
    blocks = soup.select("div[data-hook='review']")

    if debug:
        print(f"  [DEBUG] Amazon blocks found: {len(blocks)}")
        if not blocks:
            snippet = soup.get_text()[:500].replace("\n", " ")
            print(f"  [DEBUG] Page text snippet: {snippet}")

    for b in blocks:
        r = Review(source_url=url)

        el = b.select_one("span.a-profile-name")
        r.customer_name = clean(el.text) if el else "Anonymous"

        el = b.select_one("i[data-hook='review-star-rating'] span.a-offscreen,"
                          "i[data-hook='cmps-review-star-rating'] span.a-offscreen")
        if el:
            m = re.search(r"([\d.]+)", el.text)
            r.rating = float(m.group(1)) if m else None

        el = b.select_one("a[data-hook='review-title'] span:last-child,"
                          "span[data-hook='review-title']")
        r.title = clean(el.text) if el else ""

        el = b.select_one("span[data-hook='review-body'] span,"
                          "div[data-hook='review-collapsed'] span")
        r.body = clean(el.text) if el else ""

        el = b.select_one("span[data-hook='review-date']")
        r.date = clean(el.text) if el else ""

        el = b.select_one("span[data-hook='avp-badge']")
        r.verified = bool(el)

        el = b.select_one("span[data-hook='helpful-vote-statement']")
        if el:
            m = re.search(r"(\d+)", el.text)
            r.helpful_votes = int(m.group(1)) if m else 0

        tag_els = b.select("span[data-hook='review-badge-text']")
        r.tags = list({clean(t.text) for t in tag_els if clean(t.text)})

        if r.body or r.title:
            reviews.append(r)

    return reviews

def scrape_amazon(url: str, pages: int, debug: bool) -> List[Review]:
    session = requests.Session()
    all_reviews = []
    print(f"\n📦  Amazon scraper — {pages} page(s)")
    for page in range(1, pages + 1):
        rev_url = amazon_reviews_url(url, page)
        print(f"  ➜  Page {page}: {rev_url}")
        soup = fetch(rev_url, session, debug)
        if not soup:
            break
        found = parse_amazon(soup, rev_url, debug)
        print(f"     Found {len(found)} reviews")
        all_reviews.extend(found)
    return all_reviews


# ─────────────────────────────────────────────
#  FLIPKART SCRAPER
# ─────────────────────────────────────────────

def flipkart_reviews_url(product_url: str, page: int = 1) -> str:
    base = product_url.split("?")[0].rstrip("/")
    if "/reviews" not in base:
        base += "/reviews"
    return f"{base}?page={page}"

def parse_flipkart(soup: BeautifulSoup, url: str, debug: bool) -> List[Review]:
    reviews = []

    blocks = (
        soup.select("div[class*='_27M-vq']") or
        soup.select("div[class*='col._2wzgFH']") or
        soup.select("div[class*='_3LWZlK']") or
        soup.select("div[class*='EKFha-']")
    )

    if not blocks:
        blocks = [div for div in soup.find_all("div")
                  if div.find(string=re.compile(r"^[1-5]$")) and
                  len(clean(div.get_text())) > 40][:30]

    if debug:
        print(f"  [DEBUG] Flipkart blocks found: {len(blocks)}")

    for b in blocks:
        r = Review(source_url=url)
        text = clean(b.get_text(" "))
        if len(text) < 20:
            continue

        for sel in ["p._2sc7ZR", "p._2NsDsF", "span._1anr7e", "span[class*='name']"]:
            el = b.select_one(sel)
            if el and len(el.text.strip()) < 80:
                r.customer_name = clean(el.text)
                break

        for sel in ["div._3LWZlK", "span._2_R_DZ", "span[class*='_1lRcqv']"]:
            el = b.select_one(sel)
            if el:
                m = re.search(r"([1-5])", clean(el.text))
                if m:
                    r.rating = float(m.group(1))
                    break

        for sel in ["p._2-N8zT", "p.s-name", "div.SGoXP1 p", "p[class*='title']"]:
            el = b.select_one(sel)
            if el:
                r.title = clean(el.text)
                break

        for sel in ["div.t-ZTKy div div", "div._6K-7Co", "div[class*='qwjRop']"]:
            el = b.select_one(sel)
            if el and len(clean(el.text)) > 15:
                r.body = clean(el.text)
                break

        if not r.body:
            r.body = text[:500]

        for sel in ["p._2sc7ZR", "span._3LYOAd"]:
            el = b.select_one(sel)
            if el and re.search(r"\d{4}", el.text):
                r.date = clean(el.text)
                break

        tag_els = b.select("span._1E2LiA, div._3B9EBD span")
        r.tags = list({clean(t.text) for t in tag_els if clean(t.text)})

        verified = b.find(string=re.compile("Certified Buyer|Verified", re.I))
        r.verified = bool(verified)

        if r.body or r.title:
            reviews.append(r)

    return reviews

def scrape_flipkart(url: str, pages: int, debug: bool) -> List[Review]:
    session = requests.Session()
    all_reviews = []
    print(f"\n🛒  Flipkart scraper — {pages} page(s)")
    for page in range(1, pages + 1):
        rev_url = flipkart_reviews_url(url, page)
        print(f"  ➜  Page {page}: {rev_url}")
        soup = fetch(rev_url, session, debug)
        if not soup:
            break
        found = parse_flipkart(soup, rev_url, debug)
        print(f"     Found {len(found)} reviews")
        all_reviews.extend(found)
    return all_reviews


# ─────────────────────────────────────────────
#  BOOKS.TOSCRAPE SCRAPER  (free test target)
# ─────────────────────────────────────────────

WORD_RATING = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}

def scrape_books(url: str, pages: int, debug: bool) -> List[Review]:
    """
    books.toscrape.com — a free sandbox site built for scraper practice.
    No login, no captcha, scraping-friendly.
    """
    session = requests.Session()
    all_reviews = []
    print(f"\n📚  Books.ToScrape scraper (free test target — no blocks!)")

    # Single book page
    if "/catalogue/" in url and "index.html" in url:
        urls_to_scrape = [url]
    else:
        urls_to_scrape = []
        for page in range(1, pages + 1):
            cat_url = f"https://books.toscrape.com/catalogue/page-{page}.html"
            print(f"  ➜  Catalogue page {page}: {cat_url}")
            soup = fetch(cat_url, session, debug)
            if not soup:
                break
            links = soup.select("article.product_pod h3 a")
            for a in links:
                href = a.get("href", "")
                full = urljoin("https://books.toscrape.com/catalogue/", href)
                urls_to_scrape.append(full)
            print(f"     Found {len(links)} books on this page")

    print(f"\n  Fetching details for {min(len(urls_to_scrape), 20)} book(s)...")
    for book_url in urls_to_scrape[:20]:
        soup = fetch(book_url, session, debug)
        if not soup:
            continue

        r = Review(source_url=book_url)

        h1 = soup.select_one("div.product_main h1")
        r.title = clean(h1.text) if h1 else "Unknown"

        star_el = soup.select_one("p.star-rating")
        if star_el:
            for cls in (star_el.get("class") or []):
                if cls in WORD_RATING:
                    r.rating = float(WORD_RATING[cls])
                    break

        desc = soup.select_one("article.product_page > p")
        r.body = clean(desc.text) if desc else "No description available."

        price_el = soup.select_one("p.price_color")
        avail_el = soup.select_one("p.availability")
        tags = []
        if price_el:
            tags.append(f"Price: {clean(price_el.text)}")
        if avail_el:
            tags.append(clean(avail_el.text))
        r.tags = tags

        rows = soup.select("table.table-striped tr")
        info = {}
        for row in rows:
            th = row.select_one("th")
            td = row.select_one("td")
            if th and td:
                info[clean(th.text)] = clean(td.text)
        r.customer_name = info.get("UPC", "N/A")

        if r.title:
            all_reviews.append(r)
            print(f"     ✓ {r.title[:55]:<55}  ⭐ {r.rating}")

    return all_reviews


# ─────────────────────────────────────────────
#  GENERIC / HEURISTIC SCRAPER
# ─────────────────────────────────────────────

RATING_RE = [
    re.compile(r"([\d.]+)\s*/\s*5"),
    re.compile(r"([\d.]+)\s*(?:out of|stars?)", re.I),
    re.compile(r"rating[^\d]*([\d.]+)", re.I),
]

def extract_rating(text: str) -> Optional[float]:
    for pat in RATING_RE:
        m = pat.search(text)
        if m:
            val = float(m.group(1))
            if 0 <= val <= 5:
                return val
    return None

def parse_generic(soup: BeautifulSoup, url: str, debug: bool) -> List[Review]:
    reviews = []

    # 1. Schema.org microdata
    schema_items = soup.find_all(attrs={"itemtype": re.compile(r"schema\.org/Review", re.I)})
    if schema_items:
        if debug:
            print(f"  [DEBUG] Schema.org Review items: {len(schema_items)}")
        for item in schema_items:
            r = Review(source_url=url)
            el = item.find(attrs={"itemprop": "author"})
            r.customer_name = clean(el.text) if el else "Anonymous"
            el = item.find(attrs={"itemprop": "reviewBody"})
            r.body = clean(el.text) if el else ""
            el = item.find(attrs={"itemprop": "ratingValue"})
            if el:
                m = re.search(r"([\d.]+)", el.get("content", el.text))
                r.rating = float(m.group(1)) if m else None
            el = item.find(attrs={"itemprop": "datePublished"})
            r.date = clean(el.get("content", el.text)) if el else ""
            el = item.find(attrs={"itemprop": "name"})
            r.title = clean(el.text) if el else ""
            if r.body or r.title:
                reviews.append(r)
        if reviews:
            return reviews

    # 2. JSON-LD structured data
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") == "Product":
                    review_list = item.get("review", [])
                    if not isinstance(review_list, list):
                        review_list = [review_list]
                    for rv in review_list:
                        r = Review(source_url=url)
                        author = rv.get("author", {})
                        r.customer_name = (author.get("name", "Anonymous")
                                           if isinstance(author, dict) else str(author))
                        r.body = rv.get("reviewBody", "")
                        r.title = rv.get("name", "")
                        rating = rv.get("reviewRating", {})
                        if isinstance(rating, dict):
                            rv_val = rating.get("ratingValue", 0)
                            r.rating = float(rv_val) if rv_val else None
                        r.date = rv.get("datePublished", "")
                        if r.body or r.title:
                            reviews.append(r)
        except Exception:
            pass

    if reviews:
        return reviews

    # 3. Heuristic HTML
    REVIEW_KEYWORDS = re.compile(
        r"review|comment|feedback|testimonial|rating|opinion", re.I)

    candidates = []
    for tag in soup.find_all(["div", "li", "article", "section"]):
        classes = " ".join(tag.get("class") or [])
        tag_id  = tag.get("id") or ""
        if REVIEW_KEYWORDS.search(classes) or REVIEW_KEYWORDS.search(tag_id):
            text = clean(tag.get_text(" "))
            if 30 < len(text) < 3000:
                candidates.append((tag, text))

    if debug:
        print(f"  [DEBUG] Heuristic candidates: {len(candidates)}")

    seen = set()
    for tag, text in candidates[:60]:
        if text in seen:
            continue
        seen.add(text)
        r = Review(source_url=url, body=text[:1000])
        r.rating = extract_rating(text)
        for sel in ["span.author", "span.name", "div.author", "p.author",
                    "span[class*='author']", "strong", "b", "cite"]:
            el = tag.select_one(sel)
            if el and 2 < len(el.text.strip()) < 80:
                r.customer_name = clean(el.text)
                break
        date_m = re.search(
            r"\b(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}|"
            r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\b",
            text, re.I)
        if date_m:
            r.date = date_m.group(0)
        reviews.append(r)

    return reviews

def scrape_generic(url: str, pages: int, debug: bool) -> List[Review]:
    session = requests.Session()
    all_reviews = []
    print(f"\n🌐  Generic scraper — {pages} page(s)")
    for page in range(1, pages + 1):
        sep = "&" if "?" in url else "?"
        paged = url if page == 1 else f"{url}{sep}page={page}"
        print(f"  ➜  Page {page}: {paged}")
        soup = fetch(paged, session, debug)
        if not soup:
            break
        found = parse_generic(soup, paged, debug)
        print(f"     Found {len(found)} reviews")
        all_reviews.extend(found)
    return all_reviews


# ─────────────────────────────────────────────
#  DEMO DATA
# ─────────────────────────────────────────────

def demo_reviews() -> List[Review]:
    return [
        Review("Priya Sharma", 5.0, "Absolutely love this product!",
               "Best purchase this year. Build quality is outstanding, arrived early.",
               ["Verified Purchase", "Top Reviewer"], "March 28, 2025", True, 42,
               "https://demo.example.com/product/123"),
        Review("Rahul Mehta", 4.0, "Good but minor packaging issue",
               "Works exactly as described. Packaging could be better but product is solid.",
               ["Verified Purchase"], "March 20, 2025", True, 18,
               "https://demo.example.com/product/123"),
        Review("Ananya Krishnan", 3.0, "Average experience",
               "Okay for the price but not as premium-feeling as the photos suggest.",
               [], "March 15, 2025", False, 5,
               "https://demo.example.com/product/123"),
        Review("Vikram Nair", 5.0, "Exceeded expectations",
               "Used it daily for two weeks, zero issues. Fast shipping and great packaging.",
               ["Verified Purchase", "Early Reviewer"], "March 10, 2025", True, 76,
               "https://demo.example.com/product/123"),
        Review("Sunita Rao", 2.0, "Disappointed with quality",
               "Stopped working after one week. Raised return request, still waiting.",
               ["Verified Purchase"], "March 5, 2025", True, 31,
               "https://demo.example.com/product/123"),
        Review("Arjun Patel", 4.5, "Great value for money",
               "Solid build, fast delivery. Instructions could be clearer but easy to figure out.",
               ["Top Reviewer", "Verified Purchase"], "February 28, 2025", True, 22,
               "https://demo.example.com/product/123"),
        Review("Deepa Iyer", 5.0, "Perfect gift",
               "Bought as a birthday gift — huge hit! Presentation lovely, quality matched photos.",
               ["Gift Purchase", "Verified Purchase"], "February 22, 2025", True, 14,
               "https://demo.example.com/product/123"),
        Review("Mohammed Zafar", 1.0, "Received wrong item",
               "Ordered blue variant, received completely different color. Return process is slow.",
               ["Verified Purchase"], "February 18, 2025", True, 63,
               "https://demo.example.com/product/123"),
    ]


# ─────────────────────────────────────────────
#  OUTPUT
# ─────────────────────────────────────────────

def save_json(reviews: List[Review], path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in reviews], f, indent=2, ensure_ascii=False)
    print(f"\n✅  JSON saved → {path}")

def save_csv(reviews: List[Review], path: str):
    if not reviews:
        return
    fields = list(asdict(reviews[0]).keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in reviews:
            row = asdict(r)
            row["tags"] = " | ".join(row["tags"])
            w.writerow(row)
    print(f"✅  CSV  saved → {path}")

def print_summary(reviews: List[Review]):
    if not reviews:
        print("\n⚠️   No reviews collected.")
        print("\n  Possible reasons & fixes:")
        print("  1. Site is blocking the scraper  → add --debug to diagnose")
        print("  2. Wrong --site flag             → try --site generic")
        print("  3. URL has no reviews            → check the URL in browser first")
        print("  4. Test with the free sandbox    → --url https://books.toscrape.com --site books")
        print("  5. See mock data                 → --demo")
        return

    ratings = [r.rating for r in reviews if r.rating is not None]
    avg = sum(ratings) / len(ratings) if ratings else 0
    print(f"\n{'─'*54}")
    print(f"   📊  SUMMARY")
    print(f"{'─'*54}")
    print(f"   Total reviews   : {len(reviews)}")
    print(f"   Average rating  : {avg:.2f} / 5.00")
    print(f"   Verified        : {sum(r.verified for r in reviews)}")
    print(f"   With tags       : {sum(bool(r.tags) for r in reviews)}")
    print(f"{'─'*54}")
    s = reviews[0]
    print(f"\n   First result:")
    print(f"   👤  {s.customer_name}")
    print(f"   ⭐  {s.rating}")
    print(f"   📌  {s.title}")
    if s.body:
        print(f"   💬  {s.body[:200]}...")
    print()


# ─────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Universal E-commerce Review Scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scraper.py --demo
  python scraper.py --url "https://books.toscrape.com" --site books --pages 1
  python scraper.py --url "https://www.amazon.in/dp/B09G3HRMVB" --site amazon --pages 3
  python scraper.py --url "https://www.flipkart.com/..." --site flipkart --pages 2
  python scraper.py --url "https://example.com/product" --site generic --debug
        """
    )
    parser.add_argument("--url",    help="Product / listing URL to scrape")
    parser.add_argument("--site",   choices=["amazon", "flipkart", "books", "generic"],
                        default="generic",
                        help="Target site parser  (default: generic)")
    parser.add_argument("--pages",  type=int, default=2,
                        help="Pages to scrape  (default: 2)")
    parser.add_argument("--output", default="reviews_output",
                        help="Output filename base  (default: reviews_output)")
    parser.add_argument("--demo",   action="store_true",
                        help="Use built-in demo data — no network needed")
    parser.add_argument("--debug",  action="store_true",
                        help="Print diagnostic info while scraping")
    args = parser.parse_args()

    if args.demo:
        print("🎭  Running in DEMO mode — using built-in mock data")
        reviews = demo_reviews()
    elif not args.url:
        parser.error("Provide --url <URL>  or use --demo")
    else:
        scrapers = {
            "amazon":   scrape_amazon,
            "flipkart": scrape_flipkart,
            "books":    scrape_books,
            "generic":  scrape_generic,
        }
        reviews = scrapers[args.site](args.url, args.pages, args.debug)

    print_summary(reviews)

    if reviews:
        save_json(reviews, f"{args.output}.json")
        save_csv(reviews,  f"{args.output}.csv")
    else:
        print("No output files written.")

if __name__ == "__main__":
    main()