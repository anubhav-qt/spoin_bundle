"""Deterministic repairs applied to every drafted card body before the gate.

These are all failures of TRANSPORT, not of taste: the model chose the right
content and the wire format mangled it on the way here. That is why they are
repaired in server code instead of asked for in a prompt -- CLAUDE.md's
"generator trusted for taste, never for constraints". A prompt line saying
"please emit four backticks as three" is a wish; this module is a check.

Three distinct corruptions, all measured against the live corpus on 2026-09-07
(605 active cards) and all invisible at the point they happen:

1. **Backslash escapes eaten by the JSON decoder** (36 cards, 6.0%). `\\f`,
   `\\t`, `\\b` and `\\r` are all VALID JSON escapes, so a model emitting
   `"\\frac{a}{b}"` instead of `"\\\\frac{a}{b}"` parses without error into a
   formfeed followed by `rac{a}{b}`. Nothing raises; KaTeX simply renders
   garbage. `repair_control_escapes` puts the backslash back.

2. **Fences the renderer cannot see** (9 cards). `apps/web`'s `FENCE_RE`
   requires exactly three backticks followed by a bare language tag and a
   newline, so a ````mermaid opener, or ```mermaid graph TD with the diagram's
   first line on the fence line, matches nothing and the whole block renders as
   literal backticks. `normalize_fences` rewrites both shapes.

3. **Mermaid labels that break mermaid's parser** (20 of 49 diagram blocks).
   An unquoted `(`, `<`, `&` or `{` inside `A[...]` is a syntax error, so the
   diagram throws at render time rather than at generation time.
   `quote_mermaid_labels` quotes them.

Together those accounted for roughly 28 of 49 mermaid diagrams in the corpus
failing to render -- the "most of the mermaid charts weren't rendering" the
owner reported.
"""

from __future__ import annotations

import re

#: LaTeX commands whose first letter is also a JSON escape character, so that a
#: model writing `\frac` (rather than `\\frac`) inside a JSON string yields a
#: control character plus the command's tail. Only these four letters can be
#: lost this way; `\a` and `\v` are not JSON escapes and `\n` is indistinguishable
#: from a real newline, so a `\nabla` is unrecoverable and deliberately not
#: guessed at here.
_ESCAPE_TAILS: dict[str, tuple[str, ...]] = {
    "\x0c": (  # \f
        "frac", "frak", "forall", "fbox", "footnotesize", "fill", "flat",
    ),
    "\t": (  # \t
        "text", "textbf", "textit", "textrm", "textstyle", "times", "theta",
        "tau", "tan", "tanh", "top", "triangle", "tilde", "to", "therefore",
    ),
    "\x08": (  # \b
        "beta", "bar", "big", "bigg", "bullet", "boldsymbol", "binom", "bmod",
        "bot", "boxed", "because",
    ),
    "\r": (  # \r
        "rho", "right", "rightarrow", "rangle", "ref", "rm", "rvert", "Re",
    ),
}

#: Longest first, so `textbf` wins over `text` and `rightarrow` over `right`.
_ESCAPE_TAILS = {
    char: tuple(sorted(tails, key=len, reverse=True)) for char, tails in _ESCAPE_TAILS.items()
}

_FENCE_SPLIT_RE = re.compile(r"(`{3,}[^\n]*\n[\s\S]*?`{3,})")

#: The renderer treats these as diagram fences (`apps/web/components/Card.tsx`).
_DIAGRAM_LANGS = frozenset({"mermaid", "flowchart", "diagram"})

#: Characters mermaid's flowchart parser cannot take inside an UNQUOTED node
#: label. `(` is by far the most common in practice -- "Shepherd Moons
#: (Prometheus, Pandora)" is a natural thing to write and a syntax error.
_MERMAID_LABEL_SPECIALS = re.compile(r"[(){}<>&|#;]")

