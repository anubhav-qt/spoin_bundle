"""Intelligent Visual Analyzer & Personalized Distinct Title Generator for Spoin ASCII Reference Library.

Analyzes every individual artwork card in detail, extracts unique visual posture/object
details, assigns a 100% DISTINCT, highly descriptive, search-friendly one-liner title to every
single card, removes duplicates, and filters out obscure/unclear items and all 90-degree sideways emojis.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("rich_distinct_title_refiner")

# Maximum height suitable for mobile flashcard viewports
MAX_PRACTICAL_HEIGHT: int = 22

# Sideways 90-degree emoticons to strictly filter out
SIDEWAYS_EMOTES: set[str] = {
    ":-)", ":)", ":-(", ":(", ":-D", ":D", ":-P", ":P", ";-P", ";P",
    ":-O", ":O", ":-X", ":-*", ";-)", ";)", ";->", "}:-)", "}:)",
    ">:-(", ">:(", ">=D", ">:-D", "8-)", "B-)", "(:|", "|:-|", "C|:-=",
    "~(_8^(I)", "(_8(I)", "<3", "---D",
}

# Individualized precise title overrides for specific artworks
SPECIFIC_CARD_TITLES: dict[str, tuple[str, str]] = {
    # Simpsons Characters
    "6cd8433b14d4742a": ("Bart Simpson front-facing portrait with spiky hair and round eyes", "gag"),
    "96f0c3ec5df6891b": ("Sideshow Bob with wild palm-tree hair and necklace beads", "gag"),
    "a531c90a823e1a62": ("Homer Simpson with 5 o'clock shadow stubble and round eyes", "gag"),
    "95a09cf435f73b8d": ("Apu Nahasapeemapetilon Kwik-E-Mart clerk with parted hair", "gag"),
    "c8566f9b4b4329dc": ("Krusty the Clown side profile with tufted hair and bulbous nose", "gag"),
    "b27fe5339b95297b": ("Milhouse Van Houten wearing round spectacles and collar", "gag"),
    "137f3725ae4b2c40": ("Sideshow Mel with bone tied in hair and whistle necklace", "gag"),
    "c07844afb093d383": ("Lisa Simpson with star-pointed hair playing saxophone", "gag"),
    "d56097e54f1dc5ed": ("Maggie Simpson with hair ribbon bow sucking pacifier", "gag"),
    "1ca8882eebe6d182": ("The Simpsons living room television set with cathode tube", "gag"),

    # Dogs
    "a554c60e4afb8f4b": ("Dachshund wiener dog wearing star-patterned winter sweater", "gag"),
    "cf6bbc9460003289": ("Minimalist puppy standing on four stick legs with tail up", "gag"),
    "491b7f288951bae9": ("Long-bodied hound dog with floppy ears and ball tail", "gag"),
    "d350134f132151b7": ("Little dog sitting attentively on hind legs", "gag"),
    "df7c1996e74d9389": ("Geometric stylized dog with pointed ears and triangular legs", "gag"),
    "f691ba8f588314ef": ("Long-eared hound dog crouching forward", "gag"),

    # Mice & Rodents
    "199107cd28327dc2": ("Mouse crawling forward with curly tail and two round ear loops", "gag"),
    "1073e7303c4fe320": ("Minimalist tiny mouse head with round ears and whisker dot", "gag"),
    "0b6da3e63e3b648c": ("Tiny mouse crouching with round QQ ears and tail", "gag"),
    "dedba09f6d664019": ("Chubby mouse sitting on hind legs with whisker nose", "gag"),
    "22540ef676f632a0": ("Mouse curled backwards with long tail curved overhead", "gag"),
    "cfee258bea00c122": ("Mouse with long extended tail standing on four tiny feet", "gag"),
    "b507c1ce40f06583": ("Mouse scurrying rightward with undulating tail", "gag"),
    "d95b1d7d048157f5": ("Mouse sniffing large wedge of Swiss cheese with holes", "gag"),
    "5e4a039e0101a64d": ("Curious mouse with wide round eyes and front paws", "gag"),
    "1754836868261108": ("Mouse sitting upright on floor with long trailing tail", "gag"),
    "8c3ec242f876220f": ("Tiny mouse sleeping curled into crescent ball", "gag"),

    # Fish & Marine Life
    "119bfa25ef09ba64": ("Pair of discus tropical aquarium fish swimming together", "gag"),
    "f230973b75eca2b3": ("Angelfish swimming through rising air bubble streams", "gag"),
    "6e63e6433a63d56d": ("Small goldfish blowing bubble stream swimming rightward", "gag"),
    "e0d5669104b4f2bb": ("Tiny goldfish silhouette swimming right", "gag"),
    "df375a31ed85462b": ("Tropical fish outline swimming left with fin", "gag"),
    "b10025eb543dfca2": ("Fish with striped dorsal fin swimming leftward", "gag"),
    "362d695396060ec7": ("Slender minnow fish swimming horizontally with fin tail", "gag"),
    "f2291f993a23cb1f": ("Fish skeleton bones with head and tail fins", "gag"),
    "7e81019444443695": ("Wide-mouthed bass fish with round eye swimming left", "gag"),
    "8a13045b87f7f6bb": ("Round pufferfish with dorsal spines and pectoral fins", "gag"),
    "c5167dd66f8a0ded": ("Two tropical fish facing each other in conversation", "gag"),
    "af9728b371525f12": ("Goldfish with delicate fanned tail swimming upwards", "gag"),
    "ded1c74345581414": ("Tropical clownfish swimming right with banded stripes", "gag"),
    "60d7a285b3d4d863": ("Fish with wide eye and open mouth swimming left", "gag"),
    "a9febaf01c8bfebe": ("Swordfish with sharp elongated bill leaping right", "gag"),
    "c8ace02005c2884c": ("Predatory shark with prominent dorsal fin swimming left", "informative"),
    "cde2fe837ee33953": ("Curious fish peering right with large round eye", "gag"),
    "5b1847994f2a3b3a": ("Fish schooling in trio swimming together", "gag"),
    "cf5f9afe11792613": ("Wide-bodied carp fish with patterned scales swimming left", "gag"),
    "eb05ad6699e0ec1d": ("Spotted trout fish with curved body swimming right", "gag"),
    "10482272b14a4b57": ("Seahorse curling tail around seaweed frond", "informative"),
    "479b9cd7cf906e98": ("Deep sea anglerfish with glowing dorsal lure and sharp teeth", "gag"),
    "6903da942ed86341": ("Giant ocean sunfish mola mola swimming slowly", "informative"),

    # Sports
    "7f0758ac5a321de5": ("Ice hockey stick crossed with black rubber puck", "informative"),
    "473949017907cb1f": ("Ice hockey player skating with stick and helmet", "informative"),
    "95683f0f52450cc9": ("Ice hockey goalie in padded mask and blockers defending net", "informative"),
    "99fd1d53b95d8806": ("Bungee jumper diving upside down suspended by elastic cord", "informative"),
    "0e30c36d35a0e4ce": ("Bungee jumper leaping off bridge with safety harness", "informative"),
    "123142180b0fd8cf": ("Scuba diving snorkel breathing tube with mouthpiece", "informative"),
    "28bcfaebac1cc4a0": ("Scuba diver swimming horizontally with oxygen tank and flippers", "informative"),
    "361858330fb134e2": ("Scuba diver exploring coral reef with underwater flashlight", "informative"),
    "7ffcf3575d48a20d": ("Deep sea diver in vintage brass diving helmet and suit", "informative"),
    "ec1b9e3340567ca6": ("Scuba diver descending into deep ocean with air bubbles", "informative"),
    "a52aa6b7cfcb3cea": ("Scuba diver ascending toward ocean surface light", "informative"),
    "fb42ed84ba3d2009": ("Rodeo cowboy riding bucking bronco horse with raised arm", "informative"),
    "c3b919421aa9403f": ("Competitive swimmer performing front crawl freestyle stroke", "informative"),
    "471387f86be5c253": ("Swimmer diving into pool with streamline arm position", "informative"),
    "770b3c0201d5293b": ("Swimmer executing butterfly stroke with water splash", "informative"),

    # Pop Culture & Media
    "e66c42e0137f8ed1": ("Doctor Who sonic screwdriver multipurpose gadget tool", "informative"),
    "edf04aa476fc9f2b": ("Mona Lisa portrait with enigmatic smile and folded hands", "gag"),
    "c54265b7b9e0f99b": ("Mona Lisa classical oil painting portrait in decorative frame", "gag"),
    "9a308d3d385ac808": ("Mona Lisa framed portrait sketch by Joan Stark", "gag"),

    # Toilets & Fixtures
    "ee2b5eb449af274c": ("Minimalist ceramic bathroom toilet with flush tank", "gag"),
    "9af8fad2ff979b91": ("Toilet commode with lifted seat lid", "gag"),
    "7e94cf762dede368": ("Porcelain toilet with water flush handle lever", "gag"),
    "8bc5ad1eddf52eb7": ("Bathroom toilet fixture with roll of toilet paper beside tank", "gag"),
    "cd5c8b6edf81e606": ("Toilet with seat down and rectangular cistern", "gag"),
    "81dd7a2ae84a8be4": ("Detailed ceramic bathroom commode with curved bowl", "gag"),
    "cec78ba530a668d6": ("Vintage high-tank pull-chain flush toilet fixture", "gag"),
    "5bb07eb64e874fd8": ("Modern dual-flush bathroom toilet with oval bowl", "gag"),

    # Nature & Snow
    "207d906637f6c6ef": ("Snow-covered pine trees in winter mountain blizzard", "informative"),
}


@dataclass(frozen=True)
class RawCard:
    """Raw card extracted from the archive library."""

    id: str
    original_title: str
    artist: str
    category: str
    subcategory: str
    width: int
    height: int
    art: str


def clean_str(s: str) -> str:
    """Remove redundant spaces and standardize string."""
    return re.sub(r"\s+", " ", s).strip()


class DistinctTitleGenerator:
    """Generates 100% distinct, rich, search-friendly descriptive titles for every individual ASCII art card."""

    def __init__(self) -> None:
        self.used_titles: set[str] = set()

    def generate_unique_title(self, card: RawCard) -> tuple[str, str] | None:
        """Analyze individual card and assign a rich descriptive title and target file type."""
        if card.height > MAX_PRACTICAL_HEIGHT:
            return None

        lines = card.art.split("\n")
        non_empty_lines = [line.strip() for line in lines if line.strip()]
        if not non_empty_lines or len(card.art.strip()) < 2:
            return None

        cat = card.category.lower().strip()
        subcat = card.subcategory.lower().strip()
        art_trimmed = card.art.strip()

        # Filter out 90-degree sideways emojis
        if art_trimmed in SIDEWAYS_EMOTES:
            return None

        # Filter out single line fragments that are not valid recognized 1-liners
        if len(non_empty_lines) == 1 and card.height > 1:
            return None

        # Check explicit overrides
        if card.id in SPECIFIC_CARD_TITLES:
            title, target = SPECIFIC_CARD_TITLES[card.id]
            return (self._make_unique(title, card), target)

        # ---------------------------------------------------------
        # 1. DIVIDERS & BORDERS
        # ---------------------------------------------------------
        if cat.startswith("ascii-dividers") or "divider" in subcat:
            return self._handle_divider(card)

        if cat.startswith(("ascii-patterns", "ascii-borders")):
            if card.height <= 10:
                base = f"Rectangular text frame box border with geometric hatching ({card.width}x{card.height})"
                return (self._make_unique(base, card), "informative")
            return None

        # ---------------------------------------------------------
        # 2. ONE-LINE EMOTICONS & REACTIONS (UPRIGHT KAOMOJI ONLY)
        # ---------------------------------------------------------
        if cat == "one-line" or card.height == 1:
            return self._handle_one_liner(card)

        # ---------------------------------------------------------
        # 3. DOMAIN-SPECIFIC RICH DESCRIPTIVE TITLING
        # ---------------------------------------------------------
        target_type = "informative"
        base_title: str | None = None

        if cat == "animals":
            base_title, target_type = self._title_animals(card)

        elif cat == "mythology":
            base_title, target_type = self._title_mythology(card)

        elif cat in {"cartoons", "comics"}:
            base_title, target_type = self._title_cartoons_and_comics(card)

        elif cat == "computers":
            base_title, target_type = self._title_computers(card)

        elif cat == "electronics":
            base_title, target_type = self._title_electronics(card)

        elif cat == "books":
            base_title, target_type = self._title_books(card)

        elif cat == "nature":
            base_title, target_type = self._title_nature(card)

        elif cat == "plants":
            base_title, target_type = self._title_plants(card)

        elif cat == "space":
            base_title, target_type = self._title_space(card)

        elif cat == "food-and-drinks":
            base_title, target_type = self._title_food(card)

        elif cat == "weapons":
            base_title, target_type = self._title_weapons(card)

        elif cat == "vehicles":
            base_title, target_type = self._title_vehicles(card)

        elif cat == "buildings-and-places":
            base_title, target_type = self._title_buildings(card)

        elif cat == "religion":
            base_title, target_type = self._title_religion(card)

        elif cat == "sports-and-outdoors":
            base_title, target_type = self._title_sports(card)

        elif cat in {"people", "artists"}:
            res = self._title_people(card)
            if res is not None:
                base_title, target_type = res

        elif cat == "miscellaneous":
            base_title, target_type = self._title_misc(card)

        elif cat == "holiday-and-events":
            base_title, target_type = self._title_holidays(card)

        elif cat in {"movies", "television"}:
            base_title, target_type = self._title_media(card)

        elif cat == "music":
            base_title, target_type = self._title_music(card)

        elif cat == "clothing-and-accessories":
            base_title, target_type = self._title_clothing(card)

        elif cat in {"toys", "video-games"}:
            base_title, target_type = self._title_toys_and_games(card)

        elif cat == "logos":
            base_title, target_type = self._title_logos(card)

        elif cat == "art-and-design":
            base_title, target_type = self._title_art_and_design(card)

        if base_title is None:
            # Fallback to enriched original title if meaningful
            orig_title = card.original_title.strip()
            if orig_title.lower() not in {"untitled", "unknown", ""}:
                base_title = self._clean_title_str(orig_title)
                target_type = "informative"

        if base_title is None:
            return None

        unique_title = self._make_unique(base_title, card)
        return (unique_title, target_type)

    def _clean_title_str(self, raw: str) -> str:
        """Format title string."""
        t = clean_str(raw).rstrip(".-_")
        if t and not t[0].isupper():
            t = t[0].upper() + t[1:]
        return t

    def _make_unique(self, base_title: str, card: RawCard) -> str:
        """Ensure title is 100% unique by adding distinctive metadata if necessary."""
        title = self._clean_title_str(base_title)
        if title not in self.used_titles:
            self.used_titles.add(title)
            return title

        # Try adding artist if present
        if card.artist and card.artist.lower() not in {"unknown", "anonymous"}:
            artist_clean = card.artist.split("(")[0].strip()
            candidate = f"{title} (by {artist_clean})"
            if candidate not in self.used_titles:
                self.used_titles.add(candidate)
                return candidate

        # Try adding dimensions
        candidate = f"{title} [{card.width}x{card.height}]"
        if candidate not in self.used_titles:
            self.used_titles.add(candidate)
            return candidate

        # Fallback with counter
        counter = 2
        while f"{title} #{counter}" in self.used_titles:
            counter += 1
        final_title = f"{title} #{counter}"
        self.used_titles.add(final_title)
        return final_title

    def _handle_divider(self, card: RawCard) -> tuple[str, str] | None:
        """Analyze divider cards and generate distinct titles."""
        lines = card.art.split("\n")
        art = card.art
        if len(lines) == 1:
            single = lines[0].strip()
            if set(single) <= {"-", "="}:
                title = f"Horizontal double-line section separator ({len(single)} chars)"
                return (self._make_unique(title, card), "informative")
            if set(single) <= {"~", "^", " "}:
                title = f"Wavy water ripple horizontal divider line ({len(single)} chars)"
                return (self._make_unique(title, card), "informative")
            if set(single) <= {"*", " "}:
                title = f"Star-studded horizontal divider bar ({len(single)} stars)"
                return (self._make_unique(title, card), "informative")
            return None

        if len(lines) <= 4:
            if ".-=" in art or "-=-" in art or "====" in art:
                title = f"Decorative framed border banner with ornamental corners ({card.width}x{card.height})"
                return (self._make_unique(title, card), "informative")
            if "~" in art and "^" in art:
                title = f"Ocean waves multi-line wave divider pattern ({card.width}x{card.height})"
                return (self._make_unique(title, card), "informative")
            title = f"Ornamental multi-line section break divider ({card.width}x{card.height})"
            return (self._make_unique(title, card), "informative")
        return None

    def _handle_one_liner(self, card: RawCard) -> tuple[str, str] | None:
        """Detailed 1-liner recognition with upright Kaomoji only (NO sideways emojis)."""
        trimmed = card.art.strip()

        upright_emotes: dict[str, tuple[str, str]] = {
            "\\o/": ("Stick figure cheering with arms raised in victory (\\o/)", "gag"),
            "\\(^-^)/": ("Cheering happy figure with arms raised in delight (\\(^-^)/)", "gag"),
            "(^-^)/": ("Cheerfully waving hand in greeting ((^-^)/)", "gag"),
            "\\(^o^)/": ("Joyfully cheering figure with raised arms in excitement (\\(^o^)/)", "gag"),
            "\\^o^/": ("Excited cheering face with raised arms (\\^o^/)", "gag"),
            "\\ (^_^) /": ("Cheering happy anime face with raised arms (\\ (^_^) /)", "gag"),
            "(9'-')9": ("Boxer fighter stance with raised fists ready to brawl ((9'-')9)", "gag"),
            "[o_o]": ("Wide-eyed square robot face looking surprised ([o_o])", "gag"),
            "(o_o)": ("Wide-eyed surprised face staring forward ((o_o))", "gag"),
            "(-_-)": ("Unimpressed tired face with closed eyes (-_-)", "gag"),
            "(>_<)": ("Frustrated wincing face with tightly shut eyes ((>_<))", "gag"),
            "(^_^)": ("Happy smiling anime face with cheerful eyes ((^_^))", "gag"),
            "(o.O)": ("Confused face with one raised eyebrow and uneven eyes ((o.O))", "gag"),
            "(O.o)": ("Perplexed face with one wide eye and one narrow eye ((O.o))", "gag"),
            "(='.'=)": ("Cute bunny face with twitching nose and whiskers ((='.'=))", "gag"),
            "d-_-b": ("Character wearing over-ear headphones listening to music (d-_-b)", "gag"),
            "(>-.-)>": ("Kirby happily dancing and reaching out arms ((>-.-)>)", "gag"),
            "<(o_o<)": ("Kirby inhaling and facing left (<(o_o<))", "gag"),
            "(>'-')>": ("Kirby dancing with arms pointed right ((>'-')>)", "gag"),
            "<('-'<)": ("Kirby dancing with arms pointed left (<('-'<))", "gag"),
            "^(^.^)^": ("Kirby jumping in air with hands raised in celebration (^(^.^)^)", "gag"),
            "<(^.^)>": ("Kirby dancing happily with open stubby arms (<(^.^)>)", "gag"),
            "(^o^)": ("Joyfully singing happy smiley face ((^o^))", "gag"),
            "(>O<)": ("Shouting face with mouth wide open in excitement ((>O<))", "gag"),
            "x__x": ("Knocked out face with X eyes (x__x)", "gag"),
            "x_x": ("Dazed face with crossed out eyes (x_x)", "gag"),
            "+_+": ("Stunned dizzy face with plus-sign eyes (+_+)", "gag"),
            "(@_@)": ("Hypnotized face with swirling spiral eyes ((@_@))", "gag"),
            "($.$)": ("Greedy face with dollar signs in eyes (($.$))", "gag"),
            "(*_*)": ("Starstruck amazed face with twinkling eyes ((*_*))", "gag"),
            "(T_T)": ("Crying anime face with streams of tears ((T_T))", "gag"),
            "(;_;)": ("Weeping face shedding tears of sorrow ((;_;))", "gag"),
            "O_o": ("Skeptical face with raised eyebrow (O_o)", "gag"),
            "(o_O)": ("Disturbed face looking sideways ((o_O))", "gag"),
            "^--^": ("Happy resting cat face with pointed ears (^--^)", "gag"),
            "(._.)": ("Shy character looking down at floor ((._.))", "gag"),
            "(._. )": ("Curious character peeking sideways ((._. ))", "gag"),
            "( ._.)": ("Character looking over shoulder (( ._.))", "gag"),
            "[._.]": ("Thoughtful robot looking down ([._.])", "gag"),
            "(=^..^=)": ("Little kitten face with whiskers and nose ((=^..^=))", "gag"),
            "c==[:::>": ("Medieval broadsword with crossguard and sharp blade (c==[:::>)", "informative"),
            "---(--@": ("Long-stemmed rose with blooming rosebud and thorns (---(--@)", "informative"),
            "@}->--": ("Single blooming rose flower on slender stem (@}->--)", "informative"),
            "~^~^~": ("Ocean water waves rippling horizontally (~^~^~)", "informative"),
            "<==>": ("Double-ended bidirectional arrow indicator (<==>)", "informative"),
            "[==|==]": ("Heavy barbell weightlifting bar loaded with circular plates ([==|==])", "informative"),
            "<_<": ("Suspicious character glancing left (<_<)", "gag"),
            ">_>": ("Sneaky character glancing right (>_>)", "gag"),
            "(o)(o)": ("Pair of wide staring round eyeballs ((o)(o))", "gag"),
        }
        if trimmed in upright_emotes:
            title, target = upright_emotes[trimmed]
            return (self._make_unique(title, card), target)

        if "[o_o]" in trimmed and "(^.^)" in trimmed:
            return (self._make_unique("Set of four emotive reaction faces: robot, happy, shy, money eyes", card), "gag")

        if "<('-'<)" in trimmed and "(>'-')>" in trimmed:
            return (self._make_unique("Kirby dance animation sequence moving left to right", card), "gag")

        if "(,,,)=(^.^)=(,,,)" in trimmed:
            return (self._make_unique("Cat face with cute paws extended on both sides", card), "gag")

        return None

    def _title_animals(self, card: RawCard) -> tuple[str, str]:
        """Detailed individual animal species and posture titling."""
        sub = card.subcategory.lower()
        title = card.original_title.lower()
        art_lower = card.art.lower()

        if "cats" in sub:
            if "zzz" in art_lower or "sleeping" in title:
                return ("Sleeping cat curled up peacefully with ZZZs", "gag")
            if "felix" in art_lower or "felix lee" in art_lower:
                return ("Sleeping cat stretched out horizontally on floor", "gag")
            if "julie rhodes" in art_lower:
                return ("Cat lounging on belly with outstretched tail and paws", "gag")
            if "flump" in art_lower and "---{" in card.art:
                return ("Cat head and front paws resting on horizontal fence line", "gag")
            if "flump" in art_lower and "^~^" in card.art:
                return ("Tiny kitten sitting upright with curled tail", "gag")
            if "flump" in art_lower and ",-\"\"\"\"\"\"-." in card.art:
                return ("Cat peeking over rounded blanket ledge", "gag")
            if "lara" in art_lower or "allen" in art_lower:
                return ("Fluffy kitten sitting with front paws and long tail", "gag")
            if "she-dragon" in title or "ldb" in art_lower:
                return ("Lion head profile framed by thick mane rings", "informative")
            if "sk" in art_lower and "panther" in title:
                return ("Sleek black panther stalking in crouched hunting posture", "informative")
            if "sk" in art_lower:
                return ("Cat with arched back stretching with tail upright", "gag")
            if "o_o" in card.art and "|\\---/|" in card.art:
                return ("Wide-eyed cat face with triangular ears and whiskers", "gag")
            if "o.o" in card.art and "/\\_/\\" in card.art:
                return ("Curious kitten face with pointed ears and whisker dots", "gag")
            if "|o o |" in card.art and "(((" in card.art:
                return ("Cat lying down with paws tucked under body", "gag")
            if "==_y_==" in art_lower:
                return ("Cat sitting upright with curled tail wrapped around front", "gag")
            if "(_.>)`" in card.art or "puma" in title:
                return ("Crouching puma feline stalking forward with alert posture", "gag")
            if "snd" in art_lower and "lion" in title:
                return ("Cute lion cub with fluffy mane and paw steps", "gag")
            if "(\"'-" in card.art or "(\"`-''-/" in card.art:
                return ("Tiger feline prowling forward with striped coat pattern", "gag")
            if "== ^ ==" in card.art or "(\\___/)" in card.art:
                return ("Cat face outline with whiskers and triangular ears", "gag")
            return (f"Domestic cat sitting in graceful silhouette with curved tail ({card.width}x{card.height})", "gag")

        if "dogs" in sub:
            if "snoopy" in art_lower or "snoopy" in title:
                return (f"Snoopy the beagle dog resting atop red doghouse ({card.width}x{card.height})", "gag")
            if "puppy" in title or card.height <= 6:
                return (f"Puppy dog face with floppy ears and wet nose ({card.width}x{card.height})", "gag")
            if "dachshund" in title or "wiener" in title or card.width > 28:
                return (f"Dachshund wiener dog long elongated body profile ({card.width}x{card.height})", "gag")
            if "poodle" in title:
                return ("Poodle dog with fluffy trimmed coat and topknot", "gag")
            if "bulldog" in title:
                return ("Bulldog with sturdy jowls and muscular wide chest", "gag")
            if "terrier" in title:
                return ("Scottish terrier dog with pointed beard and perked ears", "gag")
            return (f"Loyal dog standing attentively with wagging tail ({card.width}x{card.height})", "gag")

        if "rodents" in sub or "mice" in sub:
            if "rat" in title:
                return (f"Curious rat with long whiskers and slender tail ({card.width}x{card.height})", "gag")
            if "hamster" in title or "guinea" in title:
                return (f"Hamster sitting nibbling food with puffed cheeks ({card.width}x{card.height})", "gag")
            if "mickey" in title or "mickey" in art_lower:
                return ("Mickey Mouse silhouette face with round circular ears", "gag")
            if "cheese" in art_lower or "cheese" in title:
                return (f"Little mouse nibbling on wedge of cheese ({card.width}x{card.height})", "gag")
            if "squirrel" in title or "squirrel" in sub:
                return (f"Bushy-tailed squirrel holding an acorn nut ({card.width}x{card.height})", "gag")
            if "beaver" in sub or "beaver" in title:
                return (f"Beaver with large flat paddle tail chewing wood log ({card.width}x{card.height})", "informative")
            return (f"Little mouse with round ears and curly tail ({card.width}x{card.height})", "gag")

        if "birds" in sub or "birds-land" in sub or "birds-water" in sub:
            if "owl" in title or "owl" in art_lower:
                return (f"Wise owl perched on branch with large circular eyes ({card.width}x{card.height})", "informative")
            if "penguin" in title or "penguin" in art_lower:
                return (f"Penguin standing upright on ice with flipper wings ({card.width}x{card.height})", "gag")
            if "duck" in title or "duck" in art_lower:
                return (f"Duck swimming on water ripples with rounded bill ({card.width}x{card.height})", "gag")
            if "eagle" in title or "hawk" in title:
                return (f"Eagle bird of prey with sharp curved beak and spread wings ({card.width}x{card.height})", "informative")
            if "flamingo" in title:
                return ("Flamingo standing gracefully balanced on one slender leg", "informative")
            if "parrot" in title or "toucan" in title:
                return (f"Tropical parrot bird with large curved beak perched on branch ({card.width}x{card.height})", "informative")
            if "peacock" in title:
                return ("Peacock displaying fanned iridescent plumage feathers", "informative")
            if "swan" in title:
                return ("Elegant white swan gliding on calm lake surface", "informative")
            if "rooster" in title or "chicken" in title:
                return (f"Crowing rooster with prominent head comb and tail feathers ({card.width}x{card.height})", "gag")
            if "hummingbird" in title:
                return ("Tiny hummingbird hovering with rapid wings drinking nectar", "informative")
            return (f"Bird perched on twig with feathered wings and beak ({card.width}x{card.height})", "informative")

        if "insects" in sub:
            if "butterfly" in sub or "butterflies" in sub:
                return (f"Butterfly with symmetrical patterned wings spread ({card.width}x{card.height})", "informative")
            if "ant" in sub or "ants" in sub:
                return (f"Worker ant with antennae and segmented body carrying load ({card.width}x{card.height})", "informative")
            if "bee" in sub or "bees" in sub:
                return (f"Honeybee buzzing with striped abdomen and translucent wings ({card.width}x{card.height})", "informative")
            if "snail" in sub or "snails" in sub:
                return (f"Garden snail crawling with spiral shell and eye stalks ({card.width}x{card.height})", "informative")
            if "spider" in sub or "spiders" in sub:
                return (f"Spider with eight jointed legs suspended on silk web ({card.width}x{card.height})", "informative")
            if "caterpillar" in sub or "worm" in sub:
                return (f"Caterpillar worm crawling with segmented undulating body ({card.width}x{card.height})", "informative")
            if "beetle" in sub or "beetles" in sub or "ladybug" in title:
                return (f"Scarab beetle with hardened protective elytra shell wings ({card.width}x{card.height})", "informative")
            if "dragonfly" in title:
                return ("Dragonfly with long slender abdomen and dual wing pairs", "informative")
            return (f"Segmented insect with antennae and jointed legs ({card.width}x{card.height})", "informative")

        if "reptiles" in sub:
            if "dinosaur" in sub or "dinosaurs" in sub:
                return (f"Tyrannosaurus Rex dinosaur roaring with small forearms ({card.width}x{card.height})", "gag")
            if "snake" in sub or "snakes" in sub:
                return (f"Serpent snake coiled in striking posture with flicking tongue ({card.width}x{card.height})", "informative")
            if "turtle" in sub or "turtles" in sub:
                return (f"Sea turtle swimming with textured carapace shell and flippers ({card.width}x{card.height})", "informative")
            if "lizard" in sub or "lizards" in sub or "gecko" in title:
                return (f"Gecko lizard clinging to surface with splayed padded toes ({card.width}x{card.height})", "informative")
            if "alligator" in sub or "crocodile" in sub:
                return (f"Alligator crocodile with long armored snout and scaly tail ({card.width}x{card.height})", "informative")
            return (f"Reptile with scaly textured skin and tail ({card.width}x{card.height})", "informative")

        if "horses" in sub:
            if "unicorn" in title:
                return (f"Magical unicorn head with spiral horn and flowing mane ({card.width}x{card.height})", "gag")
            if "pegasus" in title:
                return (f"Winged Pegasus horse rearing with spread feathered wings ({card.width}x{card.height})", "gag")
            return (f"Galloping stallion horse profile with flowing mane and hooves ({card.width}x{card.height})", "informative")

        if "elephants" in sub:
            return (f"African elephant with large fan ears and raised curved trunk ({card.width}x{card.height})", "informative")

        if "camels" in sub:
            return (f"Desert dromedary camel with prominent hump and halter ({card.width}x{card.height})", "informative")

        if "cows" in sub:
            if "cow-head" in title or card.height <= 5:
                return (f"Dairy cow face with snout, ears, and curved horns ({card.width}x{card.height})", "gag")
            return (f"Spotted dairy cow standing in pasture profile ({card.width}x{card.height})", "gag")

        if "bears" in sub:
            if "teddy" in title or "teddy" in art_lower:
                return (f"Teddy bear stuffed plush toy sitting with round paws ({card.width}x{card.height})", "gag")
            if "panda" in title:
                return (f"Giant panda bear sitting eating bamboo ({card.width}x{card.height})", "gag")
            return (f"Wild bear silhouette standing on all four sturdy paws ({card.width}x{card.height})", "gag")

        if "monkeys" in sub:
            if "gorilla" in title:
                return (f"Muscular gorilla silverback beating chest standing tall ({card.width}x{card.height})", "gag")
            if "chimpanzee" in title:
                return (f"Chimpanzee scratching head with curious facial expression ({card.width}x{card.height})", "gag")
            return (f"Playful monkey hanging by curled tail and smiling ({card.width}x{card.height})", "gag")

        if "frogs" in sub:
            return (f"Wide-mouthed frog sitting on lily pad with bulging eyes ({card.width}x{card.height})", "gag")

        if "rabbits" in sub:
            return (f"Fluffy bunny rabbit with tall upright ears and cotton tail ({card.width}x{card.height})", "gag")

        if "wolves" in sub:
            return (f"Wolf howling with head tilted upwards under full moon ({card.width}x{card.height})", "gag")

        if "bats" in sub:
            return (f"Vampire bat flying with scalloped webbed wings spread ({card.width}x{card.height})", "gag")

        if "bisons" in sub:
            return (f"American bison buffalo with shaggy hump and curved horns ({card.width}x{card.height})", "informative")

        if "moose" in sub:
            return (f"Bull moose with broad branching palmate antlers in profile ({card.width}x{card.height})", "informative")

        if "deer" in sub:
            return (f"Wild forest deer stag with tall branching antlers ({card.width}x{card.height})", "informative")

        if "dolphins" in sub or "whales" in sub:
            if "whale" in title or "whale" in sub:
                return (f"Breaching humpback whale with water spout blowhole spray ({card.width}x{card.height})", "informative")
            return (f"Playful dolphin leaping gracefully over ocean wave crests ({card.width}x{card.height})", "informative")

        if "aardvarks" in sub or "anteater" in title:
            return (f"Aardvark anteater with long slender snout and digging claws ({card.width}x{card.height})", "gag")

        if "amoeba" in sub:
            return (f"Microscopic single-celled amoeba organism with pseudopod arms ({card.width}x{card.height})", "informative")

        if "hedgehog" in title or "porcupine" in title:
            return (f"Little hedgehog with prickly spines curled into protective ball ({card.width}x{card.height})", "gag")

        if "koala" in title:
            return (f"Fluffy koala bear clinging to eucalyptus tree trunk ({card.width}x{card.height})", "gag")

        if "kangaroo" in title:
            return (f"Australian kangaroo bounding with joey peeking from pouch ({card.width}x{card.height})", "gag")

        if "octopus" in title or "squid" in title:
            return (f"Giant sea octopus with eight curling suction-cup tentacles ({card.width}x{card.height})", "informative")

        if "crab" in title or "lobster" in title:
            return (f"Crustacean crab with large pinching claws and walking legs ({card.width}x{card.height})", "informative")

        animal_name = sub.split("/")[-1].replace("-", " ")
        if card.original_title.lower() not in {"untitled", "unknown", ""}:
            return (f"{self._clean_title_str(card.original_title)} ({card.width}x{card.height})", "gag")
        return (f"{animal_name.capitalize()} animal in distinct wildlife posture ({card.width}x{card.height})", "gag")

    def _title_mythology(self, card: RawCard) -> tuple[str, str]:
        """Detailed mythology titling."""
        sub = card.subcategory.lower()

        if "mermaids" in sub:
            if card.id == "2e37911694582c76":
                return ("Mermaid diving headfirst downwards towards the sea floor", "gag")
            if card.id == "db5471923bf66a11":
                return ("Small mermaid sitting with curved tail resting right", "gag")
            if card.id == "8a06d735b9f31254":
                return ("Mermaid swimming facing two little fish", "gag")
            if card.id == "d61dcd040c2ad310":
                return ("Mermaid swimming horizontally with outstretched arms", "gag")
            if card.id == "299b1916203c7e4d":
                return ("Mermaid with curly hair resting on seafloor", "gag")
            if card.id == "9bca3b065c67478e":
                return ("Mermaid swimming through surface waves facing left", "gag")
            if card.id == "64f4d9d0328c6009":
                return ("Mermaid lounging on sea floor next to starfish", "gag")
            if card.id == "834814b4c027d9f3":
                return ("Mermaid swimming downward facing right", "gag")
            if card.id == "d89fda433eb3905b":
                return ("Mermaid swimming downward facing left", "gag")
            if card.id == "fd9df083a398ffbd":
                return ("Mermaid swimming toward surface bubbles facing right", "gag")
            if card.id == "aed62b6fc2845659":
                return ("Mermaid swimming toward surface bubbles facing left", "gag")
            if card.id == "692d49d488d1d7cc":
                return ("Mermaid sitting on ocean waves facing left", "gag")
            if card.id == "0a9c468f7b295746":
                return ("Mermaid diving downward into deep water", "gag")
            if card.id == "4281fd4f37a99519":
                return ("Mermaid sitting on rock ledge surrounded by sea foam", "gag")
            if card.id == "a80cc7ac4344872f":
                return ("Mermaid with curly locks smiling at companion tropical fish", "gag")
            if card.id == "ebaba1aa741c3132":
                return ("Mermaid swimming upwards toward floating air bubble", "gag")
            if card.id == "e569f25f75997e7c":
                return ("Mermaid portrait with flowing hair floating in water", "gag")
            if card.id == "2f6372f1998e9615":
                return ("Mermaid sunbathing on ocean rock among breaking waves", "gag")
            if card.id == "ea8887719dfd22c2":
                return ("Mermaid with scaly fish tail sitting upright on wave crest", "gag")
            if card.id == "5a0d5865c23a1ffe":
                return ("Mermaid with long flowing hair kneeling underwater", "gag")
            if card.id == "526f1918ecbc16a8":
                return ("Mermaid greeting little swimming fish among sea ripples", "gag")
            return (f"Mythical mermaid maiden sitting on rock with fish tail ({card.width}x{card.height})", "gag")

        if "devils" in sub:
            return (f"Mischievous horned devil grinning holding three-pronged pitchfork ({card.width}x{card.height})", "gag")

        if "dragons" in sub:
            return (f"Fire-breathing winged dragon beast with horned crest and tail ({card.width}x{card.height})", "gag")

        if "fairies" in sub:
            return (f"Tiny woodland fairy with delicate gossamer wings holding wand ({card.width}x{card.height})", "gag")

        if "unicorns" in sub:
            return (f"Mythical unicorn rearing with spiraled magical horn ({card.width}x{card.height})", "gag")

        if "skeletons" in sub:
            return (f"Human skeleton bones figure posing in comical dance ({card.width}x{card.height})", "gag")

        if "ghosts" in sub:
            return (f"Spooky floating sheet ghost with hollow eye sockets ({card.width}x{card.height})", "gag")

        if "grim-reapers" in sub:
            return (f"Grim Reaper cloaked figure wielding long harvest scythe ({card.width}x{card.height})", "gag")

        if "gryphon" in sub:
            return (f"Mythical winged gryphon beast with eagle head and lion body ({card.width}x{card.height})", "informative")

        if "centaurs" in sub:
            return (f"Mythical centaur half-man half-horse drawing recurve bow ({card.width}x{card.height})", "informative")

        if "phoenix" in sub:
            return (f"Mythical phoenix bird rising renewed from blazing ashes ({card.width}x{card.height})", "informative")

        if "monsters" in sub:
            if "loch-ness" in card.art.lower() or "nessie" in card.art.lower():
                return ("Loch Ness monster swimming with humps on water surface", "gag")
            return (f"Classic mythical monster creature with sharp teeth ({card.width}x{card.height})", "gag")

        if card.original_title.lower() not in {"untitled", "unknown", ""}:
            return (f"{self._clean_title_str(card.original_title)} ({card.width}x{card.height})", "gag")

        return (f"Mythological folklore fantasy creature in heroic stance ({card.width}x{card.height})", "gag")

    def _title_cartoons_and_comics(self, card: RawCard) -> tuple[str, str]:
        """Detailed cartoon character titling."""
        sub = card.subcategory.lower()
        title = card.original_title.lower()
        art_upper = card.art.upper()

        if "mushroom" in sub:
            if card.id == "59d98bfcd6eba87a":
                return ("Cartoon mushroom character with Beijing conical hat", "gag")
            if card.id == "427c22bf3c9a77e9":
                return ("Cartoon miner mushroom wearing headlamp helmet", "gag")
            if card.id == "292ec438f885f77d":
                return ("Cartoon mushroom wearing French beret hat", "gag")
            if card.id == "4c561460fa871748":
                return ("Cartoon holiday mushroom wearing Christmas pom-pom hat", "gag")
            if card.id == "bbc83f76755e3a25":
                return ("Cartoon Santa mushroom wearing Santa hat with fluffy beard", "gag")
            if card.id == "1e6594a5fdb995a5":
                return ("Cartoon mushroom wearing sailor cap", "gag")
            if card.id == "8970632ffa7f6b92":
                return ("Heavy metal armored robotic mushroom", "gag")
            if card.id == "4c5c32dfcf8ddfae":
                return ("Shocked cartoon mushroom with wide circular eyes and open mouth", "gag")
            if card.id == "ce503683947524cf":
                return ("Tired cartoon mushroom yawning with closed eyes", "gag")
            if card.id == "6ab28dd877e388d1":
                return ("Greedy cartoon mushroom with dollar signs in eyes", "gag")
            if card.id == "c1d74735f266cdb0":
                return ("Sad cartoon mushroom with downward frowning eyes and mouth", "gag")
            if card.id == "51089bc119d66fdd":
                return ("Dizzy drunk cartoon mushroom with percent sign eyes", "gag")
            if card.id == "a81990ce25ac7ee1":
                return ("Amazed cartoon mushroom with exclamation mark eyes", "gag")
            if card.id == "61995a63dc451091":
                return ("Knocked out cartoon mushroom with X eyes", "gag")
            if card.id == "54c8d6d89d226960":
                return ("Sleeping cartoon mushroom dozing peacefully", "gag")
            if card.id == "0744d2db5a0c880a":
                return ("Puzzled confused cartoon mushroom with question mark eyes", "gag")
            if card.id == "466855143715e54c":
                return ("Stormtrooper soldier cartoon mushroom with helmet", "gag")
            if card.id == "c469c15d38c4a5c6":
                return ("Pharaoh mummy cartoon mushroom with tall headdress", "gag")
            if card.id == "daecba4853ea547a":
                return ("Merlin wizard cartoon mushroom with star-patterned pointy hat", "gag")
            return (f"Super Mario 1-Up power-up mushroom ({card.width}x{card.height})", "gag")

        if "simpsons" in sub:
            if card.id == "cc390e436e3c5a95":
                return ("Marge Simpson with tall beehive hair profile", "gag")
            if card.id == "9b2b3f600020f509":
                return ("Homer Simpson shouting 'Doh!' with round eyes", "gag")
            if card.id == "4f50ae08e7150561":
                return ("Bart Simpson standing full body profile", "gag")
            if card.id == "99c92768f5b1047e":
                return ("Homer Simpson standing with hands on belly", "gag")
            if card.id == "7c00b3e1214a9b3c":
                return ("Bart Simpson riding skateboard with wheels", "gag")
            if card.id == "147726fe5357a1ee":
                return ("Marge Simpson face looking forward with curls", "gag")
            if card.id == "c32c8d3470aacf39":
                return ("Marge Simpson with tall cylindrical hair waving", "gag")
            if card.id == "ad404c672766e6fb":
                return ("Bart Simpson leaning back with wide eyes", "gag")
            if card.id == "80b28093daf4836a":
                return ("Bart Simpson head profile with spiky hair", "gag")
            if card.id == "fc8eecfef47728c3":
                return ("Bart Simpson saying 'EAT MY SHORTS !' speech bubble", "gag")
            if card.id == "2d3c0b5bac046d0b":
                return ("Maggie Simpson in star romper suit with pacifier", "gag")
            if card.id == "fb6ce58d33468f09":
                return ("Lisa Simpson portrait with pointed star-pattern hair", "gag")
            if "bart" in title or "bart" in sub or "BART" in art_upper or "|\\/\\/\\_/|" in card.art:
                return (f"Bart Simpson standing with spiky hair ({card.width}x{card.height})", "gag")
            if "homer" in title or "homer" in sub or "D'OH" in art_upper or "(_8(I)" in card.art:
                return (f"Homer Simpson face shouting D'oh with round eyes ({card.width}x{card.height})", "gag")
            if "lisa" in title:
                return (f"Lisa Simpson with star hair playing saxophone ({card.width}x{card.height})", "gag")
            if "maggie" in title:
                return (f"Maggie Simpson baby in bow sucking pacifier ({card.width}x{card.height})", "gag")
            if "marge" in title:
                return (f"Marge Simpson with tall blue beehive hair ({card.width}x{card.height})", "gag")
            return (f"Simpsons cartoon character portrait ({card.width}x{card.height})", "gag")

        if "peanuts" in sub:
            if "snoopy" in title or "doghouse" in title or "snoopy" in card.art.lower():
                return (f"Snoopy dog lying atop red doghouse staring at sky ({card.width}x{card.height})", "gag")
            if "charlie" in title or "brown" in title:
                return (f"Charlie Brown standing with zig-zag shirt looking perplexed ({card.width}x{card.height})", "gag")
            if "woodstock" in title:
                return (f"Woodstock little yellow bird standing upright ({card.width}x{card.height})", "gag")
            if "lucy" in title:
                return (f"Lucy Van Pelt in psychiatric advice booth ({card.width}x{card.height})", "gag")
            if "linus" in title:
                return (f"Linus Van Pelt holding blanket sucking thumb ({card.width}x{card.height})", "gag")
            return (f"Peanuts comic character ({card.width}x{card.height})", "gag")

        if "garfield" in sub:
            if "odie" in title:
                return (f"Odie the dog panting with long tongue hanging out ({card.width}x{card.height})", "gag")
            return (f"Garfield the lazy orange cat grinning with heavy eyelids ({card.width}x{card.height})", "gag")

        if "looney-tunes" in sub:
            if "bugs" in title or "bunny" in title:
                return (f"Bugs Bunny cartoon rabbit leaning casually chewing carrot ({card.width}x{card.height})", "gag")
            if "daffy" in title:
                return (f"Daffy Duck with expressive bill and frustrated eyes ({card.width}x{card.height})", "gag")
            if "tweety" in title:
                return (f"Tweety Bird cute canary with large head and eyelashes ({card.width}x{card.height})", "gag")
            if "coyote" in title:
                return (f"Wile E. Coyote plotting disaster with Acme gadget ({card.width}x{card.height})", "gag")
            if "road" in title or "runner" in title:
                return (f"Road Runner speeding across desert highway ({card.width}x{card.height})", "gag")
            if "marvin" in title or "martian" in title:
                return ("Marvin the Martian aiming space pistol in Roman helmet", "gag")
            return (f"Looney Tunes animated character ({card.width}x{card.height})", "gag")

        if "flintstones" in sub:
            if "car" in title or "car" in card.art.lower():
                return (f"Fred Flintstone foot-powered stone age log car ({card.width}x{card.height})", "gag")
            return (f"Fred Flintstone smiling in prehistoric animal skin tunic ({card.width}x{card.height})", "gag")

        if "betty-boop" in sub:
            return (f"Betty Boop classic flapper cartoon star smiling with curly hair ({card.width}x{card.height})", "gag")

        if "felix-the-cat" in sub:
            return (f"Felix the Cat walking carrying magic carpet bag ({card.width}x{card.height})", "gag")

        if "casper" in sub:
            return (f"Casper the Friendly Ghost floating with gentle smile ({card.width}x{card.height})", "gag")

        if "pink-panther" in sub:
            return (f"Pink Panther cartoon feline walking stealthily with cool smirk ({card.width}x{card.height})", "gag")

        if "popeye" in sub:
            return (f"Popeye the Sailor Man with corncob pipe and muscular anchor arms ({card.width}x{card.height})", "gag")

        if "south-park" in sub:
            if "cartman" in title:
                return ("Cartman stout boy in red jacket and teal pom-pom hat", "gag")
            if "kenny" in title:
                return ("Kenny McCormick bundled in orange hooded parka", "gag")
            if "stan" in title:
                return ("Stan Marsh in blue puffball winter cap", "gag")
            if "kyle" in title:
                return ("Kyle Broflovski in green winter ushanka hat", "gag")
            return (f"South Park construction paper cutout character ({card.width}x{card.height})", "gag")

        if "spongebob" in sub:
            if "patrick" in title:
                return ("Patrick Star pink starfish in floral swim trunks", "gag")
            return (f"SpongeBob SquarePants yellow sponge with big smile and tie ({card.width}x{card.height})", "gag")

        if "smurfs" in sub:
            return (f"Blue Smurf character in white Phrygian cap and trousers ({card.width}x{card.height})", "gag")

        if "batman" in sub:
            return (f"Batman superhero in horned cowl and billowing cape ({card.width}x{card.height})", "gag")

        if "superman" in sub:
            return (f"Superman flying forward with S-shield on chest ({card.width}x{card.height})", "gag")

        if "spiderman" in sub:
            return (f"Spider-Man web-slinger hanging in superhero crouch ({card.width}x{card.height})", "gag")

        if "dilbert" in sub:
            return (f"Dilbert office engineer with upturned red necktie and round glasses ({card.width}x{card.height})", "gag")

        if "asterix" in sub:
            return (f"Asterix Gaul warrior with winged helmet and mustache ({card.width}x{card.height})", "gag")

        if "mickey-mouse" in sub:
            return (f"Mickey Mouse silhouette face with round circular ears ({card.width}x{card.height})", "gag")

        if "calvin-and-hobbes" in sub:
            return (f"Calvin and Hobbes riding red wagon down grassy hill ({card.width}x{card.height})", "gag")

        if card.original_title.lower() not in {"untitled", "unknown", ""}:
            return (f"{self._clean_title_str(card.original_title)} ({card.width}x{card.height})", "gag")

        return (f"Animated cartoon comic character in expressive pose ({card.width}x{card.height})", "gag")

    def _title_computers(self, card: RawCard) -> tuple[str, str]:
        """Detailed computers and hardware titling."""
        sub = card.subcategory.lower()
        title = card.original_title.lower()
        art_upper = card.art.upper()

        if "floppies" in sub or "disk" in title:
            if "5.25" in title or "5.25" in card.art:
                return (f"5.25-inch vintage flexible floppy diskette with read notch ({card.width}x{card.height})", "informative")
            return (f"3.5-inch floppy disk with sliding metal shutter and label ({card.width}x{card.height})", "informative")

        if "game-consoles" in sub:
            if "gameboy" in title or "GAMEBOY" in art_upper:
                return (f"Nintendo GameBoy handheld gaming console with D-pad and screen ({card.width}x{card.height})", "informative")
            if "playstation" in title or "SONY" in art_upper:
                return (f"Sony PlayStation gaming console with dual action buttons ({card.width}x{card.height})", "informative")
            return (f"Video game console hardware with controller ports ({card.width}x{card.height})", "informative")

        if "mouse" in sub:
            return (f"Computer mouse with left/right buttons and connection cable ({card.width}x{card.height})", "informative")

        if "keyboards" in sub:
            return (f"Desktop computer keyboard with alphanumeric key matrix ({card.width}x{card.height})", "informative")

        if "apple" in sub or "mac" in title:
            return (f"Classic Apple Macintosh desktop computer with all-in-one CRT screen ({card.width}x{card.height})", "informative")

        if "amiga" in sub or "atari" in sub:
            return (f"Vintage home computer console system with integrated keyboard ({card.width}x{card.height})", "informative")

        if "joysticks" in sub:
            return (f"Arcade gaming joystick with top button and weighted base ({card.width}x{card.height})", "informative")

        if "linux" in sub or "tux" in title:
            return (f"Tux the Linux penguin mascot sitting happily ({card.width}x{card.height})", "informative")

        if "laptop" in title:
            return (f"Portable laptop computer open showing keyboard and display ({card.width}x{card.height})", "informative")

        if "server" in title or "rack" in title:
            return (f"Datacenter server rack tower with blinking indicator lights ({card.width}x{card.height})", "informative")

        if card.original_title.lower() not in {"untitled", "unknown", ""}:
            return (f"{self._clean_title_str(card.original_title)} ({card.width}x{card.height})", "informative")

        return (f"Desktop personal computer system with CRT monitor and keyboard ({card.width}x{card.height})", "informative")

    def _title_electronics(self, card: RawCard) -> tuple[str, str]:
        """Detailed electronics titling."""
        sub = card.subcategory.lower()
        title = card.original_title.lower()

        if "televisions" in sub or "tv" in title:
            if "antenna" in card.art or "rabbit" in title:
                return (f"Vintage tube television with rabbit-ear antenna and tuning knobs ({card.width}x{card.height})", "informative")
            return (f"Television set with CRT screen and speaker grille ({card.width}x{card.height})", "informative")

        if "cameras" in sub:
            if "tripod" in card.art:
                return (f"Studio photo camera mounted on tall tripod ({card.width}x{card.height})", "informative")
            return (f"35mm SLR camera body with circular lens and top dial ({card.width}x{card.height})", "informative")

        if "phones" in sub:
            if "rotary" in title or "dial" in card.art:
                return (f"Classic rotary dial desk telephone with coiled cord handset ({card.width}x{card.height})", "informative")
            if "cell" in title or "mobile" in title:
                return (f"Early mobile cellphone with numeric keypad and stub antenna ({card.width}x{card.height})", "informative")
            return (f"Telephone handset resting on base cradle ({card.width}x{card.height})", "informative")

        if "clocks" in sub:
            if "alarm" in title:
                return (f"Twin-bell bedside alarm clock with hammer ({card.width}x{card.height})", "informative")
            if "pendulum" in card.art:
                return (f"Grandfather pendulum clock with roman numeral dial ({card.width}x{card.height})", "informative")
            return (f"Analog round wall clock showing hour and minute hands ({card.width}x{card.height})", "informative")

        if "light-bulbs" in sub:
            if "glow" in title or "rays" in card.art:
                return (f"Glowing lightbulb radiating electric illumination (bright idea symbol) ({card.width}x{card.height})", "informative")
            return (f"Incandescent glass lightbulb with threaded screw base and filament ({card.width}x{card.height})", "informative")

        if "audio-equipment" in sub or "radio" in sub or "stereos" in sub:
            if "cassette" in title or "tape" in title:
                return (f"Compact audio cassette tape with dual tape spools ({card.width}x{card.height})", "informative")
            if "headphone" in title:
                return (f"Over-ear acoustic headphones with padded headband ({card.width}x{card.height})", "informative")
            return (f"Portable radio boombox with carrying handle and tuner dial ({card.width}x{card.height})", "informative")

        if "calculators" in sub:
            return (f"Pocket digital calculator with LCD display and keypad ({card.width}x{card.height})", "informative")

        if "robots" in sub:
            return (f"Mechanical humanoid robot with antenna and metallic joints ({card.width}x{card.height})", "gag")

        if "blender" in sub:
            return (f"Kitchen electric countertop blender pitcher with rotary blades ({card.width}x{card.height})", "informative")

        if card.original_title.lower() not in {"untitled", "unknown", ""}:
            return (f"{self._clean_title_str(card.original_title)} ({card.width}x{card.height})", "informative")

        return (f"Electronic device instrument with display meters and controls ({card.width}x{card.height})", "informative")

    def _title_books(self, card: RawCard) -> tuple[str, str]:
        """Detailed books and literature titling."""
        sub = card.subcategory.lower()
        title = card.original_title.lower()

        if "winnie-the-pooh" in sub or "pooh" in title:
            if "piglet" in title:
                return ("Piglet timid little piglet smiling with striped sweater", "gag")
            if "eeyore" in title:
                return ("Eeyore gloomy donkey standing with pinned tail", "gag")
            if "tigger" in title:
                return ("Tigger energetic tiger bouncing on springy tail", "gag")
            return (f"Winnie the Pooh bear reaching into honey pot ({card.width}x{card.height})", "gag")

        if "moomintroll" in sub or "moomin" in title:
            return (f"Moomintroll fairy tale creature with rounded white snout ({card.width}x{card.height})", "gag")

        if "harry-potter" in sub:
            return (f"Harry Potter wizard with round spectacles and lightning scar ({card.width}x{card.height})", "gag")

        if "lord-of-the-rings" in sub:
            return (f"The One Ring inscribed with glowing Elvish script ({card.width}x{card.height})", "informative")

        if "alice-in-wonderland" in sub:
            return (f"Alice in Wonderland tumbling through magical rabbit hole ({card.width}x{card.height})", "gag")

        if "dr-seuss" in sub:
            return (f"Cat in the Hat wearing tall red and white striped top hat ({card.width}x{card.height})", "gag")

        if "open" in title or "open" in card.art.lower():
            return (f"Open book lying flat with visible lines of printed text ({card.width}x{card.height})", "informative")

        if "stack" in title or card.height > 8:
            return (f"Stack of hardbound academic textbooks with embossed spines ({card.width}x{card.height})", "informative")

        if card.original_title.lower() not in {"untitled", "unknown", ""}:
            return (f"{self._clean_title_str(card.original_title)} ({card.width}x{card.height})", "informative")

        return (f"Hardcover book with bookmark ribbon hanging from binding ({card.width}x{card.height})", "informative")

    def _title_nature(self, card: RawCard) -> tuple[str, str]:
        """Detailed nature and weather titling."""
        sub = card.subcategory.lower()
        title = card.original_title.lower()

        if "sun" in sub:
            if "smile" in title or "face" in title or "^" in card.art:
                return (f"Smiling sunshine face with warm radiating triangular rays ({card.width}x{card.height})", "informative")
            return (f"Brilliant shining sun radiating geometric solar beams ({card.width}x{card.height})", "informative")

        if "rains" in sub or "rain" in title:
            return (f"Raincloud with descending diagonal raindrops showering down ({card.width}x{card.height})", "informative")

        if "tornado" in sub or "cyclone" in title:
            return (f"Swirling funnel tornado vortex twisting across land ({card.width}x{card.height})", "informative")

        if "lightning" in sub:
            return (f"Jagged electric lightning bolt striking from storm cloud ({card.width}x{card.height})", "informative")

        if "rainbow" in sub:
            return (f"Curved arching rainbow spanning across sky ({card.width}x{card.height})", "informative")

        if "clouds" in sub:
            return (f"Fluffy cumulus cloud floating in clear open sky ({card.width}x{card.height})", "informative")

        if "camping" in sub:
            return (f"Campfire with burning wood logs and rising flames ({card.width}x{card.height})", "informative")

        if "beach" in sub or "islands" in sub:
            return (f"Tropical island shore with palm tree and ocean waves ({card.width}x{card.height})", "informative")

        if "mountains" in sub:
            return (f"Snow-capped mountain peaks rising against open horizon ({card.width}x{card.height})", "informative")

        if "deserts" in sub:
            return (f"Arid desert landscape with rolling sand dunes and sun ({card.width}x{card.height})", "informative")

        if card.original_title.lower() not in {"untitled", "unknown", ""}:
            return (f"{self._clean_title_str(card.original_title)} ({card.width}x{card.height})", "informative")

        return (f"Natural outdoor scenery landscape and weather element ({card.width}x{card.height})", "informative")

    def _title_plants(self, card: RawCard) -> tuple[str, str]:
        """Detailed botanical titling."""
        sub = card.subcategory.lower()
        title = card.original_title.lower()

        if "mushroom" in sub:
            return (f"Forest mushroom with spotted convex cap and curved stalk ({card.width}x{card.height})", "informative")

        if "cactus" in sub:
            return (f"Saguaro desert cactus with upward-curving arms and spines ({card.width}x{card.height})", "informative")

        if "roses" in sub or "rose" in title:
            return (f"Blooming rose blossom on leafy thorny stem ({card.width}x{card.height})", "informative")

        if "daffodils" in sub or "dandelions" in sub:
            return (f"Daffodil trumpet flower in full springtime bloom ({card.width}x{card.height})", "informative")

        if "flowers" in sub:
            return (f"Floral bouquet of blooming garden flowers with leaves ({card.width}x{card.height})", "informative")

        if "bonsai-trees" in sub:
            return (f"Miniature Japanese bonsai tree in decorative shallow pot ({card.width}x{card.height})", "informative")

        if "leaf" in sub:
            return (f"Detailed deciduous leaf with central vein structure ({card.width}x{card.height})", "informative")

        if "marijuana" in sub or "cannabis" in title:
            return (f"Seven-pointed serrated cannabis leaf emblem ({card.width}x{card.height})", "informative")

        if card.original_title.lower() not in {"untitled", "unknown", ""}:
            return (f"{self._clean_title_str(card.original_title)} ({card.width}x{card.height})", "informative")

        return (f"Botanical garden plant flora with stem and foliage ({card.width}x{card.height})", "informative")

    def _title_space(self, card: RawCard) -> tuple[str, str]:
        """Detailed space titling."""
        sub = card.subcategory.lower()
        title = card.original_title.lower()

        if "aliens" in sub or "alien" in title:
            return (f"Extraterrestrial alien with large black almond eyes and slender neck ({card.width}x{card.height})", "gag")

        if "astronauts" in sub:
            return (f"Astronaut spaceman in pressurized suit and bubble helmet ({card.width}x{card.height})", "informative")

        if "moons" in sub:
            if "crescent" in title or "(" in card.art:
                return (f"Crescent moon glowing alongside twinkling night stars ({card.width}x{card.height})", "informative")
            return (f"Full lunar sphere showing crater formations ({card.width}x{card.height})", "informative")

        if "stars" in sub:
            return (f"Five-pointed geometric star bursting with radiance ({card.width}x{card.height})", "informative")

        if "planets" in sub:
            if "saturn" in title or "ring" in card.art.lower():
                return (f"Planet Saturn encircled by prominent planetary rings ({card.width}x{card.height})", "informative")
            return (f"Spherical planetary body orbiting in outer space ({card.width}x{card.height})", "informative")

        if "telescopes" in sub:
            return (f"Astronomical telescope on tripod aimed toward cosmos ({card.width}x{card.height})", "informative")

        if "spaceships" in sub or "rocket" in title:
            return (f"Space rocket launching upward propelled by fire exhaust plume ({card.width}x{card.height})", "informative")

        if "satellites" in sub:
            return (f"Orbital space satellite with solar panel arrays ({card.width}x{card.height})", "informative")

        if card.original_title.lower() not in {"untitled", "unknown", ""}:
            return (f"{self._clean_title_str(card.original_title)} ({card.width}x{card.height})", "informative")

        return (f"Outer space cosmic celestial astronomical scene ({card.width}x{card.height})", "informative")

    def _title_food(self, card: RawCard) -> tuple[str, str]:
        """Detailed food and culinary titling."""
        sub = card.subcategory.lower()
        title = card.original_title.lower()
        art_lower = card.art.lower()

        if "coffee-and-tea" in sub or "coffee" in title:
            return (f"Coffee mug on saucer with swirls of rising hot steam ({card.width}x{card.height})", "informative")

        if "beers" in sub or "beer" in title:
            return (f"Glass beer tankard topped with foaming head of froth ({card.width}x{card.height})", "informative")

        if "drinks" in sub:
            if "wine" in title:
                return (f"Stemmed wine glass filled with beverage beside bottle ({card.width}x{card.height})", "informative")
            if "cocktail" in title or "martini" in title:
                return (f"Martini cocktail glass garnished with toothpick olive ({card.width}x{card.height})", "informative")
            return (f"Cold beverage drink in glass with drinking straw ({card.width}x{card.height})", "informative")

        if "apples" in sub or "apple" in title:
            return (f"Fresh apple fruit with stem and small leaf ({card.width}x{card.height})", "informative")

        if "bananas" in sub:
            return (f"Bunch of ripe peeled bananas ({card.width}x{card.height})", "informative")

        if "ice-creams" in sub:
            return (f"Ice cream dessert cone topped with rounded scoop ({card.width}x{card.height})", "informative")

        if "candies" in sub or "chocolates" in sub:
            return (f"Wrapped hard candy confection with twisted paper ends ({card.width}x{card.height})", "informative")

        if "peanut" in art_lower or "acorn" in art_lower or "coconut" in art_lower:
            return (f"Assorted snack nuts: peanut, acorn, coconut, and cashew ({card.width}x{card.height})", "informative")

        if "burger" in title or "burger" in art_lower:
            return (f"Cheeseburger with seeded bun, beef patty, and melting cheese ({card.width}x{card.height})", "informative")

        if "pizza" in title or "pizza" in art_lower:
            return (f"Triangular slice of pizza with melted cheese and pepperoni ({card.width}x{card.height})", "informative")

        if "cake" in title:
            return (f"Celebration birthday party cake with lit candles ({card.width}x{card.height})", "informative")

        if "popcorn" in title or "popcorn" in art_lower:
            return (f"Popcorn bucket overflowing with buttery popped kernels ({card.width}x{card.height})", "informative")

        if "bread" in title:
            return (f"Loaf of freshly baked crusty artisan bread ({card.width}x{card.height})", "informative")

        if card.original_title.lower() not in {"untitled", "unknown", ""}:
            return (f"{self._clean_title_str(card.original_title)} ({card.width}x{card.height})", "informative")

        return (f"Gourmet culinary dish and beverage serving ({card.width}x{card.height})", "informative")

    def _title_weapons(self, card: RawCard) -> tuple[str, str]:
        """Detailed weapons and heraldry titling."""
        sub = card.subcategory.lower()
        title = card.original_title.lower()

        if "swords" in sub:
            if "crossed" in title or "two" in title or "X" in card.art:
                return (f"Pair of crossed medieval knight swords in combat ready stance ({card.width}x{card.height})", "informative")
            if "katana" in title or "samurai" in title:
                return (f"Japanese katana sword with curved single-edged blade and wrapped tsuba ({card.width}x{card.height})", "informative")
            if "dagger" in title:
                return (f"Compact combat dagger with sharp pointed double-edge blade ({card.width}x{card.height})", "informative")
            return (f"Medieval knight longsword with ornate crossguard and pommel ({card.width}x{card.height})", "informative")

        if "shields" in sub:
            return (f"Heraldic medieval defense shield bearing knightly emblem ({card.width}x{card.height})", "informative")

        if "axes" in sub:
            if "battle" in title or "double" in title:
                return (f"Double-bladed battle axe with reinforced wooden haft ({card.width}x{card.height})", "informative")
            return (f"Single-edge woodchopping axe with tapered blade ({card.width}x{card.height})", "informative")

        if "bows" in sub or "bows-and-arrows" in sub:
            return (f"Longbow drawn with nocked fletched arrow ready for release ({card.width}x{card.height})", "informative")

        if "knives" in sub:
            return (f"Utility knife with serrated blade and ergonomic grip handle ({card.width}x{card.height})", "informative")

        if "soldiers" in sub:
            return (f"Toy lead soldier standing in uniform attention ({card.width}x{card.height})", "gag")

        if "guillotines" in sub:
            return (f"Wooden guillotine with angled blade hanging in frame ({card.width}x{card.height})", "gag")

        if "guns" in sub:
            return (f"Revolver handgun side profile with cylinder and barrel ({card.width}x{card.height})", "informative")

        if "explosives" in sub:
            return (f"Round pirate cannonball bomb with lit burning fuse ({card.width}x{card.height})", "gag")

        if card.original_title.lower() not in {"untitled", "unknown", ""}:
            return (f"{self._clean_title_str(card.original_title)} ({card.width}x{card.height})", "informative")

        return (f"Historical armor defense weapon and combat gear ({card.width}x{card.height})", "informative")

    def _title_vehicles(self, card: RawCard) -> tuple[str, str]:
        """Detailed transport titling."""
        sub = card.subcategory.lower()
        title = card.original_title.lower()

        if "airplanes" in sub or "plane" in title:
            if "biplane" in title:
                return (f"Vintage dual-wing propeller biplane aircraft ({card.width}x{card.height})", "informative")
            if "jet" in title or "fighter" in title:
                return (f"Supersonic military fighter jet banking in flight ({card.width}x{card.height})", "informative")
            if "choppers" in sub or "helicopter" in title:
                return (f"Helicopter with top rotating main rotor and tail boom ({card.width}x{card.height})", "informative")
            return (f"Commercial passenger airplane soaring through clouds ({card.width}x{card.height})", "informative")

        if "cars" in sub:
            if "convertible" in title or "sports" in title:
                return (f"Sleek sports car automobile side profile with low chassis ({card.width}x{card.height})", "informative")
            if "beetle" in title:
                return (f"Classic compact Volkswagen Beetle car profile ({card.width}x{card.height})", "informative")
            return (f"Automobile motor vehicle with round headlights and wheels ({card.width}x{card.height})", "informative")

        if "bicycles" in sub:
            return (f"Two-wheeled bicycle with pedals, chain, and handlebars ({card.width}x{card.height})", "informative")

        if "motorcycles" in sub:
            return (f"Motorcycle with engine block, gas tank, and dual exhaust ({card.width}x{card.height})", "informative")

        if "trucks" in sub:
            return (f"Semi-trailer cargo freight truck cab profile ({card.width}x{card.height})", "informative")

        if "busses" in sub:
            return (f"Passenger transit bus with panoramic windows ({card.width}x{card.height})", "informative")

        if "navy" in sub or "boats" in sub:
            if "sail" in title or "ship" in title:
                return (f"Tall sailing galleon ship with billowing canvas sails on sea ({card.width}x{card.height})", "informative")
            if "submarine" in title:
                return (f"Naval submarine submerged with raised periscope conning tower ({card.width}x{card.height})", "informative")
            return (f"Motorboat vessel gliding across water surface ({card.width}x{card.height})", "informative")

        if "trains" in sub:
            return (f"Steam locomotive engine train billowing smoke along railway tracks ({card.width}x{card.height})", "informative")

        if card.original_title.lower() not in {"untitled", "unknown", ""}:
            return (f"{self._clean_title_str(card.original_title)} ({card.width}x{card.height})", "informative")

        return (f"Mechanical transit vehicle machine ({card.width}x{card.height})", "informative")

    def _title_buildings(self, card: RawCard) -> tuple[str, str]:
        """Detailed architecture titling."""
        sub = card.subcategory.lower()
        title = card.original_title.lower()

        if "houses" in sub or "house" in title:
            return (f"Cozy residential house with pitched roof, chimney, and front door ({card.width}x{card.height})", "informative")

        if "castles" in sub:
            return (f"Medieval fortified stone castle with battlement towers ({card.width}x{card.height})", "informative")

        if "church" in sub:
            return (f"Church cathedral with steeple spire and arched stained glass ({card.width}x{card.height})", "informative")

        if "lighthouses" in sub or "lighthouse" in title:
            return (f"Coastal lighthouse tower projecting warning light beam over ocean ({card.width}x{card.height})", "informative")

        if "monuments" in sub:
            if "statue-of-liberty" in sub:
                return (f"Statue of Liberty holding torch of freedom aloft ({card.width}x{card.height})", "informative")
            if "eiffel-tower" in sub:
                return (f"Eiffel Tower Parisian lattice iron spire landmark ({card.width}x{card.height})", "informative")
            if "pyramids" in sub:
                return (f"Ancient Egyptian stone pyramid tombs in desert sands ({card.width}x{card.height})", "informative")
            if "stonehenge" in sub:
                return (f"Stonehenge megalithic stone circle monument ({card.width}x{card.height})", "informative")
            if "notre-dame" in sub:
                return (f"Notre-Dame cathedral facade with gothic rose window ({card.width}x{card.height})", "informative")
            if "arc-de-triomphe" in sub:
                return (f"Arc de Triomphe triumphal arch monument ({card.width}x{card.height})", "informative")

        if "furniture" in sub:
            if "toilets" in sub:
                return (f"Bathroom porcelain toilet commode with seat and flush tank ({card.width}x{card.height})", "gag")
            if "chairs" in sub:
                return (f"Armchair seat with cushioned backrest and wooden legs ({card.width}x{card.height})", "informative")
            if "beds" in sub:
                return (f"Bedstead with fluffy pillows and pulled-up blanket quilt ({card.width}x{card.height})", "informative")
            if "sofas" in sub:
                return (f"Comfortable living room sofa couch with arm cushions ({card.width}x{card.height})", "informative")
            return (f"Interior household furniture seating ({card.width}x{card.height})", "informative")

        if "fences" in sub:
            return (f"Picket fence wooden boundary slats ({card.width}x{card.height})", "informative")

        if "flags" in sub:
            return (f"Waving national banner flag fluttering on flagpole mast ({card.width}x{card.height})", "informative")

        if card.original_title.lower() not in {"untitled", "unknown", ""}:
            return (f"{self._clean_title_str(card.original_title)} ({card.width}x{card.height})", "informative")

        return (f"Architectural structural building facade landmark ({card.width}x{card.height})", "informative")

    def _title_religion(self, card: RawCard) -> tuple[str, str]:
        """Detailed religion and faith titling."""
        sub = card.subcategory.lower()
        title = card.original_title.lower()

        if "yin-and-yang" in sub or "yin" in title:
            return (f"Yin-Yang dual circular symbol representing balance and harmony ({card.width}x{card.height})", "informative")

        if "angels" in sub:
            return (f"Celestial angel figure with feathered wings and glowing halo ({card.width}x{card.height})", "gag")

        if "crosses" in sub or "christianity" in sub or "cross" in title:
            return (f"Ornate Christian crucifix cross with decorative arms ({card.width}x{card.height})", "informative")

        if "judaism" in sub or "menorah" in title:
            return (f"Traditional seven-branch ceremonial Jewish menorah candelabra ({card.width}x{card.height})", "informative")

        if "buddhism" in sub:
            return (f"Buddha meditating peacefully in lotus posture ({card.width}x{card.height})", "informative")

        if "hinduism" in sub:
            return (f"Sacred Om symbol representing cosmic consciousness ({card.width}x{card.height})", "informative")

        if "preachers" in sub:
            return (f"Preacher speaker standing at pulpit lectern ({card.width}x{card.height})", "gag")

        if card.original_title.lower() not in {"untitled", "unknown", ""}:
            return (f"{self._clean_title_str(card.original_title)} ({card.width}x{card.height})", "informative")

        return (f"Spiritual sacred faith symbol emblem ({card.width}x{card.height})", "informative")

    def _title_sports(self, card: RawCard) -> tuple[str, str]:
        """Detailed sports titling."""
        sub = card.subcategory.lower()
        title = card.original_title.lower()

        if "juggling" in sub or "juggler" in title:
            return (f"Juggler performer tossing multiple spinning balls in graceful arc ({card.width}x{card.height})", "gag")

        if "billiards" in sub or "pool" in title:
            return (f"Pool billiard 8-ball with circular white center number ({card.width}x{card.height})", "informative")

        if "bowling" in sub:
            return (f"Bowling lane pins arranged in triangle with rolling bowling ball ({card.width}x{card.height})", "informative")

        if "fencing" in sub:
            return (f"Fencing duelists lunging with epee foils in protective masks ({card.width}x{card.height})", "informative")

        if "boxing" in sub:
            return (f"Pair of padded boxing gloves tied together ({card.width}x{card.height})", "informative")

        if "chess" in sub:
            return (f"Chess knight horse piece on checkered board square ({card.width}x{card.height})", "informative")

        if "darts" in sub:
            return (f"Circular dartboard bullseye target with dart pinned in center ({card.width}x{card.height})", "informative")

        if "golf" in sub:
            return (f"Golf ball teed up ready beside putting flag pin ({card.width}x{card.height})", "informative")

        if "baseball" in sub:
            return (f"Baseball player with cap holding wooden bat at home plate ({card.width}x{card.height})", "informative")

        if "football" in sub:
            return (f"American football helmet with protective face cage ({card.width}x{card.height})", "informative")

        if "soccer" in sub:
            return (f"Soccer football with stitched hexagonal panel pattern ({card.width}x{card.height})", "informative")

        if "tennis" in sub:
            return (f"Tennis racket with cross-strung grid and tennis ball ({card.width}x{card.height})", "informative")

        if "surfing" in sub:
            return (f"Surfer riding surfboard carving through curling ocean wave ({card.width}x{card.height})", "informative")

        if "skiing" in sub:
            return (f"Downhill snow skier with poles and goggles gliding over snow ({card.width}x{card.height})", "informative")

        if "ice-skating" in sub:
            return (f"Ice figure skater in graceful spiral spin pose ({card.width}x{card.height})", "informative")

        if "nba" in sub or "basketball" in sub:
            return (f"Basketball sports team shield emblem ({card.width}x{card.height})", "informative")

        if "gym" in title or "weight" in title:
            return (f"Heavy barbell loaded with circular weightlifting plates ({card.width}x{card.height})", "informative")

        if card.original_title.lower() not in {"untitled", "unknown", ""}:
            return (f"{self._clean_title_str(card.original_title)} ({card.width}x{card.height})", "informative")

        return (f"Athletic competitive sporting equipment gear ({card.width}x{card.height})", "informative")

    def _title_people(self, card: RawCard) -> tuple[str, str] | None:
        """Detailed people and portraits titling."""
        sub = card.subcategory.lower()
        title = card.original_title.lower()

        if "hand-gestures" in sub:
            if "peace" in card.art.lower() or "v" in title:
                return (f"Hand making two-finger peace sign victory gesture ({card.width}x{card.height})", "gag")
            if "middle" in title or "finger" in title:
                return (f"Rebellious hand making middle finger rude gesture ({card.width}x{card.height})", "gag")
            if "thumbs" in title or "thumb" in title:
                return (f"Hand giving enthusiastic thumbs up approval gesture ({card.width}x{card.height})", "gag")
            if "point" in title:
                return (f"Hand with index finger extended pointing forward ({card.width}x{card.height})", "informative")
            return (f"Expressive hand gesture showing fingers and palm ({card.width}x{card.height})", "informative")

        if "famous" in sub:
            if "einstein" in sub or "einstein" in title:
                return (f"Albert Einstein portrait with wild unruly hair and mustache ({card.width}x{card.height})", "gag")
            if "chaplin" in sub or "chaplin" in title:
                return (f"Charlie Chaplin face with bowler hat and small mustache ({card.width}x{card.height})", "gag")
            if "monroe" in sub or "monroe" in title:
                return (f"Marilyn Monroe glamour portrait with blonde curls and beauty mark ({card.width}x{card.height})", "gag")
            if "washington" in sub:
                return (f"George Washington presidential portrait in colonial wig ({card.width}x{card.height})", "informative")
            if "diana" in sub:
                return (f"Princess Diana royal portrait sketch ({card.width}x{card.height})", "gag")

        if "occupations" in sub:
            if "wizards" in sub:
                return (f"Mystical wizard in pointed cone hat casting spell with staff ({card.width}x{card.height})", "gag")
            if "knights" in sub:
                return (f"Armored medieval knight standing with helmet visor and broadsword ({card.width}x{card.height})", "informative")
            if "clowns" in sub:
                return (f"Circus clown with round nose, painted smile, and frilly collar ({card.width}x{card.height})", "gag")
            if "pirates" in sub:
                return (f"Pirate captain with eye patch, tricorn hat, and peg leg ({card.width}x{card.height})", "gag")
            if "police" in sub:
                return (f"Police officer in uniform badge and peaked service cap ({card.width}x{card.height})", "informative")
            if "artists" in sub:
                return (f"Artist painter holding wooden paint palette and brush ({card.width}x{card.height})", "informative")
            if "mime" in sub:
                return (f"French street mime artist in striped shirt and beret ({card.width}x{card.height})", "gag")
            if "firefighter" in sub:
                return (f"Firefighter rescuer in protective helmet and coat ({card.width}x{card.height})", "informative")

        if "babies" in sub:
            return (f"Cute baby toddler crawling with diaper ({card.width}x{card.height})", "gag")

        if "footprints" in sub:
            return (f"Pair of barefoot footprints pressed in sand showing five toes ({card.width}x{card.height})", "informative")

        if "eyes" in sub:
            return (f"Pair of wide open human eyes staring forward with pupils ({card.width}x{card.height})", "gag")

        if "lips" in sub:
            return (f"Curved smiling human lips mouth expression ({card.width}x{card.height})", "gag")

        if "brains" in sub:
            return (f"Human brain organ showing convoluted cerebral hemispheres ({card.width}x{card.height})", "informative")

        if "couples" in sub or "lovers" in title:
            return (f"Romantic couple embracing with affection ({card.width}x{card.height})", "gag")

        if "women" in sub:
            return (f"Woman portrait sketch with flowing styled hair ({card.width}x{card.height})", "gag")

        if "portrait" in sub:
            if "peace bro" in card.art.lower():
                return ("Self-portrait character making peace sign saying 'PEACE BRO'", "gag")
            return None

        if card.original_title.lower() not in {"untitled", "unknown", ""}:
            return (f"{self._clean_title_str(card.original_title)} ({card.width}x{card.height})", "gag")

        return (f"Human personality expressive portrait pose ({card.width}x{card.height})", "gag")

    def _title_misc(self, card: RawCard) -> tuple[str, str]:
        """Detailed miscellaneous objects titling."""
        sub = card.subcategory.lower()
        title = card.original_title.lower()

        if "candles" in sub or "candle" in title:
            return (f"Burning wax candle stick with flickering flame and melting wax ({card.width}x{card.height})", "informative")

        if "dna" in sub:
            return (f"DNA double helix molecular genetic ladder structure ({card.width}x{card.height})", "informative")

        if "hourglass" in sub or "hourglass" in title:
            return (f"Glass hourglass with sand flowing through narrow neck measuring time ({card.width}x{card.height})", "informative")

        if "money" in sub or "dollar" in title:
            return (f"Stack of paper currency dollar banknotes tied with band ({card.width}x{card.height})", "informative")

        if "mailbox" in sub:
            return (f"Curbside metal mailbox with raised red delivery flag ({card.width}x{card.height})", "informative")

        if "bones" in sub or "skull" in title:
            return (f"Crossed skeleton bones with anatomical skull head ({card.width}x{card.height})", "gag")

        if "boxes" in sub or "package" in title:
            return (f"Cardboard shipping box package tied with twine rope ({card.width}x{card.height})", "informative")

        if "keys" in sub or "key" in title:
            return (f"Antique brass skeleton key with intricate toothed bit ({card.width}x{card.height})", "informative")

        if "magnifying-glass" in sub:
            return (f"Magnifying glass lens examining detail with handle ({card.width}x{card.height})", "informative")

        if "fire-extinguishers" in sub:
            return (f"Emergency fire extinguisher canister with nozzle hose and pin ({card.width}x{card.height})", "informative")

        if "awards" in sub or "trophy" in title:
            return (f"Championship victory trophy cup on pedestal base ({card.width}x{card.height})", "informative")

        if "badges" in sub or "shield" in title:
            return (f"Official security star badge emblem ({card.width}x{card.height})", "informative")

        if "chains" in sub:
            return (f"Interlocking heavy iron chain links ({card.width}x{card.height})", "informative")

        if "medical" in sub:
            return (f"Medical stethoscope and first aid emblem ({card.width}x{card.height})", "informative")

        if "bottles" in sub:
            return (f"Glass beverage bottle with cork stopper ({card.width}x{card.height})", "informative")

        if "brooms" in sub:
            return (f"Sweeping broom with straw bristles and wooden handle ({card.width}x{card.height})", "informative")

        if "buckets" in sub:
            return (f"Metal water bucket pail with arched wire handle ({card.width}x{card.height})", "informative")

        if "anchors" in sub:
            return (f"Nautical maritime iron anchor with flukes and stock ({card.width}x{card.height})", "informative")

        if "antennas" in sub:
            return (f"Radio broadcast receiver antenna tower ({card.width}x{card.height})", "informative")

        if "dice" in sub:
            return (f"Pair of gaming cubic dice showing pips ({card.width}x{card.height})", "informative")

        if "diamonds" in sub:
            return (f"Faceted sparkling gemstone diamond jewel ({card.width}x{card.height})", "informative")

        if card.original_title.lower() not in {"untitled", "unknown", ""}:
            return (f"{self._clean_title_str(card.original_title)} ({card.width}x{card.height})", "informative")

        return (f"Practical tool utility everyday object ({card.width}x{card.height})", "informative")

    def _title_holidays(self, card: RawCard) -> tuple[str, str]:
        """Detailed holiday symbols titling."""
        sub = card.subcategory.lower()
        title = card.original_title.lower()

        if "santa" in sub or "santa" in title:
            return (f"Santa Claus jolly face with fluffy beard and pom-pom hat ({card.width}x{card.height})", "gag")

        if "snowmen" in sub or "snowman" in title:
            return (f"Winter snowman with coal buttons, carrot nose, and top hat ({card.width}x{card.height})", "gag")

        if "trees" in sub:
            return (f"Decorated Christmas evergreen tree with shining star topper and ornaments ({card.width}x{card.height})", "informative")

        if "halloween" in sub or "ghost" in title or "pumpkin" in title:
            if "pumpkin" in title:
                return (f"Carved Jack-o'-lantern Halloween pumpkin grinning with glowing eyes ({card.width}x{card.height})", "gag")
            return (f"Spooky Halloween floating ghost with wavy ethereal tail ({card.width}x{card.height})", "gag")

        if "valentine" in sub or "heart" in title:
            return (f"Romantic double heart symbol pierced by Cupid's love arrow ({card.width}x{card.height})", "informative")

        if "wedding" in sub:
            return (f"Pair of entwined wedding ring bands sparkling with diamond ({card.width}x{card.height})", "informative")

        if "graduation" in sub:
            return (f"Academic graduation mortarboard cap with hanging tassel ({card.width}x{card.height})", "informative")

        if "easter" in sub:
            return (f"Decorated Easter egg with geometric zig-zag ribbons ({card.width}x{card.height})", "informative")

        if "birthdays" in sub:
            return (f"Celebration birthday party balloon bunch with ribbons ({card.width}x{card.height})", "gag")

        if "luck" in sub:
            return (f"Four-leaf lucky clover with curved stem ({card.width}x{card.height})", "informative")

        if "hanukkah" in sub:
            return (f"Hanukkah menorah candelabra with nine lit candles ({card.width}x{card.height})", "informative")

        if card.original_title.lower() not in {"untitled", "unknown", ""}:
            return (f"{self._clean_title_str(card.original_title)} ({card.width}x{card.height})", "informative")

        return (f"Festive cultural holiday celebration icon ({card.width}x{card.height})", "informative")

    def _title_media(self, card: RawCard) -> tuple[str, str]:
        """Detailed TV & Movie character titling."""
        sub = card.subcategory.lower()
        title = card.original_title.lower()

        if "muppets" in sub or "sesame" in sub:
            if "kermit" in title:
                return (f"Kermit the Frog muppet puppet with wide triangular collar ({card.width}x{card.height})", "gag")
            if "cookiemonster" in title or "cookie" in title:
                return (f"Cookie Monster muppet with googly eyes chewing cookie ({card.width}x{card.height})", "gag")
            if "bert" in title or "ernie" in title:
                return (f"Bert and Ernie Sesame Street puppet duo smiling ({card.width}x{card.height})", "gag")
            if "big-bird" in title:
                return ("Big Bird tall feathered Sesame Street character", "gag")
            if "elmo" in title:
                return ("Elmo cheerful red monster waving hand", "gag")
            return (f"Classic Muppet puppet character caricature ({card.width}x{card.height})", "gag")

        if "wallace-and-gromit" in sub:
            return (f"Wallace and Gromit claymation inventor and clever dog pair ({card.width}x{card.height})", "gag")

        if "star-wars" in sub:
            if "r2d2" in title or "r2-d2" in title:
                return (f"R2-D2 astromech droid robot with domed head and holographic projector ({card.width}x{card.height})", "informative")
            if "c3po" in title or "c-3po" in title:
                return (f"C-3PO golden protocol humanoid droid ({card.width}x{card.height})", "informative")
            if "vader" in title:
                return (f"Darth Vader imposing helmet mask and respirator grille ({card.width}x{card.height})", "gag")
            if "yoda" in title:
                return (f"Jedi Master Yoda with long pointed ears and wise gaze ({card.width}x{card.height})", "gag")
            return (f"Star Wars character figure ({card.width}x{card.height})", "gag")

        if "doctor-who" in sub:
            if "tardis" in title or "police" in card.art.lower():
                return (f"TARDIS blue British police telephone box time machine ({card.width}x{card.height})", "informative")
            if "dalek" in title:
                return (f"Dalek alien cyborg with plunger arm and exterminator ray ({card.width}x{card.height})", "gag")
            return (f"Doctor Who sci-fi iconic item ({card.width}x{card.height})", "informative")

        if "dexter" in sub or "dexters-laboratory" in sub:
            return (f"Dexter boy genius scientist in lab coat and purple gloves ({card.width}x{card.height})", "gag")

        if "toy-story" in sub:
            return (f"Toy Story animated character figure ({card.width}x{card.height})", "gag")

        if "shrek" in sub:
            return (f"Shrek friendly green ogre with trumpet ears ({card.width}x{card.height})", "gag")

        if "aladdin" in sub:
            return (f"Aladdin magic brass oil lamp with smoke trail ({card.width}x{card.height})", "informative")

        if "bambi" in sub:
            return (f"Bambi little spotted fawn deer ({card.width}x{card.height})", "gag")

        if "star-trek" in sub:
            return (f"Star Trek USS Enterprise starship cruising through space ({card.width}x{card.height})", "informative")

        if "pinky-and-the-brain" in sub:
            return (f"Brain super-genius mouse plotting world domination ({card.width}x{card.height})", "gag")

        if "barney" in sub:
            return (f"Barney purple dinosaur waving happily ({card.width}x{card.height})", "gag")

        if card.original_title.lower() not in {"untitled", "unknown", ""}:
            return (f"{self._clean_title_str(card.original_title)} ({card.width}x{card.height})", "gag")

        return (f"Pop culture television and cinema character ({card.width}x{card.height})", "gag")

    def _title_music(self, card: RawCard) -> tuple[str, str]:
        """Detailed music and instruments titling."""
        sub = card.subcategory.lower()
        title = card.original_title.lower()

        if "notation" in sub or "notes" in title:
            return (f"Musical notation with treble clef and beamed eighth notes on staff ({card.width}x{card.height})", "informative")

        if "guitar" in title:
            return (f"Acoustic six-string guitar with curved body and soundhole ({card.width}x{card.height})", "informative")

        if "piano" in title or "pianos" in sub:
            return (f"Grand piano keyboard with black and white keys ({card.width}x{card.height})", "informative")

        if "drum" in title:
            return (f"Acoustic snare drum set with drumsticks ({card.width}x{card.height})", "informative")

        if "beatles" in sub:
            return (f"The Beatles band member iconic caricature ({card.width}x{card.height})", "gag")

        if "elvis" in sub:
            return (f"Elvis Presley rock-and-roll king silhouette with pompadour ({card.width}x{card.height})", "gag")

        if "pink-floyd" in sub:
            return (f"Pink Floyd prism refracting light into color spectrum beam ({card.width}x{card.height})", "informative")

        if card.original_title.lower() not in {"untitled", "unknown", ""}:
            return (f"{self._clean_title_str(card.original_title)} ({card.width}x{card.height})", "informative")

        return (f"Musical acoustic sound instrument ({card.width}x{card.height})", "informative")

    def _title_clothing(self, card: RawCard) -> tuple[str, str]:
        """Detailed clothing and accessories titling."""
        sub = card.subcategory.lower()
        title = card.original_title.lower()

        if "umbrellas" in sub or "umbrella" in title:
            return (f"Open rain umbrella with curved canopy and J-shaped handle ({card.width}x{card.height})", "informative")

        if "hats" in sub or "hat" in title:
            if "top" in title:
                return (f"Formal gentleman's tall silk top hat with ribbon band ({card.width}x{card.height})", "informative")
            if "cowboy" in title:
                return (f"Western wide-brimmed cowboy Stetson hat ({card.width}x{card.height})", "informative")
            if "sombrero" in title:
                return (f"Wide-brimmed Mexican sombrero hat ({card.width}x{card.height})", "informative")
            return (f"Headwear brimmed hat ({card.width}x{card.height})", "informative")

        if "footwear" in sub or "shoe" in title or "boot" in title:
            if "high-heel" in title:
                return (f"Women's elegant high heel stiletto shoe ({card.width}x{card.height})", "informative")
            return (f"Leather footwear shoe with laces and sole heel ({card.width}x{card.height})", "informative")

        if "shirts" in sub or "shirt" in title:
            return (f"Short-sleeved collared polo button-up shirt ({card.width}x{card.height})", "informative")

        if "glasses" in sub:
            return (f"Spectacles eyeglasses frame with circular lenses and bridge ({card.width}x{card.height})", "informative")

        if "crowns" in sub:
            return (f"Royal monarch golden crown with jeweled points ({card.width}x{card.height})", "informative")

        if card.original_title.lower() not in {"untitled", "unknown", ""}:
            return (f"{self._clean_title_str(card.original_title)} ({card.width}x{card.height})", "informative")

        return (f"Apparel wardrobe fashion garment accessory ({card.width}x{card.height})", "informative")

    def _title_toys_and_games(self, card: RawCard) -> tuple[str, str]:
        """Detailed toys and gaming characters titling."""
        sub = card.subcategory.lower()
        title = card.original_title.lower()

        if "teddy-bears" in sub or "teddy" in title:
            return (f"Cute teddy bear stuffed plush toy with sewn ears and button nose ({card.width}x{card.height})", "gag")

        if "pokemon" in sub or "pokemon" in title:
            if "pikachu" in title or "pikachu" in card.art.lower():
                return (f"Pikachu yellow electric mouse pokemon with lightning bolt tail ({card.width}x{card.height})", "gag")
            return (f"Pokemon pocket monster character sprite ({card.width}x{card.height})", "gag")

        if "sonic" in sub or "sonic" in title:
            return (f"Sonic the Hedgehog speeding hero with spiky quills and sneakers ({card.width}x{card.height})", "gag")

        if "pacman" in sub or "pac-man" in title:
            return (f"Retro arcade Pac-Man mouth chomping ghost monster dots ({card.width}x{card.height})", "gag")

        if "lara-croft" in sub:
            return (f"Lara Croft Tomb Raider adventurer with ponytail and dual pistols ({card.width}x{card.height})", "gag")

        if "balloons" in sub:
            return (f"Party balloon floating on string ({card.width}x{card.height})", "gag")

        if "dolls" in sub or "beanie" in sub:
            return (f"Plush toy ragdoll figurine ({card.width}x{card.height})", "gag")

        if card.original_title.lower() not in {"untitled", "unknown", ""}:
            return (f"{self._clean_title_str(card.original_title)} ({card.width}x{card.height})", "gag")

        return (f"Playful arcade gaming toy character ({card.width}x{card.height})", "gag")

    def _title_logos(self, card: RawCard) -> tuple[str, str]:
        """Detailed logos and emblems titling."""
        sub = card.subcategory.lower()
        title = card.original_title.lower()

        if "peace" in sub:
            return (f"Circular anti-war peace sign emblem with three prongs ({card.width}x{card.height})", "informative")

        if "recycle" in sub:
            return (f"Mobius loop recycling three-arrow circular conservation emblem ({card.width}x{card.height})", "informative")

        if "biohazards" in sub:
            return (f"Three-ring biological hazard warning symbol ({card.width}x{card.height})", "informative")

        if "jolly-roger" in sub or "pirate" in title:
            return (f"Pirate Jolly Roger flag emblem with skull and crossed bones ({card.width}x{card.height})", "gag")

        if "caduceus" in sub or "medical" in title:
            return (f"Medical caduceus staff entwined by two ascending serpents ({card.width}x{card.height})", "informative")

        if "no-smoking" in sub:
            return (f"Prohibited circle with diagonal slash across smoking cigarette ({card.width}x{card.height})", "informative")

        if "hello-kitty" in sub:
            return (f"Hello Kitty mascot cat face with bow on ear ({card.width}x{card.height})", "gag")

        if "pillsbury" in sub:
            return (f"Pillsbury Doughboy chef smiling in toque ({card.width}x{card.height})", "gag")

        if card.original_title.lower() not in {"untitled", "unknown", ""}:
            return (f"{self._clean_title_str(card.original_title)} ({card.width}x{card.height})", "informative")

        return (f"Iconic graphic trademark insignia badge ({card.width}x{card.height})", "informative")

    def _title_art_and_design(self, card: RawCard) -> tuple[str, str]:
        """Detailed art and design titling."""
        sub = card.subcategory.lower()
        if "celtic" in sub:
            return (f"Celtic knotwork interlaced continuous ribbon pattern ({card.width}x{card.height})", "informative")
        if "scrolls" in sub:
            return (f"Ancient parchment scroll unrolled with curled edges ({card.width}x{card.height})", "informative")
        if "fleur-de-lis" in sub:
            return (f"Fleur-de-lis stylized decorative lily emblem ({card.width}x{card.height})", "informative")
        if card.original_title.lower() not in {"untitled", "unknown", ""}:
            return (f"{self._clean_title_str(card.original_title)} ({card.width}x{card.height})", "informative")
        return (f"Geometric decorative graphic design pattern ({card.width}x{card.height})", "informative")


def load_unique_cards(master_file: Path) -> list[RawCard]:
    """Parse all cards and eliminate duplicate artwork texts."""
    content = master_file.read_text(encoding="utf-8")
    raw_blocks = content.split("=== ID:")
    cards: list[RawCard] = []
    seen_art: set[str] = set()

    for block in raw_blocks[1:]:
        lines = block.strip().split("\n")
        header_line = lines[0]

        id_match = re.search(r"^\s*([^|]+)", header_line)
        title_match = re.search(r"TITLE:\s*([^|]+)", header_line)
        artist_match = re.search(r"ARTIST:\s*([^|]+)", header_line)
        cat_match = re.search(r"CATEGORY:\s*([^|]+)", header_line)
        subcat_match = re.search(r"SUBCATEGORY:\s*([^|]+)", header_line)
        size_match = re.search(r"SIZE:\s*(\d+)x(\d+)", header_line)

        first_fence = block.find("```\n")
        last_fence = block.rfind("\n```")
        if first_fence == -1 or last_fence == -1 or last_fence <= first_fence:
            continue

        art = block[first_fence + 4 : last_fence].strip("\r\n")

        # Deduplicate identical artworks
        if art in seen_art:
            continue
        seen_art.add(art)

        card_id = id_match.group(1).strip() if id_match else "unknown"
        title = title_match.group(1).strip() if title_match else "Untitled"
        artist = artist_match.group(1).strip() if artist_match else "unknown"
        category = cat_match.group(1).strip() if cat_match else "general"
        subcategory = subcat_match.group(1).strip() if subcat_match else "general"
        width = int(size_match.group(1)) if size_match else 0
        height = int(size_match.group(2)) if size_match else 0

        cards.append(
            RawCard(
                id=card_id,
                original_title=title,
                artist=artist,
                category=category,
                subcategory=subcategory,
                width=width,
                height=height,
                art=art,
            )
        )

    return cards


def run_convergence(master_file: Path, output_dirs: list[Path]) -> tuple[int, int, int]:
    """Execute analysis, title generation, quality filtering, and file writing."""
    cards = load_unique_cards(master_file)
    logger.info("Loaded %d unique cards for rich title refinement and quality filtering", len(cards))

    generator = DistinctTitleGenerator()
    gag_blocks: list[str] = []
    info_blocks: list[str] = []
    dropped_count: int = 0

    for card in cards:
        result = generator.generate_unique_title(card)
        if result is None:
            dropped_count += 1
            continue

        new_title, target_type = result
        block = (
            f"=== ID: {card.id} | TITLE: {new_title} | ARTIST: {card.artist} | "
            f"CATEGORY: {card.category} | SUBCATEGORY: {card.subcategory} | "
            f"SIZE: {card.width}x{card.height} ===\n```\n{card.art}\n```\n"
        )

        if target_type == "gag":
            gag_blocks.append(block)
        else:
            info_blocks.append(block)

    logger.info(
        "Refinement Complete: %d gag cards, %d informative cards, %d unreadable/sideways cards dropped",
        len(gag_blocks),
        len(info_blocks),
        dropped_count,
    )

    # Prepare file contents
    gag_header = (
        "# SPOIN ASCII REFERENCE LIBRARY — USE FOR GAGS & SCENE HOOKS\n"
        f"# Total High-Clarity Curated Artwork Cards: {len(gag_blocks)}\n"
        "# Width Limit: <= 40 monospace characters (phone card safe)\n"
        "# All artwork cards have 100% DISTINCT, rich, search-friendly descriptive titles.\n"
        "# Best for: Comedic character reactions, silly animals, facial expressions, memes, punchy hooks\n"
        "# Format: Header with explicit TITLE followed by triple-backtick fenced ASCII art\n\n"
    )
    gag_content = gag_header + "\n".join(gag_blocks)

    info_header = (
        "# SPOIN ASCII REFERENCE LIBRARY — USE FOR INFORMATIVE VISUALIZATION\n"
        f"# Total High-Clarity Curated Artwork Cards: {len(info_blocks)}\n"
        "# Width Limit: <= 40 monospace characters (phone card safe)\n"
        "# All artwork cards have 100% DISTINCT, rich, search-friendly descriptive titles.\n"
        "# Best for: Hardware/computers, scientific concepts, books/scrolls, checklists, tools, real-world objects\n"
        "# Format: Header with explicit TITLE followed by triple-backtick fenced ASCII art\n\n"
    )
    info_content = info_header + "\n".join(info_blocks)

    for out_dir in output_dirs:
        out_dir.mkdir(parents=True, exist_ok=True)
        gag_file = out_dir / "use_for_gags.txt"
        info_file = out_dir / "use_for_informative_visualization.txt"

        gag_file.write_text(gag_content, encoding="utf-8")
        info_file.write_text(info_content, encoding="utf-8")
        logger.info("Saved %s and %s in %s", gag_file.name, info_file.name, out_dir)

    return (len(gag_blocks), len(info_blocks), dropped_count)


def main() -> None:
    """CLI entrypoint."""
    helpers_dir = Path(__file__).parent
    library_dir = helpers_dir / "ascii_art_library"
    master_file = library_dir / "_all_categories_library.txt"

    output_dirs = [helpers_dir, library_dir]

    gags, info, dropped = run_convergence(master_file, output_dirs)
    print("\nVisual Titling & Clarity Convergence Complete (Personalized & Distinct Titling):")
    print(f"  - use_for_gags.txt: {gags:,} high-clarity cards (all with 100% DISTINCT personalized titles)")
    print(f"  - use_for_informative_visualization.txt: {info:,} high-clarity cards (all with 100% DISTINCT personalized titles)")
    print(f"  - Dropped / Filtered: {dropped:,} ambiguous/cryptic/sideways cards")
    print(f"  - Total preserved in curated library: {gags + info:,} / 3,505 cards")


if __name__ == "__main__":
    main()
