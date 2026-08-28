"""Builds 42 comprehensive worked few-shot examples for Spoin LLM generator
covering all 21 active DB topics (1 Gag + 1 Informative per topic).

Features:
- Genuine illustrative ASCII art & fancy pop-culture / trendy GenZ artworks.
- Clear dialogues, speech bubbles, reaction tags, and structural annotations.
- Strict <= 40 monospace characters width limit on every line.
- Text-only flowcharts/boxes are prohibited (handled by Mermaid maker agent).
- Boxer emotes explicitly labeled with *BOXER STANCE*.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

HELPERS_DIR = Path(__file__).parent
GAGS_FILE = HELPERS_DIR / "use_for_gags.txt"
INFO_FILE = HELPERS_DIR / "use_for_informative_visualization.txt"
OUT_1 = HELPERS_DIR / "examples.txt"
OUT_2 = HELPERS_DIR / "ascii_art_library" / "examples.txt"


@dataclass
class ExampleSpec:
    topic_slug: str
    topic_name: str
    subtopic_name: str
    difficulty: str
    example_type: str  # "GAG" or "INFORMATIVE"
    descriptive_name: str
    card_id: str
    asset_direction: str
    canonical_title: str
    ascii_label: str
    ascii_alt: str
    title: str
    hook: str
    body: str
    custom_art_override: str | None = None


def load_card_map(file_path: Path) -> dict[str, dict[str, str]]:
    content = file_path.read_text(encoding="utf-8")
    blocks = content.split("=== ID:")
    card_map = {}
    for block in blocks[1:]:
        header_line = block.strip().split("\n")[0]
        id_match = re.search(r"^\s*([^|]+)", header_line)
        title_match = re.search(r"TITLE:\s*([^|]+)", header_line)
        if not id_match or not title_match:
            continue
        cid = id_match.group(1).strip()
        title = title_match.group(1).strip()
        first_fence = block.find("```\n")
        last_fence = block.rfind("\n```")
        if first_fence != -1 and last_fence != -1:
            art = block[first_fence + 4 : last_fence].strip("\r\n")
            info = {"id": cid, "title": title, "art": art}
            card_map[cid] = info
            card_map[title] = info
            card_map[f"{cid}:{title}"] = info
    return card_map


gag_cards = load_card_map(GAGS_FILE)
info_cards = load_card_map(INFO_FILE)

# 21 Real DB Topics specifications (2 examples per topic: 1 Gag + 1 Informative)
SPECS: list[ExampleSpec] = [
    # 1. 10m Air Pistol Shooting
    ExampleSpec(
        topic_slug="10m-air-pistol-shooting",
        topic_name="10m Air Pistol Shooting",
        subtopic_name="Advanced Trigger Kinematics & Eliminating Horizontal Vector Offsets",
        difficulty="Intermediate",
        example_type="GAG",
        descriptive_name="Olympic Marksman Trigger Jerk Recoil Flinch",
        card_id="art_52_33",  # (-_-)
        asset_direction="Olympic shooter dialogue anticipating pneumatic recoil and flinching as the shot breaks.",
        canonical_title="Trigger Jerk Dynamics in Precision Air Pistol",
        ascii_label="shooter-trigger-jerk-flinch",
        ascii_alt="Olympic marksman sweating and flinching against zero recoil on pneumatic pistol",
        title="The Recoil Flinch on a Gun With Zero Recoil",
        hook="Anticipating the shot on a pneumatic pistol makes your muscles flinch against a recoil that doesn't even exist.",
        body="""In 10m Air Pistol, the projectile weighs barely 0.5 grams and has near-zero recoil. Yet subconscious anticipation causes **trigger jerk**:

- **Lateral Vector Deflection**: Squeezing with secondary finger joints pulls the front sight horizontally right before sear release.
- **The Smooth Squeeze Fix**: Pressure must build strictly along the bore axis until the shot breaks as a surprise.

