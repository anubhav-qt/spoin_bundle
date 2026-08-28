"""Scraper for the ASCII Art Archive (https://www.asciiart.eu/).

Crawls the gallery hierarchy, extracts ASCII artwork cards with metadata,
enforces the <= 40 column width constraint (ADR-0021 / langchain_impl.py
_ASCII_MAX_WIDTH = 40), and outputs formatted reference text files for
use by the Spoin content generator.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import html
import json
import logging
import time
import urllib.parse
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx
from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning

# Suppress XML parsed as HTML warnings from bs4
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# Maximum monospace width budget for Spoin cards on mobile displays (ADR-0021, ADR-0066)
DEFAULT_MAX_WIDTH: int = 40
BASE_URL: str = "https://www.asciiart.eu"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ascii_scraper")

# Silence noisy third-party loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


@dataclass(frozen=True)
class AsciiCard:
    """A single scraped ASCII artwork with metadata."""

    id: str
    title: str
    artist: str
    category: str
    subcategory: str
    source_url: str
    art: str
    width: int
    height: int
    views: int

    def to_reference_block(self) -> str:
        """Format the card with metadata header and triple-backtick fence."""
        header = (
            f"=== ID: {self.id} | TITLE: {self.title} | ARTIST: {self.artist} | "
            f"CATEGORY: {self.category} | SUBCATEGORY: {self.subcategory} | "
            f"SIZE: {self.width}x{self.height} ==="
        )
        return f"{header}\n```\n{self.art}\n```\n"


def is_valid_ascii_art(art: str, max_width: int = DEFAULT_MAX_WIDTH) -> bool:
    """Verify that every line of the ASCII art strictly satisfies the width constraint.

    Trailing whitespace on lines is stripped before length measurement because trailing
    spaces do not contribute visible characters, whereas leading indentation is preserved.
    """
    if not art.strip():
        return False
    lines = art.split("\n")
    return all(len(line.rstrip()) <= max_width for line in lines)


def clean_ascii_art(raw_art: str) -> str:
    """Standardize newlines and trim leading/trailing blank lines while preserving indentation."""
    normalized = raw_art.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")

    # Strip empty lines from start and end
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    # rstrip each line to eliminate trailing whitespace without affecting left indentation
    return "\n".join(line.rstrip() for line in lines)


def compute_dimensions(art: str) -> tuple[int, int]:
    """Compute (max_width, height) from the cleaned art string."""
    lines = art.split("\n")
    if not lines:
        return (0, 0)
    max_w = max(len(line) for line in lines)
    return (max_w, len(lines))


def parse_category_from_url(url: str) -> tuple[str, str]:
    """Extract top-level category and subcategory path from an asciiart.eu URL."""
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.strip("/")
    parts = path.split("/")
    if not parts or parts == [""]:
        return ("general", "root")
    category = parts[0]
    subcategory = "/".join(parts[1:]) if len(parts) > 1 else "general"
    return (category, subcategory)


class AsciiArchiveCrawler:
    """Asynchronous crawler and scraper for asciiart.eu."""

    def __init__(
        self,
        max_width: int = DEFAULT_MAX_WIDTH,
        concurrency: int = 25,
        timeout: float = 25.0,
        category_filter: str | None = None,
    ) -> None:
        self.max_width = max_width
        self.concurrency = concurrency
        self.timeout = timeout
        self.category_filter = category_filter.lower().strip() if category_filter else None
        self.visited_urls: set[str] = set()
        self.discovered_cards: list[AsciiCard] = []
        self.rejected_cards_count: int = 0

    async def crawl_and_scrape(self) -> list[AsciiCard]:
        """Perform full discovery and extraction of valid ASCII cards."""
        limits = httpx.Limits(max_keepalive_connections=self.concurrency, max_connections=self.concurrency)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        async with httpx.AsyncClient(headers=headers, timeout=self.timeout, limits=limits, follow_redirects=True) as client:
            if self.category_filter:
                seeds = [f"{BASE_URL}/{self.category_filter}"]
            else:
                seeds = [
                    f"{BASE_URL}/gallery",
                    f"{BASE_URL}/one-line",
                    f"{BASE_URL}/ascii-borders/gallery",
                    f"{BASE_URL}/ascii-dividers/gallery",
                    f"{BASE_URL}/ascii-patterns/gallery",
                    f"{BASE_URL}/artists",
                ]

            queue: set[str] = set(seeds)
            semaphore = asyncio.Semaphore(self.concurrency)
            start_time = time.perf_counter()

            logger.info("Starting site discovery and scraping (max_width=%d)...", self.max_width)

            while queue:
                batch = list(queue)
                queue = set()

                async def process_url(url: str) -> tuple[list[AsciiCard], int, list[str]]:
                    if url in self.visited_urls:
                        return ([], 0, [])
                    self.visited_urls.add(url)

                    async with semaphore:
                        try:
                            resp = await client.get(url)
                            if resp.status_code != 200:
                                return ([], 0, [])

                            soup = BeautifulSoup(resp.text, "html.parser")
                            cards_on_page: list[AsciiCard] = []
                            rejected_on_page: int = 0
                            new_urls: list[str] = []

                            # Extract art cards if present
                            art_elements = [el for el in soup.find_all("div", class_="art-card") if isinstance(el, Tag)]
                            cat, subcat = parse_category_from_url(url)

                            # Apply category filter if specified
                            if not self.category_filter or cat == self.category_filter:
                                for el in art_elements:
                                    ascii_div = el.find("div", class_="art-card__ascii")
                                    if not isinstance(ascii_div, Tag):
                                        continue

                                    raw_art = ascii_div.get_text()
                                    cleaned = clean_ascii_art(raw_art)

                                    if not is_valid_ascii_art(cleaned, self.max_width):
                                        rejected_on_page += 1
                                        continue

                                    width, height = compute_dimensions(cleaned)
                                    raw_id = el.get("data-id")
                                    card_id = str(raw_id) if raw_id else f"art_{len(self.discovered_cards)}_{len(cards_on_page)}"
                                    raw_title = el.get("data-title")
                                    title = html.unescape(str(raw_title) if raw_title else "Untitled").strip()
                                    raw_artist = el.get("data-artist")
                                    artist = html.unescape(str(raw_artist) if raw_artist else "unknown").strip()
                                    raw_views = el.get("data-views")

                                    try:
                                        views = int(str(raw_views)) if raw_views else 0
                                    except ValueError:
                                        views = 0

                                    card = AsciiCard(
                                        id=card_id,
                                        title=title,
                                        artist=artist,
                                        category=cat,
                                        subcategory=subcat,
                                        source_url=url,
                                        art=cleaned,
                                        width=width,
                                        height=height,
                                        views=views,
                                    )
                                    cards_on_page.append(card)

                            # Discover next links
                            for a in soup.find_all("a", href=True):
                                if not isinstance(a, Tag):
                                    continue
                                raw_href = a.get("href")
                                if not raw_href:
                                    continue
                                href_str = str(raw_href).split("#")[0].split("?")[0].strip()
                                if not href_str:
                                    continue
                                if href_str.startswith("/"):
                                    full_url = urllib.parse.urljoin(BASE_URL, href_str)
                                elif href_str.startswith(BASE_URL):
                                    full_url = href_str
                                else:
                                    continue

                                # If category filter is active, only follow links in that category
                                if self.category_filter:
                                    parsed_cat, _ = parse_category_from_url(full_url)
                                    if parsed_cat != self.category_filter:
                                        continue

                                # Ignore non-content sections
                                if any(
                                    x in full_url
                                    for x in [
                                        "/account",
                                        "/search",
                                        "/ascii-draw-studio/app",
                                        "/archives/usenet",
                                        "/tools",
                                        "mailto:",
                                        "/binaryia",
                                        "/cookie-policy",
                                        "/privacy-policy",
                                        "/terms-of-use",
                                    ]
                                ):
                                    continue

                                if full_url not in self.visited_urls:
                                    new_urls.append(full_url)

                            return (cards_on_page, rejected_on_page, new_urls)
                        except (httpx.HTTPError, TimeoutError, OSError) as err:
                            logger.warning("Network or I/O error processing %s: %s", url, err)
                            return ([], 0, [])

                tasks = [process_url(u) for u in batch]
                results = await asyncio.gather(*tasks)

                for valid_cards, rejected_count, discovered_urls in results:
                    self.discovered_cards.extend(valid_cards)
                    self.rejected_cards_count += rejected_count
                    for nu in discovered_urls:
                        if nu not in self.visited_urls:
                            queue.add(nu)

                logger.info(
                    "Progress: %d pages visited, %d valid cards collected, %d rejected (> %d cols), queue=%d",
                    len(self.visited_urls),
                    len(self.discovered_cards),
                    self.rejected_cards_count,
                    self.max_width,
                    len(queue),
                )

            elapsed = time.perf_counter() - start_time
            logger.info(
                "Completed crawl in %.2fs. Total pages: %d, Valid cards (<= %d cols): %d, Rejected cards: %d",
                elapsed,
                len(self.visited_urls),
                self.max_width,
                len(self.discovered_cards),
                self.rejected_cards_count,
            )

        return self.discovered_cards


def save_ascii_library(
    cards: Sequence[AsciiCard],
    output_dir: Path,
    max_width: int = DEFAULT_MAX_WIDTH,
) -> dict[str, int]:
    """Save cards into category-based .txt files, summary document, and manifest."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Group cards by top-level category
    by_category: dict[str, list[AsciiCard]] = collections.defaultdict(list)
    for card in cards:
        by_category[card.category].append(card)

    stats: dict[str, int] = {}

    # Write each category file
    for category, category_cards in sorted(by_category.items()):
        file_path = output_dir / f"{category}.txt"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"# ASCII ART ARCHIVE REFERENCE LIBRARY - CATEGORY: {category.upper()}\n")
            f.write(f"# Total artworks in category fitting <={max_width} cols: {len(category_cards)}\n")
            f.write("# Format: Header followed by triple-backtick fenced ASCII art\n\n")

            for card in category_cards:
                f.write(card.to_reference_block())
                f.write("\n")

        stats[category] = len(category_cards)
        logger.info("Saved %d cards to %s", len(category_cards), file_path.name)

    # Write consolidated full library file
    consolidated_file = output_dir / "_all_categories_library.txt"
    with open(consolidated_file, "w", encoding="utf-8") as f:
        f.write("# ASCII ART ARCHIVE REFERENCE LIBRARY - COMPLETE CONSOLIDATED COLLECTION\n")
        f.write(f"# Total artworks fitting <={max_width} cols: {len(cards)}\n")
        f.write("# Format: Header followed by triple-backtick fenced ASCII art\n\n")
        for card in cards:
            f.write(card.to_reference_block())
            f.write("\n")

    # Write readable summary text
    summary_txt = output_dir / "_summary.txt"
    with open(summary_txt, "w", encoding="utf-8") as f:
        f.write("ASCII ART ARCHIVE REFERENCE LIBRARY SUMMARY\n")
        f.write("=" * 50 + "\n\n")
        f.write("Source: https://www.asciiart.eu\n")
        f.write(f"Max Column Width Constraint: <= {max_width} characters\n")
        f.write(f"Total Valid Artworks Stored: {len(cards):,}\n")
        f.write(f"Total Categories: {len(by_category)}\n\n")
        f.write("Category Breakdown:\n")
        f.write("-" * 50 + "\n")
        f.writelines(
            f"  {cat:<30}: {cnt:>5} cards\n"
            for cat, cnt in sorted(stats.items(), key=lambda x: x[1], reverse=True)
        )
        f.write("-" * 50 + "\n")
        f.write(f"  {'TOTAL':<30}: {len(cards):>5} cards\n")

    # Write index & summary JSON
    manifest_file = output_dir / "_library_manifest.json"
    manifest_data = {
        "source": "https://www.asciiart.eu",
        "max_column_width": max_width,
        "total_cards": len(cards),
        "categories_count": len(by_category),
        "category_breakdown": stats,
    }
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)

    logger.info("Saved complete library index to %s", consolidated_file.name)
    logger.info("Saved summary report to %s", summary_txt.name)
    logger.info("Saved metadata manifest to %s", manifest_file.name)
    return stats