#: Mermaid's node shapes as (open, close) delimiter pairs, **longest opener
#: first** -- the ordering is load-bearing. `B[(Shared Cache Line)]` is a
#: cylinder whose label is `Shared Cache Line`; matching a bare `[` first would
#: read the label as `(Shared Cache Line)`, "find" parens in it and quote them,
#: turning valid mermaid into a different shape. Every compound form has to be
#: tried before the single-character form it starts with.
_MERMAID_SHAPES: tuple[tuple[str, str], ...] = (
    ("[[", "]]"),
    ("[(", ")]"),
    ("((", "))"),
    ("([", "])"),
    ("{{", "}}"),
    ("[/", "/]"),
    ("[\\", "\\]"),
    ("[", "]"),
    ("(", ")"),
    ("{", "}"),
)

#: Statements whose text is NOT a node label and must never be scanned for one:
#: `style`/`classDef`/`click`/`linkStyle` take selectors and CSS, where a `#`
#: is a colour and quoting it breaks the rule.
_MERMAID_SKIP_LINE_RE = re.compile(
    r"^\s*(end|style|classDef|class|click|linkStyle|direction|accTitle|accDescr)\b"
)

#: `subgraph` takes a TITLE, not a label, so it needs quoting of its own shape:
#: the whole title is wrapped, where a node label's brackets stay outside the
#: quotes. `subgraph Shared Reads (&str)` does not parse; `subgraph "Shared
#: Reads (&str)"` does. A title already quoted, or given in the explicit
#: `id[title]` form, is left alone.
_MERMAID_SUBGRAPH_RE = re.compile(r"^(?P<indent>\s*)subgraph\s+(?P<title>\S.*?)\s*$")

#: Label quoting applies to flowcharts ONLY. A sequence diagram's `A->>B: text`
#: message is free prose after the colon, and a state or class diagram uses
#: brackets differently again -- running a flowchart's rules over any of them
#: corrupts working syntax. Anything not declared here is left untouched.
_MERMAID_FLOWCHART_DECL_RE = re.compile(r"^\s*(graph|flowchart)\b")

#: A mermaid line that declares the diagram type. Everything before the first
#: one is preamble the label-quoting pass must leave alone.
_MERMAID_DECL_RE = re.compile(
    r"^\s*(graph|flowchart|sequenceDiagram|stateDiagram(?:-v2)?|classDiagram|"
    r"erDiagram|journey|gantt|pie|mindmap|timeline|quadrantChart|gitGraph|"
    r"requirementDiagram|C4Context)\b"
)

#: Editorial scaffolding the writer sometimes leaves in `body`. These are notes
#: to the pipeline, not content: a reader seeing "*Source: Source 3*" learns
#: nothing and the quiz writer treats it as material. 13 cards carried one.
_SOURCE_NOTE_RE = re.compile(
    r"(?im)^[ \t]*[*_]{0,2}(?:Source|Sources|Source Note|Citation|Refs?|References)"
    r"[*_]{0,2}\s*:.*$"
)
_INLINE_SOURCE_NOTE_RE = re.compile(r"(?i)\*\s*Sources?\s*:[^*\n]*\*")
_EDITORIAL_NOTE_RE = re.compile(
    r"(?im)^[ \t]*\*{0,2}(?:Key Correction|Correction|Editor'?s Note|Note to (?:the )?"
    r"(?:reviewer|editor)|Reviewer Note)\*{0,2}\s*:.*$"
)