If you *know* the exact millisecond the shot fires, your hand already moved.""",
        custom_art_override="""    [SHOOTER]: "Steady... squeeze..."
        \\
      (-_-') - - - > [GUN]: *CLICK*
       /|\\                  |
      / | \\         [RECOIL FLINCH]
     *SWEAT*       (Pulls to 7-ring)""",
    ),
    ExampleSpec(
        topic_slug="10m-air-pistol-shooting",
        topic_name="10m Air Pistol Shooting",
        subtopic_name="Advanced Sight Adjustment, Rear Notch Width, and Zeroing",
        difficulty="Advanced",
        example_type="INFORMATIVE",
        descriptive_name="Target Bullseye and Sight Alignment Geometry",
        card_id="30dce128ef69b191",  # Circular dartboard bullseye target
        asset_direction="Circular 10-ring target diagram with side annotations showing sub-six hold and equal light bar distribution.",
        canonical_title="Sight Picture and Notch Ratio Geometry",
        ascii_label="sight-alignment-target-rings",
        ascii_alt="Circular precision target diagram illustrating sight alignment light bars",
        title="Sub-Millimeter Sight Picture Alignment",
        hook="At 10 meters, a 0.1mm misplacement of your front sight translates to a complete miss of the 0.5mm 10-ring.",
        body="""Achieving a perfect 10.9 in Olympic air pistol requires strict **optical prioritization**:

1. **Focus on Front Sight**: The eye cannot focus simultaneously on target, rear notch, and front blade. Crystal-clear focus must stay on the front sight.
2. **Equal Light Bars**: Symmetrical slivers of white space must appear on either side of the front post inside the rear notch.
3. **Sub-Six Hold**: Aiming slightly below the black bullseye prevents optical blending and vertical fatigue.""",
        custom_art_override="""    ,-'\"\"\"`-,
  ,' \\ _|_ / `.    [SUB-SIX HOLD]
 /`.,'\\ | /`.,'\\   Aim below black.
(  /`. \\|/ ,\'\\  )
|--|--;(O);--|--|  [EQUAL LIGHT]
(  \\,' /|\\ `./  )  Symmetric notch
 \\,'`./ | \\,'`./   white space.
  `. / \"\"\" \\ ,'
    '-._|_,-`""",
    ),

    # 2. Bhagavad Gita in Easy Language
    ExampleSpec(
        topic_slug="bhagvad-geeta-in-easy-language",
        topic_name="Bhagavad Gita in Easy Language",
        subtopic_name="Applied Gita: Stress, Decision-Making, and Selfless Leadership",
        difficulty="Beginner",
        example_type="GAG",
        descriptive_name="Snoopy Zen Meditation vs Nishkama Karma",
        card_id="16b5cd95f61fd82b",  # Snoopy dog lying atop red doghouse staring at sky
        asset_direction="Snoopy lying peacefully atop his doghouse detached from outcome scores and result anxiety.",
        canonical_title="Nishkama Karma and Outcome Attachment",
        ascii_label="snoopy-zen-doghouse-karma",
        ascii_alt="Snoopy lying on doghouse meditating on action without outcome attachment",
        title="Stop Obsessing Over the Scoreboard",
        hook="Karmanye vadhikaraste: you own 100% of your effort, but exactly 0% of the fruit.",
        body="""The core psychological remedy of the Bhagavad Gita (*Chapter 2, Verse 47*) targets **anxiety of results**:

- **The Trap (Sanga)**: Focusing on the bonus, grades, or validation drains cognitive energy away from actual execution.
- **Nishkama Karma**: Perform action as focused duty without clinging to outcome. 

When you detach from the victory trophy, performance anxiety collapses instantly.""",
        custom_art_override="""          .:\\ '`-.   [SNOOPY]:
          |:|  __ b  "Detached from
           `;-(       the scoreboard."
          ,'  |           \\
         ( \\|||_      [GITA CH. 2]:
  ,-----(.-''--``--. "Focus on
 /_______`'_________\\ ACTION 100%\"""",
    ),
    ExampleSpec(
        topic_slug="bhagvad-geeta-in-easy-language",
        topic_name="Bhagavad Gita in Easy Language",
        subtopic_name="Divine vs Demonic Qualities in Human Nature",
        difficulty="Intermediate",
        example_type="INFORMATIVE",
        descriptive_name="Solar Radiance and Spiritual Equanimity",
        card_id="9f94006d23bba026",  # Brilliant shining sun
        asset_direction="Radiant sun diagram labeled with steady equanimity (Samatvam) anchoring between pain and pleasure.",
        canonical_title="Samatvam: Equanimity in Success and Failure",
        ascii_label="samatvam-solar-radiance",
        ascii_alt="Radiant sun diagram illustrating steady spiritual equanimity and clarity",
        title="Samatvam: The Art of Unshakable Balance",
        hook="Yoga is defined in the Gita as equanimity (Samatvam yoga uchyate)—poise in both victory and defeat.",
        body="""Equanimity is not passive apathy; it is **emotional homeostasis under pressure**:

1. **Duality (Dvandva)**: Life fluctuates inevitably between praise/blame, pleasure/pain, and profit/loss.
2. **The Anchored Mind (Sthitaprajna)**: Like an ocean that absorbs rushing rivers without overflowing, the master mind processes chaos without losing internal stillness.

Steady leadership requires being undisturbed by short-term volatility.""",
        custom_art_override="""    \\  |  /     [SAMATVAM]
  '  .---.  '   Inner poise in
 -  /  *  \\  -  praise & blame.
  . `---' .
    /  |  \\
 [PAIN] <---> [PLEASURE]""",
    ),

    # 3. Building a Game Engine Using Raylib
    ExampleSpec(
        topic_slug="building-a-game-engine-using-raylib",
        topic_name="Building a Game Engine Using Raylib",
        subtopic_name="2D Camera Control and Viewports",
        difficulty="Intermediate",
        example_type="GAG",
        descriptive_name="Confused Developer Looking at Camera Offset Bug",
        card_id="art_52_8",  # (\ (^_^) /)
        asset_direction="Confused game developer dialogue looking for HUD health bar launched into orbit by camera zoom.",
        canonical_title="Coordinate Space Transformations in 2D",
        ascii_label="gamer-camera-space-offset",
        ascii_alt="Developer dialogue looking for HUD text launched by world camera zoom",
        title="Why Your UI Flew Off Into Deep Space",
        hook="Rendering UI elements inside the world camera matrix is the fastest way to launch your health bar into orbit.",
        body="""Raylib separates rendering into distinct coordinate contexts:

- **World Space (`BeginMode2D(camera)`)**: Game objects transform by camera target, rotation, and zoom.
- **Screen Space (`EndMode2D()`)**: HUD, score text, and dialogue boxes must render in raw screen pixel coordinates.

```c
BeginMode2D(camera);
DrawTexture(playerTexture, player.x, player.y, WHITE);
EndMode2D();
DrawText("HP: 100", 10, 10, 20, RED); // Screen HUD
```""",
        custom_art_override="""    [DEV]: "Where did my UI go?!"
        \\
       (o_O)   [WORLD ZOOM: 5x]
       /| |\\        |
        | |     [HUD]: *In Orbit*""",
    ),
    ExampleSpec(
        topic_slug="building-a-game-engine-using-raylib",
        topic_name="Building a Game Engine Using Raylib",
        subtopic_name="2D Vector Math for Game Mechanics",
        difficulty="Intermediate",
        example_type="INFORMATIVE",
        descriptive_name="Rocket Trajectory Vector Normalization",
        card_id="4daf316445a7926c",  # Space rocket launching upward
        asset_direction="Rocket motion vector diagram annotated with directional components and delta time integration.",
        canonical_title="Vector Normalization and Frame-Independent Motion",
        ascii_label="raylib-vector-normalization",
        ascii_alt="Rocket trajectory vector showing normalized delta-time movement physics",
        title="The Diagonal Speed Cheat & Delta Time",
        hook="Without vector normalization, pressing W + D makes your character move 41.4% faster diagonally.",
        body="""Two vital mathematical primitives every game programmer must implement:

1. **Vector Normalization**: $(1, 1)$ has a length of $\\sqrt{2} \\approx 1.414$. Normalize the input vector before multiplying by speed:
   $$\\vec{v}_{\\text{norm}} = \\frac{\\vec{v}}{\\|\\vec{v}\\|}$$
2. **Frame-Rate Independence**: Multiply velocity by `GetFrameTime()` (delta time) so physics runs identically at 60 FPS and 144 FPS.""",
        custom_art_override="""  ^  Y-axis
  |   /\\      [VELOCITY VECTOR]
  |  /  \\     vec.x = cos(a) * v
  | / [] \\    vec.y = sin(a) * v
  |-------|
  |  /||\\ |   [DELTA TIME]:
  | / || \\|   pos += vec * dt""",
    ),

    # 4. Building a Successful Kurtis Business in E-Commerce for India
    ExampleSpec(
        topic_slug="building-a-successful-kurtis-business-in-e-commerce-for-india",
        topic_name="Building a Successful Kurtis Business in E-Commerce for India",
        subtopic_name="Logistics, COD Management & RTO Mitigation",
        difficulty="Intermediate",
        example_type="GAG",
        descriptive_name="Cash on Delivery RTO Courier Shock",
        card_id="art_52_38",  # ((;_;))
        asset_direction="Courier and D2C founder dialogue reacting to rejected cash-on-delivery order at doorstep.",
        canonical_title="Cash-on-Delivery RTO Risk Mitigation",
        ascii_label="rto-cod-weeping-face",
        ascii_alt="Dialogue showing courier returning rejected COD parcel to weeping founder",
        title="The Silent Killer of Indian D2C: Return to Origin (RTO)",
        hook="A 35% COD RTO rate means you pay forward and reverse shipping on a dress you never actually sold.",
        body="""In Indian fashion e-commerce, **Cash on Delivery (COD)** drives initial conversion but carries severe return risks:

- **The RTO Math**: When a ₹799 Kurti gets rejected at delivery, the brand loses ₹80 forward shipping + ₹70 reverse freight + packaging costs.
- **Mitigation Tactics**:
  1. **WhatsApp Address Verification**: Confirm geolocation and phone validity before dispatch.
  2. **Prepaid Discounts**: Offer ₹50 off or UPI cashback to convert COD into prepaid orders.""",
        custom_art_override="""[COURIER]: "Delivery rejected."
    \\
   (;_;) <--- [FOUNDER]: "Lost
   /| |\\      ₹150 shipping!"
  [COD RETURN TO ORIGIN]""",
    ),
    ExampleSpec(
        topic_slug="building-a-successful-kurtis-business-in-e-commerce-for-india",
        topic_name="Building a Successful Kurtis Business in E-Commerce for India",
        subtopic_name="Kurtis Fabrics, Workmanship & Fabric Sourcing",
        difficulty="Beginner",
        example_type="INFORMATIVE",
        descriptive_name="3D Parcel Box Logistics & GSM Textile Specs",
        card_id="bd9edbb3752b0f6a",  # Cardboard shipping box package tied with twine
        asset_direction="3D isometric parcel box package tied with twine rope labeled with Rayon GSM weight and air freight limits.",
        canonical_title="Fabric Selection: Rayon vs Cotton vs Chanderi",
        ascii_label="kurtis-packaging-box-specs",
        ascii_alt="3D parcel box drawing illustrating GSM textile weight and volumetric shipping limits",
        title="Fabric Chemistry: Why 140 GSM Rayon Rules Indian E-Commerce",
        hook="Rayon dominates 60%+ of daily-wear Kurtis because of its fluid drape, vibrant dye uptake, and sub-₹60/meter mill price.",
        body="""Selecting the right textile substrate determines repeat purchase rates:

| Fabric | GSM | Best Use Case | Risk Factor |
| :--- | :--- | :--- | :--- |
| **140 GSM Liva Rayon** | 135-145 | Daily office wear, straight Kurtas | Shrinkage if unwashed |
| **60s Cambric Cotton** | 100-115 | Summer breathable collections | Creasing, higher cost |
| **Chanderi Silk** | 80-95 | Festive Anarkali sets & Dupattas | Requires inner lining |

Always run pre-production wash tests to calculate exact 3-5% shrinkage buffers.""",
        custom_art_override="""      .--------.
     /        /|  [KURTI SHIPMENT]
    +--------+ |  140 GSM Rayon
    |  |  |  | |  Pre-shrunk fabric
    |--+--+--| /  Vol. Wt <500g
    +--------+'   (Save ₹35 air freight)""",
    ),

    # 5. Carl Jung's Philosophy
    ExampleSpec(
        topic_slug="carl-jungs-philosophy",
        topic_name="Carl Jung's Philosophy",
        subtopic_name="Shadow and the Collective Unconscious",
        difficulty="Intermediate",
        example_type="GAG",
        descriptive_name="Encountering the Repressed Shadow",
        card_id="ce81f944ef293bf4",  # Mischievous horned devil grinning
        asset_direction="Ego and Shadow dialogue showing the polite conscious persona meeting its repressed shadow.",
        canonical_title="The Shadow Archetype and Moral Superiority",
        ascii_label="jung-shadow-devil-profile",
        ascii_alt="Dialogue between conscious ego persona and smiling unconscious shadow",
        title="Your Repressed Shadow Knows All Your Passwords",
        hook="The brighter the persona you present to society, the darker the shadow lurking in your unconscious.",
        body="""Carl Jung identified the **Shadow** as the hidden, rejected aspects of the psyche:

- **Projection**: When you feel irrational irritation at someone else's flaws, you are often observing your own disowned traits projected onto them.
- **Integration**: Denying your capacity for aggression does not make you virtuous; it makes you naive.
- **Wholeness over Perfection**: True psychological maturity requires confronting and integrating your shadow into conscious awareness.""",
        custom_art_override="""[EGO]: "I am 100% rational!"
   \\
  ( ^_^)     (`-') <--- [SHADOW]:
  <|  |>     /| |\\      "Really?"
  /    \\     /   \\""",
    ),
    ExampleSpec(
        topic_slug="carl-jungs-philosophy",
        topic_name="Carl Jung's Philosophy",
        subtopic_name="Anima and Animus",
        difficulty="Advanced",
        example_type="INFORMATIVE",
        descriptive_name="Psychic Structure: Persona Mask & Unconscious Shadow",
        card_id="e8c8e226df8f5005",  # Human brain organ showing convoluted cerebral hemispheres
        asset_direction="Human head and psyche diagram dividing conscious Persona from deep unconscious shadow layers.",
        canonical_title="Topography of the Psyche: Ego to Collective Unconscious",
        ascii_label="jungian-psyche-brain-structure",
        ascii_alt="Graphic diagram illustrating psychic layers from Persona to Collective Unconscious",
        title="The Deep Architecture of the Psyche",
        hook="Your conscious ego is merely a tiny island floating on the vast ocean of the collective unconscious.",
        body="""Jung divided human psychological architecture into three distinct layers:

1. **Ego & Persona**: The conscious center of identity and the social mask worn to adapt to culture.
2. **Personal Unconscious**: Repressed memories, forgotten impressions, and personal complexes.
3. **Collective Unconscious**: Universal ancestral memory patterns (Archetypes: *The Hero, Anima/Animus, The Wise Old Man, The Self*).

Individuation is the lifelong journey of harmonizing all layers into the **Self**.""",
        custom_art_override="""       .-""-.     [CONSCIOUS EGO]
     .' _  _ '.   Rational Persona
    /  (o)(o)  \\  ================
    |    /\\    |  [UNCONSCIOUS]
     \\  '--'  /   Repressed Shadow
      '.____.'    & Archetypes""",
    ),

    # 6. Claude Code: Becoming a 10x Developer
    ExampleSpec(
        topic_slug="claude-code-becoming-a-10x-developer",
        topic_name="Claude Code: Becoming a 10x Developer",
        subtopic_name="Basic Refactoring & Bug Fixing Workflows",
        difficulty="Beginner",
        example_type="GAG",
        descriptive_name="Superman Speed Refactoring with Claude Code",
        card_id="248e9f395440a68f",  # Superman flying forward with S-shield on chest
        asset_direction="Superman flight icon representing Claude Code refactoring 50 files across codebase in seconds.",
        canonical_title="Autonomous Agentic Pair Programming",
        ascii_label="claude-code-superman-speed",
        ascii_alt="Superman crest symbol representing ultra-fast autonomous refactoring",
        title="From Typing Code to Directing Architecture",
        hook="Why spend 3 hours writing repetitive boilerplate when you can review a clean pull request in 30 seconds?",
        body="""Using Claude Code effectively shifts your engineering role from manual syntax author to **senior code reviewer**:

- **Give Context Early**: Provide file links, reproduction steps, and constraints (e.g. `mypy --strict`).
- **Review Diffs with Precision**: Verify edge cases, transaction rollbacks, and security boundaries.

The 10x engineer is not the fastest typist, but the clearest thinker and prompt director.""",
        custom_art_override=""" ________________     [CLAUDE CODE]:
 /.,------------,.\\   "Refactored
///  .=^^^^^^^\\__|\\\\  50 files in 3s!\"
\\\\\\   `------.   .//        |
 `\\\\`--...._  `;//'   [TESTS]: PASS
   `\\\\.-,___;.//'     [PR]: READY""",
    ),
    ExampleSpec(
        topic_slug="claude-code-becoming-a-10x-developer",
        topic_name="Claude Code: Becoming a 10x Developer",
        subtopic_name="Automated Git Workflows & Smart Commits",
        difficulty="Intermediate",
        example_type="INFORMATIVE",
        descriptive_name="Terminal Workstation Screen REPL Verification Loop",
        card_id="8f039d07ecff8bc2",  # Desktop personal computer system with CRT monitor and keyboard
        asset_direction="Computer terminal workstation screen illustrating Claude Code REPL verification loop.",
        canonical_title="The Agentic REPL: Edit-Verify-Commit Loop",
        ascii_label="claude-code-tool-loop",
        ascii_alt="Terminal workstation monitor illustrating automated edit, test, and commit loops",
        title="The Tight Feedback Verification Loop",
        hook="Autonomous AI coding assistants succeed because of rapid local verification loops, not just raw token prediction.",
        body="""The anatomy of an effective Claude Code iteration cycle:

1. **Semantic Search & Context Gathering**: Reading ASTs, grep patterns, and test suites.
2. **Atomic Editing**: Applying targeted line edits rather than destructive full-file overwrites.
3. **Automated Verification**: Running `pytest`, `cargo check`, or `tsc` immediately to catch syntax errors before human handoff.

Always ensure your project has automated linters and tests for the agent to verify against.""",
        custom_art_override="""   .----------------------.
   | [CLAUDE CODE REPL]   |
   | > AST grep search OK |
   | > mypy --strict PASS |
   | > 100% tests passing |
   '----------------------'
          |        |
        .-'--------'-.
       (______________)""",
    ),

    # 7. Current AI Capabilities & Scope
    ExampleSpec(
        topic_slug="current-ai-capabilities-and-scope",
        topic_name="Current AI Capabilities & Scope",
        subtopic_name="AI Evaluation Frameworks, Benchmarks, and LLM-as-a-Judge",
        difficulty="Intermediate",
        example_type="GAG",
        descriptive_name="Robot Bragging About Benchmarks vs Production Runtime",
        card_id="26e586d5db023498",  # Mechanical humanoid robot with antenna and metallic joints
        asset_direction="Robot dialogue bragging about perfect benchmark score while failing on basic imports.",
        canonical_title="LLM Benchmarks vs Real-World Hallucinations",
        ascii_label="robot-benchmark-runtime-hallucination",
        ascii_alt="Robot dialogue bragging about exam score while hallucinating package import",
        title="100% on the Benchmark, 0% on Production Edge Cases",
        hook="An LLM can score 95% on medical exams yet hallucinate a non-existent Python package in production.",
        body="""Evaluating modern Large Language Models requires looking beyond synthetic benchmarks:

- **Goodhart's Law**: When a benchmark metric (MMLU, HumanEval) becomes the optimization target, it ceases to be a reliable measure.
- **LLM-as-a-Judge Pitfalls**: Using GPT-4 to judge other models introduces self-preference bias, verbosity bias, and positional ordering bias.

Real reliability requires deterministic unit testing, ground-truth retrieval eval, and human-in-the-loop validation.""",
        custom_art_override="""      \\_/
     (* *)      [AI ROBOT]:
    __)#(__     "100% on MMLU bar exam!"
   ( )...( )         \\
   || |_| ||    [RUNTIME]:
 >==() | | ()/  *Hallucinates fake API*
    _(___)_""",
    ),
    ExampleSpec(
        topic_slug="current-ai-capabilities-and-scope",
        topic_name="Current AI Capabilities & Scope",
        subtopic_name="Computer Vision: Detection, Segmentation, and Diffusion",
        difficulty="Advanced",
        example_type="INFORMATIVE",
        descriptive_name="Diffusion Models and Latent Denoising Process",
        card_id="4be1d2ccdc76fbd5",  # Incandescent glass lightbulb
        asset_direction="Illuminated lightbulb diagram representing latent space reverse denoising steps.",
        canonical_title="Score-Based Denoising Diffusion Probabilistic Models",
        ascii_label="diffusion-denoising-rays",
        ascii_alt="Lightbulb illustration showing latent reverse diffusion noise subtraction",
        title="How Diffusion Models Create Order Out of Chaos",
        hook="Image diffusion models do not draw lines; they repeatedly subtract random noise until a high-resolution image emerges.",
        body="""Modern generative vision models (Stable Diffusion, Midjourney, Flux) operate in two stages:

1. **Forward Process ($q$)**: Gradually adds Gaussian noise to an image over $T$ timesteps until it becomes pure static noise.
2. **Reverse Process ($p_\\theta$)**: A U-Net or DiT (Diffusion Transformer) predicts and subtracts the exact noise component at each step, guided by text embeddings from CLIP/T5.

Operating in **Latent Space** (via VAEs) reduces computational cost by $64\\times$ compared to pixel space.""",
        custom_art_override="""       :     [LATENT DIFFUSION]
     '.  _  .'  Reverse U-Net
    -=  (~)  =- subtracts noise
     .'  #  '.  step by step.
         #      (Decodes to image)""",
    ),

    # 8. FastAPI
    ExampleSpec(
        topic_slug="fastapi",
        topic_name="FastAPI",
        subtopic_name="Concurrency, Threadpools, & Async I/O",
        difficulty="Intermediate",
        example_type="GAG",
        descriptive_name="Steaming Coffee Mug & Blocked Async Event Loop",
        card_id="0f4e4c43bc5a1c83",  # Coffee mug on saucer with swirls of rising hot steam
        asset_direction="Steaming coffee mug representing developer stepping away while synchronous time.sleep blocks entire async server.",
        canonical_title="Event Loop Blocking in Async Python",
        ascii_label="coffee-mug-event-loop-freeze",
        ascii_alt="Steaming coffee mug dialogue showing synchronous time.sleep freezing FastAPI event loop",
        title="Why Your Async FastAPI App Froze at 1 RPS",
        hook="Writing `time.sleep(5)` inside an `async def` endpoint freezes the entire server for all other concurrent users.",
        body="""In FastAPI, declaring an endpoint as `async def` runs it directly on the single-threaded **AsyncIO Event Loop**:

- **Non-Blocking I/O**: Use `await asyncio.sleep()` or async database drivers (`asyncpg`).
- **Synchronous CPU/Disk Tasks**: Use standard `def` (FastAPI automatically runs regular `def` functions in an external threadpool).

```python
# DANGEROUS: Freezes entire event loop
@app.get("/bad")
async def bad():
    time.sleep(5) 

# SAFE: Runs in separate threadpool worker
@app.get("/good")
def good():
    time.sleep(5)
```""",
        custom_art_override="""      ( (      [DEV]: "sleep(5)..."
       ) )          \\
     .-----.   [SERVER]: *FREEZES*
     |     |]  (Single-threaded loop
     `-----'    blocks all users)""",
    ),
    ExampleSpec(
        topic_slug="fastapi",
        topic_name="FastAPI",
        subtopic_name="ASGI Architecture & Uvicorn Fundamentals",
        difficulty="Intermediate",
        example_type="INFORMATIVE",
        descriptive_name="ASGI Pipeline: Uvicorn, Starlette, and Pydantic",
        card_id="afdfab7c353c0f60",  # Classic Apple Macintosh desktop computer
        asset_direction="ASGI web server workstation drawing showing Uvicorn event loop and Pydantic validation.",
        canonical_title="The ASGI Request-Response Pipeline",
        ascii_label="fastapi-asgi-workstation",
        ascii_alt="Web server workstation drawing showing ASGI concurrency pipeline",
        title="The Triad Powering FastAPI's Speed",
        hook="FastAPI is not an engine; it is a high-performance orchestration layer built on three specialized pillars.",
        body="""FastAPI achieves near-Go performance by delegating distinct responsibilities:

1. **Uvicorn (ASGI Web Server)**: Handles raw TCP connections and HTTP parsing via `uvloop` and `httptools` in C.
2. **Starlette (Routing & Middleware)**: High-speed async request dispatching, WebSocket management, and streaming responses.
3. **Pydantic (Validation & Serialization)**: Core data validation compiled in Rust (`pydantic-core`) for sub-millisecond parsing.""",
        custom_art_override="""    .--------------------.
    | [ASGI SERVER NODE] |
    | Uvicorn -> Rust C  |
    | Pydantic V2 Valid  |
    '--------------------'
       | |     [NON-BLOCKING]
     .-'-'-.   Handles 10k+
    (_______)  concurrent reqs""",
    ),

    # 9. Financial Literacy & Investing Mechanics
    ExampleSpec(
        topic_slug="financial-literacy--investing-mechanics",
        topic_name="Financial Literacy & Investing Mechanics",
        subtopic_name="Asset Allocation & Modern Portfolio Theory",
        difficulty="Beginner",
        example_type="GAG",
        descriptive_name="Eric Cartman Festively Plump Portfolio",
        card_id="7a4c93ab6c221ff6",  # South Park construction paper cutout character
        asset_direction="South Park Eric Cartman dialogue justifying severe market dip losses as festively plump assets.",
        canonical_title="FOMO and Emotional Market Timing",
        ascii_label="cartman-festively-plump-dip",
        ascii_alt="Cartman dialogue claiming his falling stock portfolio is festively plump",
        title="The Buy-High, Sell-Low Ritual",
        hook="Retail investors consistently underperform the index by 3-4% annually because greed buys peaks and fear sells bottoms.",
        body="""The psychology of disastrous market timing:

- **The Cycle**: Euphoria pushes capital into trending meme assets at all-time highs $\\rightarrow$ a 20% correction triggers panic $\\rightarrow$ selling at the exact local bottom.
- **The Remedy (Dollar-Cost Averaging)**: Automate fixed monthly purchases into low-cost index funds (e.g. S&P 500 or Nifty 50) regardless of short-term market noise.""",
        custom_art_override="""        .-"           "-.   [CARTMAN]:
      .'  __.........__  '. "I'm not
     /.-'` /   \\ /   \\ `'-.  down 40%,
    |     |   '/ \\'   |   |  I am
    _\\         ___         /_festively
   /  '.'-.__  ___  __.-'.'  \\plump!\"
 _/_    `'-..._____...-'`    _\\_""",
    ),
    ExampleSpec(
        topic_slug="financial-literacy--investing-mechanics",
        topic_name="Financial Literacy & Investing Mechanics",
        subtopic_name="Banking, Savings & Inflation Impact",
        difficulty="Intermediate",
        example_type="INFORMATIVE",
        descriptive_name="Compound Interest Curve and Inflation Drag",
        card_id="07153e5553c889ff",  # Pocket digital calculator with LCD display and keypad
        asset_direction="Pocket digital calculator drawing with LCD display showing the Rule of 72 formula.",
        canonical_title="The Power of Compound Interest & Inflation Erosion",
        ascii_label="compound-interest-calculator",
        ascii_alt="Pocket digital calculator drawing displaying the Rule of 72 calculation",
        title="The Rule of 72 & The Invisible Inflation Tax",
        hook="Leaving cash in a 3% savings account when inflation runs at 6% guarantees a 50% loss of purchasing power in 24 years.",
        body="""Two mathematical laws governing real personal wealth:

1. **The Rule of 72**: Divide 72 by the annual return rate to calculate doubling time:
   $$\\text{Years to Double} \\approx \\frac{72}{\\text{Rate of Return (\\%)}}$$
   *(At 10% equity returns, capital doubles every 7.2 years).*
2. **Real vs Nominal Return**: $\\text{Real Return} = \\text{Nominal Return} - \\text{Inflation}$. Investments must outpace inflation after taxes to generate true wealth.""",
        custom_art_override=""" .--------------------.
 |  ________________  |  [RULE OF 72]
 | | 72 / 10% = 7.2y | |  Doubles in
 | |________________| |  7.2 years!
 |  [7][8][9]  [+]    |
 |  [4][5][6]  [-]    |  [REAL RETURN]
 |  [1][2][3]  [x]    |  = Nom - Infl
 |  [.][0][=]  [/]    |  = 10% - 4% = 6%
 '--------------------'""",
    ),

    # 10. German Language
    ExampleSpec(
        topic_slug="german-language",
        topic_name="German Language",
        subtopic_name="Definite & Indefinite Articles: Gender Mechanics",
        difficulty="Beginner",
        example_type="GAG",
        descriptive_name="Boxer Stance Battling German Noun Genders",
        card_id="art_52_5",  # Boxer stance ((9'-')9)
        asset_direction="Student in boxer fighting stance squaring up against the arbitrary grammatical genders of common objects.",
        canonical_title="Grammatical Gender System in German",
        ascii_label="der-die-das-gender-boxing",
        ascii_alt="Student in boxer stance protesting contradictory German noun genders",
        title="Why the Sun is Female and the Moon is Male",
        hook="In German, a tree is masculine (der Baum), a flower is feminine (die Blume), and a young girl is neuter (das Mädchen).",
        body="""German assigns every noun one of three grammatical genders, which dictate article declensions across four cases:

- **Der** (Masculine) $\\rightarrow$ *der Hund, der Tisch*
- **Die** (Feminine) $\\rightarrow$ *die Katze, die Sonne*
- **Das** (Neuter) $\\rightarrow$ *das Buch, das Kind*

**Pro-Tip**: Look for noun endings! Words ending in *-ung, -heit, -keit, -schaft, -tion* are 100% feminine (*die*). Words ending in *-chen, -lein* are always neuter (*das*).""",
        custom_art_override="""[STUDENT]: "Why DIE Sonne..."
    \\
  (9'-')9 <--- *BOXER STANCE*
   / | \\       "...but DER Mond?!"
  *FIGHTS NOUN GENDERS*""",
    ),
    ExampleSpec(
        topic_slug="german-language",
        topic_name="German Language",
        subtopic_name="Advanced Sentence Topology & Information Structure",
        difficulty="Intermediate",
        example_type="INFORMATIVE",
        descriptive_name="Verb-Second (V2) Word Order & Subordinate Clauses",
        card_id="e2674480576895fe",  # Stack of hardbound academic textbooks
        asset_direction="Hardbound grammar book stack drawing with V2 second-position verb bookmark annotation.",
        canonical_title="German Sentence Topology: V2 Rule & Verb Kicker",
        ascii_label="german-syntax-v2-rules",
        ascii_alt="Grammar book stack diagram illustrating the V2 verb second position rule",
        title="The Golden Rule of German Syntax: Verb in Second Position",
        hook="No matter how many elements you place at the start of a main German sentence, the conjugated verb ALWAYS stays in position 2.",
        body="""German sentence structure follows strict topological fields (*Satzklammer*):

1. **Main Clause (V2 Rule)**:
   - *Heute **gehe** ich ins Kino.* (Today go I to the cinema).
   - The time adverbial takes position 1, forcing the verb into position 2 and subject into position 3.
2. **Subordinate Clause (*weil, dass, obwohl*)**:
   - Subordinating conjunctions **kick** the conjugated verb to the very end:
   - *...weil ich keine Zeit **habe**.*""",
        custom_art_override="""     .----------------.
    /  GRAMMATIK BUCH/|  [V2 RULE]
   +----------------+ |  "Heute [GEHE]
   | Pos 1: "Heute" | |   ich..."
   | Pos 2: Verb    | /  (Main Clause)
   +----------------+'   [SUBORDINATE]
                         Verb at end""",
    ),

    # 11. Gym & Physical Fitness
    ExampleSpec(
        topic_slug="gym-physical-fitness",
        topic_name="Gym & Physical Fitness",
        subtopic_name="Autoregulation: RPE, RIR, and Load Management",
        difficulty="Intermediate",
        example_type="GAG",
        descriptive_name="Leg Day Heavy Squat Paralysis",
        card_id="art_52_33",  # (-_-)
        asset_direction="Dialogue between trainer calling for 2 more reps and exhausted lifter on floor.",
        canonical_title="RPE 10 True Failure vs Perceived Effort",
        ascii_label="rpe10-exhausted-squat-face",
        ascii_alt="Trainer and athlete dialogue about pushing past true failure on leg day",
        title="What 'Reps in Reserve' Actually Feels Like",
        hook="Most gym-goers think they hit failure at 10 reps, but with a gun to their head could easily grind out 4 more.",
        body="""Effective hypertrophy requires training close to **true muscular failure**:

- **RPE (Rate of Perceived Exertion)**: RPE 8 means 2 reps were left in reserve (2 RIR).
- **The Junk Volume Trap**: Doing 5 sets at RPE 5 creates fatigue without triggering high-threshold mechanical tension.

Stop counting reps until the barbell slows down noticeably despite maximum voluntary intent.""",
        custom_art_override="""[TRAINER]: "RPE 8, 2 more reps!"
    \\
  (x_x) <--- [LIFTER]: "Legs
  /| |\\      have left chat..."
  /   \\""",
    ),
    ExampleSpec(
        topic_slug="gym-physical-fitness",
        topic_name="Gym & Physical Fitness",
        subtopic_name="Cable Machines, Cams, and Resistance Profile Physics",
        difficulty="Advanced",
        example_type="INFORMATIVE",
        descriptive_name="Cable Pulley Machine & Constant Mechanical Tension",
        card_id="30dce128ef69b191",  # Cable Pulley System
        asset_direction="Cable pulley machine diagram illustrating constant mechanical tension across active range of motion.",
        canonical_title="Mechanical Tension & Resistance Profiles",
        ascii_label="cable-pulley-tension-cam",
        ascii_alt="Cable pulley machine diagram illustrating continuous mechanical tension",
        title="Physics in the Gym: Matching the Resistance Profile",
        hook="A dumbbell lateral raise has zero resistance at the bottom and maximum torque at the top; cables solve this flaw.",
        body="""Hypertrophy is driven primarily by **mechanical tension** across the active range of motion:

1. **Strength Curve**: A muscle's leverage changes as joint angles open and close.
2. **Moment Arm ($\\tau = F \\times r_\\perp$)**: Free weights only pull vertically downward due to gravity. At bottom of a dumbbell fly, torque on pecs is minimal.
3. **Cable Cams**: By angling cable pulleys, you maintain peak tension in the fully lengthened (stretched) position where hypertrophy stimulation is highest.""",
        custom_art_override="""       (O)   [PULLEY CAM MACHINE]
      / |
     /  |    [CABLE TENSION]
    O   |    Constant tension across
   /|\\  |    full range of motion.
   / \\ [=]   [WEIGHT STACK]""",
    ),

    # 12. How Everyday Things Work
    ExampleSpec(
        topic_slug="how-everyday-things-work",
        topic_name="How Everyday Things Work",
        subtopic_name="Active Noise Cancellation and Phase Inversion",
        difficulty="Intermediate",
        example_type="GAG",
        descriptive_name="ANC Headphone Serenity vs Vacuum Noise",
        card_id="art_52_33",  # (-_-)
        asset_direction="Dialogue contrasting ambient vacuum and dog barking noise against total ANC headphone serenity.",
        canonical_title="Destructive Interference in Active Noise Cancellation",
        ascii_label="anc-unimpressed-peace-face",
        ascii_alt="Dialogue showing noisy environment canceled out by active noise cancellation headphones",
        title="Destroying Sound With More Sound",
        hook="Active Noise Cancellation works by blasting the exact inverse sound wave into your ears at the speed of sound.",
        body="""How modern ANC headphones create silence:

- **External Microphones**: Sample incoming low-frequency ambient rumble (engine hum, fan droning).
- **Phase Inversion (Anti-Noise)**: The onboard DSP flips the wave polarity by $180^\\circ$.
- **Destructive Interference**: Peak meets trough ($1 + (-1) = 0$), canceling the pressure wave before it vibrates your eardrum.""",
        custom_art_override="""[NOISE]: *BARKING & VACUUM*
               |
[ANC]: d-_-b ---> "Pure silence.\"""",
    ),
    ExampleSpec(
        topic_slug="how-everyday-things-work",
        topic_name="How Everyday Things Work",
        subtopic_name="Active Noise Cancellation and Phase Inversion",
        difficulty="Intermediate",
        example_type="INFORMATIVE",
        descriptive_name="Destructive Interference Wave Cancellation",
        card_id="203ad6554a26870a",  # Incandescent glass lightbulb
        asset_direction="Acoustic headphone speaker drawing emitting 180-degree inverted anti-noise wave.",
        canonical_title="Destructive Interference & Wave Inversion",
        ascii_label="wave-phase-inversion-anc",
        ascii_alt="Headphone speaker illustration emitting destructive phase inversion sound waves",
        title="The Wave Math Behind Active Noise Cancellation",
        hook="When an acoustic wave peak at +1 meets a synthesized trough at -1, the resulting air pressure is exactly zero.",
        body="""The physical mechanics of **Active Noise Cancellation (ANC)**:

1. **Phase Inversion**: Incoming ambient noise is captured by external microphones and inverted by $180^\\circ$:
   $$y_{\\text{anti}}(t) = -y_{\\text{noise}}(t)$$
2. **Destructive Interference**: The internal speaker emits the inverted wave, summing net sound pressure to zero:
   $$y_{\\text{net}}(t) = y_{\\text{noise}}(t) + (-y_{\\text{noise}}(t)) = 0$$

Works best on predictable low-frequency sounds (<1 kHz) such as jet engines and train hums.""",
        custom_art_override="""      .-----.     [ANC HEADPHONES]
     /  .-.  \\    Mic samples noise
    |  (   )  |   DSP inverts 180 deg
    |   `-'   |
    '---------'   _.~\"~._  (0 deg)
      ||   ||     ~._.~\"~  (180 deg)
     (==) (==)    -------  (Silence)""",
    ),

    # 13. Kubernetes
    ExampleSpec(
        topic_slug="kubernetes",
        topic_name="Kubernetes",
        subtopic_name="Advanced Health Probes: Liveness, Readiness, and Startup",
        difficulty="Intermediate",
        example_type="GAG",
        descriptive_name="Pikachu Shocked Face at CrashLoopBackOff",
        card_id="bce6c6738005dded",  # Pikachu yellow electric mouse pokemon
        asset_direction="Pikachu with shocked face reacting as aggressive liveness probe murders pod before database warmup.",
        canonical_title="Kubernetes CrashLoopBackOff and Probe Misconfiguration",
        ascii_label="pikachu-shocked-crashloop",
        ascii_alt="Pikachu shocked face seeing pod killed by aggressive Kubernetes liveness probe",
        title="Death by Misconfigured Liveness Probe",
        hook="Setting an aggressive 3-second liveness probe on a heavy Java app ensures your pod gets murdered before it finishes starting.",
        body="""Why pods get trapped in **CrashLoopBackOff**:

- **The Culprit**: The Liveness probe checks `/healthz` before database connection pools initialize $\\rightarrow$ Kubelet kills container $\\rightarrow$ restarts $\\rightarrow$ repeats.
- **The Modern Fix**: Use **Startup Probes** to hold off liveness checks until heavy warmups complete:

```yaml
startupProbe:
  httpGet:
    path: /healthz
    port: 8080
  failureThreshold: 30
  periodSeconds: 10 # Gives 300s grace period!
```""",
        custom_art_override=""" \\:.             .:/   [PIKACHU]:
  \\``._________.'' /    *SHOCKED*
   \\             /          \\
   / .':.   .':. \\    [KUBELET]:
   | '::' . '::' |   "Liveness failed,
   |`.   ._.   .'|    killing pod!\"
   |.'         '.|
   |.\\  \\   /  /.|   [STATUS]:
   |''\\.;   ;,/ '|   *CrashLoopBackOff*""",
    ),
    ExampleSpec(
        topic_slug="kubernetes",
        topic_name="Kubernetes",
        subtopic_name="Basic Cluster Networking & Services",
        difficulty="Advanced",
        example_type="INFORMATIVE",
        descriptive_name="Kube-Proxy, iptables, and CoreDNS Packet Routing",
        card_id="b79c7ed1f80ac3af",  # Tall sailing galleon ship with billowing canvas sails
        asset_direction="Sailing flagship drawing representing the Kubernetes cluster routing packets across service endpoints.",
        canonical_title="ClusterIP Service Routing & Kube-Proxy iptables",
        ascii_label="k8s-control-ship-routing",
        ascii_alt="Sailing flagship drawing illustrating Kubernetes control plane routing traffic",
        title="How a Virtual ClusterIP Actually Routes Packets",
        hook="A Kubernetes ClusterIP is not a real network interface; it is a ghost IP existing only in kernel iptables/eBPF rules.",
        body="""When a pod sends traffic to a Service IP (`10.96.0.1`):

1. **CoreDNS Resolution**: Service name resolves to a virtual ClusterIP.
2. **Kube-Proxy & iptables/IPVS**: Kernel intercepts the packet and applies NAT (Network Address Translation) with random weight distribution across backend pod IPs.
3. **Overlay Network (CNI: Calico/Cilium)**: Encapsulates the packet (Geneve/VXLAN) and delivers directly to destination node.""",
        custom_art_override="""              ---|    [K8s HELMSMAN]
              /| \\    Steering ClusterIP
             / |  \\   packets through
            /  ||  \\  iptables / IPVS.
           /___/____\\
        ___\\________/___
  ~~~~  \\______________/ ~~~~""",
    ),

    # 14. Mathematics
    ExampleSpec(
        topic_slug="mathematics",
        topic_name="Mathematics",
        subtopic_name="Abstract Algebra: Groups and Fields",
        difficulty="Advanced",
        example_type="GAG",
        descriptive_name="R2-D2 & C-3PO on Division by Zero Error",
        card_id="13dc54f397efe8cf",  # Star Wars character figure
        asset_direction="C-3PO and R2-D2 panic over algebraic field axiom collapse when dividing by zero.",
        canonical_title="Division by Zero and Field Axiom Violation",
        ascii_label="r2d2-c3po-divide-by-zero",
        ascii_alt="C-3PO and R2-D2 dialogue warning that dividing by zero collapses field axioms",
        title="Why You Cannot Divide by Zero (Algebraic Proof)",
        hook="If dividing by zero were allowed, you could mathematically prove that $1 = 2$ and destroy all logic.",
        body="""In abstract algebra, a **Field** $(\\mathbb{R}, +, \\cdot)$ requires an additive identity ($0$) where $a \\cdot 0 = 0$ for all elements:

- **The Multiplicative Inverse**: Dividing by $b$ is defined as multiplying by $b^{-1}$ such that $b \\cdot b^{-1} = 1$.
- **The Paradox**: If $0^{-1}$ existed, then $1 = 0 \\cdot 0^{-1} = (0 + 0) \\cdot 0^{-1} = 1 + 1 = 2$.

To preserve arithmetic consistency, $0$ cannot have a multiplicative inverse.""",
        custom_art_override="""          .==.        [C-3PO]:
           ()''()-.   "Probability of
.---.       ;--; /    dividing by zero
|__ =|     .'  __'.   is zero, Master!"
[  ] |    /   |---\\       \\
|__| |  .'    '.   \\   [R2-D2]:
/__\\ /  :       '._:   *Beep Boop Error*""",
    ),
    ExampleSpec(
        topic_slug="mathematics",
        topic_name="Mathematics",
        subtopic_name="Absolute Value & Number Line Properties",
        difficulty="Beginner",
        example_type="INFORMATIVE",
        descriptive_name="Geometric Metric Distance on the Real Number Line",
        card_id="7042a12186a00c4e",  # Pair of gaming cubic dice
        asset_direction="Cubic 3D gaming dice drawing illustrating coordinate Euclidean distance and field algebra.",
        canonical_title="Absolute Value as Euclidean Metric Distance",
        ascii_label="absolute-value-metric-distance",
        ascii_alt="Pair of 3D gaming dice drawing illustrating metric coordinates",
        title="Absolute Value is Distance, Not Just 'Removing the Minus'",
        hook="Thinking of $|x|$ as 'making it positive' blinds students to its true meaning: Euclidean distance from origin.",
        body="""The formal mathematical definition of absolute value on the real line $\\mathbb{R}$:

$$|x| = \\begin{cases} x & \\text{if } x \\ge 0 \\\\ -x & \\text{if } x < 0 \\end{cases}$$

- **Metric Property**: $|a - b|$ is the exact physical distance between points $a$ and $b$.
- **Triangle Inequality**: For all $x, y \\in \\mathbb{R}$, $|x + y| \\le |x| + |y|$.

This metric foundation forms the basis of all real analysis, calculus limits, and topology.""",
        custom_art_override="""       /\\ o o o\\      [EUCLIDEAN METRIC]
      /o \\ o o o\\     Distance |a - b|
     <    >------>    Between origin &
      \\ o/  o   /     points on line.
       \\/______/      |x| >= 0 always""",
    ),

    # 15. Mental Models & Cognitive Biases
    ExampleSpec(
        topic_slug="mental-models--cognitive-biases",
        topic_name="Mental Models & Cognitive Biases",
        subtopic_name="Anchoring, Framing, and Context Effects",
        difficulty="Beginner",
        example_type="GAG",
        descriptive_name="Anchoring Bias in Restaurant Wine Menus",
        card_id="art_52_12",  # ($.$)
        asset_direction="Restaurant menu price decoy dialogue triggering customer anchoring reaction.",
        canonical_title="Anchoring Effect and Price Relativity",
        ascii_label="anchoring-bias-wine-menu",
        ascii_alt="Dialogue showing restaurant menu anchor trick making expensive item seem cheap",
        title="The $200 Wine Bottle That Exists Only to Sell the $60 One",
        hook="The human brain cannot evaluate absolute value; it can only compare against the nearest available anchor.",
        body="""The **Anchoring Effect** is a cognitive bias where initial exposure to a number skews all subsequent estimates:

- **The Decoy Pricing Trick**: Restaurants place a ₹15,000 wine at the top of the menu not to sell it, but to make the ₹4,500 bottle below it feel like a rational bargain.
- **Salary Negotiations**: The first number mentioned in a negotiation acts as an invisible gravitational anchor pulling the final settlement toward it.""",
        custom_art_override="""[MENU]:  "Wine: ₹15,000" (Anchor)
[GUEST]: "Look, ₹4,500 is cheap!"
       \\
      ($.$) <--- [ANCHORED]
      /| |\\""",
    ),
    ExampleSpec(
        topic_slug="mental-models--cognitive-biases",
        topic_name="Mental Models & Cognitive Biases",
        subtopic_name="Antifragility, Fragility, & Robustness",
        difficulty="Intermediate",
        example_type="INFORMATIVE",
        descriptive_name="Taleb's Triad: Fragile, Robust, and Antifragile Systems",
        card_id="525e0f24dbf181f3",  # Magnifying glass lens examining detail
        asset_direction="Magnifying glass drawing examining systemic stress testing and nonlinear convex payoffs.",
        canonical_title="Nassim Taleb's Antifragility Framework",
        ascii_label="antifragile-triad-magnifier",
        ascii_alt="Magnifying glass drawing illustrating inspection of Antifragile systems",
        title="Beyond Robust: Gaining from Disorder",
        hook="A ceramic vase is fragile; a rock is robust; human bone and open-source code are antifragile.",
        body="""Nassim Taleb categorizes all systems into the **Triad** based on response to stressors:

| System | Response to Volatility | Example |
| :--- | :--- | :--- |
| **Fragile** | Suffers from disorder, hates shock | Monolithic bank, porcelain cup |
| **Robust** | Resists shocks, remains unchanged | Concrete bunker, gold ingot |
| **Antifragile** | **Grows stronger from shocks** | Immune system, muscle tissue, Hydra |

To make your career antifragile: limit downside risks while maintaining asymmetric, unlimited upside exposure.""",
        custom_art_override="""          .-""-.      [TALEB'S TRIAD]
  _______/  *   \\     Fragile -> Breaks
 |_______  * *   ;    Robust -> Stays
         \\  *   /     Antifragile ->
          '-..-'      GROWS FROM SHOCK""",
    ),

    # 16. Philosophy
    ExampleSpec(
        topic_slug="philosophy",
        topic_name="Philosophy",
        subtopic_name="Applied Ethics & Trolley Problems",
        difficulty="Intermediate",
        example_type="GAG",
        descriptive_name="The Trolley Problem Lever Panic",
        card_id="art_52_33",  # (-_-)
        asset_direction="Utilitarian and Kantian dialogue debating moral complicity as the runaway trolley approaches.",
        canonical_title="Utilitarianism vs Deontology in Trolley Dilemma",
        ascii_label="trolley-problem-lever-dilemma",
        ascii_alt="Ethical dialogue debating lever pull in the runaway trolley problem",
        title="To Pull or Not to Pull the Lever",
        hook="Utilitarians pull the lever in 0.1 seconds; Kantians spend 4 hours debating whether pulling constitutes murder.",
        body="""Philippa Foot's classic **Trolley Problem** pits ethical frameworks in conflict:

- **Utilitarianism (Bentham/Mill)**: Maximize net lives saved. Killing 1 to save 5 is morally required ($5 - 1 = +4$).
- **Deontology (Kant)**: The Categorical Imperative forbids using a human being as a mere instrument or means to an end. Pulling the switch makes you an active participant in homicide.""",
        custom_art_override="""[UTILITARIAN]: "PULL IT! Save 5!"
[KANTIAN]:     "NO! That's murder!"
       \\        /
       (-_-)   (Lever in middle)""",
    ),
    ExampleSpec(
        topic_slug="philosophy",
        topic_name="Philosophy",
        subtopic_name="Aristotelian Logic & Virtue Ethics",
        difficulty="Intermediate",
        example_type="INFORMATIVE",
        descriptive_name="Aristotle's Golden Mean Between Extremes",
        card_id="07b6700c5fb39e04",  # Stack of hardbound academic textbooks
        asset_direction="Philosophical hardbound book drawing illustrating Aristotle's Golden Mean.",
        canonical_title="The Golden Mean & Nicomachean Ethics",
        ascii_label="aristotle-golden-mean-books",
        ascii_alt="Philosophical books drawing illustrating virtue as the Golden Mean",
        title="Virtue is the Mean Between Two Vices",
        hook="Courage is not the absence of fear; it is the exact golden midpoint between cowardice and reckless stupidity.",
        body="""In the *Nicomachean Ethics*, Aristotle defines moral virtue as a balanced midpoint:

$$\\text{Deficiency (Vice)} \\longleftrightarrow \\mathbf{\\text{Golden Mean (Virtue)}} \\longleftrightarrow \\text{Excess (Vice)}$$

- **Cowardice** $\\longleftrightarrow$ **Courage** $\\longleftrightarrow$ **Rashness**
- **Stinginess** $\\longleftrightarrow$ **Generosity** $\\longleftrightarrow$ **Profligacy**
- **Humility/Self-Doubt** $\\longleftrightarrow$ **Magnanimity** $\\longleftrightarrow$ **Vanity/Hubris**

Virtue is not a theoretical rule; it is an ingrained character habit (*hexis*).""",
        custom_art_override="""       .--------------.
      / ETHICA NICOM /|  [GOLDEN MEAN]
     +--------------+ |  Virtue between
     |  [ COURAGE ] | |  deficiency and
     | Mean between | /  excess vices.
     +--------------+'   (Habit)""",
    ),

    # 17. PostgreSQL
    ExampleSpec(
        topic_slug="postgresql",
        topic_name="PostgreSQL",
        subtopic_name="B-Tree Indexes & Basic Optimization",
        difficulty="Intermediate",
        example_type="GAG",
        descriptive_name="Homer Simpson Screaming at Sequential Scan",
        card_id="9b2b3f600020f509",  # Homer Simpson shouting 'Doh!' with round eyes
        asset_direction="Homer Simpson shouting D'oh as unindexed query burns 100% disk I/O on 50M rows.",
        canonical_title="Sequential Scan vs B-Tree Index Lookup",
        ascii_label="homer-seq-scan-doh",
        ascii_alt="Homer Simpson shouting D'oh on unindexed 50M row database query",
        title="When You Forget the Index on `user_id`",
        hook="A query that takes 2 milliseconds with a B-Tree index takes 45 seconds when Postgres is forced to inspect every row from disk.",
        body="""What happens during an unindexed query:

- **Sequential Scan (`Seq Scan`)**: The database engine reads every single page block from storage into memory, burning I/O.
- **B-Tree Index Scan**: Traverses a balanced tree in $O(\\log N)$ time, resolving in 3-4 page reads.

```sql
-- The 5-second fix:
CREATE INDEX CONCURRENTLY idx_orders_user_id ON orders(user_id);
```""",
        custom_art_override="""      .-"`"-.      [DEV HOMER]:
     /       \\    "D'OH! Forgot index
     |   __  _|    on user_id!"
     |  /  \\/ \\         \\
    WW  \\_o/_o/    [POSTGRES]:
    (        _)    *Seq Scan 50M rows*
     |   .----\\    (100% Disk I/O)
      \\__'--;`""",
    ),
    ExampleSpec(
        topic_slug="postgresql",
        topic_name="PostgreSQL",
        subtopic_name="Common Table Expressions & Recursive CTEs",
        difficulty="Advanced",
        example_type="INFORMATIVE",
        descriptive_name="Hierarchical Graph Traversal via Recursive CTEs",
        card_id="b3f5c150cf1a2af4",  # 3.5-inch floppy disk with sliding shutter
        asset_direction="Floppy diskette storage medium drawing representing database engine recursive query evaluation.",
        canonical_title="Recursive CTEs: Graph and Tree Traversal",
        ascii_label="postgres-recursive-cte-disk",
        ascii_alt="Floppy disk drive symbol illustrating database recursive tree query execution",
        title="Traversing Trees in SQL Without N+1 Queries",
        hook="Recursive Common Table Expressions (CTEs) allow you to query nested organizational hierarchies in a single query.",
        body="""How `WITH RECURSIVE` executes in PostgreSQL:

1. **Anchor Member**: Evaluates initial root nodes (e.g. `parent_id IS NULL`).
2. **Recursive Member**: Joins the previous iteration's working table until no new rows are returned.

```sql
WITH RECURSIVE org_tree AS (
    SELECT id, name, manager_id, 1 as depth 
    FROM employees WHERE manager_id IS NULL
  UNION ALL
    SELECT e.id, e.name, e.manager_id, o.depth + 1
    FROM employees e JOIN org_tree o ON e.manager_id = o.id
)
SELECT * FROM org_tree;
```""",
        custom_art_override="""     .--------.
     | |____| |   [PERSISTENCE DISK]
     |  (..)  |   WITH RECURSIVE
     |________|   Tree graph in 1 query""",
    ),

    # 18. Rust Programming Language
    ExampleSpec(
        topic_slug="rust-programming-language",
        topic_name="Rust Programming Language",
        subtopic_name="Borrowing, References, and Slices",
        difficulty="Intermediate",
        example_type="GAG",
        descriptive_name="Boxer Stance Battling Rust Borrow Checker",
        card_id="art_52_5",  # ((9'-')9)
        asset_direction="Developer in boxer fighting stance squaring off against the strict rustc borrow checker.",
        canonical_title="Aliasing XOR Mutability in Rust",
        ascii_label="borrow-checker-boxing-brawl",
        ascii_alt="Developer in boxer stance fighting the Rust borrow checker",
        title="The Borrow Checker Does Not Care About Your Feelings",
        hook="In Rust, you can have infinite read-only references OR exactly one mutable reference, but never both at the same time.",
        body="""Rust achieves memory safety without a garbage collector via **The Aliasing Rule**:

- **Aliasing XOR Mutability**: Data can be either widely shared (`&T`) OR modified (`&mut T`), but never simultaneously.
- **Why? Data Race Prevention**: If one thread reads while another writes, memory becomes undefined. The compiler rejects this at compile time.

Embrace it: the borrow checker is preventing multi-threaded crashes before your code ever hits staging.""",
        custom_art_override="""[DEV]: "Let me mutate while reading!"
   \\
 (9'-')9 <--- *BOXER STANCE*
  / | \\       [RUSTC]: "Error[E0502]:
 *BRAWL*      cannot borrow &mut\"""",
    ),
    ExampleSpec(
        topic_slug="rust-programming-language",
        topic_name="Rust Programming Language",
        subtopic_name="Async Rust and the Future Trait Architecture",
        difficulty="Advanced",
        example_type="INFORMATIVE",
        descriptive_name="Rust Future Polling State Machine & Pinning",
        card_id="bade71d2cced1cbb",  # Interlocking heavy iron chain links
        asset_direction="Interlocking heavy chain links drawing representing pinned memory guarantees and zero-cost state machines.",
        canonical_title="Zero-Cost Async: Rust State Machines & Pin",
        ascii_label="rust-async-chain-links",
        ascii_alt="Interlocking chain links drawing representing pinned async state machines",
        title="How Async Rust Compiles to Zero-Allocation State Machines",
        hook="Unlike JavaScript or Go, Rust async creates zero hidden heap allocations; your entire async function compiles into an enum.",
        body="""The core mechanics of Rust's `Future` trait:

1. **Pull-Based Execution**: Futures do nothing until polled by an executor (e.g. Tokio):
   ```rust
   pub trait Future {
       type Output;
       fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output>;
   }
   ```
2. **`Pin<P>` Guarantee**: Prevents self-referential generator structs from moving in memory, ensuring internal pointers remain valid across `await` points.""",
        custom_art_override="""   (===)---(===)---(===)  [PINNED CHAIN]
     |       |       |    Zero-cost
   [PIN]   [ASYNC] [FUT]  state machine
   Tokio poll -> Ready    in Rust enum""",
    ),

    # 19. Study Abroad Full Guide
    ExampleSpec(
        topic_slug="study-abroad-full-guide",
        topic_name="Study Abroad Full Guide",
        subtopic_name="Cross-Cultural Adaptation & Culture Shock",
        difficulty="Beginner",
        example_type="GAG",
        descriptive_name="International Supermarket Culture Shock",
        card_id="art_52_33",  # (-_-)
        asset_direction="Dialogue of confused international student trying to decipher foreign supermarket ingredient labels.",
        canonical_title="The U-Curve of Culture Shock in Study Abroad",
        ascii_label="culture-shock-supermarket-stare",
        ascii_alt="Dialogue showing foreign student bewildered by grocery labels abroad",
        title="The Four Stages of International Culture Shock",
        hook="Week 1: 'Everything here is magical!' $\\rightarrow$ Month 2: 'Why is all the milk unpasteurized and where is my favorite tea?'",
        body="""The psychological **U-Curve of Adaptation**:

1. **Honeymoon Phase**: High excitement, tourist curiosity.
2. **Culture Shock & Frustration**: Daily cognitive exhaustion from foreign language, bureaucracy, and unfamiliar social norms.
3. **Adjustment**: Building local routines, cross-cultural friendships, and language fluency.
4. **Integration/Biculturalism**: Comfortably navigating both cultural contexts.""",
        custom_art_override="""[STUDENT]: "Is this salt or sugar?"
    \\
  (-_-) <--- [FOREIGN GROCERY AISLE]
  /| |\\
  /   \\""",
    ),
    ExampleSpec(
        topic_slug="study-abroad-full-guide",
        topic_name="Study Abroad Full Guide",
        subtopic_name="Crafting Admissions Essays & Statements of Purpose",
        difficulty="Intermediate",
        example_type="INFORMATIVE",
        descriptive_name="Statement of Purpose Narrative Architecture",
        card_id="aa868273222af847",  # Academic graduation mortarboard cap with hanging tassel
        asset_direction="Graduation cap drawing worn by graduate labeled with 3-act SOP narrative structure.",
        canonical_title="Structure of a Winning Statement of Purpose (SOP)",
        ascii_label="sop-admissions-mortarboard",
        ascii_alt="Graduation mortarboard cap drawing illustrating university SOP structure",
        title="The 3-Act Structure of a Winning SOP",
        hook="Admissions committees read 500 essays a week; opening with 'I have loved computers since childhood' guarantees rejection.",
        body="""How to structure an elite graduate university Statement of Purpose:

1. **Specific Problem Statement (Act I)**: Open immediately with the exact research question or industry bottleneck you aim to solve.
2. **Demonstrated Competence (Act II)**: Quantified past projects, publications, and specific technical failures you overcame.
3. **Institutional Alignment (Act III)**: Name specific lab facilities, professors, and course modules unique to that university.""",
        custom_art_override="""   |""-..._____   [GRADUATION SOP]
     '-.____    _  Act I: Problem
         \\  ``` `` Act II: Proof
         |         Act III: Lab Fit
         }--..____
        }}}}} _  _
        }}}}  6  6  (Admissions Success)""",
    ),

    # 20. System Design & Distributed Systems
    ExampleSpec(
        topic_slug="system-design--distributed-systems",
        topic_name="System Design & Distributed Systems",
        subtopic_name="CAP Theorem and PACELC",
        difficulty="Intermediate",
        example_type="GAG",
        descriptive_name="Network Partition Split-Brain Panic",
        card_id="b1be10c26aff68cb",  # Wide-eyed cat face
        asset_direction="Dialogue between two partitioned database nodes both claiming to be the active primary leader.",
        canonical_title="CAP Theorem and Split-Brain Partitioning",
        ascii_label="split-brain-network-partition",
        ascii_alt="Dialogue between two partitioned database nodes causing split-brain syndrome",
        title="CAP Theorem: You Cannot Choose 'P'",
        hook="In distributed systems, network cables get cut; you don't choose Partition Tolerance, you choose how to fail when it happens.",
        body="""The **CAP Theorem** dictates that a distributed data store can guarantee at most two of three properties:

- **Consistency (C)**: Every read receives the most recent write or an error.
- **Availability (A)**: Every non-failing node returns a response (without guarantee of latest data).
- **Partition Tolerance (P)**: The system continues operating despite dropped messages between nodes.

When a network partition occurs, you must choose: reject writes (**CP**) or serve stale reads (**AP**).""",
        custom_art_override="""[NODE A]: "I am Leader!"
[NODE B]: "NO, I am Leader!"
       \\     /
        (O.o) <--- [SPLIT-BRAIN]
       (Network Partition)""",
    ),
    ExampleSpec(
        topic_slug="system-design--distributed-systems",
        topic_name="System Design & Distributed Systems",
        subtopic_name="Caching Strategies and Eviction Policies",
        difficulty="Advanced",
        example_type="INFORMATIVE",
        descriptive_name="Write-Through vs Write-Back Cache Coherency",
        card_id="c8c2873591e9a686",  # Glass hourglass with sand flowing
        asset_direction="Glass hourglass drawing with flowing sand grains illustrating TTL eviction and write synchronization.",
        canonical_title="Cache Invalidation & Write Patterns",
        ascii_label="cache-coherency-hourglass",
        ascii_alt="Glass hourglass drawing showing TTL cache invalidation and database synchronization",
        title="Cache-Aside vs Write-Through Patterns",
        hook="There are only two hard things in Computer Science: cache invalidation and naming things.",
        body="""Choosing the right caching topology for high-throughput architectures:

| Strategy | Write Path | Read Path | Trade-Off |
| :--- | :--- | :--- | :--- |
| **Cache-Aside** | Application writes to DB, invalidates cache | Read cache; on miss, load from DB | Cache misses incur dual latency |
| **Write-Through** | Write to cache $\\rightarrow$ cache writes to DB synchronously | Always read cache | Higher write latency |
| **Write-Behind (Back)**| Write to cache immediately $\\rightarrow$ async flush to DB | Ultra-fast read/write | Data loss if cache crashes before flush |""",
        custom_art_override="""     .====.
     |(::)|   [CACHE TTL EXPIRY]
     | )( |   Sand runs out ->
     |(..)|   Evict & refresh DB
     +====+   (Write-Through / Aside)""",
    ),

    # 21. The Epic of Gilgamesh
    ExampleSpec(
        topic_slug="the-epic-of-gilgamesh",
        topic_name="The Epic of Gilgamesh",
        subtopic_name="The Death of Enkidu and Gilgamesh's Grief",
        difficulty="Intermediate",
        example_type="GAG",
        descriptive_name="Mermaid Lounging on Seafloor Mocking Gilgamesh",
        card_id="64f4d9d0328c6009",  # Mermaid lounging on sea floor next to starfish
        asset_direction="Mermaid lounging on ocean seafloor asking Gilgamesh how a water serpent stole his flower of eternal youth.",
        canonical_title="The Stolen Youth Plant and Mortal Reality",
        ascii_label="mermaid-gilgamesh-youth-plant",
        ascii_alt="Mermaid lounging on seafloor asking Gilgamesh about the lost immortality plant",
        title="The Oldest Anti-Climax in Human Literature",
        hook="Gilgamesh dove to the bottom of the cosmic ocean for the flower of eternal youth, only for a snake to eat it while he took a bath.",
        body="""The climax of the world's oldest surviving literary epic (*Tablet XI*):

- **The Quest**: Devastated by the death of his friend Enkidu, King Gilgamesh travels beyond the waters of death to obtain immortality.
- **The Loss**: While bathing in a cold spring, a water serpent smells the magical flower, snatches it, and sheds its skin—rejuvenating itself while leaving Gilgamesh weeping on the shore.
- **The Moral**: Humanity cannot escape physical death; our only immortality is the virtue of our deeds and the walls we build for our cities.""",
        custom_art_override=""".-""-.                 [MERMAID]:
  (___/\\ \\             "Did a snake
  (|^ ^ ) )             steal your
 _)_\\=_/  (             youth plant?"
(_/_ ` \\   )                 \\
  (_)_  `\\ (           [GILGAMESH]:
    (_), |  )          (;_;) "Yes..."
   __.'_| |__/
  `~----\"`""",
    ),
    ExampleSpec(
        topic_slug="the-epic-of-gilgamesh",
        topic_name="The Epic of Gilgamesh",
        subtopic_name="The Bond of Friendship: Gilgamesh and Enkidu",
        difficulty="Intermediate",
        example_type="INFORMATIVE",
        descriptive_name="Mesopotamian Cuneiform Epic & The Wild Man Archetype",
        card_id="e2674480576895fe",  # Stack of hardbound academic textbooks
        asset_direction="Ancient Mesopotamian clay tablet drawing detailing King Gilgamesh and the Wild Man Enkidu.",
        canonical_title="Civilization vs Wilderness: Gilgamesh and Enkidu",
        ascii_label="mesopotamian-cuneiform-tablet",
        ascii_alt="Mesopotamian clay tablet drawing illustrating the epic of Gilgamesh and Enkidu",
        title="The Mirror of the Soul: Enkidu and the Wild Archetype",
        hook="Enkidu was created by the gods from raw clay to be a wild counterweight to the tyrannical urban pride of King Gilgamesh.",
        body="""The thematic heart of the Mesopotamian epic:

1. **The Transformation**: Enkidu begins as an untamed beast living among gazelles until humanized by Shamhat through bread, beer, and intimacy.
2. **The Sacred Bond**: When Gilgamesh and Enkidu wrestle in Uruk, their equal strength transforms rivalry into brotherhood.
3. **The Lesson of Uruk**: Returning home empty-handed, Gilgamesh gazes upon the brickwork walls of Uruk and finally accepts his human mortality.""",
        custom_art_override="""     .--------------.
    /  TABLET XI    /|  [GILGAMESH EPIC]
   +--------------+ |  King of Uruk &
   | Cuneiform    | |  Enkidu: Hubris
   | Youth Stolen | /  meets Nature.
   +--------------+'   (Mortality)""",
    ),
]


