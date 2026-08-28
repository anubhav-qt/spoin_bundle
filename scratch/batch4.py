# -*- coding: utf-8 -*-
"""Full decision map for Batch 4: indexes 1401 to 1900 (info part 2)."""
import json, io

entries = json.load(open(r"C:\Temp\entries.json", encoding="utf-8"))

def get_batch4():
    d = {}
    
    # 1401..1403: buildings-and-places/windmills
    d[1401] = ("RETITLE", "Traditional wooden windmill with canvas-covered lattice sails")
    d[1402] = ("RETITLE", "Rustic stone millhouse with rotating wooden wind turbine blades")
    d[1403] = ("RETITLE", "Modern three-bladed wind power turbine generator on tall tower")
    
    # 1404..1407: computers/linux
    d[1404] = ("RETITLE", "Tux the Linux penguin sitting with round white belly and yellow beak")
    d[1405] = ("RETITLE", "Tux penguin mascot waving hand while holding a coffee mug")
    d[1406] = ("RETITLE", "Linux penguin wearing a wizard hat casting kernel compile magic")
    d[1407] = ("RETITLE", "Tux penguin sliding down an icy slope on his belly")
    
    # 1408..1409: vehicles/navy
    d[1408] = ("RETITLE", "Naval aircraft carrier warship with runway deck and radar tower")
    d[1409] = ("RETITLE", "Battleship cruiser with heavy gun turrets firing over sea")
    
    # 1410..1414: sports-and-outdoors/other
    d[1410] = ("RETITLE", "Weightlifter athlete lifting heavy barbell overhead in clean and jerk")
    d[1411] = ("RETITLE", "Gymnast performing a handstand balance on parallel gymnastics bars")
    d[1412] = ("RETITLE", "Rock climber scaling a vertical mountain cliff with harness")
    d[1413] = ("RETITLE", "Skateboarder performing an ollie jump trick in skate park")
    d[1414] = ("DELETE", "nsfw") # Nude Beach Volley Ball per README rule!
    
    # 1415..1416: space/satellites
    d[1415] = ("RETITLE", "Orbital communications satellite with dual blue solar panel wings")
    d[1416] = ("RETITLE", "Sputnik 1 spherical satellite with four trailing radio antennae")
    
    # 1417..1420: religion/other
    d[1417] = ("RETITLE", "Hindu Om Aum sacred spiritual symbol drawn in flowing curves")
    d[1418] = ("RETITLE", "Islamic crescent moon and five-pointed star religious emblem")
    d[1419] = ("RETITLE", "Ancient Egyptian Ankh key of life hieroglyphic cross symbol")
    d[1420] = ("RETITLE", "Dharmachakra eight-spoked Buddhist wheel of doctrine law")
    
    # 1421: animals/amoeba
    d[1421] = ("RETITLE", "Microscopic amoeba cell with irregular pseudopod arms and nucleus")
    
    # 1422: art-and-design/sculptures
    d[1422] = ("RETITLE", "Classical Greek stone statue sculpture of Venus de Milo")
    
    # 1423..1425: sports-and-outdoors/skiing
    d[1423] = ("RETITLE", "Downhill skier carving through fresh powder snow with poles")
    d[1424] = ("RETITLE", "Cross-country Nordic skier gliding along a forest trail track")
    d[1425] = ("RETITLE", "Ski jumper soaring airborne from an Olympic ski jump ramp")
    
    # 1426: sports-and-outdoors/boxing
    d[1426] = ("RETITLE", "Pair of padded leather boxing gloves laced ready for match")
    
    # 1427..1441: plants/flowers
    d[1427] = ("RETITLE", "Blooming sunflower with wide dark seed center and yellow petals")
    d[1428] = ("RETITLE", "Tulip flower with smooth cup-shaped blossom on upright stem")
    d[1429] = ("RETITLE", "Daisy flower with delicate slender petals radiating from center disk")
    d[1430] = ("RETITLE", "Potted flowering plant growing in a terracotta ceramic pot")
    d[1431] = ("RETITLE", "Water lily blossom floating on a flat round pond lilypad")
    d[1432] = ("RETITLE", "Bouquet of mixed wildflowers tied together with a satin ribbon")
    d[1433] = ("RETITLE", "Orchid flower blossom with exotic patterned petals and labellum lip")
    d[1434] = ("RETITLE", "Single blooming carnation with ruffled serrated flower petals")
    d[1435] = ("RETITLE", "Hibiscus tropical flower with long prominent central stamen column")
    d[1436] = ("RETITLE", "Morning glory bell-shaped climbing flower on a garden trellis")
    d[1437] = ("RETITLE", "Iris flower blossom with upright standards and drooping fall petals")
    d[1438] = ("RETITLE", "Poppy flower with dark black center surrounded by crinkled petals")
    d[1439] = ("RETITLE", "Lotus flower rising pure and pristine above muddy water surface")
    d[1440] = ("RETITLE", "Garden watering can pouring water droplets over blooming seedlings")
    d[1441] = ("RETITLE", "Glass vase filled with fresh cut spring flower stems")
    
    # 1442..1444: nature/tornado
    d[1442] = ("RETITLE", "Violent tornado funnel cloud swirling down from dark storm clouds")
    d[1443] = ("RETITLE", "Waterspout vortex spinning across the surface of the ocean")
    d[1444] = ("RETITLE", "Dust devil whirlwind spiraling across arid desert ground")
    
    # 1445..1448: miscellaneous/money
    d[1445] = ("RETITLE", "Dollar sign currency symbol with two vertical stroke lines")
    d[1446] = ("RETITLE", "Stack of minted gold coins piled neatly on a table")
    d[1447] = ("RETITLE", "Paper bank note currency bill with portrait oval in center")
    d[1448] = ("RETITLE", "Cloth money bag tied with string and dollar sign on side")
    
    # 1449: nature/snows
    d[1449] = ("RETITLE", "Six-pointed symmetrical crystalline ice snowflake with intricate lace arms")
    
    # 1450..1453: buildings-and-places/lighthouses
    d[1450] = ("RETITLE", "Coastal lighthouse tower on rocky cliff shining beacon light beam")
    d[1451] = ("RETITLE", "Spiral striped lighthouse overlooking stormy crashing ocean waves")
    d[1452] = ("RETITLE", "Lighthouse lantern room with rotating Fresnel lens casting rays")
    d[1453] = ("RETITLE", "Historic brick lighthouse with keeper cottage dwelling beside")
    
    # 1454: clothing-and-accessories/skirts
    d[1454] = ("RETITLE", "Pleated A-line mini skirt with belted waistband trim")
    
    # 1455..1456: weapons/other
    d[1455] = ("RETITLE", "Medieval spiked morningstar mace weapon on a wooden shaft")
    d[1456] = ("RETITLE", "Flail weapon with iron spiked ball attached by chain to handle")
    
    # 1457..1458: buildings-and-places/other
    d[1457] = ("RETITLE", "Arched stone bridge spanning across a flowing river stream")
    d[1458] = ("RETITLE", "Suspension bridge with tall supporting towers and steel cables")
    
    # 1459..1468: music/musical-notation
    d[1459] = ("RETITLE", "Treble clef G-clef musical staff notation symbol on five lines")
    d[1460] = ("RETITLE", "Bass clef F-clef symbol with two notation dots")
    d[1461] = ("RETITLE", "Pair of eighth notes beamed together on musical staff")
    d[1462] = ("RETITLE", "Single quarter note with stem and solid black notehead")
    d[1463] = ("RETITLE", "Sixteenth note with double flag waving from stem")
    d[1464] = ("RETITLE", "Musical staff measure with treble clef, sharp, and notes")
    d[1465] = ("RETITLE", "Sharp accident musical symbol with intersecting parallel lines")
    d[1466] = ("RETITLE", "Flat musical note accident symbol with curved b shape")
    d[1467] = ("RETITLE", "Natural musical cancellation accident sign on staff")
    d[1468] = ("RETITLE", "Quarter rest musical notation symbol marking a silent beat")
    
    # 1469..1475: sports-and-outdoors/soccer
    d[1469] = ("RETITLE", "Classic soccer football with black pentagon and white hexagon patches")
    d[1470] = ("RETITLE", "Soccer ball hitting the back of the goal net")
    d[1471] = ("RETITLE", "Soccer player kicking the ball in a powerful forward volley")
    d[1472] = ("RETITLE", "Goalkeeper diving horizontally to block a soccer goal shot")
    d[1473] = ("RETITLE", "Pair of soccer cleat shoes with rubber traction studs")
    d[1474] = ("RETITLE", "Referee showing a yellow card warning during soccer match")
    d[1475] = ("RETITLE", "Soccer championship trophy cup with dual handles and base")
    
    # 1476..1481: clothing-and-accessories/handwears
    d[1476] = ("RETITLE", "Pair of knitted winter mittens with ribbed wrist cuffs")
    d[1477] = ("RETITLE", "Leather five-finger glove with wrist strap buckle")
    d[1478] = ("RETITLE", "Pair of rubber household cleaning gloves on countertop")
    d[1479] = ("RETITLE", "Formal white silk dress gloves reaching up the forearm")
    d[1480] = ("RETITLE", "Heavy insulated ski glove with waterproof grip palm")
    d[1481] = ("RETITLE", "Fingerless weightlifting glove with padded palm cushioning")
    
    # 1482..1483: sports-and-outdoors/football
    d[1482] = ("RETITLE", "American football oval pigskin ball with stitched white laces")
    d[1483] = ("RETITLE", "Football helmet with protective face cage grill and chin strap")
    
    # 1484..1485: miscellaneous/handcuffs
    d[1484] = ("RETITLE", "Pair of steel police handcuffs linked by metal chain links")
    d[1485] = ("RETITLE", "Handcuffs clicked open with key inserted into keyhole")
    
    # 1486..1487: sports-and-outdoors/dancing
    d[1486] = ("RETITLE", "Ballroom dance couple waltzing in formal gown and tuxedo")
    d[1487] = ("RETITLE", "Flamenco dancer swirling in layered ruffled dress with fan")
    
    # 1488..1499: computers/smileys
    d[1488] = ("RETITLE", "Classic round yellow smiley face smiling with dot eyes")
    d[1489] = ("RETITLE", "Smiley face winking cheekily with one eye closed")
    d[1490] = ("RETITLE", "Smiley face wearing cool black sunglasses with broad grin")
    d[1491] = ("RETITLE", "Laughing smiley face with wide open mouth and closed eyes")
    d[1492] = ("RETITLE", "Sad smiley face with down-turned frowning mouth")
    d[1493] = ("RETITLE", "Surprised smiley face with round O mouth and wide eyes")
    d[1494] = ("RETITLE", "Crying smiley face with tear drop rolling down cheek")
    d[1495] = ("RETITLE", "Angry smiley face with furrowed V-shaped eyebrows")
    d[1496] = ("RETITLE", "Smiley face with halo floating overhead in angel innocence")
    d[1497] = ("RETITLE", "Smiley face sticking tongue out in a playful expression")
    d[1498] = ("RETITLE", "Love-struck smiley face with heart-shaped romantic eyes")
    d[1499] = ("RETITLE", "Sleeping smiley face with Zzz letters floating upward")
    
    # 1500..1519: computers/floppies (20 floppies)
    d[1500] = ("RETITLE", "3.5 inch micro floppy disk cartridge with metal shutter slider")
    d[1501] = ("RETITLE", "Floppy disk with handwritten adhesive paper label on top")
    d[1502] = ("RETITLE", "Stack of three 3.5 inch magnetic floppy diskettes")
    d[1503] = ("RETITLE", "Floppy disk with write-protect tab notch set to read-only")
    d[1504] = ("RETITLE", "5.25 inch flexible floppy disk with circular center spindle hole")
    d[1505] = ("RETITLE", "Floppy disk being inserted into the drive slot of a PC")
    d[1506] = ("RETITLE", "Floppy disk storage storage box with flip-top clear plastic lid")
    d[1507] = ("RETITLE", "3.5 inch floppy disk viewed from reverse side showing hub")
    d[1508] = ("RETITLE", "Floppy disk save icon symbol representing data storage")
    d[1509] = ("RETITLE", "High density 1.44 MB floppy disk with dual corner sensor holes")
    d[1510] = ("RETITLE", "Vintage 8 inch magnetic diskette from early mainframe systems")
    d[1511] = ("RETITLE", "Floppy disk case holding ten organized software program disks")
    d[1512] = ("RETITLE", "Floppy diskette with paper label reading System Backup Disk")
    d[1513] = ("RETITLE", "Floppy disk with metal shutter spring mechanism exposed")
    d[1514] = ("RETITLE", "Floppy disk resting on a wooden computer desk next to mouse")
    d[1515] = ("RETITLE", "Floppy disk showing magnetic mylar oxide disk surface through window")
    d[1516] = ("RETITLE", "Floppy disk labeled Boot Disk with arrow insertion indicator")
    d[1517] = ("RETITLE", "Stack of five 5.25 inch floppy envelopes in protective sleeves")
    d[1518] = ("RETITLE", "Two 3.5 inch floppy disks lying side by side on table")
    d[1519] = ("RETITLE", "Floppy disk eject button popping out from computer disk drive")
    
    # 1520..1521: miscellaneous/awards
    d[1520] = ("RETITLE", "First place gold medal ribbon with number one in center")
    d[1521] = ("RETITLE", "Championship trophy cup standing tall with dual handles and plaque")
    
    # 1522..1526: plants/roses
    d[1522] = ("RETITLE", "Single blooming red rose blossom on long thorny stem")
    d[1523] = ("RETITLE", "Rose bud beginning to unfurl its tightly wound petals")
    d[1524] = ("RETITLE", "Two roses tied together with a flowing ribbon bow")
    d[1525] = ("RETITLE", "Rose blossom viewed from above showing spiraling concentric petal layers")
    d[1526] = ("RETITLE", "Rose resting horizontally with fallen petals scattered beside")
    
    # 1527..1530: weapons/knives
    d[1527] = ("RETITLE", "Folding pocket pocketknife with multiple folding utility blades")
    d[1528] = ("RETITLE", "Hunting knife with serrated gut hook spine and bone handle")
    d[1529] = ("RETITLE", "Chef kitchen santoku knife with broad chopping blade and rivets")
    d[1530] = ("RETITLE", "Combat survival dagger knife in heavy tactical sheath")
    
    # 1531..1536: plants/dandelions
    d[1531] = ("RETITLE", "Dandelion seed head clock with white fluffy parachute seeds")
    d[1532] = ("RETITLE", "Dandelion seeds blowing away floating in a gentle breeze")
    d[1533] = ("RETITLE", "Yellow dandelion flower blossom growing in green grass")
    d[1534] = ("RETITLE", "Dandelion plant showing serrated leaves, root, and puffball stem")
    d[1535] = ("RETITLE", "Child blowing on a dandelion seed head making a wish")
    d[1536] = ("RETITLE", "Single dandelion seed parachute drifting through the air")
    
    # 1537..1547: sports-and-outdoors/nba-logos
    d[1537] = ("RETITLE", "Chicago Bulls basketball team logo angry bull face with horns")
    d[1538] = ("RETITLE", "Los Angeles Lakers basketball logo with speed lines across ball")
    d[1539] = ("RETITLE", "Boston Celtics basketball leprechaun mascot spinning ball on finger")
    d[1540] = ("RETITLE", "Golden State Warriors basketball bridge icon logo")
    d[1541] = ("RETITLE", "San Antonio Spurs basketball spur logo with sharp rowel wheel")
    d[1542] = ("RETITLE", "Miami Heat flaming basketball dropping through hoop net")
    d[1543] = ("RETITLE", "New York Knicks basketball logo with angled banner block letters")
    d[1544] = ("RETITLE", "Houston Rockets basketball rocket ship launching through hoop")
    d[1545] = ("RETITLE", "Philadelphia 76ers basketball logo with thirteen circling stars")
    d[1546] = ("RETITLE", "Toronto Raptors dinosaur claw footprint basketball logo")
    d[1547] = ("RETITLE", "NBA official silhouette logo of dribbling basketball player")
    
    # 1548..1550: logos/recycle
    d[1548] = ("RETITLE", "Mobius loop recycling symbol with three chasing folded arrows")
    d[1549] = ("RETITLE", "Recycle symbol surrounding a globe representing environmental conservation")
    d[1550] = ("RETITLE", "Green curbside recycling bin container with three chasing arrows")
    
    # 1551..1552: miscellaneous/feathers
    d[1551] = ("RETITLE", "Bird quill feather with sharp nib point for calligraphy writing")
    d[1552] = ("RETITLE", "Soft downy bird feather drifting gently through the air")
    
    # 1553..1568: nature/sun (16 suns)
    d[1553] = ("RETITLE", "Radiant shining sun with straight triangular ray beams")
    d[1554] = ("RETITLE", "Smiling cartoon sun face with rosy cheeks and wavy rays")
    d[1555] = ("RETITLE", "Sun rising over ocean water horizon with rippling reflection")
    d[1556] = ("RETITLE", "Sun setting behind mountain peaks casting twilight shadows")
    d[1557] = ("RETITLE", "Sun partially obscured behind fluffy cumulus cloud cover")
    d[1558] = ("RETITLE", "Celestial sun with serene sleeping human face in center")
    d[1559] = ("RETITLE", "Tribal stylized sun medallion with spiral flame ray tendrils")
    d[1560] = ("RETITLE", "Total solar eclipse with moon blocking sun creating diamond ring")
    d[1561] = ("RETITLE", "Sun with alternating straight and wavy flaming solar flares")
    d[1562] = ("RETITLE", "Sun wearing dark sunglasses looking cool in summer sky")
    d[1563] = ("RETITLE", "Geometric Aztec style sun stone calendar disc face")
    d[1564] = ("RETITLE", "Sun with concentric halo rings radiating heat energy")
    d[1565] = ("RETITLE", "Morning sun shining through trees in an orchard meadow")
    d[1566] = ("RETITLE", "Sun bursting through storm clouds with god ray light beams")
    d[1567] = ("RETITLE", "Symmetrical solar emblem with eight pointed cardinal rays")
    d[1568] = ("RETITLE", "Golden sun shining bright over a field of blooming sunflowers")
    
    # 1569..1571: miscellaneous/bottles
    d[1569] = ("RETITLE", "Glass bottle containing a rolled secret parchment message inside")
    d[1570] = ("RETITLE", "Glass beverage bottle sealed with a crimped metal crown cap")
    d[1571] = ("RETITLE", "Wine bottle with long slender neck and natural cork stopper")
    
    # 1572..1574: plants/daffodils
    d[1572] = ("RETITLE", "Daffodil narcissus flower with trumpet-shaped central corona cup")
    d[1573] = ("RETITLE", "Two blooming daffodil flowers nodding on slender green stems")
    d[1574] = ("RETITLE", "Cluster of spring daffodils growing in a garden border patch")
    
    # 1575: holiday-and-events/hanukkah
    d[1575] = ("RETITLE", "Dreidel four-sided spinning top toy with Hebrew letters")
    
    # 1576..1589: weapons/axes (14 axes)
    d[1576] = ("RETITLE", "Double-bladed battle axe with curved crescent steel edges")
    d[1577] = ("RETITLE", "Woodcutter chopping axe embedded in a tree stump log")
    d[1578] = ("RETITLE", "Viking bearded axe with downward extended cutting hook edge")
    d[1579] = ("RETITLE", "Two crossed battle axes with spiked top points and handles")
    d[1580] = ("RETITLE", "Firefighter rescue axe with pick spike on reverse head")
    d[1581] = ("RETITLE", "Native American tomahawk axe with feather decorations on shaft")
    d[1582] = ("RETITLE", "Medieval halberd polearm combining axe blade, spear, and hook")
    d[1583] = ("RETITLE", "Lumberjack felling axe resting against a freshly cut log")
    d[1584] = ("RETITLE", "Broadaxe with wide flat blade for squaring hewn timber")
    d[1585] = ("RETITLE", "Throwing hatchet axe spinning through air toward target")
    d[1586] = ("RETITLE", "Heavy executioner axe with extra-wide curved cutting head")
    d[1587] = ("RETITLE", "Dwarven war axe with rune engravings and reinforced steel haft")
    d[1588] = ("RETITLE", "Small camping hatchet with rubberized grip handle and sheath")
    d[1589] = ("RETITLE", "Two crossed tomahawks above an eagle feather shield medallion")
    
    # 1590..1600: miscellaneous/other
    d[1590] = ("RETITLE", "Handheld magnifying glass enlarging lines of text on paper")
    d[1591] = ("RETITLE", "Horseshoe metal shoe with seven nail holes for good luck")
    d[1592] = ("RETITLE", "Four-leaf clover lucky charm sitting beside a silver coin")
    d[1593] = ("RETITLE", "Brass balance scale of justice weighing two hanging pans equally")
    d[1594] = ("RETITLE", "Wooden gavel hammer resting beside round sound block judge bench")
    d[1595] = ("RETITLE", "Compass rose direction star indicator showing four cardinal points")
    d[1596] = ("RETITLE", "Magic crystal ball sitting on a carved velvet pedestal")
    d[1597] = ("RETITLE", "Metal padlock locked securely through a heavy link chain")
    d[1598] = ("RETITLE", "Ship steering wheel helm with eight wooden turned spokes")
    d[1599] = ("RETITLE", "Hot coffee mug sitting on a saucer with rising aroma steam")
    d[1600] = ("RETITLE", "Smoking pipe resting in a carved wooden desktop pipe stand")
    
    # 1601..1603: logos/biohazards
    d[1601] = ("RETITLE", "Biohazard international biological danger warning symbol with three rings")
    d[1602] = ("RETITLE", "Radiation trefoil hazard symbol with three fan blades around dot")
    d[1603] = ("RETITLE", "Toxic chemical hazard warning symbol with skull and crossbones")
    
    # 1604..1606: miscellaneous/diamonds
    d[1604] = ("RETITLE", "Brilliant-cut sparkling diamond gemstone with geometric facets")
    d[1605] = ("RETITLE", "Diamond crystal reflecting bright light flashes from top table")
    d[1606] = ("RETITLE", "Solitaire diamond gemstone mounted in a six-prong gold ring")
    
    # 1607..1610: miscellaneous/noose
    d[1607] = ("RETITLE", "Hangman gallows noose rope with thirteen wound coils hanging")
    d[1608] = ("RETITLE", "Rope tied in a knot loop suspended from a wooden beam")
    d[1609] = ("RETITLE", "Execution gallows wooden platform scaffold with hanging noose rope")
    d[1610] = ("RETITLE", "Coiled nautical rope with hangman knot laid on wooden deck")
    
    # 1611..1613: logos/amnesty-international
    d[1611] = ("RETITLE", "Amnesty International candle symbol wrapped in barbed wire coils")
    d[1612] = ("RETITLE", "Flaming candle inside barbed wire loop symbol for human rights")
    d[1613] = ("RETITLE", "Amnesty International emblem with burning flame shining through barbs")
    
    # 1614..1627: clothing-and-accessories/hats
    d[1614] = ("RETITLE", "Formal black silk top hat with satin ribbon band around crown")
    d[1615] = ("RETITLE", "Cowboy ten-gallon hat with wide rolled brim and creased crown")
    d[1616] = ("RETITLE", "Baseball cap with curved front visor brim and button top")
    d[1617] = ("RETITLE", "Fedora felt hat with indented teardrop crown and pinched front")
    d[1618] = ("RETITLE", "Bowler derby hat with round dome crown and curled brim")
    d[1619] = ("RETITLE", "Sombrero wide-brimmed Mexican hat with tall conical crown")
    d[1620] = ("RETITLE", "Academic graduation mortarboard cap with hanging tassel cord")
    d[1621] = ("RETITLE", "Winter knitted beanie ski cap with fluffy yarn pompom top")
    d[1622] = ("RETITLE", "Chef tall pleated white toque hat for professional kitchen cooking")
    d[1623] = ("RETITLE", "Pirate tricorn three-cornered hat with feather plume attached")
    d[1624] = ("RETITLE", "Viking helmet with two curved horns mounted on the sides")
    d[1625] = ("RETITLE", "Hard hat construction safety helmet with front visor brim")
    d[1626] = ("RETITLE", "Lady wide-brimmed sun hat with decorative flower and ribbon")
    d[1627] = ("RETITLE", "Beret French woolen cap with tiny stem stalk on crown")
    
    # 1628..1629: animals/cats
    d[1628] = ("RETITLE", "Domestic cat sitting in graceful silhouette with curved tail")
    d[1629] = ("RETITLE", "Cat crouching with playful eyes preparing to pounce forward")
    
    # 1630: nature/other
    d[1630] = ("RETITLE", "Volcano mountain erupting with thick smoke plume and lava flow")
    
    # 1631..1654: electronics/televisions (24 TVs)
    d[1631] = ("RETITLE", "Vintage tube television set on four wooden peg legs with antenna")
    d[1632] = ("RETITLE", "Retro cathode ray TV with rabbit ear antennas and rotary tuning dials")
    d[1633] = ("RETITLE", "Modern widescreen flat panel smart television on tabletop stand")
    d[1634] = ("RETITLE", "Small portable television set with carrying handle on top")
    d[1635] = ("RETITLE", "Television screen displaying static fuzzy noise snow interference")
    d[1636] = ("RETITLE", "Wall-mounted television with home theater speaker soundbar below")
    d[1637] = ("RETITLE", "Television displaying SMPTE color calibration test pattern bars")
    d[1638] = ("RETITLE", "Vintage wooden console cabinet television with built-in speaker grill")
    d[1639] = ("RETITLE", "TV remote control handheld wand with rubber power and channel buttons")
    d[1640] = ("RETITLE", "Curved OLED wide television screen showing cinematic landscape picture")
    d[1641] = ("RETITLE", "Television screen showing an eye staring out at the viewer")
    d[1642] = ("RETITLE", "Old black and white television set showing a news broadcast")
    d[1643] = ("RETITLE", "Television with VCR video cassette recorder player deck stacked below")
    d[1644] = ("RETITLE", "Retro 1950s TV with circular round picture tube screen window")
    d[1645] = ("RETITLE", "Television antenna aerial mast mounted on a residential rooftop")
    d[1646] = ("RETITLE", "Person watching television while relaxing on the living room sofa")
    d[1647] = ("RETITLE", "Television screen showing No Signal disconnected message box")
    d[1648] = ("RETITLE", "Closed-circuit security surveillance CCTV monitor unit")
    d[1649] = ("RETITLE", "Compact bedside mini TV with telescopic metal aerial antenna")
    d[1650] = ("RETITLE", "Television studio broadcasting camera on heavy wheeled pedestal tripod")
    d[1651] = ("RETITLE", "Retro TV with rabbit ears wrapped in aluminum foil for signal")
    d[1652] = ("RETITLE", "Television monitor showing a human face on the screen")
    d[1653] = ("RETITLE", "Split-screen four-channel multi-view security display monitor")
    d[1654] = ("RETITLE", "Old CRT television sitting on an empty wooden table")
    
    # 1655: sports-and-outdoors/surfing
    d[1655] = ("RETITLE", "Surfer riding inside the barrel tube of a cresting ocean wave")
    
    # 1656..1666: miscellaneous/dna
    d[1656] = ("RETITLE", "DNA double helix molecular strand with twisting base pair rungs")
    d[1657] = ("RETITLE", "Genetic chromosome structure displaying DNA helix winding pattern")
    d[1658] = ("RETITLE", "Vertical DNA ladder model showing adenine, thymine, cytosine, guanine")
    d[1659] = ("RETITLE", "Stylized molecular biology DNA spiral strand spinning in 3D")
    d[1660] = ("RETITLE", "Segment of DNA double helix unzipping for genetic replication")
    d[1661] = ("RETITLE", "DNA helix strand surrounded by molecular chemical bond nodes")
    d[1662] = ("RETITLE", "Gene editing CRISPR diagram showing DNA strand cut by Cas9 enzyme")
    d[1663] = ("RETITLE", "Microscopic view of cellular chromosome X shape containing DNA")
    d[1664] = ("RETITLE", "DNA double helix helix winding through a biohazard security frame")
    d[1665] = ("RETITLE", "Futuristic biotechnology DNA biometric scanner interface graphic")
    d[1666] = ("RETITLE", "Continuous spiraling DNA polymer chain model")
    
    # 1667..1670: buildings-and-places/cities
    d[1667] = ("RETITLE", "Urban city skyline silhouette with skyscrapers under starry sky")
    d[1668] = ("RETITLE", "Modern metropolis towers with glowing office window lights at night")
    d[1669] = ("RETITLE", "City skyline reflecting across calm bay harbor waterfront")
    d[1670] = ("RETITLE", "Futuristic cityscape with soaring skybridges connecting skyscraper towers")
    
    # 1671: nature/mountains
    d[1671] = ("RETITLE", "Snow-capped mountain range peaks with pine trees in foreground valley")
    
    # 1672..1675: vehicles/other
    d[1672] = ("RETITLE", "Steam railway locomotive train engine chugging along metal tracks")
    d[1673] = ("RETITLE", "Farm tractor vehicle with massive treaded rear wheels in field")
    d[1674] = ("RETITLE", "School bus vehicle with stop sign arm and passenger windows")
    d[1675] = ("RETITLE", "Construction excavator digging machine with hydraulic bucket scoop arm")
    
    # 1676..1682: miscellaneous/mailbox
    d[1676] = ("RETITLE", "Curbside residential mailbox with red postal flag raised up")
    d[1677] = ("RETITLE", "Public postal collection letter drop box with pull-down slot door")
    d[1678] = ("RETITLE", "Mailbox mounted on wooden post with envelope peeking out")
    d[1679] = ("RETITLE", "Apartment wall mailboxes with individual key locks and nameplates")
    d[1680] = ("RETITLE", "Rural mailbox covered in fresh snow with icicles on latch")
    d[1681] = ("RETITLE", "Bird perching atop a wooden garden post mailbox")
    d[1682] = ("RETITLE", "Front door mail slot with incoming letter dropping through")
    
    # 1683: clothing-and-accessories/dresses
    d[1683] = ("RETITLE", "Strapless formal evening ballgown dress with flared billowing skirt")
    
    # 1684..1688: miscellaneous/buckets
    d[1684] = ("RETITLE", "Metal water bucket with arched wire bail carrying handle")
    d[1685] = ("RETITLE", "Wooden well bucket filled with fresh water drawn from a rope")
    d[1686] = ("RETITLE", "Plastic mop bucket with wringer mechanism on caster wheels")
    d[1687] = ("RETITLE", "Beach sand bucket with plastic shovel tool sticking out")
    d[1688] = ("RETITLE", "Paint bucket with drips of paint running down the side")
    
    # 1689..1690: space/spaceships
    d[1689] = ("RETITLE", "Futuristic starship battlecruiser cruising through deep interstellar space")
    d[1690] = ("RETITLE", "Rocket spaceship with triangular fins firing thruster exhaust flame")
    
    # 1691..1692: miscellaneous/brooms
    d[1691] = ("RETITLE", "Traditional straw broom with long wooden sweeping handle")
    d[1692] = ("RETITLE", "Witch flying broomstick tied with natural twig bristles")
    
    # 1693..1700: food-and-drinks/drinks
    d[1693] = ("RETITLE", "Stemmed wine glass filled with red wine showing liquid meniscus")
    d[1694] = ("RETITLE", "Tall cocktail highball glass with ice cubes and striped straw")
    d[1695] = ("RETITLE", "Martini cocktail glass garnished with an olive on a wooden pick")
    d[1696] = ("RETITLE", "Mug of hot chocolate topped with miniature floating marshmallows")
    d[1697] = ("RETITLE", "Glass beer mug with thick handle and overflowing foamy head")
    d[1698] = ("RETITLE", "Champagne flute glass with rising stream of fizzy bubbles")
    d[1699] = ("RETITLE", "Mason jar drinking glass filled with iced lemonade and lemon slice")
    d[1700] = ("RETITLE", "Shot glass filled with spirit liquor resting on a bar counter")
    
    # 1701..1705: music/musical-instruments
    d[1701] = ("RETITLE", "Acoustic six-string guitar with wooden soundboard and soundhole")
    d[1702] = ("RETITLE", "Electric guitar with dual pickups and volume control knobs")
    d[1703] = ("RETITLE", "Violin with wooden bridge, f-holes, and horsehair bow")
    d[1704] = ("RETITLE", "Saxophone brass instrument with intricate key levers and curved bell")
    d[1705] = ("RETITLE", "Drum kit set with snare, bass drum, tom-toms, and cymbals")
    
    # 1706: food-and-drinks/ice-creams
    d[1706] = ("RETITLE", "Waffle cone with two round scoops of ice cream on top")
    
    # 1707: sports-and-outdoors/baseball
    d[1707] = ("RETITLE", "Crossed wooden baseball bats behind a leather ball with red stitching")
    
    # 1708..1711: buildings-and-places/church
    d[1708] = ("RETITLE", "Gothic cathedral church with tall pointed steeple cross and rose window")
    d[1709] = ("RETITLE", "Country wooden church chapel with bell tower and arched doorway")
    d[1710] = ("RETITLE", "Church sanctuary interior with wooden pews and altar cross")
    d[1711] = ("RETITLE", "Russian Orthodox church with ornate onion dome spires and crosses")
    
    # 1712..1715: religion/buddhism
    d[1712] = ("RETITLE", "Buddha sitting in lotus meditation posture with hands in mudra")
    d[1713] = ("RETITLE", "Lotus flower throne supporting a meditative Buddha silhouette")
    d[1714] = ("RETITLE", "Eight-spoked Buddhist wheel of Dharma Dharmachakra symbol")
    d[1715] = ("RETITLE", "Buddhist monk praying in saffron robes with shaved head")
    
    # 1716..1719: religion/crosses-and-crucifixes
    d[1716] = ("RETITLE", "Ornate Celtic cross with intricate knotwork patterns on stone shaft")
    d[1717] = ("RETITLE", "Wooden crucifix cross with INRI banner sign above")
    d[1718] = ("RETITLE", "Maltese cross with eight sharp points and equal arms")
    d[1719] = ("RETITLE", "Russian Orthodox three-bar cross with slanted lower footrest")
    
    # 1720..1721: holiday-and-events/other
    d[1720] = ("RETITLE", "Carnival party mask with feathers and eye cutouts on a stick")
    d[1721] = ("RETITLE", "Cornucopia horn of plenty overflowing with autumn harvest fruit")
    
    # 1722..1723: vehicles/choppers
    d[1722] = ("RETITLE", "Military transport helicopter with twin tandem rotor blades")
    d[1723] = ("RETITLE", "Attack helicopter with nose machine gun turret and rocket pods")
    
    # 1724..1728: computers/joysticks
    d[1724] = ("RETITLE", "Flight simulator flightstick joystick with top trigger and hat switch")
    d[1725] = ("RETITLE", "Arcade gaming joystick with square base and red ball grip")
    d[1726] = ("RETITLE", "Retro single-button Atari joystick with black rubber boot")
    d[1727] = ("RETITLE", "Dual joystick arcade panel with primary fire buttons")
    d[1728] = ("RETITLE", "USB computer gaming flight control stick with throttle quadrant")
    
    # 1729..1731: nature/clouds
    d[1729] = ("RETITLE", "Fluffy white cumulus cloud floating in an open sky")
    d[1730] = ("RETITLE", "Dark storm thundercloud with lightning bolt flashing downward")
    d[1731] = ("RETITLE", "Cloud drifting in front of the sun with silver lining glow")
    
    # 1732: clothing-and-accessories/nightwears -> DELETE nsfw
    d[1732] = ("DELETE", "nsfw")
    
    # 1733..1736: holiday-and-events/fireworks
    d[1733] = ("RETITLE", "Firework rocket exploding into a starry burst in night sky")
    d[1734] = ("RETITLE", "Cluster of fireworks bursting above city horizon silhouette")
    d[1735] = ("RETITLE", "Sparkler wand burning with bright sparkling crackling sparks")
    d[1736] = ("RETITLE", "Chrysanthemum fireworks shell blossoming across the dark sky")
    
    # 1737..1748: animals/horses
    d[1737] = ("RETITLE", "Horse standing proud in profile with flowing mane and tail")
    d[1738] = ("RETITLE", "Stallion rearing up majestically on its powerful hind legs")
    d[1739] = ("RETITLE", "Horse galloping at full sprint speed across an open pasture")
    d[1740] = ("RETITLE", "Horse head portrait with alert pointed ears and bridle")
    d[1741] = ("RETITLE", "Mare grazing gently in a field beside a running spring foal")
    d[1742] = ("RETITLE", "Wild mustang running free with wind blowing through long mane")
    d[1743] = ("RETITLE", "Horse jumping gracefully over a wooden showjumping fence rail")
    d[1744] = ("RETITLE", "Draft horse standing heavy and muscular with feathered hooves")
    d[1745] = ("RETITLE", "Two horses standing together nuzzling each other necks")
    d[1746] = ("RETITLE", "Horse silhouette galloping against a glowing evening sunset")
    d[1747] = ("RETITLE", "Horse trotting with arched neck and high lifted hooves")
    d[1748] = ("RETITLE", "Equestrian rider on horse executing a formal dressage movement")
    
    # 1749..1771: plants/other
    d[1749] = ("RETITLE", "Oak tree with broad spreading leafy canopy and thick trunk")
    d[1750] = ("RETITLE", "Palm tree on tropical island with hanging coconuts and fronds")
    d[1751] = ("RETITLE", "Evergreen pine tree with needles and pine cones on branches")
    d[1752] = ("RETITLE", "Weeping willow tree with drooping leafy branches touching water")
    d[1753] = ("RETITLE", "Cactus plant growing in desert sand with sharp spiny needles")
    d[1754] = ("RETITLE", "Maple tree leaf showing five-pointed serrated autumn leaf shape")
    d[1755] = ("RETITLE", "Bonsai tree in shallow ceramic pot with pruned gnarled branches")
    d[1756] = ("RETITLE", "Bamboo stalks growing tall with segmented nodes and leaves")
    d[1757] = ("RETITLE", "Potted succulent plant growing in a round terracotta dish")
    d[1758] = ("RETITLE", "Fern frond unfurling in a graceful spiral fiddlehead curve")
    d[1759] = ("RETITLE", "Ear of corn maize on stalk with leafy green husk")
    d[1760] = ("RETITLE", "Cluster of grapes on vine with tendrils and grape leaf")
    d[1761] = ("RETITLE", "Wheat stalk sheaf tied with twine ready for harvest")
    d[1762] = ("RETITLE", "Mushroom toadstool growing in moss with speckled cap")
    d[1763] = ("RETITLE", "Ivy vine climbing upward across an old stone brick wall")
    d[1764] = ("RETITLE", "Apple tree laden with ripe red fruit in an orchard")
    d[1765] = ("RETITLE", "Tree stump with concentric annual growth rings on top surface")
    d[1766] = ("RETITLE", "Sprout seedling emerging from fertile soil with two cotyledon leaves")
    d[1767] = ("RETITLE", "Carnivorous Venus flytrap plant with open tooth-lined leaf trap")
    d[1768] = ("RETITLE", "Potted indoor houseplant on a decorative wooden plant stand")
    d[1769] = ("RETITLE", "Acorn nut resting inside its textured wooden scaly cup")
    d[1770] = ("RETITLE", "Bonsai juniper tree with twisted driftwood jin branches")
    d[1771] = ("RETITLE", "Autumn leaf falling through the air in swirling breeze")
    
    # 1772..1773: vehicles/bicycles
    d[1772] = ("RETITLE", "Classic two-wheeled bicycle with pedals, chain, and handlebars")
    d[1773] = ("RETITLE", "Mountain bicycle with front suspension fork and knobby offroad tires")
    
    # 1774..1775: buildings-and-places/buildings
    d[1774] = ("RETITLE", "Modern corporate office building with reflective glass facade panels")
    d[1775] = ("RETITLE", "Classic Greek temple building with fluted pillars and pediment roof")
    
    # 1776..1782: weapons/shields
    d[1776] = ("RETITLE", "Medieval heater shield bearing an embossed rampant lion emblem")
    d[1777] = ("RETITLE", "Round Viking wooden shield with iron center boss and rim")
    d[1778] = ("RETITLE", "Kite shield with pointed base and cross heraldry pattern")
    d[1779] = ("RETITLE", "Roman scutum rectangular curved legionary shield with lightning wings")
    d[1780] = ("RETITLE", "Ornate knight shield with quartered family coat of arms")
    d[1781] = ("RETITLE", "Captain America circular star shield with concentric red white rings")
    d[1782] = ("RETITLE", "Two crossed swords displayed behind a polished steel shield")
    
    # 1783..1791: vehicles/trains
    d[1783] = ("RETITLE", "Steam engine train puffing white smoke plumes along railroad tracks")
    d[1784] = ("RETITLE", "Modern high-speed bullet train streamlined aerodynamic locomotive")
    d[1785] = ("RETITLE", "Diesel freight train pulling a long line of cargo container cars")
    d[1786] = ("RETITLE", "Vintage railroad passenger train car with windows and roof vents")
    d[1787] = ("RETITLE", "Red caboose railway car on the end of a train line")
    d[1788] = ("RETITLE", "Subway metro train pulling into an underground station platform")
    d[1789] = ("RETITLE", "Train crossing over a high arched stone railway viaduct bridge")
    d[1790] = ("RETITLE", "Toy wooden train engine with wagons on wooden track loop")
    d[1791] = ("RETITLE", "Railway signal crossing lights with lowered gate arms flashing")
    
    # 1792..1794: animals/other-water
    d[1792] = ("RETITLE", "Giant octopus with eight tentacle arms covered in suction cups")
    d[1793] = ("RETITLE", "Jellyfish drifting through deep ocean water with stinging tentacles")
    d[1794] = ("RETITLE", "Sea horse swimming vertically with curved prehensile tail")
    
    # 1795..1797: miscellaneous/magnifying-glass
    d[1795] = ("RETITLE", "Handheld magnifying glass with brass frame and wooden handle")
    d[1796] = ("RETITLE", "Magnifying glass inspecting a set of human fingerprint ridges")
    d[1797] = ("RETITLE", "Magnifying glass focusing sunlight rays to ignite a spark")
    
    # 1798..1800: miscellaneous/kleenex
    d[1798] = ("RETITLE", "Rectangular box of facial tissue with tissue pulled up ready")
    d[1799] = ("RETITLE", "Crumpled soft paper handkerchief tissue on a bedside table")
    d[1800] = ("RETITLE", "Tissue box with decorative floral print on cardboard sides")
    
    # 1801..1803: animals/birds-water
    d[1801] = ("RETITLE", "Great blue heron wading through shallow wetland water")
    d[1802] = ("RETITLE", "White pelican with large throat pouch resting on dock post")
    d[1803] = ("RETITLE", "Loon water bird diving beneath the surface of a northern lake")
    
    # 1804..1809: sports-and-outdoors/scuba
    d[1804] = ("RETITLE", "Scuba diver swimming horizontally with oxygen tank and flippers")
    d[1805] = ("RETITLE", "Scuba diving mask with tempered glass faceplate and snorkel tube")
    d[1806] = ("RETITLE", "Diver exploring a tropical coral reef with swimming sea turtles")
    d[1807] = ("RETITLE", "Scuba regulator mouthpiece attached to high-pressure air hose")
    d[1808] = ("RETITLE", "Underwater diver shining a dive light into a dark sea cave")
    d[1809] = ("RETITLE", "Pair of rubber scuba diving swim fins lying on boat deck")
    
    # 1810..1815: clothing-and-accessories/glasses
    d[1810] = ("RETITLE", "Pair of classic round wire-rimmed optical eyeglasses on table")
    d[1811] = ("RETITLE", "Dark aviator sunglasses with teardrop metal frames and brow bar")
    d[1812] = ("RETITLE", "Cat-eye glasses frame with flared pointed upper outer corners")
    d[1813] = ("RETITLE", "Reading glasses folded with temples resting inside a hard case")
    d[1814] = ("RETITLE", "Monocle single circular lens with attached hanging gallery cord")
    d[1815] = ("RETITLE", "Safety goggles with protective side shields and elastic strap")
    
    # 1816..1820: space/telescopes
    d[1816] = ("RETITLE", "Astronomical refractor telescope mounted on an adjustable tripod stand")
    d[1817] = ("RETITLE", "Reflecting telescope with large optical tube pointed at night sky")
    d[1818] = ("RETITLE", "Astronomer looking through the eyepiece of an observatory telescope")
    d[1819] = ("RETITLE", "Radio telescope satellite dish antenna pointed at distant cosmos")
    d[1820] = ("RETITLE", "Hubble space telescope orbiting high above planet Earth")
    
    # 1821..1835: plants/mushroom (15 mushrooms)
    d[1821] = ("RETITLE", "Fly agaric toadstool mushroom with white spots on rounded cap")
    d[1822] = ("RETITLE", "Cluster of three wild forest mushrooms growing from mossy soil")
    d[1823] = ("RETITLE", "Morel mushroom with deeply pitted honeycomb textured sponge cap")
    d[1824] = ("RETITLE", "Chanterelle funnel-shaped yellow mushroom with wavy gill ridges")
    d[1825] = ("RETITLE", "Mushroom sprouting out from a decaying fallen tree log")
    d[1826] = ("RETITLE", "Little mushroom fairy house with carved door and chimney cap")
    d[1827] = ("RETITLE", "Pair of button mushrooms sitting on a kitchen cutting board")
    d[1828] = ("RETITLE", "Mushroom with broad flat umbrella cap showing gills underneath")
    d[1829] = ("RETITLE", "Shaggy ink cap mushroom with bell-shaped dissolving cap rim")
    d[1830] = ("RETITLE", "Tiny woodland mushroom growing under a sheltering fallen leaf")
    d[1831] = ("RETITLE", "Mushroom spore cloud releasing fine powder from under cap")
    d[1832] = ("RETITLE", "Bracket fungus shelf mushroom growing horizontally on tree bark")
    d[1833] = ("RETITLE", "Trio of slender mushroom stalks with delicate conical caps")
    d[1834] = ("RETITLE", "Giant puffball mushroom sitting round like a white sphere")
    d[1835] = ("RETITLE", "Mushroom growing in grass with morning dew drops on cap")
    
    # 1836..1838: nature/lightning
    d[1836] = ("RETITLE", "Jagged lightning bolt striking down from clouds to ground")
    d[1837] = ("RETITLE", "Branching lightning fork flashing across a dark night storm sky")
    d[1838] = ("RETITLE", "Lightning bolt hitting the spire of a tall skyscraper tower")
    
    # 1839..1840: logos/playboy -> DELETE nsfw
    d[1839] = ("DELETE", "nsfw")
    d[1840] = ("DELETE", "nsfw")
    
    # 1841: nature/deserts
    d[1841] = ("RETITLE", "Desert landscape with sand dunes, sun, and saguaro cactus")
    
    # 1842: holiday-and-events/new-year
    d[1842] = ("RETITLE", "Champagne bottle popping cork with sparkling spray and party poppers")
    
    # 1843: miscellaneous/antennas
    d[1843] = ("RETITLE", "Television antenna array tower with metal crossbars on rooftop")
    
    # 1844..1853: plants/marijuana
    d[1844] = ("RETITLE", "Cannabis marijuana plant leaf with seven radiating serrated leaflets")
    d[1845] = ("RETITLE", "Single five-fingered cannabis leaf drawn in clean botanical lines")
    d[1846] = ("RETITLE", "Cannabis leaf silhouette enclosed inside a circular emblem ring")
    d[1847] = ("RETITLE", "Botanical illustration of cannabis sativa plant with branching stems")
    d[1848] = ("RETITLE", "Detailed marijuana leaf with intricate vein network and teeth")
    d[1849] = ("RETITLE", "Stylized geometric cannabis leaf with sharp angular symmetry")
    d[1850] = ("RETITLE", "Cannabis leaf with nine pointed leaflets fanning out from petiole")
    d[1851] = ("RETITLE", "Medical cannabis green cross symbol with leaf in the center")
    d[1852] = ("RETITLE", "Cannabis leaf emerging from a small seedling terracotta pot")
    d[1853] = ("RETITLE", "Pot leaf silhouette with serrated leaflets over white backdrop")
    
    # 1854: sports-and-outdoors/logos
    d[1854] = ("RETITLE", "Olympic Games symbol with five interlocking colored rings")
    
    # 1855..1860: computers/apple
    d[1855] = ("RETITLE", "Apple computer logo bitten apple silhouette with leaf stem")
    d[1856] = ("RETITLE", "Original rainbow striped Apple computer logo with bite on side")
    d[1857] = ("RETITLE", "Vintage Apple Macintosh all-in-one personal computer with disk drive")
    d[1858] = ("RETITLE", "Apple II microcomputer with monitor and dual floppy drive units")
    d[1859] = ("RETITLE", "Apple PowerBook laptop computer open on a desk")
    d[1860] = ("RETITLE", "Modern Apple iMac desktop computer with ultra-thin profile display")
    
    # 1861: space/astronauts
    d[1861] = ("RETITLE", "Astronaut in pressurized space suit planting a flag on lunar soil")
    
    # 1862..1877: electronics/phones (16 phones)
    d[1862] = ("RETITLE", "Vintage rotary dial telephone with round finger wheel and handset")
    d[1863] = ("RETITLE", "Push-button touch tone desktop landline office desk phone")
    d[1864] = ("RETITLE", "Classic British red telephone call box booth on sidewalk")
    d[1865] = ("RETITLE", "Retro 1980s brick cellular mobile phone with pull-out antenna")
    d[1866] = ("RETITLE", "Flip phone mobile handset open showing keypad and screen")
    d[1867] = ("RETITLE", "Modern touchscreen smartphone displaying app home screen grid")
    d[1868] = ("RETITLE", "Old antique wall-mounted wooden crank telephone with twin bells")
    d[1869] = ("RETITLE", "Cordless home telephone resting in its charging cradle base")
    d[1870] = ("RETITLE", "Payphone public telephone station on a street wall")
    d[1871] = ("RETITLE", "Telephone handset receiver resting off the hook on desk")
    d[1872] = ("RETITLE", "Telephone pole carrying electric power lines and transformer drum")
    d[1873] = ("RETITLE", "Coiled telephone handset wire cord stretching between receiver and base")
    d[1874] = ("RETITLE", "Smartphone ringing with vibrating sound waves around screen")
    d[1875] = ("RETITLE", "Person holding a cellular phone to ear having a conversation")
    d[1876] = ("RETITLE", "Rotary telephone receiver handset lying flat on table")
    d[1877] = ("RETITLE", "Old candlestick telephone with separate earpiece and mouth tube")
    
    # 1878: holiday-and-events/graduation
    d[1878] = ("RETITLE", "Graduate portrait wearing graduation gown cap and holding diploma scroll")
    
    # 1879..1884: miscellaneous/boxes
    d[1879] = ("RETITLE", "Cardboard shipping box sealed with packing tape across top seams")
    d[1880] = ("RETITLE", "Open cardboard box with top flaps folded back outward")
    d[1881] = ("RETITLE", "Gift present box wrapped in paper and tied with ribbon bow")
    d[1882] = ("RETITLE", "Wooden wooden shipping crate with steel reinforcement corner brackets")
    d[1883] = ("RETITLE", "Stack of three cardboard storage boxes labeled with marker")
    d[1884] = ("RETITLE", "Jack-in-the-box toy with clown popping out of an open box")
    
    # 1885..1900: clothing-and-accessories/umbrellas (16 umbrellas)
    d[1885] = ("RETITLE", "Open rain umbrella with curved wooden J-hook handle")
    d[1886] = ("RETITLE", "Closed folded umbrella wrapped neatly with snap fastener strap")
    d[1887] = ("RETITLE", "Umbrella standing open deflecting heavy rain shower drops")
    d[1888] = ("RETITLE", "Two people sharing an umbrella walking together through rain")
    d[1889] = ("RETITLE", "Parasol sun umbrella with delicate lace trim along the scalloped edge")
    d[1890] = ("RETITLE", "Striped beach patio umbrella providing shade over sand")
    d[1891] = ("RETITLE", "Cocktail paper drink umbrella toothpick stuck in fruit slice")
    d[1892] = ("RETITLE", "Umbrella blown inside out by a strong gust of wind")
    d[1893] = ("RETITLE", "Umbrella stand holder in hallway containing folded wet umbrellas")
    d[1894] = ("RETITLE", "Rain boots wellingtons standing in puddle under an open umbrella")
    d[1895] = ("RETITLE", "Cat sitting dry underneath an open umbrella during rain")
    d[1896] = ("RETITLE", "Compact folding pocket umbrella with push-button automatic release")
    d[1897] = ("RETITLE", "Transparent clear dome bubble umbrella covering a person head")
    d[1898] = ("RETITLE", "Umbrella floating down through the sky like a parachute")
    d[1899] = ("RETITLE", "Open umbrella viewed from directly above showing radial canopy ribs")
    d[1900] = ("RETITLE", "Frog sitting dry under an umbrella on a pond lily pad")
    
    return d

if __name__ == "__main__":
    b4 = get_batch4()
    print(f"Batch 4 generated {len(b4)} decisions (expected 500: 1401..1900)")