def repair_control_escapes(text: str) -> str:
    """Restore backslashes that the JSON decoder ate (see module docstring).

    Runs OUTSIDE fenced blocks only. A tab inside a ```` ```python ```` fence is
    real indentation, and rewriting it would corrupt working code; a raw tab,
    formfeed or backspace in prose never is.

    A control character whose tail matches no known command is replaced with a
    single space rather than left in place -- it is still a corrupted escape,
    just one whose command this table does not carry, and a literal formfeed in
    a card body has no legitimate reading.
    """

    def repair_segment(segment: str) -> str:
        out: list[str] = []
        i = 0
        while i < len(segment):
            char = segment[i]
            tails = _ESCAPE_TAILS.get(char)
            if tails is None:
                out.append(char)
                i += 1
                continue
            rest = segment[i + 1 :]
            for tail in tails:
                # tail[0] is the letter the backslash was attached to; the
                # decoder consumed the backslash AND that letter together.
                if rest.startswith(tail[1:]):
                    out.append("\\" + tail)
                    i += len(tail)  # 1 for the eaten char + len(tail) - 1 consumed
                    break
            else:
                out.append(" ")
                i += 1
        return "".join(out)

    return "".join(
        part if part.startswith("```") or part.startswith("````") else repair_segment(part)
        for part in _FENCE_SPLIT_RE.split(text)
    )


def normalize_fences(text: str) -> str:
    """Rewrite every fenced block into the exact shape the renderer parses.

    Two repairs, both of which currently make a block vanish into literal
    backticks on the card:

    - **4+ backticks collapse to 3.** Nothing in a card body needs a longer
      fence; the renderer's regex matches three and only three.
    - **An info string carrying content is split.** ```` ```mermaid graph TD ````
      puts the diagram's declaration line on the fence line, where the renderer
      reads it as part of the language tag and matches nothing. The tail moves
      down to the first content line, which is where the author meant it.

    The closing fence is normalized to three backticks on its own line for the
    same reason.
    """

    def rewrite(match: re.Match[str]) -> str:
        block = match.group(0)
        opener, _, remainder = block.partition("\n")
        info = opener.lstrip("`").strip()
        body = remainder
        # Drop the closing run, whatever length it is, and re-add a clean one.
        body = re.sub(r"\n?`{3,}\s*$", "", body)

        lang, _, tail = info.partition(" ")
        lang = re.sub(r"[^A-Za-z0-9_-]", "", lang)
        tail = tail.strip()
        if tail:
            body = f"{tail}\n{body}" if body.strip() else tail
        return f"```{lang}\n{body.rstrip()}\n```"

    return _FENCE_SPLIT_RE.sub(rewrite, text)


def quote_mermaid_labels(text: str) -> str:
    """Quote mermaid node labels containing characters that break its parser.

    `A[Shepherd Moons (Prometheus, Pandora)]` is a mermaid syntax error and
    throws at render time; `A["Shepherd Moons (Prometheus, Pandora)"]` is the
    same diagram and renders. The model is not asked to remember this -- 20 of
    49 diagram blocks in the corpus got it wrong -- so it is done here.

    Only lines AFTER the diagram-type declaration are touched: `graph TD` and
    `flowchart LR` carry no labels, and the edge-label form `-->|text|` is left
    alone because a pipe label tolerates what a bracket label does not.
    """

    def quote_line(line: str) -> str:
        """Scan one flowchart line, quoting only genuine node labels.

        A scanner rather than a regex substitution because the decision at any
        `[` depends on what came before it: an already-quoted label must be
        skipped WHOLE (otherwise a later pass quotes again inside it, and
        `B["fn x(&self) -> &T"]` becomes `B["fn x("&self") -> &T"]`), and the
        compound shapes need their closer matched, not guessed.
        """

        out: list[str] = []
        i = 0
        while i < len(line):
            for open_delim, close_delim in _MERMAID_SHAPES:
                if not line.startswith(open_delim, i):
                    continue
                end = line.find(close_delim, i + len(open_delim))
                if end == -1:
                    continue
                label = line[i + len(open_delim) : end]
                stripped = label.strip()
                #: Already quoted: emit the whole span verbatim and jump past
                #: it, so nothing re-enters this label.
                if stripped.startswith('"') and stripped.endswith('"') and len(stripped) > 1:
                    out.append(line[i : end + len(close_delim)])
                elif stripped and _MERMAID_LABEL_SPECIALS.search(label):
                    out.append(f"{open_delim}\"{stripped}\"{close_delim}")
                else:
                    out.append(line[i : end + len(close_delim)])
                i = end + len(close_delim)
                break
            else:
                out.append(line[i])
                i += 1
        return "".join(out)

    def rewrite_block(lang: str, content: str) -> str:
        if lang not in _DIAGRAM_LANGS:
            return content
        lines = content.split("\n")
        seen_decl = False
        for n, line in enumerate(lines):
            if not seen_decl:
                if _MERMAID_DECL_RE.match(line):
                    #: A non-flowchart diagram is left entirely alone -- see
                    #: `_MERMAID_FLOWCHART_DECL_RE`.
                    if not _MERMAID_FLOWCHART_DECL_RE.match(line):
                        return content
                    seen_decl = True
                continue
            if "%%" in line or _MERMAID_SKIP_LINE_RE.match(line):
                continue
            subgraph = _MERMAID_SUBGRAPH_RE.match(line)
            if subgraph is not None:
                title = subgraph.group("title")
                if (
                    not title.startswith('"')
                    and "[" not in title
                    and _MERMAID_LABEL_SPECIALS.search(title)
                ):
                    lines[n] = f'{subgraph.group("indent")}subgraph "{title}"'
                continue
            lines[n] = quote_line(line)
        return "\n".join(lines)

    def rewrite(match: re.Match[str]) -> str:
        block = match.group(0)
        opener, _, remainder = block.partition("\n")
        lang = opener.lstrip("`").strip().split(" ")[0].lower()
        body = re.sub(r"\n?`{3,}\s*$", "", remainder)
        return f"```{lang}\n{rewrite_block(lang, body).rstrip()}\n```"

    return _FENCE_SPLIT_RE.sub(rewrite, text)