def generate_examples_file() -> None:
    output_blocks = [
        "# SPOIN ART GENERATOR — WORKED FEW-SHOT PROMPTING EXAMPLES",
        "# Sourced directly from use_for_gags.txt and use_for_informative_visualization.txt",
        "# Covering all 21 active database topics with exactly 1 Gag and 1 Informative card each.",
        f"# Total Examples: {len(SPECS)} (21 Gags + 21 Informative)",
        "# Width limit: <= 40 monospace characters strictly verified on all ASCII art lines.",
        "# Style: Rich fancy pop-culture / trendy GenZ illustrative ASCII artwork with dialogues & labels.",
        "# Note: Text-only flowcharts/boxes are prohibited in ASCII art (handled by Mermaid agent).",
        "",
    ]

    for idx, spec in enumerate(SPECS, 1):
        # Retrieve art from cards
        if spec.example_type == "GAG":
            src_file = "use_for_gags.txt"
            card_info = gag_cards.get(spec.card_id)
            if not card_info:
                card_info = info_cards.get(spec.card_id)
                if card_info:
                    src_file = "use_for_informative_visualization.txt"
        else:
            src_file = "use_for_informative_visualization.txt"
            card_info = info_cards.get(spec.card_id)
            if not card_info:
                card_info = gag_cards.get(spec.card_id)
                if card_info:
                    src_file = "use_for_gags.txt"

        if not card_info:
            # Fallback search if id not direct
            candidates = {**gag_cards, **info_cards}
            card_info = next((v for k, v in candidates.items() if spec.card_id in k or spec.card_id in v["title"]), None)

        if not card_info:
            raise ValueError(f"Could not find card '{spec.card_id}' in {src_file}")

        art_text = spec.custom_art_override if spec.custom_art_override is not None else card_info["art"]
        art_lines = art_text.split("\n")
        indented_art = "\n".join("    " + line for line in art_lines)

        # Check line width
        for l_num, line in enumerate(art_lines, 1):
            if len(line) > 40:
                raise ValueError(f"Width violation (>40) in {spec.card_id} line {l_num}: {len(line)} chars: {line!r}")

        block = f"""=== EXAMPLE {idx} ({spec.topic_slug.upper()} - {spec.example_type}): {spec.descriptive_name} ===
Source Reference: {src_file} (ID: {card_info['id']} | TITLE: {card_info['title']})
Topic: {spec.topic_name}
Subtopic: {spec.subtopic_name}
Difficulty: {spec.difficulty}

[Asset Direction]:
{spec.asset_direction}

[Generated LLM Output]:
canonical_title: "{spec.canonical_title}"
card_type: "ascii"
ascii_label: "{spec.ascii_label}"
ascii_art: |
{indented_art}
ascii_alt: "{spec.ascii_alt}"
title: "{spec.title}"
hook: "{spec.hook}"
body: |
{re.sub(r'(?m)^', '  ', spec.body.strip())}
"""
        output_blocks.append(block)

    full_text = "\n".join(output_blocks) + "\n"

    OUT_1.write_text(full_text, encoding="utf-8")
    OUT_2.write_text(full_text, encoding="utf-8")
    print(f"Successfully generated {len(SPECS)} examples in:")
    print(f" - {OUT_1}")
    print(f" - {OUT_2}")


if __name__ == "__main__":
    generate_examples_file()
