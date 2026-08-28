# -*- coding: utf-8 -*-
"""Full decision map for Batch 5: indexes 1901 to 2486 (info part 3, end of library)."""
import json, io

entries = json.load(open(r"C:\Temp\entries.json", encoding="utf-8"))

def get_batch5():
    d = {}
    
    # 1901: clothing-and-accessories/umbrellas
    d[1901] = ("RETITLE", "Closed black umbrella with wooden curved handle standing upright")
    
    # 1902..1914: computers/mouse (13 computer mice)
    d[1902] = ("RETITLE", "Computer optical mouse with scroll wheel and connecting USB cord")
    d[1903] = ("RETITLE", "Classic two-button mechanical roller ball computer mouse")
    d[1904] = ("RETITLE", "Ergonomic wireless computer mouse with side thumb grip buttons")
    d[1905] = ("RETITLE", "Computer mouse resting on a rectangular fabric foam mousepad")
    d[1906] = ("RETITLE", "Three-button computer workstation mouse with central button")
    d[1907] = ("RETITLE", "Hand grasping and moving a computer mouse on a desktop surface")
    d[1908] = ("RETITLE", "Retro vintage 1980s angular single-button computer mouse")
    d[1909] = ("RETITLE", "Gaming computer mouse with customizable RGB lighting and weights")
    d[1910] = ("RETITLE", "Trackball computer mouse with thumb-operated stationary rolling sphere")
    d[1911] = ("RETITLE", "Computer mouse with curling tangled USB connecting wire cable")
    d[1912] = ("RETITLE", "Minimalist single-click slim profile travel laptop mouse")
    d[1913] = ("RETITLE", "Computer mouse showing internal circuit board and click microswitches")
    d[1914] = ("RETITLE", "Computer mouse and keyboard set on modern office workspace")
    
    # 1915..1930: miscellaneous/candles (16 candles)
    d[1915] = ("RETITLE", "Lit wax taper candle standing in an ornate brass candlestick holder")
    d[1916] = ("RETITLE", "Thick pillar candle burning with melting wax dripping down sides")
    d[1917] = ("RETITLE", "Three burning candles in a triangular ceremonial candlestick arrangement")
    d[1918] = ("RETITLE", "Small tea light candle burning in a round metal cup")
    d[1919] = ("RETITLE", "Candle flame flickering with a delicate curling wisp of smoke")
    d[1920] = ("RETITLE", "Decorative scented candle burning inside a round glass jar")
    d[1921] = ("RETITLE", "Pair of tall dining table candles in silver candelabra branches")
    d[1922] = ("RETITLE", "Candle snuffer bell tool putting out a burning candle flame")
    d[1923] = ("RETITLE", "Burning candle illuminating a dark room with gentle warm glow")
    d[1924] = ("RETITLE", "Candle sitting in an antique chamberstick holder with ring handle")
    d[1925] = ("RETITLE", "Melting candle stub burned down to a pool of wax")
    d[1926] = ("RETITLE", "Floating candle blossom burning on water in a decorative bowl")
    d[1927] = ("RETITLE", "Seven-branch menorah candelabrum with all seven candles illuminated")
    d[1928] = ("RETITLE", "Spiral twisted taper candle standing in a ceramic holder base")
    d[1929] = ("RETITLE", "Hand holding a burning matchstick to light a candle wick")
    d[1930] = ("RETITLE", "Advent wreath with four burning purple and pink holiday candles")
    
    # 1931..1933: sports-and-outdoors/tennis
    d[1931] = ("RETITLE", "Tennis racket with strung grid face crossing over fuzzy tennis ball")
    d[1932] = ("RETITLE", "Tennis player executing a high overhead smashing serve stroke")
    d[1933] = ("RETITLE", "Tennis court net dividing green playing surface with baseline mark")
    
    # 1934: clothing-and-accessories/bra -> DELETE nsfw
    d[1934] = ("DELETE", "nsfw")
    
    # 1935..1936: television/doctor-who
    d[1935] = ("RETITLE", "TARDIS time machine police box materializing through the vortex")
    d[1936] = ("RETITLE", "Sonic Screwdriver futuristic scanning wand tool with illuminated tip")
    
    # 1937..1939: food-and-drinks/chocolates
    d[1937] = ("RETITLE", "Chocolate bar divided into segmented rectangular bite-sized squares")
    d[1938] = ("RETITLE", "Box of assorted gourmet chocolate truffles in paper cups")
    d[1939] = ("RETITLE", "Heart-shaped Valentine chocolate box with decorative ribbon bow")
    
    # 1940..1941: sports-and-outdoors/golf
    d[1940] = ("RETITLE", "Golf ball resting on a wooden tee with driver club head behind")
    d[1941] = ("RETITLE", "Golf flagstick pin standing in cup hole on green putting surface")
    
    # 1942..1944: computers/sun-microsystems
    d[1942] = ("RETITLE", "Sun Microsystems rotational symmetrical SUN diamond logo emblem")
    d[1943] = ("RETITLE", "Sun SPARC workstation computer tower with dual monitor displays")
    d[1944] = ("RETITLE", "Sun Microsystems server rack chassis unit in data center")
    
    # 1945..1952: sports-and-outdoors/basketball
    d[1945] = ("RETITLE", "Basketball ball with pebbled leather surface and black channel seams")
    d[1946] = ("RETITLE", "Basketball swooshing through iron rim hoop and white string net")
    d[1947] = ("RETITLE", "Basketball player leaping high in air to slam dunk ball")
    d[1948] = ("RETITLE", "Basketball backboard with square target box and mounted rim hoop")
    d[1949] = ("RETITLE", "Pair of high-top basketball athletic sneaker shoes")
    d[1950] = ("RETITLE", "Basketball player dribbling ball past defending opponent on court")
    d[1951] = ("RETITLE", "Three-point arc and key court markings on hardwood basketball gym floor")
    d[1952] = ("RETITLE", "Championship basketball trophy with gold basketball mounted on pillar")
    
    # 1953..1954: electronics/other
    d[1953] = ("RETITLE", "Printed circuit board PCB with electronic copper traces and solder pads")
    d[1954] = ("RETITLE", "Electronic microchip integrated circuit IC with dual row connector pins")
    
    # 1955..1958: computers/other
    d[1955] = ("RETITLE", "Ethernet RJ45 network cable connector plug with flexible release tab")
    d[1956] = ("RETITLE", "Computer hard disk drive HDD with spinning magnetic platter and read head")
    d[1957] = ("RETITLE", "Universal Serial Bus USB flash memory thumb drive stick")
    d[1958] = ("RETITLE", "Compact Disc CD optical media disk showing circular central hub hole")
    
    # 1959..1960: clothing-and-accessories/overalls
    d[1959] = ("RETITLE", "Denim carpenter bib overalls with adjustable shoulder buckle straps")
    d[1960] = ("RETITLE", "Farmer work overalls with front chest pocket and tool loop")
    
    # 1961..1965: sports-and-outdoors/darts
    d[1961] = ("RETITLE", "Round dartboard with numbered segments and centered red bullseye")
    d[1962] = ("RETITLE", "Three steel-tip darts sticking directly into the central bullseye")
    d[1963] = ("RETITLE", "Feather-flighted dart flying through the air toward dartboard target")
    d[1964] = ("RETITLE", "Pair of crossed darts with brass barrels and flights")
    d[1965] = ("RETITLE", "Dartboard cabinet with open wooden doors and chalk scoreboard")
    
    # 1966..1969: vehicles/motorcycles
    d[1966] = ("RETITLE", "Cruiser motorcycle with chrome exhaust pipes and raised handlebars")
    d[1967] = ("RETITLE", "Sport racing motorcycle superbike with aerodynamic fairings and windshield")
    d[1968] = ("RETITLE", "Vintage classic motorcycle with spoked wheels and teardrop fuel tank")
    d[1969] = ("RETITLE", "Motorcycle helmet with tinted face shield visor and chin strap")
    
    # 1970..1979: art-and-design/fleur-de-lis (10 fleur-de-lis)
    d[1970] = ("RETITLE", "Royal Fleur-de-lis heraldic lily flower emblem with binding crossband")
    d[1971] = ("RETITLE", "Stylized Fleur-de-lis symbol drawn in bold symmetrical silhouette lines")
    d[1972] = ("RETITLE", "Ornate medieval Fleur-de-lis with curled outer petals and central spear")
    d[1973] = ("RETITLE", "French royal coat of arms Fleur-de-lis on decorative shield")
    d[1974] = ("RETITLE", "Three golden Fleur-de-lis emblems arranged in triangular heraldic formation")
    d[1975] = ("RETITLE", "Celtic knotwork Fleur-de-lis interwoven with continuous ribbon bands")
    d[1976] = ("RETITLE", "Gothic architectural Fleur-de-lis stone carving finial crest")
    d[1977] = ("RETITLE", "Fleur-de-lis crest framed by an ornamental circular filigree border")
    d[1978] = ("RETITLE", "Imperial Fleur-de-lis symbol adorned with crown and laurel leaves")
    d[1979] = ("RETITLE", "Intricate shaded Fleur-de-lis emblem with decorative banner ribbon")
    
    # 1980..1981: food-and-drinks/bananas
    d[1980] = ("RETITLE", "Single peeled banana with skin peeled back in three sections")
    d[1981] = ("RETITLE", "Bunch of four yellow ripe bananas attached at the crown stem")
    
    # 1982..1986: miscellaneous/badges
    d[1982] = ("RETITLE", "Six-pointed sheriff star badge with circular tips on star points")
    d[1983] = ("RETITLE", "Police officer shield badge with eagle crest and centered badge number")
    d[1984] = ("RETITLE", "Military service award medal ribbon pinned onto uniform cloth")
    d[1985] = ("RETITLE", "Round pinback button badge with personalized slogan text area")
    d[1986] = ("RETITLE", "Security officer badge emblem with banner ribbon and laurel wreath")
    
    # 1987..1988: vehicles/busses
    d[1987] = ("RETITLE", "City transit commuter bus with passenger windows and destination sign")
    d[1988] = ("RETITLE", "London red double-decker bus with upper and lower passenger decks")
    
    # 1989..1990: miscellaneous/chains
    d[1989] = ("RETITLE", "Heavy interlocking iron chain links stretched in horizontal line")
    d[1990] = ("RETITLE", "Broken chain with snapped link representing freedom and liberation")
    
    # 1991..1994: buildings-and-places/castles
    d[1991] = ("RETITLE", "Medieval stone castle with crenellated battlement towers and portcullis gate")
    d[1992] = ("RETITLE", "Fairy tale fantasy castle with tall soaring spires and flying pennants")
    d[1993] = ("RETITLE", "Castle fortress surrounded by deep water moat and lowered drawbridge")
    d[1994] = ("RETITLE", "Stone castle keep tower standing on a rocky defensive hill")
    
    # 1995: sports-and-outdoors/rodeo
    d[1995] = ("RETITLE", "Rodeo cowboy riding a bucking bronco horse with one hand raised")
    
    # 1996: computers/amiga
    d[1996] = ("RETITLE", "Commodore Amiga computer checkmark check logo symbol")
    
    # 1997..2005: space/stars (9 stars)
    d[1997] = ("RETITLE", "Five-pointed geometric star drawn in crisp outline symmetry")
    d[1998] = ("RETITLE", "Four-pointed twinkling celestial diamond star radiating light flares")
    d[1999] = ("RETITLE", "Constellation star chart pattern connecting stars with dashed lines")
    d[2000] = ("RETITLE", "Shooting star meteor burning across night sky with streaking tail")
    d[2001] = ("RETITLE", "Cluster of sparkling stars twinkling in deep interstellar space")
    d[2002] = ("RETITLE", "Eight-pointed nautical compass star symbol with shaded facets")
    d[2003] = ("RETITLE", "Crescent moon cradling a glowing five-pointed star in its curve")
    d[2004] = ("RETITLE", "Supernova star explosion radiating powerful cosmic energy shockwaves")
    d[2005] = ("RETITLE", "Circle of twelve golden stars arranged in heraldic ring formation")
    
    # 2006..2011: mythology/phoenix
    d[2006] = ("RETITLE", "Mythical phoenix bird rising majestic from burning fire flames")
    d[2007] = ("RETITLE", "Phoenix soaring with spread flaming wings and trailing tail plumage")
    d[2008] = ("RETITLE", "Immortal phoenix bird reborn from its nest of glowing ashes")
    d[2009] = ("RETITLE", "Phoenix silhouette with blazing plumage and fiery crest feathers")
    d[2010] = ("RETITLE", "Heraldic phoenix displayed with wings elevated and head crowned")
    d[2011] = ("RETITLE", "Fiery firebird swooping down with talons outstretched")
    
    # 2012: miscellaneous/fire-extinguishers
    d[2012] = ("RETITLE", "Red pressurized fire extinguisher canister with nozzle hose and pin")
    
    # 2013..2019: sports-and-outdoors/chess
    d[2013] = ("RETITLE", "Chess King piece standing tall with cross finial on crown")
    d[2014] = ("RETITLE", "Chess Queen piece with coronet peaks and flared base pedestal")
    d[2015] = ("RETITLE", "Chess Knight piece sculpted in profile as a horse head")
    d[2016] = ("RETITLE", "Chess Rook castle tower piece with crenellated battlement top")
    d[2017] = ("RETITLE", "Chess Bishop piece with miter hat and cleft cross notch")
    d[2018] = ("RETITLE", "Chess Pawn piece with round spherical ball head on pedestal")
    d[2019] = ("RETITLE", "Checkered sixty-four square chessboard with pieces in starting ranks")
    
    # 2020..2023: logos/peace
    d[2020] = ("RETITLE", "International peace sign symbol with circle and downward fork lines")
    d[2021] = ("RETITLE", "Peace sign adorned with blooming floral vine flower garland")
    d[2022] = ("RETITLE", "Hand making the two-finger V peace victory sign gesture")
    d[2023] = ("RETITLE", "Peace dove flying with olive branch held in its beak")
    
    # 2024..2028: clothing-and-accessories/underwear -> DELETE nsfw
    for idx in range(2024, 2029):
        d[idx] = ("DELETE", "nsfw")
        
    # 2029..2030: buildings-and-places/fences
    d[2029] = ("RETITLE", "White wooden picket fence row running along garden border")
    d[2030] = ("RETITLE", "Rustic wooden split-rail farm fence with intersecting logs")
    
    # 2031..2044: plants/cactus (14 cacti)
    d[2031] = ("RETITLE", "Tall saguaro desert cactus with two upward curving branching arms")
    d[2032] = ("RETITLE", "Potted prickly pear cactus with flat oval pads and blooming flower")
    d[2033] = ("RETITLE", "Barrel cactus with round ribbed body covered in sharp spines")
    d[2034] = ("RETITLE", "Cactus growing in a terracotta pot on a sunny windowsill")
    d[2035] = ("RETITLE", "Desert landscape with three branching saguaro cacti under scorching sun")
    d[2036] = ("RETITLE", "Flowering desert cactus blossom blooming bright on spiny stem")
    d[2037] = ("RETITLE", "Organ pipe cactus with multiple vertical ribbed stems rising together")
    d[2038] = ("RETITLE", "Small succulent cactus in decorative ceramic glazed mug planter")
    d[2039] = ("RETITLE", "Cactus with blooming red flower growing in cracked dry soil")
    d[2040] = ("RETITLE", "Cute cartoon cactus smiling happily inside a striped flowerpot")
    d[2041] = ("RETITLE", "Saguaro cactus silhouette standing stark against a desert sunset")
    d[2042] = ("RETITLE", "Collection of miniature potted cacti and succulents on shelf")
    d[2043] = ("RETITLE", "Cactus pad sprouting new baby nopalito pads from edges")
    d[2044] = ("RETITLE", "Spiny desert cactus beside an animal steer skull in sand")
    
    # 2045..2049: sports-and-outdoors/ice-skating
    d[2045] = ("RETITLE", "Figure skater spinning gracefully on one ice skate in arabesque pose")
    d[2046] = ("RETITLE", "Pair of white leather figure ice skates with sharp toe picks")
    d[2047] = ("RETITLE", "Speed skater crouching low in streamlined racing posture on ice")
    d[2048] = ("RETITLE", "Ice skater performing a camel spin with leg extended backward")
    d[2049] = ("RETITLE", "Figure skating pair executing a dramatic overhead lift on ice")
    
    # 2050..2098: animals/birds-land (49 land birds)
    d[2050] = ("RETITLE", "Barn owl perched quietly on a wooden beam with heart-shaped face")
    d[2051] = ("RETITLE", "Bald eagle perching on a craggy mountain cliff ledge")
    d[2052] = ("RETITLE", "Hawk in flight with broad spread wings and fanned tail feathers")
    d[2053] = ("RETITLE", "Peregrine falcon diving at high speed with wings tucked back")
    d[2054] = ("RETITLE", "Peacock displaying magnificent iridescent fanned eye-spotted tail train")
    d[2055] = ("RETITLE", "Tiny hummingbird hovering in midair feeding from a flower blossom")
    d[2056] = ("RETITLE", "Parrot macaw perched on a tropical branch with long tail feathers")
    d[2057] = ("RETITLE", "Toucan with large colorful curved bill perched in rainforest tree")
    d[2058] = ("RETITLE", "Woodpecker clinging vertically to a tree trunk drilling wood")
    d[2059] = ("RETITLE", "Robin bird singing perched on a garden spade handle")
    d[2060] = ("RETITLE", "Cockatoo with raised feathered crest standing on a perch bar")
    d[2061] = ("RETITLE", "Blue jay bird perched on an evergreen branch with crested head")
    d[2062] = ("RETITLE", "Cardinal songbird with pointed crest perching on snowy pine bough")
    d[2063] = ("RETITLE", "Crow raven perched on an old wooden fence post looking alert")
    d[2064] = ("RETITLE", "Swallow bird soaring with long deeply forked aerodynamic tail")
    d[2065] = ("RETITLE", "Dove of peace flying carrying a green olive twig in bill")
    d[2066] = ("RETITLE", "Pigeon standing on city pavement pecking at bread crumbs")
    d[2067] = ("RETITLE", "Ostrich standing tall on long legs with large inquisitive eyes")
    d[2068] = ("RETITLE", "Canary songbird singing inside an open decorative wire cage")
    d[2069] = ("RETITLE", "Rooster crowing proudly at dawn with red comb and wattle")
    d[2070] = ("RETITLE", "Hen sitting on a straw nest incubating a clutch of eggs")
    d[2071] = ("RETITLE", "Fluffy baby chick freshly hatched standing beside cracked eggshell")
    d[2072] = ("RETITLE", "Pheasant bird walking through meadow with long barred tail plumage")
    d[2073] = ("RETITLE", "Turkey displaying broad fanned tail feathers and neck snood")
    d[2074] = ("RETITLE", "Vulture perching on a dead tree limb scanning desert below")
    d[2075] = ("RETITLE", "Kingfisher bird perched over water holding a small silver fish")
    d[2076] = ("RETITLE", "Budgerigar parakeet resting on a swinging wooden cage ring")
    d[2077] = ("RETITLE", "Lovebirds pair of two colorful parakeets snuggling on a branch")
    d[2078] = ("RETITLE", "Bird feeding three chirping baby nestlings in a woven twig nest")
    d[2079] = ("RETITLE", "Sparrow bathing and splashing happily in a stone garden birdbath")
    d[2080] = ("RETITLE", "Stork standing in a large rooftop chimney nest in Europe")
    d[2081] = ("RETITLE", "Roadrunner bird sprinting swiftly across arid desert scrubland")
    d[2082] = ("RETITLE", "Kiwi flightless bird probing soil with long slender curved beak")
    d[2083] = ("RETITLE", "Emu bird standing upright with shaggy grey-brown plumage")
    d[2084] = ("RETITLE", "Great horned owl with prominent feathered ear tufts staring ahead")
    d[2085] = ("RETITLE", "Flamingo flock feeding in a shallow pink tropical salt lake")
    d[2086] = ("RETITLE", "Quail running through underbrush with curved head plume feather")
    d[2087] = ("RETITLE", "Magpie bird perched on a branch showing black and white feathers")
    d[2088] = ("RETITLE", "Cockatiel with orange cheek patches and elegant yellow crest")
    d[2089] = ("RETITLE", "Cuckoo bird emerging from a wooden clock doorway to chime")
    d[2090] = ("RETITLE", "Seagull perching on a wooden pier piling overlooking harbour")
    d[2091] = ("RETITLE", "Falcon sitting hooded on a leather falconer training glove")
    d[2092] = ("RETITLE", "Birdhouse wooden nesting box hanging from a leafy tree limb")
    d[2093] = ("RETITLE", "Two birds singing a musical duet on telephone wire line")
    d[2094] = ("RETITLE", "Bird silhouette flying across the glowing disc of full moon")
    d[2095] = ("RETITLE", "Weaver bird building an intricate hanging woven nest from grass")
    d[2096] = ("RETITLE", "Blackbird singing on a blooming cherry tree blossom bough")
    d[2097] = ("RETITLE", "Screech owl peeking out from a hollow tree knot hole")
    d[2098] = ("RETITLE", "Flock of migrating birds flying in a V-shaped sky formation")
    
    # 2099..2104: miscellaneous/dice
    d[2099] = ("RETITLE", "Pair of six-sided gaming dice showing rolling dots on faces")
    d[2100] = ("RETITLE", "Single die showing six pips on the top facing surface")
    d[2101] = ("RETITLE", "Twenty-sided icosahedron D20 tabletop roleplaying gaming die")
    d[2102] = ("RETITLE", "Pair of lucky rolling dice showing seven total points")
    d[2103] = ("RETITLE", "Four-sided tetrahedral D4 die with numbered triangle faces")
    d[2104] = ("RETITLE", "Set of polyhedral tabletop RPG dice including D4 D6 D8 D10 D12 D20")
    
    # 2105..2109: sports-and-outdoors/swimming
    d[2105] = ("RETITLE", "Swimmer performing front crawl freestyle stroke in pool lane")
    d[2106] = ("RETITLE", "Swimmer executing a butterfly stroke with both arms emerging from water")
    d[2107] = ("RETITLE", "Competitive swimmer diving off starting block into race pool")
    d[2108] = ("RETITLE", "Swimmer backstroking through water with one arm arched overhead")
    d[2109] = ("RETITLE", "Pair of swimming goggles and silicone swim cap on deck")
    
    # 2110..2111: weapons/guns
    d[2110] = ("RETITLE", "Revolver handgun pistol with rotating six-chamber cylinder and barrel")
    d[2111] = ("RETITLE", "Semi-automatic pistol with slide, trigger, and magazine grip")
    
    # 2112..2119: animals/deer
    d[2112] = ("RETITLE", "Stag buck deer standing majestic with multi-point branched antlers")
    d[2113] = ("RETITLE", "Doe deer grazing quietly with ears perked in alert posture")
    d[2114] = ("RETITLE", "Young spotted fawn deer resting curled in forest ferns")
    d[2115] = ("RETITLE", "Deer stag silhouette standing on a mountain ridge at twilight")
    d[2116] = ("RETITLE", "Buck deer leaping gracefully over a fallen forest log")
    d[2117] = ("RETITLE", "Reindeer caribou with broad sweeping antlers in snowy tundra")
    d[2118] = ("RETITLE", "Deer head portrait with noble gaze and symmetrical antler rack")
    d[2119] = ("RETITLE", "Pair of male stag deer locking antlers in autumn rutting battle")
    
    # 2120..2122: computers/fonts -> DELETE unsuitable (non-pictorial font samples)
    d[2120] = ("DELETE", "unsuitable")
    d[2121] = ("DELETE", "unsuitable")
    d[2122] = ("DELETE", "unsuitable")
    
    # 2123..2126: electronics/blender
    d[2123] = ("RETITLE", "Electric kitchen countertop blender with measurement markings on pitcher")
    d[2124] = ("RETITLE", "Blender blending a fruit smoothie with swirling vortex liquid")
    d[2125] = ("RETITLE", "Food processor appliance with stainless steel chopping blades")
    d[2126] = ("RETITLE", "Immersion hand stick blender pureeing soup in a saucepan")
    
    # 2127..2128: nature/islands
    d[2127] = ("RETITLE", "Small deserted tropical island with single palm tree in ocean")
    d[2128] = ("RETITLE", "Island with sandy beach, volcano peak, and surrounding coral reef")
    
    # 2129..2130: music/other
    d[2129] = ("RETITLE", "Vintage gramophone phonograph with large brass flower horn speaker")
    d[2130] = ("RETITLE", "Vinyl record turntable player with tone arm needle on record")
    
    # 2131..2134: buildings-and-places/maps
    d[2131] = ("RETITLE", "World map outline showing seven continental landmasses")
    d[2132] = ("RETITLE", "Treasure map with dotted trail path leading to X marks spot")
    d[2133] = ("RETITLE", "Navigation map with compass rose and nautical grid coordinates")
    d[2134] = ("RETITLE", "Topographic contour map showing elevation lines and mountain terrain")
    
    # 2135..2142: miscellaneous/medical
    d[2135] = ("RETITLE", "Medical stethoscope instrument with ear pieces, tubing, and chest piece")
    d[2136] = ("RETITLE", "First aid medical emergency kit box with red cross symbol")
    d[2137] = ("RETITLE", "Medical syringe needle with calibrated milliliter measurement barrel")
    d[2138] = ("RETITLE", "Adhesive bandage strip plaster covering a healing skin wound")
    d[2139] = ("RETITLE", "Prescription medicine bottle filled with pharmaceutical pills")
    d[2140] = ("RETITLE", "Clinical glass fever thermometer displaying mercury level temperature")
    d[2141] = ("RETITLE", "Hospital heartbeat pulse line rhythm displaying on cardiac monitor screen")
    d[2142] = ("RETITLE", "Ambulance emergency rescue vehicle with rooftop flashing beacon lights")
    
    # 2143..2145: electronics/electronics
    d[2143] = ("RETITLE", "Electronic digital multimeter testing voltage with dual probe leads")
    d[2144] = ("RETITLE", "Soldering iron tool applying molten solder wire to circuit board")
    d[2145] = ("RETITLE", "Oscilloscope electronic testing display showing sine wave voltage signal")
    
    # 2146..2153: logos/caduceus (8 caduceus)
    d[2146] = ("RETITLE", "Rod of Asclepius medical symbol with single serpent coiled around staff")
    d[2147] = ("RETITLE", "Caduceus heraldic staff with two intertwined serpents and winged tip")
    d[2148] = ("RETITLE", "Medical caduceus emblem enclosed inside an ornamental circular frame")
    d[2149] = ("RETITLE", "Asclepius snake staff displayed in clean symmetrical silhouette lines")
    d[2150] = ("RETITLE", "Winged caduceus symbol representing commerce, healing, and communication")
    d[2151] = ("RETITLE", "Caduceus medallion badge flanked by dual olive branch wreaths")
    d[2152] = ("RETITLE", "Staff of Asclepius with serpent coiling upward toward round pommel")
    d[2153] = ("RETITLE", "Detailed medical caduceus with textured scales on entwined serpents")
    
    # 2154..2155: clothing-and-accessories/pants
    d[2154] = ("RETITLE", "Pair of blue denim jeans trousers with front pockets and belt loops")
    d[2155] = ("RETITLE", "Formal dress trousers with pressed sharp front leg creases")
    
    # 2156..2159: plants/leaf
    d[2156] = ("RETITLE", "Single deciduous tree leaf with prominent central vein and serrated margin")
    d[2157] = ("RETITLE", "Autumn maple leaf showing five pointed lobes and petiole stem")
    d[2158] = ("RETITLE", "Oak tree leaf with rounded lobed margins and attached acorn")
    d[2159] = ("RETITLE", "Tropical Monstera deliciosa leaf with natural perforated fenestration holes")
    
    # 2160..2169: space/moons (10 moons)
    d[2160] = ("RETITLE", "Crescent moon shining in dark starry night sky")
    d[2161] = ("RETITLE", "Full moon celestial sphere displaying dark lunar crater maria")
    d[2162] = ("RETITLE", "Crescent moon with sleeping serene human facial profile features")
    d[2163] = ("RETITLE", "Gibbous moon phase showing more than half illuminated surface")
    d[2164] = ("RETITLE", "Half moon quarter phase with sharp terminator shadow line")
    d[2165] = ("RETITLE", "Moon surrounded by floating nighttime clouds and twinkling stars")
    d[2166] = ("RETITLE", "Lunar eclipse with reddish blood moon shadow covering surface")
    d[2167] = ("RETITLE", "Cute cartoon smiling crescent moon wearing a sleeping nightcap")
    d[2168] = ("RETITLE", "Moon reflecting bright silvery path across calm ocean waves")
    d[2169] = ("RETITLE", "Phases of the moon sequence from new moon to full moon")
    
    # 2170..2171: electronics/audio-equipment
    d[2170] = ("RETITLE", "Professional studio microphone on stand with circular pop filter")
    d[2171] = ("RETITLE", "Over-ear audio headphones with padded earcups and connecting headband")
    
    # 2172..2185: holiday-and-events/wedding (14 weddings)
    d[2172] = ("RETITLE", "Pair of interlocking golden wedding rings symbol of marriage")
    d[2173] = ("RETITLE", "Three-tiered wedding cake decorated with icing rosettes and topper")
    d[2174] = ("RETITLE", "Bride and groom miniature couple statuette standing atop a cake")

    d[2175] = ("RETITLE", "Wedding ceremony arch decorated with draped flowers and ribbons")
    d[2176] = ("RETITLE", "Bride in wedding gown holding a blooming floral bouquet")
    d[2177] = ("RETITLE", "Wedding bells ringing together tied with a celebratory ribbon bow")
    d[2178] = ("RETITLE", "Champagne flutes toasting together at a wedding reception party")
    d[2179] = ("RETITLE", "Groom sliding wedding ring onto bride finger during vows")
    d[2180] = ("RETITLE", "Wedding car with Just Married sign and tin cans trailing behind")
    d[2181] = ("RETITLE", "Two white wedding doves holding a ribbon banner in their beaks")
    d[2182] = ("RETITLE", "Wedding invitation scroll card tied with a satin ribbon band")
    d[2183] = ("RETITLE", "Bride and groom dancing their romantic first wedding dance")
    d[2184] = ("RETITLE", "Diamond engagement ring resting inside an open velvet ring box")
    d[2185] = ("RETITLE", "Wedding horseshoe good luck charm with ribbon and flower trim")
    
    # 2186..2191: art-and-design/celtic
    d[2186] = ("RETITLE", "Celtic Trinity knot Triquetra with three interwoven continuous loops")
    d[2187] = ("RETITLE", "Celtic cross with circular halo ring and knotwork strapwork patterns")
    d[2188] = ("RETITLE", "Interlocking Celtic knot band with continuous endless woven ribbon")
    d[2189] = ("RETITLE", "Celtic spiral Triskelion emblem with three rotational curved arms")
    d[2190] = ("RETITLE", "Celtic heart knot symbol interwoven from a single continuous cord")
    d[2191] = ("RETITLE", "Circular Celtic knot mandala medallion with intricate woven symmetry")
    
    # 2192..2196: food-and-drinks/coffee-and-tea
    d[2192] = ("RETITLE", "Steaming ceramic coffee mug with hot vapor rising from surface")
    d[2193] = ("RETITLE", "Espresso coffee cup on saucer with heart-shaped latte art foam")
    d[2194] = ("RETITLE", "Porcelain teapot with curved handle and spout pouring into teacup")
    d[2195] = ("RETITLE", "French press coffee maker with plunger filter pressing ground beans")
    d[2196] = ("RETITLE", "To-go paper coffee cup with plastic sipping lid and cardboard sleeve")
    
    # 2197..2239: art-and-design/escher (43 Escher tessellations and illusions)
    d[2197] = ("RETITLE", "M.C. Escher impossible staircase loop ascending continuously in square")
    d[2198] = ("RETITLE", "Escher tessellation of interlocking fish and bird repeating silhouettes")
    d[2199] = ("RETITLE", "Drawing Hands lithograph showing two hands sketching each other")
    d[2200] = ("RETITLE", "Escher impossible waterfall with water flowing uphill in a perpetual loop")
    d[2201] = ("RETITLE", "Tessellated pattern of interlocking lizards creeping in all directions")
    d[2202] = ("RETITLE", "Relativity illusion room with three intersecting gravity field staircases")
    d[2203] = ("RETITLE", "Hand with Reflecting Sphere holding a mirrored glass ball")
    d[2204] = ("RETITLE", "Ascending and Descending monk figures walking endlessly on castle roof")
    d[2205] = ("RETITLE", "Tessellation of flying pegasus winged horses interlocking seamlessly")
    d[2206] = ("RETITLE", "Metamorphosis pattern transitioning smoothly from checkerboard to reptiles")
    d[2207] = ("RETITLE", "Belvedere impossible architectural building with impossible column pillars")
    d[2208] = ("RETITLE", "Tessellation of interlocking angels and devils in circular disc")
    d[2209] = ("RETITLE", "Concave and Convex architectural optical illusion chamber perspective")
    d[2210] = ("RETITLE", "Three Worlds reflection showing autumn leaves floating above swimming fish")
    d[2211] = ("RETITLE", "Puddle reflection showing bare winter tree branches and bicycle tracks")
    d[2212] = ("RETITLE", "Print Gallery illusion expanding outwards in self-referential spiral")
    d[2213] = ("RETITLE", "Bond of Union two spiraling ribbon strips forming intertwined human faces")
    d[2214] = ("RETITLE", "Reptiles emerging from flat drawing pad onto books and desktop")
    d[2215] = ("RETITLE", "Sky and Water transition of fish in water becoming birds in sky")
    d[2216] = ("RETITLE", "Day and Night landscape with flying black and white geese tessellation")
    d[2217] = ("RETITLE", "Encounter figures stepping out of a wall into circular courtyard")
    d[2218] = ("RETITLE", "Dragon biting its own tail coiled in flat geometric perspective")
    d[2219] = ("RETITLE", "Butterflies tessellation filling plane with interlocking winged insects")
    d[2220] = ("RETITLE", "Snakes interlocking in a circular disk of concentric woven rings")
    d[2221] = ("RETITLE", "Whirlpools spiral stream with swimming fish chasing each other tails")
    d[2222] = ("RETITLE", "Stars polyhedron geometric stars floating in deep outer space")
    d[2223] = ("RETITLE", "Tetrahedral Planetoid miniature planet with buildings on four facets")
    d[2224] = ("RETITLE", "Cube with Magic Ribbons showing impossible interlocking ribbon loops")
    d[2225] = ("RETITLE", "Moebius Strip II ants crawling continuously along infinite surface")
    d[2226] = ("RETITLE", "Rind hollow spiral ribbon forming the sculpted shape of a human face")
    d[2227] = ("RETITLE", "Double Planetoid two interlocking geometric planet shapes in space")
    d[2228] = ("RETITLE", "Cycle boy running down stairs transforming into geometric tessellation")
    d[2229] = ("RETITLE", "House of Stairs robotic centipede creatures crawling on staircases")
    d[2230] = ("RETITLE", "Circle Limit III hyperbolic tessellation of fish diminishing toward rim")
    d[2231] = ("RETITLE", "Circle Limit IV angels and demons hyperbolic plane tessellation")
    d[2232] = ("RETITLE", "Liberation flock of triangular geometric tiles transforming into flying birds")
    d[2233] = ("RETITLE", "Sun and Moon woodcut showing dual day and night cosmic halves")
    d[2234] = ("RETITLE", "Order and Chaos crystal dodecahedron surrounded by cluttered junk")
    d[2235] = ("RETITLE", "Verbum word transforming into triangles, birds, fish, and frogs")
    d[2236] = ("RETITLE", "Dewdrop on leaf magnifying the microscopic cellular vein structure")
    d[2237] = ("RETITLE", "Eye self-portrait with skull reflection visible inside the iris")
    d[2238] = ("RETITLE", "Tower of Babel biblical ziggurat tower rising into dark clouds")
    d[2239] = ("RETITLE", "High and Low perspective illusion looking both up and down concurrently")
    
    # 2240..2244: electronics/calculators
    d[2240] = ("RETITLE", "Handheld electronic pocket calculator with LCD display and numbered keys")
    d[2241] = ("RETITLE", "Scientific graphing calculator showing mathematical function curve on screen")
    d[2242] = ("RETITLE", "Vintage desktop mechanical adding machine with side crank lever")
    d[2243] = ("RETITLE", "Wooden counting abacus with beads sliding on metal rods")
    d[2244] = ("RETITLE", "Solar-powered desktop financial calculator with large plus key")
    
    # 2245..2247: food-and-drinks/beers
    d[2245] = ("RETITLE", "Pint glass filled with amber beer and white frothy foam")

    d[2246] = ("RETITLE", "Brown glass beer bottle beside a filled pilsner tulip glass")
    d[2247] = ("RETITLE", "Two beer mugs clinking together in a celebratory cheers toast")
    
    # 2248..2250: vehicles/trucks
    d[2248] = ("RETITLE", "Semi-trailer tractor truck with eighteen wheels hauling cargo container")
    d[2249] = ("RETITLE", "Heavy dump truck with hydraulic bed tilted unloading gravel rocks")
    d[2250] = ("RETITLE", "Concrete mixer truck with rotating barrel drum for construction")
    
    # 2251..2266: electronics/cameras (16 cameras)
    d[2251] = ("RETITLE", "Single-lens reflex SLR film camera with manual focus lens ring")
    d[2252] = ("RETITLE", "Compact digital point-and-shoot camera with extendable zoom lens")
    d[2253] = ("RETITLE", "Instant Polaroid camera ejecting a square developing photo print")
    d[2254] = ("RETITLE", "Vintage twin-lens reflex TLR camera with top-down waist level finder")
    d[2255] = ("RETITLE", "Professional DSLR camera with long telephoto zoom lens mounted")
    d[2256] = ("RETITLE", "Action video camera in protective waterproof housing case")
    d[2257] = ("RETITLE", "Antique folding bellows camera with brass fittings on wooden stand")
    d[2258] = ("RETITLE", "Camera tripod three-legged stand with adjustable ball head mount")
    d[2259] = ("RETITLE", "Film canister roll of 35mm photographic negative camera film")
    d[2260] = ("RETITLE", "Photographer holding camera to eye taking a focused photograph")
    d[2261] = ("RETITLE", "Camera external flash strobe unit mounted on hot shoe bracket")
    d[2262] = ("RETITLE", "CCTV dome security surveillance camera mounted on ceiling")
    d[2263] = ("RETITLE", "Camera lens displaying aperture diaphragm blades and glass elements")
    d[2264] = ("RETITLE", "Studio photography light umbrella reflector on adjustable light stand")
    d[2265] = ("RETITLE", "Vintage box camera with single front shutter lens aperture")
    d[2266] = ("RETITLE", "Camera view through square photographic viewfinder with focus brackets")
    
    # 2267..2272: space/planets
    d[2267] = ("RETITLE", "Planet Saturn with dramatic concentric orbital ring system around sphere")
    d[2268] = ("RETITLE", "Planet Earth globe showing continents surrounded by atmospheric clouds")
    d[2269] = ("RETITLE", "Planet Jupiter showing horizontal cloud bands and Great Red Spot")
    d[2270] = ("RETITLE", "Planet Mars red sphere showing polar ice caps and surface canyons")
    d[2271] = ("RETITLE", "Planet Uranus tilted with faint vertical ring system in space")
    d[2272] = ("RETITLE", "Planet Neptune deep blue ice giant with swirling white storm cirrus")
    
    # 2273..2277: religion/hinduism
    d[2273] = ("RETITLE", "Lord Ganesha elephant-headed deity sitting with sweet modak in hand")
    d[2274] = ("RETITLE", "Lord Shiva dancing as Nataraja inside a circle of cosmic fire")
    d[2275] = ("RETITLE", "Trishula trident sacred three-pronged weapon of Lord Shiva")
    d[2276] = ("RETITLE", "Sacred cow Kamadhenu adorned with festival garland and bell")
    d[2277] = ("RETITLE", "Diya oil lamp burning with a cotton wick for Diwali festival")
    
    # 2278..2281: animals/reptiles/turtles
    d[2278] = ("RETITLE", "Sea turtle swimming through ocean water with broad paddle flippers")
    d[2279] = ("RETITLE", "Land tortoise walking slowly on sturdy legs with domed patterned shell")
    d[2280] = ("RETITLE", "Baby turtle hatching from sandy beach egg walking to water")
    d[2281] = ("RETITLE", "Turtle resting on a river log basking in warm sunlight")
    
    # 2282..2284: music/musicians/pink-floyd
    d[2282] = ("RETITLE", "Pink Floyd prism dispersing white light beam into rainbow spectrum")
    d[2283] = ("RETITLE", "The Wall album brick wall with cracked missing mortar gap")
    d[2284] = ("RETITLE", "Pink Floyd flying pig inflatable floating between power station towers")
    
    # 2285..2287: animals/insects/beetles
    d[2285] = ("RETITLE", "Rhinoceros beetle with formidable curved horned armor on head")
    d[2286] = ("RETITLE", "Stag beetle with large pincer jaws spread in defensive posture")
    d[2287] = ("RETITLE", "Spotted ladybug beetle crawling on a green garden leaf")
    
    # 2288..2290: animals/reptiles/snakes
    d[2288] = ("RETITLE", "King cobra snake rearing up with wide flaring neck hood and fangs")
    d[2289] = ("RETITLE", "Rattlesnake coiled ready to strike with buzzing tail rattle")
    d[2290] = ("RETITLE", "Python snake coiling smoothly around a tree branch")
    
    # 2291: buildings-and-places/monuments/pyramids
    d[2291] = ("RETITLE", "Great Pyramids of Giza standing in desert sand before sunset")
    
    # 2292..2296: buildings-and-places/furniture/benches
    d[2292] = ("RETITLE", "Wooden park bench with cast iron scrollwork armrests in park")
    d[2293] = ("RETITLE", "Rustic garden wooden bench nestled under a leafy shade tree")
    d[2294] = ("RETITLE", "Stone memorial bench sitting beside a tranquil cemetery path")
    d[2295] = ("RETITLE", "Gym weight bench equipped with barbell rack stands")
    d[2296] = ("RETITLE", "School hallway wooden locker bench with coat peg hooks above")
    
    # 2297..2301: people/occupations/police
    d[2297] = ("RETITLE", "Police officer in uniform directing traffic with white gloved hands")
    d[2298] = ("RETITLE", "Police patrol car with flashing siren emergency light bar")
    d[2299] = ("RETITLE", "Police officer standing with service belt, holster, and badge")
    d[2300] = ("RETITLE", "K-9 unit police dog sitting beside officer handler")
    d[2301] = ("RETITLE", "Mounted police officer riding patrol on a horse in city")
    
    # 2302..2307: buildings-and-places/furniture/other
    d[2302] = ("RETITLE", "Wooden wardrobe armoire closet with dual panel doors and drawer")
    d[2303] = ("RETITLE", "Five-drawer bedroom chest of drawers with round wooden pull knobs")
    d[2304] = ("RETITLE", "Coffee table with lower storage shelf resting on living room rug")
    d[2305] = ("RETITLE", "Dining room table set with four matching wooden chairs")
    d[2306] = ("RETITLE", "Office executive desk with side drawer pedestals and leather top")
    d[2307] = ("RETITLE", "Nightstand bedside table holding a small lamp and alarm clock")
    
    # 2308..2324: animals/insects/bees (17 bees)
    d[2308] = ("RETITLE", "Honeybee hovering in flight with translucent wings and striped abdomen")
    d[2309] = ("RETITLE", "Bee collecting pollen nectar inside a blooming flower blossom")
    d[2310] = ("RETITLE", "Honeycomb hexagonal wax cell pattern filled with golden honey")
    d[2311] = ("RETITLE", "Bumblebee with fuzzy black and yellow coat resting on clover")
    d[2312] = ("RETITLE", "Queen bee with long slender abdomen attended by worker bees")
    d[2313] = ("RETITLE", "Traditional woven straw skep beehive sitting in a garden")
    d[2314] = ("RETITLE", "Wooden Langstroth beehive box with removable honeycomb frames")
    d[2315] = ("RETITLE", "Honey jar with wooden honey dipper drizzling liquid honey")
    d[2316] = ("RETITLE", "Swarm of bees flying in a cluster around a tree branch")
    d[2317] = ("RETITLE", "Beekeeper wearing protective veil suit and gloves holding smoker")
    d[2318] = ("RETITLE", "Cute cartoon bee smiling happily with tiny antennae and stinger")
    d[2319] = ("RETITLE", "Bee flying toward a flower carrying yellow pollen baskets on legs")
    d[2320] = ("RETITLE", "Honeybee close-up showing compound eyes, antennae, and proboscis")
    d[2321] = ("RETITLE", "Honey dripping from a broken piece of raw natural honeycomb")
    d[2322] = ("RETITLE", "Wasp with narrow pinched waist and warning yellow black stripes")
    d[2323] = ("RETITLE", "Hornet building a paper nest attached to a roof eave")
    d[2324] = ("RETITLE", "Bee dancing in a figure-eight waggle dance pattern in hive")
    
    # 2325..2326: buildings-and-places/monuments/notre-dame
    d[2325] = ("RETITLE", "Notre-Dame Cathedral facade with twin towers and central rose window")
    d[2326] = ("RETITLE", "Gothic cathedral flying buttress stone arch support structure")
    
    # 2327: animals/insects/worms
    d[2327] = ("RETITLE", "Earthworm wiggling through rich garden soil with segmented body")
    
    # 2328..2336: animals/insects/other
    d[2328] = ("RETITLE", "Praying mantis insect in defensive posture with folded front raptorial legs")
    d[2329] = ("RETITLE", "Dragonfly with four long delicate translucent wings resting on reed")
    d[2330] = ("RETITLE", "Grasshopper perched on a blade of grass ready to jump")
    d[2331] = ("RETITLE", "Cricket insect rubbing its wings together to produce chirping song")
    d[2332] = ("RETITLE", "Centipede with many pairs of legs crawling across tree bark")
    d[2333] = ("RETITLE", "Mosquito with long proboscis needle resting on skin")
    d[2334] = ("RETITLE", "Housefly insect viewed from above with two clear wings and red eyes")
    d[2335] = ("RETITLE", "Stick insect camouflaged seamlessly against a real tree twig")
    d[2336] = ("RETITLE", "Firefly lightning bug with glowing bioluminescent abdomen in jar")
    
    # 2337: buildings-and-places/monuments/statue-of-liberty
    d[2337] = ("RETITLE", "Statue of Liberty holding torch high in right hand with tablet")
    
    # 2338: people/body-parts/brains
    d[2338] = ("RETITLE", "Human brain showing left and right cerebral hemispheres with neural sulci")
    
    # 2339..2352: people/occupations/knights (14 knights)
    d[2339] = ("RETITLE", "Medieval knight standing clad in full plate armor holding longsword")
    d[2340] = ("RETITLE", "Knight in armor charging on horseback with jousting lance leveled")
    d[2341] = ("RETITLE", "Knight helmet with movable face visor and plume feather crest")
    d[2342] = ("RETITLE", "Knight kneeling in reverent pledge of chivalry with sword point down")
    d[2343] = ("RETITLE", "Two knights dueling with steel broadswords on a medieval battlefield")
    d[2344] = ("RETITLE", "Knight holding a heraldic shield with cross and drawn sword")
    d[2345] = ("RETITLE", "Crusader knight wearing a white tunic with red cross on chest")
    d[2346] = ("RETITLE", "Knight standing guard at a castle gate with halberd polearm")
    d[2347] = ("RETITLE", "Suit of plate armor displayed on a wooden stand in museum")
    d[2348] = ("RETITLE", "Knight slaying a fire-breathing dragon with a thrusting spear")
    d[2349] = ("RETITLE", "Knight in chainmail hauberk armor drawing an arming sword")
    d[2350] = ("RETITLE", "Jousting tournament knight galloping with colorful caparison horse blanket")
    d[2351] = ("RETITLE", "Knight receiving royal accolade knighthood tap on shoulder with sword")
    d[2352] = ("RETITLE", "Dark knight warrior clad in black spiked armor with broadsword")
    
    # 2353: holiday-and-events/christmas/religious
    d[2353] = ("RETITLE", "Nativity scene with baby Jesus in manger, Mary, and Joseph")
    
    # 2354..2370: people/body-parts/footprints (17 footprints)
    d[2354] = ("RETITLE", "Pair of bare human footprints walking across sandy beach shore")
    d[2355] = ("RETITLE", "Single barefoot human footprint showing five distinct toes and arch")
    d[2356] = ("RETITLE", "Track of boot shoe footprints walking through fresh white snow")
    d[2357] = ("RETITLE", "Baby footprint impression record from hospital birth certificate")
    d[2358] = ("RETITLE", "Trail of paw prints left by a dog running across mud")
    d[2359] = ("RETITLE", "Three-toed bird footprint tracks left in wet river sand")
    d[2360] = ("RETITLE", "Giant bear paw track with five claw puncture marks in mud")
    d[2361] = ("RETITLE", "Deer cloven hoof print tracks walking through a woodland trail")
    d[2362] = ("RETITLE", "Cat paw print impression showing four toe beans and central pad")
    d[2363] = ("RETITLE", "High heel shoe footprint imprint left in soft garden earth")
    d[2364] = ("RETITLE", "Hiking boot tread footprint showing deep rubber lug pattern")
    d[2365] = ("RETITLE", "Dinosaur three-toed theropod fossil footprint track embedded in rock")
    d[2366] = ("RETITLE", "Horse horseshoe track imprint in soft equestrian riding sand")
    d[2367] = ("RETITLE", "Duck webbed footprint tracks leading into pond water")
    d[2368] = ("RETITLE", "Astronaut boot footprint impression preserved in lunar regolith dust")
    d[2369] = ("RETITLE", "Rabbit hopping track pattern showing alternating front and hind paws")
    d[2370] = ("RETITLE", "Footprints leading away in a curved path into the distance")
    
    # 2371..2375: animals/insects/snails
    d[2371] = ("RETITLE", "Garden snail crawling slowly with spiral shell and eye stalks")
    d[2372] = ("RETITLE", "Snail leaving a glistening slime trail path across a garden leaf")
    d[2373] = ("RETITLE", "Two snails touching antennae in a slow greeting encounter")
    d[2374] = ("RETITLE", "Snail shell showing Fibonacci golden spiral growth pattern")
    d[2375] = ("RETITLE", "Cute cartoon snail with big smiling eyes and striped shell")
    
    # 2376..2402: animals/insects/butterflies (27 butterflies)
    d[2376] = ("RETITLE", "Monarch butterfly with orange and black patterned wings spread wide")
    d[2377] = ("RETITLE", "Swallowtail butterfly with yellow wings and distinctive tail extensions")
    d[2378] = ("RETITLE", "Butterfly perched gracefully on a blooming purple flower petal")
    d[2379] = ("RETITLE", "Pair of butterflies dancing and fluttering together in midair")
    d[2380] = ("RETITLE", "Butterfly silhouette drawn in delicate flowing symmetrical line curves")
    d[2381] = ("RETITLE", "Moth resting flat on tree bark with feathered sensory antennae")
    d[2382] = ("RETITLE", "Blue morpho butterfly with iridescent sapphire wings open wide")
    d[2383] = ("RETITLE", "Caterpillar crawling along a twig before butterfly metamorphosis")
    d[2384] = ("RETITLE", "Chrysalis cocoon hanging from a branch as butterfly emerges")
    d[2385] = ("RETITLE", "Butterfly with intricate filigree lace wing patterns resting")
    d[2386] = ("RETITLE", "Tribal style butterfly emblem with sharp angular wing designs")
    d[2387] = ("RETITLE", "Butterfly viewed in profile with wings folded upright over back")
    d[2388] = ("RETITLE", "Small cabbage white butterfly fluttering over garden vegetables")
    d[2389] = ("RETITLE", "Butterfly sipping nectar through long curled proboscis straw")
    d[2390] = ("RETITLE", "Luna moth with pale green wings and long sweeping tails")
    d[2391] = ("RETITLE", "Butterfly resting on an open human hand palm in trust")
    d[2392] = ("RETITLE", "Geometric butterfly drawn with sharp repeating polygon segments")
    d[2393] = ("RETITLE", "Butterfly wings displaying large false eye spots to deter predators")
    d[2394] = ("RETITLE", "Butterfly flying among floating dandelion seeds in spring breeze")
    d[2395] = ("RETITLE", "Collection of four different butterfly species pinned in display box")
    d[2396] = ("RETITLE", "Butterfly landing on a floating water lily pad blossom")
    d[2397] = ("RETITLE", "Peacock butterfly with four vibrant circular wing eye markings")
    d[2398] = ("RETITLE", "Butterfly with hearts integrated into its ornamental wing patterns")
    d[2399] = ("RETITLE", "Fairy wings styled like translucent monarch butterfly wings")
    d[2400] = ("RETITLE", "Butterfly framed inside an ornate circular floral wreath border")
    d[2401] = ("RETITLE", "Stained glass butterfly with lead came lines separating colored segments")
    d[2402] = ("RETITLE", "Butterfly hovering near a lit candle flame in the dark")
    
    # 2403: people/occupations/artists
    d[2403] = ("RETITLE", "Artist painting on canvas resting on a wooden studio easel")
    
    # 2404..2414: people/body-parts/hand-gestures (11 hands)
    d[2404] = ("RETITLE", "Hand with open palm and spread fingers facing directly forward")
    d[2405] = ("RETITLE", "Clenched fist raised in determination and solidarity strength")
    d[2406] = ("RETITLE", "Hand making the two-finger peace victory sign gesture")
    d[2407] = ("RETITLE", "Hand giving a clear thumbs up gesture of approval")
    d[2408] = ("RETITLE", "Index finger pointing directly forward to indicate direction")
    d[2409] = ("RETITLE", "Two hands clasped together in a firm handshake agreement")
    d[2410] = ("RETITLE", "Hand making the OK sign with thumb and index touching")
    d[2411] = ("RETITLE", "Hand making rock and roll sign of the horns gesture")
    d[2412] = ("RETITLE", "Pair of open cupped hands held out to receive or give")
    d[2413] = ("RETITLE", "Hand crossing index and middle fingers hoping for good luck")
    d[2414] = ("RETITLE", "Hand waving with open palm in friendly hello greeting")
    
    # 2415..2416: buildings-and-places/furniture/beds
    d[2415] = ("RETITLE", "Double bedroom bed with pillows and folded patchwork quilt blanket")
    d[2416] = ("RETITLE", "Antique four-poster canopy bed with carved wooden corner posts")
    
    # 2417..2424: holiday-and-events/christmas/trees (8 trees)
    d[2417] = ("RETITLE", "Decorated Christmas tree topped with a shining five-pointed star")
    d[2418] = ("RETITLE", "Christmas tree with hanging round bauble ornaments and tinsel garland")
    d[2419] = ("RETITLE", "Christmas tree surrounded by wrapped gift presents under lower branches")
    d[2420] = ("RETITLE", "Evergreen Christmas tree covered in a blanket of fresh snow")
    d[2421] = ("RETITLE", "Christmas tree illuminated with string lights and glowing candle bulbs")
    d[2422] = ("RETITLE", "Geometric stylized Christmas tree drawn in stepped zigzag branches")
    d[2423] = ("RETITLE", "Miniature desktop Christmas tree potted in a small holiday tin")
    d[2424] = ("RETITLE", "Christmas tree decorated with candy canes, gingerbread men, and star")
    
    # 2425..2429: music/musicians/pet-shop-boys
    d[2425] = ("RETITLE", "Pet Shop Boys duo portrait with Neil Tennant and Chris Lowe")
    d[2426] = ("RETITLE", "Chris Lowe wearing his iconic baseball cap and dark sunglasses")
    d[2427] = ("RETITLE", "Neil Tennant singing in sharp tailored suit jacket on stage")
    d[2428] = ("RETITLE", "Pet Shop Boys performing with synthesizer keyboard and microphone")
    d[2429] = ("RETITLE", "Pet Shop Boys electronic music album graphic typography logo")
    
    # 2430..2451: animals/insects/ants (22 ants)
    d[2430] = ("RETITLE", "Single black ant walking on six legs with jointed antennae")
    d[2431] = ("RETITLE", "Worker ant carrying a green leaf fragment above its head")
    d[2432] = ("RETITLE", "Line of five worker ants marching in single file line")
    d[2433] = ("RETITLE", "Ant crawling into an underground anthill sand mound entrance")
    d[2434] = ("RETITLE", "Soldier ant with large powerful mandibles in defensive stance")
    d[2435] = ("RETITLE", "Two ants touching antennae in chemical scent communication")
    d[2436] = ("RETITLE", "Ant carrying a large bread crumb back to its colony")
    d[2437] = ("RETITLE", "Queen ant with enlarged abdomen attended by worker ants")
    d[2438] = ("RETITLE", "Cross section of underground ant colony showing tunnels and chambers")
    d[2439] = ("RETITLE", "Ant holding a sweet sugar crystal cube between its mandibles")
    d[2440] = ("RETITLE", "Ants working together to carry a heavy insect prey item")
    d[2441] = ("RETITLE", "Ant viewed under magnifying glass showing body segments and thorax")
    d[2442] = ("RETITLE", "Winged flying alate ant ready for annual nuptial flight")
    d[2443] = ("RETITLE", "Ant climbing vertically up a slender green plant stem")
    d[2444] = ("RETITLE", "Cute cartoon ant smiling cheerfully with six walking legs")
    d[2445] = ("RETITLE", "Ant tending to a herd of aphids on a rose bush")
    d[2446] = ("RETITLE", "Ant drinking a tiny droplet of morning dew on a leaf")
    d[2447] = ("RETITLE", "Ant colony mound in sandy soil with ants bustling around")
    d[2448] = ("RETITLE", "Ant defending its nest against an invading beetle with jaws")
    d[2449] = ("RETITLE", "Ant grooming its antennae with front legs in clean posture")
    d[2450] = ("RETITLE", "Two ants pulling a dropped piece of candy across picnic blanket")
    d[2451] = ("RETITLE", "Ant carrying an ant pupa cocoon safely to nursery chamber")
    
    # 2452: holiday-and-events/christmas/other
    d[2452] = ("RETITLE", "Christmas stocking hung by the fireplace stuffed with toys and candy")
    
    # 2453..2460: music/musicians/other
    d[2453] = ("RETITLE", "Bob Marley portrait with dreadlocks smiling in front of microphone")
    d[2454] = ("RETITLE", "Jimi Hendrix playing electric guitar behind his back on stage")
    d[2455] = ("RETITLE", "Michael Jackson striking his signature Moonwalk dance toe stand pose")
    d[2456] = ("RETITLE", "Freddie Mercury singing with raised fist at Wembley stadium concert")
    d[2457] = ("RETITLE", "David Bowie as Ziggy Stardust with lightning bolt face paint")
    d[2458] = ("RETITLE", "Kurt Cobain playing left-handed acoustic guitar in cardigan sweater")
    d[2459] = ("RETITLE", "Madonna in iconic cone corset bustier performing on tour")
    d[2460] = ("RETITLE", "Ludwig van Beethoven portrait with furrowed brow and wild hair")
    
    # 2461..2468: buildings-and-places/furniture/chairs
    d[2461] = ("RETITLE", "Upholstered armchair with deep button tufting and rolled armrests")
    d[2462] = ("RETITLE", "Wooden dining chair with vertical slat back and curved legs")
    d[2463] = ("RETITLE", "Swivel office desk chair on wheeled star base with armrests")
    d[2464] = ("RETITLE", "Wooden rocking chair on curved runners beside a hearth")
    d[2465] = ("RETITLE", "Folding metal lawn chair with striped canvas seat and back")
    d[2466] = ("RETITLE", "Modern minimalist molded plastic shell chair on wire legs")
    d[2467] = ("RETITLE", "Tall barstool chair with round seat cushion and footrest ring")
    d[2468] = ("RETITLE", "Deck chair chaise lounge reclined on sunny pool patio")
    
    # 2469: buildings-and-places/monuments/stonehenge
    d[2469] = ("RETITLE", "Stonehenge prehistoric monument with standing megalith stones and lintels")
    
    # 2470..2473: animals/insects/cockroaches
    d[2470] = ("RETITLE", "Cockroach insect with long sweeping antennae and flat oval body")
    d[2471] = ("RETITLE", "Cockroach scurrying across a tiled floor surface on six legs")
    d[2472] = ("RETITLE", "Cockroach flipped over on its back struggling with legs kicking")
    d[2473] = ("RETITLE", "Large hissing cockroach displaying armored pronotum shield on head")
    
    # 2474..2476: buildings-and-places/furniture/sofas
    d[2474] = ("RETITLE", "Comfortable three-cushion living room sofa with throw pillows")
    d[2475] = ("RETITLE", "Chesterfield leather couch with deep button tufting and scrolled arms")
    d[2476] = ("RETITLE", "L-shaped sectional corner sofa with chaise lounge extension")
    
    # 2477: people/famous/george-washington
    d[2477] = ("RETITLE", "George Washington profile portrait with powdered wig and collar")
    
    # 2478..2480: animals/insects/caterpillars
    d[2478] = ("RETITLE", "Caterpillar crawling along a plant stem with multiple prolegs")
    d[2479] = ("RETITLE", "Woolly bear fuzzy banded caterpillar crawling across a path")
    d[2480] = ("RETITLE", "Monarch caterpillar with yellow, white, and black stripes munching leaf")
    
    # 2481: animals/reptiles/lizards
    d[2481] = ("RETITLE", "Gecko lizard clinging to a glass window with splayed toe pads")
    
    # 2482..2484: buildings-and-places/monuments/eiffel-tower
    d[2482] = ("RETITLE", "Eiffel Tower in Paris standing tall with wrought-iron lattice arches")
    d[2483] = ("RETITLE", "Eiffel Tower illuminated with glowing searchlight beams in night sky")
    d[2484] = ("RETITLE", "Eiffel Tower viewed from Champ de Mars gardens with trees")
    
    # 2485..2486: buildings-and-places/monuments/other
    d[2485] = ("RETITLE", "Big Ben clock tower of Westminster palace in London with spire")
    d[2486] = ("RETITLE", "Leaning Tower of Pisa tilting in marble tiered gallery arches")
    
    return d

if __name__ == "__main__":
    b5 = get_batch5()
    print(f"Batch 5 generated {len(b5)} decisions (expected 586: 1901..2486)")