def strip_editorial_notes(text: str) -> str:
    """Remove source citations and correction notes the writer left in `body`.

    `body` is what the quiz writer treats as ground truth and what the reader is
    tested on, so "*Source: Source 3 (Hubble tension)*" is worse than noise --
    it is a dangling reference to a numbered source the reader never sees.
    """

    text = _INLINE_SOURCE_NOTE_RE.sub("", text)
    text = _SOURCE_NOTE_RE.sub("", text)
    text = _EDITORIAL_NOTE_RE.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def normalize_card_body(body: str) -> str:
    """Every body repair, in the one order that is correct.

    Escapes first: a formfeed sitting inside a fence opener would otherwise make
    that fence unrecognisable to the two passes after it. Fences before mermaid
    labels, because label quoting has to know a block's language and the
    language tag is only trustworthy once the fence is normalized.
    """

    body = repair_control_escapes(body)
    body = normalize_fences(body)
    body = quote_mermaid_labels(body)
    return strip_editorial_notes(body)


_SNAKE_CASE_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)+$")

#: Words a title-caser must not capitalise mid-title, plus the domain acronyms
#: that must stay upper. Short list on purpose: this repairs a malformed
#: identifier into something readable, it is not a house style engine.
_LOWER_WORDS = frozenset({"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or",
                          "the", "to", "vs", "via", "with"})
_UPPER_WORDS = frozenset({"bao", "cmb", "agn", "isw", "sne", "ia", "eos", "uv", "xuv", "ede",
                          "api", "sql", "http", "json", "utf", "cpu", "gpu", "ascii", "llm"})


def humanize_canonical_title(title: str) -> str:
    """Turn a snake_case identifier back into a readable concept name.

    `canonical_title` feeds quiz stems, remediation links, search and dedup
    (ADR-0022), so `error_propagation_in_distance_ladder` degrades every one of
    them. 17 cards carried an identifier instead of a name. A title that is
    already prose is returned untouched.
    """

    if not _SNAKE_CASE_RE.match(title.strip()):
        return title
    words = title.strip().split("_")
    out = [
        word.upper()
        if word in _UPPER_WORDS
        else word
        if n > 0 and word in _LOWER_WORDS
        else word.capitalize()
        for n, word in enumerate(words)
    ]
    return " ".join(out)
