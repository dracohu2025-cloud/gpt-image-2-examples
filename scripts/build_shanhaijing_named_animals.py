#!/usr/bin/env python3
"""Build a named-animal catalog from the Shan Hai Jing wiki source.

This script crawls the "动物" category page from 酒馆百科 and extracts
independently named animal entries plus a short modern-Chinese description.
It writes both JSON and Markdown outputs under ./data.
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup


CATEGORY_URL = "https://shj.jgbk.net/f337.html"
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "catalogs"
JSON_PATH = DATA_DIR / "shanhaijing_named_animals_206.json"
MD_PATH = DATA_DIR / "shanhaijing_named_animals_206.md"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
MAX_WORKERS = 12
REQUEST_TIMEOUT = 15


@dataclass
class AnimalEntry:
    index: int
    name: str
    chapter: str
    short_summary: str
    summary: str
    url: str


@dataclass
class SourceExcerpt:
    chapter: str
    original: str
    translation: str


SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})


def fetch_text(url: str) -> str:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = SESSION.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            response.encoding = "utf-8"
            return response.text
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}") from last_error


def normalize_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"\s*([，。；：！？、“”《》（）])\s*", r"\1", text)
    return text.strip()


def first_sentences(text: str, limit: int = 2) -> str:
    parts = [part.strip() for part in re.split(r"[。！？]", text) if part.strip()]
    if not parts:
        return text.strip()
    return "；".join(parts[:limit]).strip("；") + "。"


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[。！？]", normalize_text(text)) if part.strip()]


def tidy_summary(name: str, raw_intro: str) -> str:
    intro = normalize_text(raw_intro)
    intro = re.sub(r"^Tips：.*?--0", "", intro)
    intro = intro.replace("[编辑]", "")
    intro = intro.replace(f"“{name}”", name)
    intro = re.sub(r"^在《[^》]+》(和《[^》]+》)*[^；。]*；", "", intro)
    intro = re.sub(rf"^{re.escape(name)}是《山海经》中[^；。]*；", "", intro)
    intro = re.sub(rf"^{re.escape(name)}是《山海经》中(?:出现的)?一种[^，。]*[，,]?", "", intro)
    intro = re.sub(rf"^{re.escape(name)}是《山海经》中(?:出现的)?[^，。]*[，,]?", "", intro)
    intro = re.sub(rf"^{re.escape(name)}是《山海经》中的[^，。]*[，,]?", "", intro)
    intro = re.sub(rf"^{re.escape(name)}在《[^》]+》[中里]有记载[，,]?", "", intro)
    intro = re.sub(r"读音为[^，。]+[，,]?", "", intro)
    intro = re.sub(r"在《[^》]+》中有记载[，,]?", "", intro)
    intro = re.sub(r"本文最近1个月没有更新，如果内容错误、缺失的话，你可以在评论区留言", "", intro)
    if "；" in intro and "《山海经》" in intro.split("；", 1)[0]:
        intro = intro.split("；", 1)[1]
    intro = intro.strip("；，。 ")
    intro = re.sub(r"^[；，、]+", "", intro)
    intro = intro.replace("，；", "；")
    summary = first_sentences(intro, limit=2)
    if "；" in summary and "《山海经》" in summary.split("；", 1)[0]:
        summary = summary.split("；", 1)[1].strip()
    return summary


def extract_references(entry_content: BeautifulSoup) -> list[SourceExcerpt]:
    refs: list[SourceExcerpt] = []
    for row in entry_content.select("table tbody tr"):
        cols = row.find_all("td")
        if len(cols) < 3:
            continue
        chapter_text = normalize_text(cols[0].get_text(" ", strip=True))
        chapter_match = re.search(r"《山海经：([^》]+)》", chapter_text)
        if not chapter_match:
            continue
        refs.append(
            SourceExcerpt(
                chapter=chapter_match.group(1),
                original=normalize_text(cols[1].get_text(" ", strip=True)),
                translation=normalize_text(cols[2].get_text(" ", strip=True)),
            )
        )
    return refs


def unique_keep_order(items: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def infer_visual_type(name: str, refs: list[SourceExcerpt], short_summary: str) -> str:
    text = short_summary + name
    if any(keyword in text for keyword in ["鱼", "鱬", "鯥", "鳞", "鲋", "鲤"]):
        return "fish"
    if "龟" in name or "鳖" in name:
        return "turtle"
    if any(keyword in text for keyword in ["鸟", "凤", "鹄", "鹤", "鸳", "翅", "喙", "羽"]):
        return "bird"
    return "beast"


def pick_trait_sentences(
    name: str,
    refs: list[SourceExcerpt],
    short_summary: str,
    include_variant: bool = False,
) -> list[str]:
    candidates: list[str] = []
    if short_summary:
        candidates.append(short_summary.rstrip("。"))

    if include_variant:
        descriptor_keywords = [
            "形状",
            "外形",
            "耳",
            "尾",
            "翼",
            "足",
            "爪",
            "角",
            "毛",
            "首",
            "面",
            "身",
            "音",
            "鸣",
            "食",
            "见",
            "狐",
            "马",
            "鱼",
            "鸟",
            "龟",
            "豹",
            "蛇",
            "猿",
            "鹿",
            "犬",
            "四足",
            "九尾",
        ]
        for ref in refs:
            for sentence in split_sentences(ref.translation):
                if name in sentence and any(keyword in sentence for keyword in descriptor_keywords):
                    candidates.append(sentence)

    cleaned: list[str] = []
    for sentence in unique_keep_order(candidates):
        sentence = sentence.strip("“”\" ")
        sentence = sentence.replace(f"它叫{name}", name)
        sentence = sentence.replace(f"其名叫{name}", name)
        sentence = sentence.replace(f"名为{name}", name)
        sentence = sentence.replace(f"被称为{name}", name)
        sentence = sentence.replace(f"其名曰{name}", name)
        sentence = sentence.replace(f"，它叫{name}", f"，名为{name}")
        sentence = sentence.replace(f"，其名叫{name}", f"，名为{name}")
        sentence = sentence.replace(f"，{name}，", f"，名为{name}，")
        sentence = sentence.replace(f"它叫 {name}", name)
        sentence = sentence.replace(f"它的外貌", "整体外形")
        sentence = sentence.replace(f"它的外形", "整体外形")
        sentence = sentence.replace(f"它外形", "整体外形")
        sentence = sentence.replace(f"它的声音", "声音")
        sentence = sentence.replace("有一种动物，", "")
        sentence = sentence.replace("一种动物，", "")
        sentence = sentence.replace("在这里多有", "此地多有")
        sentence = sentence.replace("其形状", "整体形状")
        cleaned.append(sentence.strip("；，。 "))

    return cleaned[:2]


def infer_scene_phrase(animal_type: str, chapter_text: str) -> str:
    chapter_text = chapter_text or ""
    default_map = {
        "bird": "高山、断崖、古木、流云与烈风",
        "fish": "深水、河泽、暗流、浪涌与水雾",
        "turtle": "古水泽、浅滩、怪石与潮湿雾气",
        "beast": "荒山、古林、怪石、薄雾与上古植被",
    }
    overseas_scene = {
        "bird": "海外荒岛、断崖、云海与烈风",
        "fish": "海外深水、礁石、浪涌与浓重水雾",
        "turtle": "海外水泽、潮滩、礁石与湿冷雾气",
        "beast": "海外荒山、古林、礁石与冷雾",
    }
    if "海外" in chapter_text or "海内" in chapter_text:
        return overseas_scene[animal_type]
    return default_map[animal_type]


def infer_tone(text: str) -> str:
    if any(keyword in text for keyword in ["食人", "大兵", "大疫", "大旱", "大水", "火灾", "则死", "则枯"]):
        return "凶异、危险、压迫感强"
    if any(keyword in text for keyword in ["宜子孙", "不蛊", "不疥", "不聋", "不迷", "安宁", "无忧", "不会得病", "祥瑞", "平安"]):
        return "神秘、带有护佑或祥瑞意味"
    return "诡谲、原始、神秘"


def focus_phrase(animal_type: str) -> str:
    mapping = {
        "bird": "羽毛色彩、喙爪结构、异形肢体与展翼姿态",
        "fish": "鳞片质感、头尾结构、躯体曲线与水中动态",
        "turtle": "甲壳纹理、头尾结构、爬行姿态与水陆交界的湿润质感",
        "beast": "头部轮廓、肢体比例、尾巴或角的结构、皮毛纹样与动作姿态",
    }
    return mapping[animal_type]


def build_prompt_description(
    name: str,
    chapters: list[str],
    refs: list[SourceExcerpt],
    short_summary: str,
) -> str:
    animal_type = infer_visual_type(name, refs, short_summary)
    trait_sentences = pick_trait_sentences(
        name,
        refs,
        short_summary,
        include_variant=len(chapters) > 1,
    )
    trait_text = "；".join(trait_sentences) if trait_sentences else short_summary.rstrip("。")
    chapter_text = "".join(f"《{chapter}》" for chapter in chapters) if chapters else "《山海经》"
    scene = infer_scene_phrase(animal_type, " ".join(chapters))
    tone = infer_tone(trait_text)
    focus = focus_phrase(animal_type)
    return (
        f"山海经异兽{name}，形象参考{chapter_text}：{trait_text}。"
        f"画面中重点突出{focus}，背景可放入{scene}，整体呈现{tone}的远古东方神话氛围。"
    )


def parse_category(html: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[tuple[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.select(".baike-list.style-1.collapse a.category-box"):
        name = normalize_text(anchor.get("title") or anchor.get_text())
        url = anchor.get("href", "").strip()
        if not name or not url or name in seen:
            continue
        seen.add(name)
        items.append((name, url))
    return items


def extract_entry(index: int, name: str, url: str) -> AnimalEntry:
    html = fetch_text(url)
    soup = BeautifulSoup(html, "html.parser")

    title = normalize_text(soup.select_one("h1.article-title").get_text())
    entry_content = soup.select_one(".entry-content")
    if entry_content is None:
        raise ValueError(f"missing .entry-content: {url}")

    content_text = normalize_text(entry_content.get_text(" ", strip=True))
    intro = content_text.split("山海图鉴", 1)[0]
    refs = extract_references(entry_content)
    chapters = unique_keep_order([ref.chapter for ref in refs])
    chapter = chapters[0] if chapters else ""
    short_summary = tidy_summary(title or name, intro)

    return AnimalEntry(
        index=index,
        name=title or name,
        chapter=chapter,
        short_summary=short_summary,
        summary=build_prompt_description(title or name, chapters, refs, short_summary),
        url=url,
    )


def to_markdown(entries: Iterable[AnimalEntry]) -> str:
    rows = [
        "# 《山海经》动物独立词条清单（206）",
        "",
        "> 说明：这份清单来自“山海经百科图鉴”的“动物”分类页自动抽取结果，收录的是可独立成条目的命名动物。",
        "> 它适合后续做 `gpt-image-2` 主题库、Prompt 库和图鉴页，但不等于常见“《山海经》动物 277 种”的学术统计口径。",
        "",
        "| 序号 | 名称 | 篇目 | 简述（可直接入Prompt） | 来源 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for entry in entries:
        summary = entry.summary.replace("|", "\\|")
        chapter = entry.chapter or "-"
        rows.append(
            f"| {entry.index} | {entry.name} | {chapter} | {summary} | [条目]({entry.url}) |"
        )
    rows.append("")
    return "\n".join(rows)


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    category_html = fetch_text(CATEGORY_URL)
    items = parse_category(category_html)

    entries: list[AnimalEntry | None] = [None] * len(items)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(extract_entry, index, name, url): index - 1
            for index, (name, url) in enumerate(items, start=1)
        }
        for future in as_completed(futures):
            slot = futures[future]
            entries[slot] = future.result()

    final_entries = [entry for entry in entries if entry is not None]
    JSON_PATH.write_text(
        json.dumps([asdict(entry) for entry in final_entries], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    MD_PATH.write_text(to_markdown(final_entries), encoding="utf-8")

    print(f"wrote {len(final_entries)} entries")
    print(JSON_PATH)
    print(MD_PATH)


if __name__ == "__main__":
    main()
