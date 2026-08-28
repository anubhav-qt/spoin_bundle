# -*- coding: utf-8 -*-
"""Full decision map for Batch 3: indexes 888 to 1400 (info part 1)."""
import json, io

entries = json.load(open(r"C:\Temp\entries.json", encoding="utf-8"))

def get_batch3():
    d = {}
    
    # 888..890: ascii-dividers/gallery -> DELETE unsuitable
    d[888] = ("DELETE", "unsuitable")
    d[889] = ("DELETE", "unsuitable")
    d[890] = ("DELETE", "unsuitable")
    
    # 891..892: ascii-patterns/gallery -> DELETE unsuitable
    d[891] = ("DELETE", "unsuitable")
    d[892] = ("DELETE", "unsuitable")
    
    # 893..927: ascii-dividers/gallery/multi -> DELETE unsuitable
    for idx in range(893, 928):
        d[idx] = ("DELETE", "unsuitable")
        
    # 928: ascii-borders/gallery/classic -> DELETE unsuitable
    d[928] = ("DELETE", "unsuitable")
    
    # 929: one-line rose
    d[929] = ("RETITLE", "Single blooming rose flower with stem and thorny leaves")
    
    # 930..938: clothing-and-accessories/other
    d[930] = ("RETITLE", "Knitted wool pullover sweater with textured cable pattern")
    d[931] = ("RETITLE", "Pair of casual bermuda shorts with waistband button")
    d[932] = ("RETITLE", "Short sleeve buttoned blouse with pointed lapel collar")
    d[933] = ("RETITLE", "Two-piece sleepwear pajamas with shirt and matching trousers")
    d[934] = ("RETITLE", "Lady leather handbag purse with arched carrying handle")
    d[935] = ("RETITLE", "Fluffy winter earmuffs with connecting curved headband")
    d[936] = ("RETITLE", "Knitted neck scarf draped smoothly with fringed tassels")
    d[937] = ("RETITLE", "Open tube of cosmetic lipstick beside its removable cap")
    d[938] = ("RETITLE", "Sewing needle pulling thread through a stitched fabric hem")
    
    # 939..942: miscellaneous/hourglass
    d[939] = ("RETITLE", "Small hourglass timer with sand trickling through glass neck")
    d[940] = ("RETITLE", "Hourglass glass instrument measuring passage of time with sand")
    d[941] = ("RETITLE", "Classical hourglass with ornate pillars and sand in lower chamber")
    d[942] = ("RETITLE", "Large wooden framed hourglass with falling sand grains")
    
    # 943..950: art-and-design/pentacles
    d[943] = ("RETITLE", "Five-pointed star pentacle symbol enclosed within a circle")
    d[944] = ("RETITLE", "Geometric five-pointed pentagram drawn in interlocking single lines")
    d[945] = ("RETITLE", "Mystical pentagram emblem with intricate interwoven band lines")
    d[946] = ("RETITLE", "Symmetrical occult star pentacle with dark shaded central field")
    d[947] = ("RETITLE", "Woven Celtic knot pentagram star inside circular border")
    d[948] = ("RETITLE", "Five-pointed star talisman with crescent moon accents around rim")
    d[949] = ("RETITLE", "Alchemical pentacle sigil with planetary glyph symbols at vertices")
    d[950] = ("RETITLE", "Detailed ritual pentagram etched onto a stone altar slab")
    
    # 951..958: clothing-and-accessories/shirts
    d[951] = ("RETITLE", "Short-sleeve casual cotton t-shirt with crew neck collar")
    d[952] = ("RETITLE", "Polo shirt with folded collar and three chest buttons")
    d[953] = ("RETITLE", "Formal long-sleeve dress shirt with stiff collar and cuffs")
    d[954] = ("RETITLE", "Sleeveless athletic tank top jersey with ribbed neckline")
    d[955] = ("RETITLE", "Hawaiian floral print button-down shirt with open camp collar")
    d[956] = ("RETITLE", "Long-sleeve flannel plaid shirt with chest button pockets")
    d[957] = ("RETITLE", "T-shirt displayed hanging on a wooden clothes hanger")
    d[958] = ("RETITLE", "Folded dress shirt with silk necktie resting on collar")
    
    # 959..974: buildings-and-places/houses
    d[959] = ("RETITLE", "Small cozy suburban cottage house with pitched roof and chimney")
    d[960] = ("RETITLE", "Two-story colonial house with front porch and shuttered windows")
    d[961] = ("RETITLE", "Rustic log cabin in the woods with smoking brick chimney")
    d[962] = ("RETITLE", "Modern split-level architectural residential home with glass panels")
    d[963] = ("RETITLE", "Suburban family house with driveway, garage, and picket fence")
    d[964] = ("RETITLE", "Thatched roof medieval country cottage with small arched doorway")
    d[965] = ("RETITLE", "Victorian mansion house with ornate gables and wrap-around veranda")
    d[966] = ("RETITLE", "A-frame wooden alpine cabin chalet nestled on a hillside")
    d[967] = ("RETITLE", "Brick townhouse rowhouse building with front entrance steps")
    d[968] = ("RETITLE", "Lakeside boathouse dwelling with wooden dock over calm water")
    d[969] = ("RETITLE", "Farmhouse dwelling beside a tall grain silo and wooden barn")
    d[970] = ("RETITLE", "Beachfront bungalow stilt house with palm thatch roof")
    d[971] = ("RETITLE", "Haunted Victorian manor house with broken windows and leaning tower")
    d[972] = ("RETITLE", "Stone masonry cottage with flowering garden hedge along pathway")
    d[973] = ("RETITLE", "Two-story family home with twin dormer windows on roof")
    d[974] = ("RETITLE", "Little garden shed building with wooden door and garden shovel")
    
    # 975..991: computers/computers
    d[975] = ("RETITLE", "Vintage desktop personal computer with CRT monitor and keyboard")
    d[976] = ("RETITLE", "Desktop PC tower unit with floppy disk drive slots")
    d[977] = ("RETITLE", "Open laptop computer displaying lines of programming terminal code")
    d[978] = ("RETITLE", "Computer workstation setup with monitor, mouse, and desktop tower")
    d[979] = ("RETITLE", "Old CRT computer screen monitor sitting on a swivel base")
    d[980] = ("RETITLE", "Computer keyboard with full QWERTY layout and numeric keypad")
    d[981] = ("RETITLE", "Two-button mechanical computer roller ball mouse with cord")
    d[982] = ("RETITLE", "Server rack cabinet filled with stacked networked blade units")
    d[983] = ("RETITLE", "Mainframe tape drive reel spinning in data center room")
    d[984] = ("RETITLE", "Retro 1980s microcomputer with integrated keyboard and tape deck")
    d[985] = ("RETITLE", "Computer motherboard circuit board with microprocessor chip socket")
    d[986] = ("RETITLE", "Flat screen LCD monitor display on a sleek metal stand")
    d[987] = ("RETITLE", "Person typing at a computer terminal in office cubicle")
    d[988] = ("RETITLE", "Floppy disk 3.5 inch magnetic storage media cartridge")
    d[989] = ("RETITLE", "Vintage 5.25 inch flexible floppy diskette with read notch")
    d[990] = ("RETITLE", "Dot matrix ribbon computer printer printing continuous feed paper")
    d[991] = ("RETITLE", "Handheld stylus drawing pad tablet connected to computer")
    
    # 992: art-and-design/origamis
    d[992] = ("RETITLE", "Origami paper crane folded with wings spread and pointed beak")
    
    # 993..995: nature/rains
    d[993] = ("RETITLE", "Rain clouds pouring down heavy diagonal rainfall droplets")
    d[994] = ("RETITLE", "Open umbrella deflecting falling raindrops onto the ground")
    d[995] = ("RETITLE", "Puddle of water with concentric ripple circles from falling rain")
    
    # 996: movies/aladdin
    d[996] = ("RETITLE", "Genie magical oil lamp pouring out swirling mystical smoke")
    
    # 997..1002: mythology/centaurs
    d[997] = ("RETITLE", "Centaur warrior drawing hunting bow with horse body rearing")
    d[998] = ("RETITLE", "Centaur standing in woodland with wooden quarterstaff in hand")
    d[999] = ("RETITLE", "Mythological centaur silhouette galloping across open mountain meadow")
    d[1000] = ("RETITLE", "Centaur aiming an arrow skyward with feathered fletching")
    d[1001] = ("RETITLE", "Centaur warrior clad in leather armor carrying a battle spear")
    d[1002] = ("RETITLE", "Female centaur standing gracefully beside a forest stream")
    
    # 1003..1011: computers/game-consoles
    d[1003] = ("RETITLE", "Classic video game gamepad controller with directional pad and buttons")
    d[1004] = ("RETITLE", "Handheld portable gaming console with small screen and speaker")
    d[1005] = ("RETITLE", "Arcade joystick cabinet with coin slot and red ball joystick")
    d[1006] = ("RETITLE", "Vintage home video game console system with dual controller ports")
    d[1007] = ("RETITLE", "Game cartridge inserted into top loading video game deck")
    d[1008] = ("RETITLE", "Ergonomic gaming controller with dual analog thumbsticks and triggers")
    d[1009] = ("RETITLE", "Retro handheld gaming system showing pixel sprite on screen")
    d[1010] = ("RETITLE", "Light gun zapper peripheral for retro console shooting games")
    d[1011] = ("RETITLE", "Steering wheel and pedal set for racing simulator gaming")
    
    # 1012..1019: sports-and-outdoors/bowling
    d[1012] = ("RETITLE", "Three bowling pins standing in formation waiting for ball")
    d[1013] = ("RETITLE", "Bowling ball rolling down lane toward ten racked pins")
    d[1014] = ("RETITLE", "Bowling ball knocking down pins in an explosive strike")
    d[1015] = ("RETITLE", "Bowling ball with three finger grip holes viewed close up")
    d[1016] = ("RETITLE", "Single wooden bowling pin with red stripe around neck")
    d[1017] = ("RETITLE", "Bowler swinging ball back on wooden bowling alley lane")
    d[1018] = ("RETITLE", "Pair of laced bowling shoes with smooth sliding soles")
    d[1019] = ("RETITLE", "Bowling lane scorekeeper terminal displaying frame breakdown")
    
    # 1020..1023: sports-and-outdoors/ice-hockey
    d[1020] = ("RETITLE", "Crossed ice hockey sticks over a black rubber puck")
    d[1021] = ("RETITLE", "Ice hockey player in protective helmet skating with puck")
    d[1022] = ("RETITLE", "Hockey goalie wearing padded leg guards blocking the net")
    d[1023] = ("RETITLE", "Hockey puck sliding into the back of a string net")
    
    # 1024..1036: electronics/clocks
    d[1024] = ("RETITLE", "Round wall clock showing three o clock with hour and minute hands")
    d[1025] = ("RETITLE", "Classic mechanical twin-bell alarm clock with hammer striker")
    d[1026] = ("RETITLE", "Digital LED alarm clock radio displaying twelve o clock numbers")
    d[1027] = ("RETITLE", "Antique grandfather pendulum clock in tall carved wooden cabinet")
    d[1028] = ("RETITLE", "Cuckoo clock with bird emerging from upper door chiming")
    d[1029] = ("RETITLE", "Pocket watch with winding crown and attached metallic chain")
    d[1030] = ("RETITLE", "Roman numeral circular watch face with ornamental filigree hands")
    d[1031] = ("RETITLE", "Sundial garden sculpture casting shadow across circular hour markings")
    d[1032] = ("RETITLE", "Stopwatch with push button timer measuring elapsed seconds")
    d[1033] = ("RETITLE", "Modern minimalist wrist watch with leather strap and buckle")
    d[1034] = ("RETITLE", "Melting clock draped over a ledge in surrealist art style")
    d[1035] = ("RETITLE", "Clock mechanism showing interlocking brass gears, cogs, and spring")
    d[1036] = ("RETITLE", "Digital wristwatch with stopwatch buttons and digital time readout")
    
    # 1037..1049: electronics/light-bulbs
    d[1037] = ("RETITLE", "Incandescent glass light bulb glowing with glowing filament coil")
    d[1038] = ("RETITLE", "Light bulb emitting radiant light rays in an idea moment")
    d[1039] = ("RETITLE", "Compact fluorescent spiral bulb with screw-in threaded base")
    d[1040] = ("RETITLE", "Vintage Edison light bulb with decorative carbon filament cage")
    d[1041] = ("RETITLE", "Broken glass light bulb with shattered fragments on table")
    d[1042] = ("RETITLE", "Hanging bare light bulb suspended from a ceiling wire cord")
    d[1043] = ("RETITLE", "Electric desk study lamp with adjustable flexible goose neck")
    d[1044] = ("RETITLE", "Fluorescent tube lighting fixture mounted in ceiling panel")
    d[1045] = ("RETITLE", "Lava lamp with floating heated wax blobs inside liquid chamber")
    d[1046] = ("RETITLE", "Decorative crystal chandelier hanging with illuminated candle bulbs")
    d[1047] = ("RETITLE", "Outdoor street lamp post casting a warm cone of light")
    d[1048] = ("RETITLE", "Handheld electric torch flashlight shining a bright forward beam")
    d[1049] = ("RETITLE", "LED diode light bulb with threaded brass base and heatsink")
    
    # 1050..1071: food-and-drinks/other
    d[1050] = ("RETITLE", "Slice of pepperoni pizza with melting stringy cheese dripping")
    d[1051] = ("RETITLE", "Juicy hamburger sandwich with sesame bun, lettuce, and patty")
    d[1052] = ("RETITLE", "Hot dog in a bun topped with a squiggle of yellow mustard")
    d[1053] = ("RETITLE", "French fries served in a striped paper fast food carton")
    d[1054] = ("RETITLE", "Steaming hot cup of black coffee on a ceramic saucer")
    d[1055] = ("RETITLE", "Glass of iced soda beverage with a bent drinking straw")
    d[1056] = ("RETITLE", "Mug of foamy draft beer with frothy head spilling over rim")
    d[1057] = ("RETITLE", "Wine bottle beside a filled stemmed wine goblet glass")
    d[1058] = ("RETITLE", "Cocktail martini glass with green olive on a toothpick garnish")
    d[1059] = ("RETITLE", "Loaf of crusty bakery bread sliced on a wooden cutting board")
    d[1060] = ("RETITLE", "Croissant flaky French pastry curved into a crescent shape")
    d[1061] = ("RETITLE", "Pretzel bread knot sprinkled with coarse sea salt crystals")
    d[1062] = ("RETITLE", "Cheese wedge with swiss holes sitting beside a round wheel")
    d[1063] = ("RETITLE", "Fried egg with sunny side up yellow yolk in frying pan")
    d[1064] = ("RETITLE", "Strip of crispy sizzling breakfast bacon curved on plate")
    d[1065] = ("RETITLE", "Roast turkey poultry feast resting in an oval serving platter")
    d[1066] = ("RETITLE", "Steak meat cutlet with grill char marks on porcelain dish")
    d[1067] = ("RETITLE", "Bowl of hot noodle soup ramen with floating egg and scallions")
    d[1068] = ("RETITLE", "Pair of sushi rolls wrapped in dark nori seaweed with rice")
    d[1069] = ("RETITLE", "Taco shell filled with seasoned meat, lettuce, and shredded cheese")
    d[1070] = ("RETITLE", "Steaming teapot kettle with spout pouring tea into a cup")
    d[1071] = ("RETITLE", "Ice cream sundae in tall tulip glass topped with cherry")
    
    # 1072..1074: art-and-design/fractals
    d[1072] = ("RETITLE", "Sierpinski triangle recursive geometric fractal pattern")
    d[1073] = ("RETITLE", "Mandelbrot set fractal boundary rendered in dense character gradient")
    d[1074] = ("RETITLE", "Koch snowflake recursive geometric crystal fractal boundary")
    
    # 1075..1078: music/pianos
    d[1075] = ("RETITLE", "Grand piano with open raised lid and curved polished wood body")
    d[1076] = ("RETITLE", "Piano keyboard showing repeating pattern of white and black keys")
    d[1077] = ("RETITLE", "Upright acoustic piano with music stand and foot pedals below")
    d[1078] = ("RETITLE", "Pianist hands playing a complex chord progression on keys")
    
    # 1079..1080: nature/rainbow
    d[1079] = ("RETITLE", "Arched rainbow spanning across clouds in a clear blue sky")
    d[1080] = ("RETITLE", "Rainbow ending in a pot of gold coins beneath a cloud")
    
    # 1081..1083: miscellaneous/cigarettes
    d[1081] = ("RETITLE", "Lit burning cigarette resting in a glass ashtray with smoke curling")
    d[1082] = ("RETITLE", "Pack of cigarettes with one cigarette pulled out ready")
    d[1083] = ("RETITLE", "Smoking pipe with carved wooden briar bowl emitting fragrant smoke")
    
    # 1084..1096: clothing-and-accessories/footwear
    d[1084] = ("RETITLE", "High-top athletic running sneaker shoe with tied shoelaces")
    d[1085] = ("RETITLE", "Pair of classic lace-up leather oxford dress shoes")
    d[1086] = ("RETITLE", "High heel stiletto shoe with slender spiked heel and pointed toe")
    d[1087] = ("RETITLE", "Cowboy boot with decorative leather tooling and stacked heel")
    d[1088] = ("RETITLE", "Heavy lace-up work combat boot with thick tread rubber sole")
    d[1089] = ("RETITLE", "Pair of summer beach flip-flop thong sandals")
    d[1090] = ("RETITLE", "Slip-on casual loafer shoe with penny strap detail")
    d[1091] = ("RETITLE", "Warm winter snow boot with fleece fur lining and straps")
    d[1092] = ("RETITLE", "Ballet pointe shoe with satin ribbon laces wrapped around ankle")
    d[1093] = ("RETITLE", "Pair of cozy woolen house slippers on the floor")
    d[1094] = ("RETITLE", "Roller skate shoe with four wheels and front rubber toe stop")
    d[1095] = ("RETITLE", "Ice skate boot with sharp steel gliding blade below")
    d[1096] = ("RETITLE", "Platform shoe with chunky elevated sole and ankle strap")
    
    # 1097..1108: books/books
    d[1097] = ("RETITLE", "Open hardcover book with pages spread flat on a wooden desk")
    d[1098] = ("RETITLE", "Stack of five antique leather-bound books piled vertically")
    d[1099] = ("RETITLE", "Book resting on its side with silk ribbon bookmark hanging")
    d[1100] = ("RETITLE", "Row of books standing upright between two decorative bookends")
    d[1101] = ("RETITLE", "Open magic spellbook with glowing runes rising from pages")
    d[1102] = ("RETITLE", "Antique tome book with metal corner clasps and embossed cover")
    d[1103] = ("RETITLE", "Pocket paperback book half open with dog-eared page corner")
    d[1104] = ("RETITLE", "Thick dictionary encyclopedia volume with thumb index notches")
    d[1105] = ("RETITLE", "Rolled parchment scroll manuscript tied with a ribbon bow")
    d[1106] = ("RETITLE", "Bookworm reading glasses resting on an open book page")
    d[1107] = ("RETITLE", "Library wooden bookshelf filled with organized novel volumes")
    d[1108] = ("RETITLE", "Person holding an open novel reading attentively")
    
    # 1109..1110: electronics/stereos
    d[1109] = ("RETITLE", "Boombox portable cassette tape stereo player with twin speakers")
    d[1110] = ("RETITLE", "Home audio stereo receiver system with amplifier volume dials")
    
    # 1111..1130: vehicles/airplanes
    d[1111] = ("RETITLE", "Commercial jet airliner flying through sky with jet engines under wings")
    d[1112] = ("RETITLE", "Vintage biplane airplane with dual wings and front spinning propeller")
    d[1113] = ("RETITLE", "Military fighter jet soaring in supersonic speed afterburner flight")
    d[1114] = ("RETITLE", "Small single-engine Cessna airplane cruising smoothly above clouds")
    d[1115] = ("RETITLE", "Concorde supersonic passenger airplane with iconic droop nose")
    d[1116] = ("RETITLE", "Helicopter with spinning main rotor blades and tail rotor")
    d[1117] = ("RETITLE", "Seaplane aircraft floating on water with dual hull pontoon floats")
    d[1118] = ("RETITLE", "Stealth bomber aircraft with triangular flying wing aerodynamic design")
    d[1119] = ("RETITLE", "Cargo transport airplane with open rear ramp loading bay")
    d[1120] = ("RETITLE", "Hot air balloon basket floating peacefully in the morning sky")
    d[1121] = ("RETITLE", "Airship zeppelin dirigible blimp cruising slowly over city landscape")
    d[1122] = ("RETITLE", "Glider sailplane soaring effortlessly without engine propulsion")
    d[1123] = ("RETITLE", "Paper airplane folded from a single sheet gliding forward")
    d[1124] = ("RETITLE", "Space shuttle orbiter mounted on booster rockets on launchpad")
    d[1125] = ("RETITLE", "Twin-engine turboprop passenger plane landing on runway tarmac")
    d[1126] = ("RETITLE", "Stunt aerobatic airplane leaving white smoke trail loop in sky")
    d[1127] = ("RETITLE", "Crop duster biplane spraying fertilizer mist over farm fields")
    d[1128] = ("RETITLE", "Drone quadcopter unmanned aerial vehicle with four rotor propellers")
    d[1129] = ("RETITLE", "Paraglider canopy wing flying high with suspended harness pilot")
    d[1130] = ("RETITLE", "Rocket spacecraft launching into orbit on a fiery plume column")
    
    # 1131..1141: vehicles/cars
    d[1131] = ("RETITLE", "Classic four-door family sedan passenger car in profile")
    d[1132] = ("RETITLE", "Sleek low-profile sports car with aerodynamic spoiler wing")
    d[1133] = ("RETITLE", "Vintage antique Model T automobile with spoked wooden wheels")
    d[1134] = ("RETITLE", "Four-wheel-drive offroad jeep vehicle with spare tire on back")
    d[1135] = ("RETITLE", "Convertible roadster car with convertible soft top retracted")
    d[1136] = ("RETITLE", "Pickup truck with open flatbed cargo bed carrying equipment")
    d[1137] = ("RETITLE", "Formula One grand prix racing car with front and rear wings")
    d[1138] = ("RETITLE", "Volkswagen Beetle compact bug car with rounded silhouette")
    d[1139] = ("RETITLE", "Limousine luxury passenger automobile with elongated wheelbase body")
    d[1140] = ("RETITLE", "Taxi cab automobile with illuminated rooftop taxi sign light")
    d[1141] = ("RETITLE", "Police patrol cruiser car with emergency light bar on roof")
    
    # 1142..1146: weapons/bows-and-arrows
    d[1142] = ("RETITLE", "Wooden recurve hunting bow strung with taut bowstring")
    d[1143] = ("RETITLE", "Feather-fletched hunting arrow with sharp steel arrowhead tip")
    d[1144] = ("RETITLE", "Archery target board with circular bullseye rings and hit arrow")
    d[1145] = ("RETITLE", "Quiver filled with arrows slung across an archer shoulder")
    d[1146] = ("RETITLE", "Modern compound archery bow with pulley cams and cable system")
    
    # 1147..1151: holiday-and-events/saint-patricks-day
    d[1147] = ("RETITLE", "Four-leaf clover lucky shamrock with slender curved stem")
    d[1148] = ("RETITLE", "Leprechaun green top hat with black buckle band and shamrock")
    d[1149] = ("RETITLE", "Pot of gold coins sitting at the end of a rainbow")
    d[1150] = ("RETITLE", "Three-leaf Irish shamrock plant leaf silhouette symbol")
    d[1151] = ("RETITLE", "Leprechaun dancing a jig holding a wooden shillelagh stick")
    
    # 1152..1153: logos/television
    d[1152] = ("RETITLE", "Vintage television broadcasting network station identification logo")
    d[1153] = ("RETITLE", "Cathode ray television screen displaying test pattern tuning card")
    
    # 1154..1160: religion/yin-and-yang
    d[1154] = ("RETITLE", "Daoist Yin and Yang circular symbol showing cosmic balance")
    d[1155] = ("RETITLE", "Interlocking Yin and Yang emblem with light and dark dots")
    d[1156] = ("RETITLE", "Stylized Yin Yang symbol surrounded by eight Bagua trigram lines")
    d[1157] = ("RETITLE", "Flaming Yin Yang medallion radiating solar energy flames")
    d[1158] = ("RETITLE", "Water and fire swirling into a harmonious Yin Yang circle")
    d[1159] = ("RETITLE", "Two koi fish swimming in a circular Yin Yang formation")
    d[1160] = ("RETITLE", "Dragon and tiger circling around a central Yin Yang core")
    
    # 1161..1162: computers/atari
    d[1161] = ("RETITLE", "Atari Fuji logo three-pronged mountain symbol")
    d[1162] = ("RETITLE", "Atari 2600 vintage video game console with joystick controller")
    
    # 1163..1165: food-and-drinks/candies
    d[1163] = ("RETITLE", "Striped peppermint hard candy wrapped in twisted cellophane wrapper")
    d[1164] = ("RETITLE", "Swirled rainbow lollipop candy on a white plastic stick")
    d[1165] = ("RETITLE", "Chocolate candy bar with paper wrapper partially peeled back")
    
    # 1166..1169: food-and-drinks/apples
    d[1166] = ("RETITLE", "Fresh round apple fruit with single leaf attached to stem")
    d[1167] = ("RETITLE", "Apple core left over after fruit has been eaten")
    d[1168] = ("RETITLE", "Apple sliced in half showing seed core and stem")
    d[1169] = ("RETITLE", "Basket filled with freshly harvested red orchard apples")
    
    # 1170..1171: logos/other
    d[1170] = ("RETITLE", "Treble clef musical notation symbol drawn in sleek curves")
    d[1171] = ("RETITLE", "International biohazard hazard warning symbol with three interlocking rings")
    
    # 1172..1190: holiday-and-events/valentine
    d[1172] = ("RETITLE", "Simple symmetrical heart symbol representing romantic love")
    d[1173] = ("RETITLE", "Heart pierced through the center by a Cupid arrow")
    d[1174] = ("RETITLE", "Two interlocking hearts joined together in eternal romance")
    d[1175] = ("RETITLE", "Winged heart soaring with feathered angel wings attached")
    d[1176] = ("RETITLE", "Heart shape formed by a decorative floral vine border")
    d[1177] = ("RETITLE", "Heart-shaped Valentine gift box tied with a satin ribbon")
    d[1178] = ("RETITLE", "Cupid cherub angel aiming bow and love arrow at a heart")
    d[1179] = ("RETITLE", "Broken heart cracked down the center into two halves")
    d[1180] = ("RETITLE", "Flaming sacred heart radiating beams of light and warmth")
    d[1181] = ("RETITLE", "Valentine greeting card envelope with a heart sealing stamp")
    d[1182] = ("RETITLE", "Heart with a ribbon banner banner wrapped across the front")
    d[1183] = ("RETITLE", "Locket necklace shaped like a heart on a delicate chain")
    d[1184] = ("RETITLE", "Padlock shaped like a heart with keyhole in center")
    d[1185] = ("RETITLE", "Heart-shaped balloon floating on a curly decorative ribbon")
    d[1186] = ("RETITLE", "Bouquet of twelve long-stem red roses in a vase")
    d[1187] = ("RETITLE", "Heart silhouette filled with intricate filigree lace patterns")
    d[1188] = ("RETITLE", "Two lovebirds sitting together on a branch shaped like a heart")
    d[1189] = ("RETITLE", "Love letter scroll sealed with a heart-shaped wax seal")
    d[1190] = ("RETITLE", "Teddy bear holding a red plush heart with I Love You")
    
    # 1191..1201: vehicles/boats
    d[1191] = ("RETITLE", "Wooden rowing rowboat floating with a pair of oars")
    d[1192] = ("RETITLE", "Sailboat cruising across open water with triangular sails billowed")
    d[1193] = ("RETITLE", "Grand pirate sailing galleon ship with multiple masts and cannons")
    d[1194] = ("RETITLE", "Motorized speedboat gliding across water leaving a wake")
    d[1195] = ("RETITLE", "Tugboat vessel with smokestack puffing exhaust over harbor")
    d[1196] = ("RETITLE", "Canoe boat with single paddle resting across the gunwale")
    d[1197] = ("RETITLE", "Modern ocean cruise liner ship with multi-deck passenger cabins")
    d[1198] = ("RETITLE", "Submarine naval vessel cruising on the surface of the sea")
    d[1199] = ("RETITLE", "Kayak sporting boat with double-bladed paddle ready for rapids")
    d[1200] = ("RETITLE", "Viking longship with dragon figurehead prow and shield row")
    d[1201] = ("RETITLE", "Fishing trawler vessel with crane nets rigged over water")
    
    # 1202..1203: space/other
    d[1202] = ("RETITLE", "Solar system diagram showing planets orbiting around the central sun")
    d[1203] = ("RETITLE", "Comet soaring through deep space with a long glowing tail")
    
    # 1204..1210: buildings-and-places/flags
    d[1204] = ("RETITLE", "American flag Stars and Stripes waving proudly on flagpole")
    d[1205] = ("RETITLE", "British Union Jack flag waving from an angled flagstaff")
    d[1206] = ("RETITLE", "Canadian maple leaf flag displayed in crisp rectangular frame")
    d[1207] = ("RETITLE", "Pirate skull and crossbones Jolly Roger flag flying in wind")
    d[1208] = ("RETITLE", "Checkered racing flag waving at the motor speedway finish line")
    d[1209] = ("RETITLE", "United Nations globe emblem flag surrounded by olive branches")
    d[1210] = ("RETITLE", "Blank pennant banner flag streaming from a vertical mast")
    
    # 1211..1212: nature/beach
    d[1211] = ("RETITLE", "Tropical sandy beach scene with palm tree and ocean waves")
    d[1212] = ("RETITLE", "Beach umbrella planted in sand beside a bucket and shovel")
    
    # 1213..1214: miscellaneous/signs
    d[1213] = ("RETITLE", "Octagonal STOP traffic sign mounted on a metal road post")
    d[1214] = ("RETITLE", "Directional wooden fingerpost signpost pointing to multiple trails")
    
    # 1215..1227: religion/christianity
    d[1215] = ("RETITLE", "Christian Latin cross symbol drawn in clean geometric lines")
    d[1216] = ("RETITLE", "Ornate Celtic cross with circular halo ring behind intersecting arms")
    d[1217] = ("RETITLE", "Crucifix showing Jesus Christ on the wooden cross")
    d[1218] = ("RETITLE", "Holy Bible book with cross embossed on front leather cover")
    d[1219] = ("RETITLE", "Ichthys Christian fish symbol drawn in an unbroken curve")
    d[1220] = ("RETITLE", "Church building with stained glass windows and tall cross steeple")
    d[1221] = ("RETITLE", "Communion chalice goblet and plate of consecrated bread wafer")
    d[1222] = ("RETITLE", "Holy Spirit dove descending in flight with olive branch")
    d[1223] = ("RETITLE", "Crown of thorns woven circle symbol from the Passion")
    d[1224] = ("RETITLE", "Praying hands clasped together in reverent spiritual devotion")
    d[1225] = ("RETITLE", "Rosary prayer beads with hanging crucifix cross medal")
    d[1226] = ("RETITLE", "Saint Peter crossed golden and silver keys of heaven")
    d[1227] = ("RETITLE", "Stained glass cathedral rose window with radial geometric segments")
    
    # 1228..1229: clothing-and-accessories/bikinis -> DELETE nsfw
    d[1228] = ("DELETE", "nsfw")
    d[1229] = ("DELETE", "nsfw")
    
    # 1230..1232: miscellaneous/anchors
    d[1230] = ("RETITLE", "Nautical ship anchor with curved flukes and heavy iron stock")
    d[1231] = ("RETITLE", "Anchor wrapped with a coiled mooring hawser rope")
    d[1232] = ("RETITLE", "Fouled anchor naval symbol with chain links wrapped around shank")
    
    # 1233..1236: books/lord-of-the-rings
    d[1233] = ("RETITLE", "One Ring of Power from Lord of the Rings with Elvish script")
    d[1234] = ("RETITLE", "Gandalf the Grey wizard hat and wooden gnarled staff")
    d[1235] = ("RETITLE", "Sauron all-seeing fiery Eye atop the dark Barad-dur tower")
    d[1236] = ("RETITLE", "Elven leaf brooch clasp from Lothlorien pinned on cloak")
    
    # 1237..1248: art-and-design/gender-symbols
    d[1237] = ("RETITLE", "Female Venus astronomical symbol with cross below circle")
    d[1238] = ("RETITLE", "Male Mars astronomical symbol with arrow pointing upper right")
    d[1239] = ("RETITLE", "Interlocking Mars and Venus symbols representing male female union")
    d[1240] = ("RETITLE", "Gender equality symbol with combined Mars arrow and Venus cross")
    d[1241] = ("RETITLE", "Two linked female Venus symbols representing lesbian partnership")
    d[1242] = ("RETITLE", "Two linked male Mars symbols representing gay partnership")
    d[1243] = ("RETITLE", "Transgender symbol combining male arrow, female cross, and merged stroke")
    d[1244] = ("RETITLE", "Non-binary gender symbol with star burst atop circle")
    d[1245] = ("RETITLE", "Mercury gender symbol with horned crescent atop circle")
    d[1246] = ("RETITLE", "Gender neutrality circle symbol without gendered extension strokes")
    d[1247] = ("RETITLE", "Androgyny symbol combining female cross and male arrow strokes")
    d[1248] = ("RETITLE", "Interlocking astrological gender glyphs arranged in circular ring")
    
    # 1249..1252: mythology/gryphon
    d[1249] = ("RETITLE", "Gryphon standing vigilant with eagle head, wings, and lion hindquarters")
    d[1250] = ("RETITLE", "Griffin rampant in heraldic pose with raised talons and beak")
    d[1251] = ("RETITLE", "Flying griffin soaring with feathered wingspan and lion tail")
    d[1252] = ("RETITLE", "Griffin guarding a hoard of treasure with hooked claws")
    
    # 1253..1255: nature/camping
    d[1253] = ("RETITLE", "Campfire with burning logs and dancing flames under starry sky")
    d[1254] = ("RETITLE", "A-frame camping tent pitched in a forest clearing near pine trees")
    d[1255] = ("RETITLE", "Camping kettle boiling water over an open wood tripod fire")
    
    # 1256..1257: television/star-trek
    d[1256] = ("RETITLE", "USS Enterprise starship soaring through warp space with dual nacelles")
    d[1257] = ("RETITLE", "Starfleet delta insignia badge emblem from Star Trek federation")
    
    # 1258: miscellaneous/playing-cards
    d[1258] = ("RETITLE", "Four playing card suit symbols spades, hearts, diamonds, and clubs")
    
    # 1259..1264: clothing-and-accessories/crowns
    d[1259] = ("RETITLE", "Royal monarch golden crown with five jeweled velvet peaks")
    d[1260] = ("RETITLE", "Imperial coronation crown adorned with diamonds and cross finial")
    d[1261] = ("RETITLE", "Princess tiara diadem with delicate filigree diamond loops")
    d[1262] = ("RETITLE", "Medieval king coronet band with Fleur-de-lis ornamental crests")
    d[1263] = ("RETITLE", "Crown resting on a soft royal velvet ceremonial cushion")
    d[1264] = ("RETITLE", "Laurel wreath victory crown worn by Roman emperors")
    
    # 1265..1266: sports-and-outdoors/bungee-jumping
    d[1265] = ("RETITLE", "Bungee jumper falling headfirst from a high bridge with cord")
    d[1266] = ("RETITLE", "Person rebounding upward on elastic bungee cord with arms out")
    
    # 1267..1270: plants/bonsai-trees
    d[1267] = ("RETITLE", "Miniature bonsai tree potted in a shallow ceramic dish")
    d[1268] = ("RETITLE", "Gnarled pine bonsai tree with curved weathered trunk and needles")
    d[1269] = ("RETITLE", "Flowering cherry blossom bonsai tree in decorative planter")
    d[1270] = ("RETITLE", "Windswept style bonsai tree with branches slanted to one side")
    
    # 1271..1272: animals/moose
    d[1271] = ("RETITLE", "Bull moose standing in profile with broad palmate antlers")
    d[1272] = ("RETITLE", "Moose head portrait showing heavy muzzle and wide spread rack")
    
    # 1273..1279: animals/camels
    d[1273] = ("RETITLE", "Dromedary camel with single hump walking across sandy dunes")
    d[1274] = ("RETITLE", "Bactrian two-humped camel resting on knees in desert")
    d[1275] = ("RETITLE", "Camel carrying a loaded caravan pack saddle with cargo")
    d[1276] = ("RETITLE", "Camel head in profile with long eyelashes and curved neck")
    d[1277] = ("RETITLE", "Baby camel standing beside its mother in a desert oasis")
    d[1278] = ("RETITLE", "Camel silhouette trekking across desert horizon at sunset")
    d[1279] = ("RETITLE", "Bedouin riding a camel across windswept desert dunes")
    
    # 1280..1290: animals/dolphins
    d[1280] = ("RETITLE", "Dolphin leaping out of the water in a graceful curved arc")
    d[1281] = ("RETITLE", "Two dolphins swimming together alongside ocean surface waves")
    d[1282] = ("RETITLE", "Dolphin smiling underwater with curved beak and dorsal fin")
    d[1283] = ("RETITLE", "Pod of three dolphins jumping in unison through water")
    d[1284] = ("RETITLE", "Dolphin tail fluke splashing above the rippling waterline")
    d[1285] = ("RETITLE", "Bottlenose dolphin balancing a play ball on its snout")
    d[1286] = ("RETITLE", "Dolphin diving downward into deep water with streamlined body")
    d[1287] = ("RETITLE", "Mother dolphin swimming closely beneath her newborn calf")
    d[1288] = ("RETITLE", "Dolphin jumping through a training hoop in marine park")
    d[1289] = ("RETITLE", "Stylized dolphin silhouette soaring over ocean crests")
    d[1290] = ("RETITLE", "Dolphin riding the bow wave pressure of a sailing ship")
    
    # 1291..1299: sports-and-outdoors/billiards
    d[1291] = ("RETITLE", "Billiard pool balls racked inside a wooden triangle frame")
    d[1292] = ("RETITLE", "Cue ball striking the eight ball into a corner table pocket")
    d[1293] = ("RETITLE", "Two crossed wooden pool cue sticks over a billiard ball")
    d[1294] = ("RETITLE", "Billiard eight ball with black glossy surface and white circle")
    d[1295] = ("RETITLE", "Player lining up a pool shot along the cue stick on felt")
    d[1296] = ("RETITLE", "Striped and solid pool balls scattered across green pool table")
    d[1297] = ("RETITLE", "Billiard cue stick resting on the wooden rail of pool table")
    d[1298] = ("RETITLE", "Square cube of blue cue tip chalk sitting on table rail")
    d[1299] = ("RETITLE", "Overhead view of rectangular green felt billiard pool table")
    
    # 1300..1301: logos/no-smoking
    d[1300] = ("RETITLE", "No smoking international prohibition sign with cigarette behind red bar")
    d[1301] = ("RETITLE", "Circle with diagonal slash over a smoking lit cigarette")
    
    # 1302: books/other
    d[1302] = ("RETITLE", "Ancient papyrus scroll document unfurled on a wooden table")
    
    # 1303..1349: weapons/swords (47 swords)
    d[1303] = ("RETITLE", "Medieval knight longsword with cruciform crossguard and round pommel")
    d[1304] = ("RETITLE", "Two crossed broadswords with ornamental hilts and sharp blades")
    d[1305] = ("RETITLE", "Japanese katana samurai sword with curved steel blade and tsuba guard")
    d[1306] = ("RETITLE", "Pirate cutlass with curved single-edged blade and basket hilt")
    d[1307] = ("RETITLE", "Renaissance dueling rapier sword with intricate swept wire hilt")
    d[1308] = ("RETITLE", "Fantasy broadsword with jagged serrated edges and rune-inscribed fuller")
    d[1309] = ("RETITLE", "Excalibur sword plunged deep into a mystical stone anvil")
    d[1310] = ("RETITLE", "Scimitar sword with deeply curved Middle Eastern curved blade")
    d[1311] = ("RETITLE", "Roman gladius short sword with wide double-edged blade and wooden grip")
    d[1312] = ("RETITLE", "Two crossed katanas with cord-wrapped tsuka handles")
    d[1313] = ("RETITLE", "Viking battle sword with patterned Damascus steel blade and pommel")
    d[1314] = ("RETITLE", "Two-handed claymore greatsword with angled quillons and leather grip")
    d[1315] = ("RETITLE", "Flaming magic sword with elemental fire blazing along blade")
    d[1316] = ("RETITLE", "Dagger stiletto with slender piercing point and brass crossguard")
    d[1317] = ("RETITLE", "Sword blade sheathed halfway inside an ornate leather scabbard")
    d[1318] = ("RETITLE", "Two crossed pirate cutlasses above a menacing Jolly Roger skull")
    d[1319] = ("RETITLE", "Cavalry saber sword with knuckle-bow handguard and curved blade")
    d[1320] = ("RETITLE", "Sword with wing-shaped crossguard and sapphire jewel set in pommel")
    d[1321] = ("RETITLE", "Ninja ninjato straight-bladed sword with square tsuba guard")
    d[1322] = ("RETITLE", "Double-bladed fantasy sword with grips in the central staff")
    d[1323] = ("RETITLE", "Knight kneeling with head bowed holding sword by the blade")
    d[1324] = ("RETITLE", "Short gladius sword resting diagonally across a round shield")
    d[1325] = ("RETITLE", "Two crossed fencing foils with bell guards and button tips")
    d[1326] = ("RETITLE", "Ornate ceremonial coronation sword with filigree gold wire grip")
    d[1327] = ("RETITLE", "Bastard sword hand-and-a-half with diamond cross section blade")
    d[1328] = ("RETITLE", "Curved falchion sword with heavy cleaver-like cutting tip")
    d[1329] = ("RETITLE", "Sword standing point down into the ground as a warrior memorial")
    d[1330] = ("RETITLE", "Pair of crossed dueling rapiers with cup hilts")
    d[1331] = ("RETITLE", "Zweihander two-handed sword with flanged parrying hooks above hilt")
    d[1332] = ("RETITLE", "Dagger with twisted serpentine wavy kris blade")
    d[1333] = ("RETITLE", "Sword blade reflecting a bright gleaming star glint")
    d[1334] = ("RETITLE", "Ancient bronze leaf-shaped sword from the classical Aegean era")
    d[1335] = ("RETITLE", "Knight sword displayed mounted vertically on a wooden wall plaque")
    d[1336] = ("RETITLE", "Two crossed short swords with brass knuckle bow guards")
    d[1337] = ("RETITLE", "Ornate elven sword with slender flowing organic curves")
    d[1338] = ("RETITLE", "Heavy executioner sword with broad blunt squared tip")
    d[1339] = ("RETITLE", "Wakizashi Japanese short companion sword with wooden saya sheath")
    d[1340] = ("RETITLE", "Broken sword blade shattered into two jagged pieces")
    d[1341] = ("RETITLE", "Two crossed scimitars above a crescent moon emblem")
    d[1342] = ("RETITLE", "Sword with serpent coiling around the steel blade")
    d[1343] = ("RETITLE", "Gothic arming sword with down-turned quillons and wheel pommel")
    d[1344] = ("RETITLE", "Sword being forged by hammer blows on a blacksmith anvil")
    d[1345] = ("RETITLE", "Small parrying main gauche dagger with pronged crossguard")
    d[1346] = ("RETITLE", "Two crossed cavalry sabers displayed on military shield")
    d[1347] = ("RETITLE", "Broadsword with dragon head carved into the pommel")
    d[1348] = ("RETITLE", "Sword with lightning bolts crackling along the sharp edge")
    d[1349] = ("RETITLE", "Twin hooked swords with crescent moon hand guards")
    
    # 1350..1351: computers/bug
    d[1350] = ("RETITLE", "Software computer bug insect trapped inside integrated circuit chip")
    d[1351] = ("RETITLE", "Magnifying glass examining a literal insect bug on a circuit")
    
    # 1352..1355: art-and-design/mazes
    d[1352] = ("RETITLE", "Square maze labyrinth with intricate branching corridors and single path")
    d[1353] = ("RETITLE", "Circular maze puzzle with concentric rings and center goal")
    d[1354] = ("RETITLE", "Diamond-shaped maze network with walls and pathway dead ends")
    d[1355] = ("RETITLE", "Complex labyrinth path connecting entry arrow to exit finish")
    
    # 1356..1363: animals/elephants
    d[1356] = ("RETITLE", "African elephant standing large with broad ears and curved tusks")
    d[1357] = ("RETITLE", "Elephant lifting its trunk high in a joyful trumpeting greeting")
    d[1358] = ("RETITLE", "Mother elephant walking with baby elephant holding mother tail")
    d[1359] = ("RETITLE", "Asian elephant with decorated ceremonial festival blanket on back")
    d[1360] = ("RETITLE", "Elephant head in profile showing wrinkled skin and trunk curve")
    d[1361] = ("RETITLE", "Elephant spraying water over its back with curled trunk")
    d[1362] = ("RETITLE", "Two elephants facing each other with trunks gently entwined")
    d[1363] = ("RETITLE", "Cute cartoon elephant sitting down with large floppy ears")
    
    # 1364..1366: animals/fish
    d[1364] = ("RETITLE", "Tropical fish swimming left with vertical yellow and black stripes")
    d[1365] = ("RETITLE", "Goldfish with delicate translucent fin rays swimming in water")
    d[1366] = ("RETITLE", "Piranha fish with sharp undershot jaw and menacing teeth")
    
    # 1367: miscellaneous/keys
    d[1367] = ("RETITLE", "Antique skeleton key with ornate circular bow and ward notches")
    
    # 1368..1382: art-and-design/geometries
    d[1368] = ("RETITLE", "Three-dimensional isometric cube wireframe box floating in space")
    d[1369] = ("RETITLE", "Pyramid geometric solid with four triangular faces and square base")
    d[1370] = ("RETITLE", "Geometric cylinder tube solid with parallel circular bases")
    d[1371] = ("RETITLE", "Sphere geometric ball wireframe with latitude and longitude lines")
    d[1372] = ("RETITLE", "Cone geometric shape tapering from circular base to vertex point")
    d[1373] = ("RETITLE", "Regular octahedron solid with eight equilateral triangular faces")
    d[1374] = ("RETITLE", "Dodecahedron twelve-sided geometric polyhedron wireframe model")
    d[1375] = ("RETITLE", "Icosahedron twenty-sided geometric polyhedron structure")
    d[1376] = ("RETITLE", "Torus donut geometric shape with hole in the center")
    d[1377] = ("RETITLE", "Hypercube tesseract four-dimensional wireframe projection")
    d[1378] = ("RETITLE", "Möbius strip continuous one-sided twisted topological loop")
    d[1379] = ("RETITLE", "Klein bottle one-sided topological non-orientable surface bottle")
    d[1380] = ("RETITLE", "Hexagonal prism geometric column with two parallel hexagon faces")
    d[1381] = ("RETITLE", "Parallelepiped three-dimensional prism with six parallelogram faces")
    d[1382] = ("RETITLE", "Penrose impossible triangle optical illusion geometric structure")
    
    # 1383..1391: sports-and-outdoors/fencing
    d[1383] = ("RETITLE", "Fencer lunging forward with foil sword extended in attack")
    d[1384] = ("RETITLE", "Two fencers dueling on a piste with masks and swords crossed")
    d[1385] = ("RETITLE", "Fencing mesh wire mask helmet protecting head and neck")
    d[1386] = ("RETITLE", "Fencer in en garde defensive ready stance with foil raised")
    d[1387] = ("RETITLE", "Fencer scoring a touch point on opponent chest jacket")
    d[1388] = ("RETITLE", "Foil sword with curved pistol grip handle and circular guard")
    d[1389] = ("RETITLE", "Fencer saluting with sword raised vertically before match")
    d[1390] = ("RETITLE", "Epee fencing weapon with large triangular blade and bell guard")
    d[1391] = ("RETITLE", "Fencer parrying an incoming sword thrust with quick blade motion")
    
    # 1392..1394: animals/bisons
    d[1392] = ("RETITLE", "American bison buffalo standing sturdy with heavy horned head")
    d[1393] = ("RETITLE", "Bison grazing on prairie grasses with thick shaggy neck coat")
    d[1394] = ("RETITLE", "Bison herd bull charging forward with head lowered")
    
    # 1395..1399: religion/judaism
    d[1395] = ("RETITLE", "Star of David Magen David six-pointed Jewish hexagram star")
    d[1396] = ("RETITLE", "Menorah seven-branched golden candelabrum with lit oil flames")
    d[1397] = ("RETITLE", "Hanukkah nine-branched menorah hanukkiah with center shamash candle")
    d[1398] = ("RETITLE", "Torah scroll parchment unrolled between two carved wooden rollers")
    d[1399] = ("RETITLE", "Shofar ram horn instrument sounded for Jewish holidays")
    
    # 1400: buildings-and-places/windmills
    d[1400] = ("RETITLE", "Traditional Dutch windmill with four large rotating wooden sails")
    
    return d

if __name__ == "__main__":
    b3 = get_batch3()
    print(f"Batch 3 generated {len(b3)} decisions (expected 513: 888..1400)")