async def main_async(args: argparse.Namespace) -> None:
    """Async entrypoint for running the scraper."""
    output_dir = Path(args.output_dir)
    crawler = AsciiArchiveCrawler(
        max_width=args.max_width,
        concurrency=args.concurrency,
        timeout=args.timeout,
        category_filter=args.category,
    )
    cards = await crawler.crawl_and_scrape()
    save_ascii_library(cards, output_dir=output_dir, max_width=args.max_width)


def main() -> None:
    """CLI argument parser and main entrypoint."""
    parser = argparse.ArgumentParser(
        description="Scrape and build the ASCII Art reference library for Spoin (<= 40 width constrained)."
    )
    parser.add_argument(
        "--max-width",
        type=int,
        default=DEFAULT_MAX_WIDTH,
        help=f"Maximum allowed monospace column width per line (default: {DEFAULT_MAX_WIDTH})",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(Path(__file__).parent / "ascii_art_library"),
        help="Directory to save the reference .txt files and manifest",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=25,
        help="Number of concurrent HTTP requests (default: 25)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=25.0,
        help="HTTP request timeout in seconds (default: 25.0)",
    )
    parser.add_argument(
        "--category",
        type=str,
        default=None,
        help="Optional: Scrape only a specific category (e.g. 'animals', 'cartoons', 'food-and-drinks')",
    )

    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
