# -*- coding: utf-8 -*-
"""Full decision map for Batch 2: indexes 501 to 887 (end of gags)."""
import json, io

entries = json.load(open(r"C:\Temp\entries.json", encoding="utf-8"))

def get_batch2():
    d = {}
    
    # 501: Birthday
    d[501] = ("RETITLE", "Tiered birthday cake with lit burning celebration candles")
    
    # 502..503: Bear in the Big Blue House
    d[502] = ("RETITLE", "Bear in the Big Blue House waving with friendly smile")
    d[503] = ("RETITLE", "Bear smelling the viewer in his morning greeting routine")
    
    # 504..508: Harry Potter
    d[504] = ("RETITLE", "Harry Potter wearing round wire glasses with lightning bolt forehead scar")
    d[505] = ("RETITLE", "Hedwig the snowy owl perched quietly on a wooden stand")
    d[506] = ("RETITLE", "Sorting Hat with creased face and pointed peaked wizard brim")
    d[507] = ("RETITLE", "Golden Snitch flying with feathered golden wings outstretched")
    d[508] = ("RETITLE", "Hogwarts school crest shield with lion, snake, eagle, and badger")
    
    # 509..512: Bears
    d[509] = ("RETITLE", "Grizzly bear standing upright on hind legs with raised claws")
    d[510] = ("RETITLE", "Polar bear walking across an icy Arctic snow sheet")
    d[511] = ("RETITLE", "Black bear cub climbing up the trunk of a pine tree")
    d[512] = ("RETITLE", "Brown bear sitting beside a river catching jumping salmon fish")
    
    # 513: Peter Pan
    d[513] = ("RETITLE", "Peter Pan flying with feathered cap and hands on hips")
    
    # 514..516: Doctor Who
    d[514] = ("RETITLE", "TARDIS blue police telephone box hovering through space and time")
    d[515] = ("RETITLE", "Dalek robot aiming its extermination laser beam and plunger arm")
    d[516] = ("RETITLE", "Cyberman metal cyborg marching forward with chestplate and ear handles")
    
    # 517..520: Movies other (Star Wars)
    d[517] = ("RETITLE", "Darth Vader wearing his iconic black breathing helmet and cape")
    d[518] = ("RETITLE", "Yoda the Jedi Master leaning on his gnarled walking cane")
    d[519] = ("RETITLE", "R2-D2 astromech droid beeping on three wheeled utility legs")
    d[520] = ("RETITLE", "C-3PO protocol droid standing stiffly with golden robotic arms")
    
    # 521..526: Halloween
    d[521] = ("RETITLE", "Carved Halloween pumpkin jack-o-lantern with glowing jagged tooth grin")
    d[522] = ("RETITLE", "Witch flying across the full moon on a wooden broomstick")
    d[523] = ("RETITLE", "Haunted house mansion silhouette on a hill with bare spooky trees")
    d[524] = ("RETITLE", "Black cat with arched back and puffed tail hissing")
    d[525] = ("RETITLE", "Halloween skull head grinning in front of two crossed bones")
    d[526] = ("RETITLE", "Ghost floating out from an open stone graveyard tombstone")
    
    # 527..532: Bats
    d[527] = ("RETITLE", "Bat hanging upside down with leathery wings wrapped around body")
    d[528] = ("RETITLE", "Vampire bat flying with pointed ears and spread webbed wings")
    d[529] = ("RETITLE", "Small fruit bat silhouette soaring against the night sky")
    d[530] = ("RETITLE", "Bat with sharp fangs and wide arched wings in flight")
    d[531] = ("RETITLE", "Two bats roosting together hanging from a dark cave ceiling")
    d[532] = ("RETITLE", "Bat swooping down with claws ready to snatch an insect")
    
    # 533: Bloom County
    d[533] = ("RETITLE", "Opus the Penguin standing perplexed with large round bill")
    
    # 534..536: Ren & Stimpy
    d[534] = ("RETITLE", "Ren the Chihuahua trembling with bulging bloodshot eyes")
    d[535] = ("RETITLE", "Stimpy the cat smiling blissfully with a big blue nose")
    d[536] = ("RETITLE", "Ren and Stimpy standing side by side in goofy buddy pose")
    
    # 537..549: Muppets
    d[537] = ("RETITLE", "Kermit the Frog singing and playing a four-string banjo")
    d[538] = ("RETITLE", "Miss Piggy posing glamorous in evening gown and feather boa")
    d[539] = ("RETITLE", "Fozzie Bear telling jokes wearing his brown pork pie hat and tie")
    d[540] = ("RETITLE", "Gonzo the Great with curved beak playing a trumpet fanfare")
    d[541] = ("RETITLE", "Animal the wild drummer chained to his rock drum kit")
    d[542] = ("RETITLE", "Swedish Chef tossing a pancake into the air with chef hat")
    d[543] = ("RETITLE", "Statler and Waldorf heckling from their ornate theater balcony box")
    d[544] = ("RETITLE", "Beaker the assistant screaming mee-mee-mee in lab explosion panic")
    d[545] = ("RETITLE", "Dr. Bunsen Honeydew wearing glasses in his Muppet research laboratory")
    d[546] = ("RETITLE", "Rowlf the dog playing grand piano with floppy brown ears")
    d[547] = ("RETITLE", "Sam the Eagle looking stern and patriotic with folded wings")
    d[548] = ("RETITLE", "Sweetums the giant furry monster lumbering with a friendly wave")
    d[549] = ("RETITLE", "Rizzo the rat wearing a tiny jacket holding a piece of cheese")
    
    # 550..564: Dragons
    d[550] = ("RETITLE", "Western dragon perched on a mountain rock with bat-like wings")
    d[551] = ("RETITLE", "Fierce dragon breathing a raging stream of fiery flames")
    d[552] = ("RETITLE", "Eastern serpentine dragon coiling gracefully through stormy sky clouds")
    d[553] = ("RETITLE", "Baby dragon hatching out of a cracked speckled eggshell")
    d[554] = ("RETITLE", "Dragon sleeping curled up atop a vast mountain hoard of gold")
    d[555] = ("RETITLE", "Dragon roaring with spread spiked wings and barbed tail")
    d[556] = ("RETITLE", "Flying dragon silhouette soaring high across the night horizon")
    d[557] = ("RETITLE", "Dragon head in profile showing sharp teeth, horns, and scales")
    d[558] = ("RETITLE", "Two dragons entwined together in a symmetrical circular knot")
    d[559] = ("RETITLE", "Medieval dragon battling a knight holding a sword and shield")
    d[560] = ("RETITLE", "Dragon perched atop a castle tower looking down menacingly")
    d[561] = ("RETITLE", "Cute cartoon dragon sitting happily wagging its spiky tail")
    d[562] = ("RETITLE", "Dragon breathing smoke rings out of its scaled nostrils")
    d[563] = ("RETITLE", "Dragon spreading grand ornate wings in an intimidating dominance display")
    d[564] = ("RETITLE", "Water dragon sea serpent emerging from ocean waves")
    
    # 565..573: Moomins
    d[565] = ("RETITLE", "Moomintroll standing cheerful with rounded snout and tail tuft")
    d[566] = ("RETITLE", "Snufkin walking with his feathered green hat and backpack pipe")
    d[567] = ("RETITLE", "Little My sitting angrily with hands on hips and high hair bun")
    d[568] = ("RETITLE", "Moominpappa wearing his black top hat holding a walking cane")
    d[569] = ("RETITLE", "Moominmamma carrying her iconic striped apron and black handbag")
    d[570] = ("RETITLE", "The Groke standing dark and chilling with staring wide eyes")
    d[571] = ("RETITLE", "Hattifatteners ghostly white creatures standing together in an electric cluster")
    d[572] = ("RETITLE", "Snorkmaiden wearing her golden ankle ring admiring a flower")
    d[573] = ("RETITLE", "Moominhouse three-story round tower with conical roof in Moominvalley")
    
    # 574: South Park
    d[574] = ("RETITLE", "Eric Cartman standing chubby in his red jacket and cyan pom-pom hat")
    
    # 575: People sleeping
    d[575] = ("RETITLE", "Person sleeping soundly in a bed with head resting on pillow")
    
    # 576..578: The Jetsons
    d[576] = ("RETITLE", "George Jetson commuting to work in his retro-futuristic flying saucer car")
    d[577] = ("RETITLE", "Rosie the robot maid rolling forward carrying a duster brush")
    d[578] = ("RETITLE", "Astro the family dog jumping cheerfully to greet George")
    
    # 579..586: Robots
    d[579] = ("RETITLE", "Vintage tin toy robot walking with windup key on back")
    d[580] = ("RETITLE", "Industrial robotic arm welding a vehicle frame with sparks flying")
    d[581] = ("RETITLE", "Humanoid android robot standing at attention with chest dials")
    d[582] = ("RETITLE", "Friendly helper robot with smiling screen face and wheeled base")
    d[583] = ("RETITLE", "Giant mech robot warrior holding an energy cannon rifle")
    d[584] = ("RETITLE", "Small lunar exploration rover robot with solar panel array")
    d[585] = ("RETITLE", "Bipedal reconnaissance robot patrolling on hydraulic mechanical legs")
    d[586] = ("RETITLE", "Cute mini robot rolling on tank treads with glowing eye visor")
    
    # 587..588: 2 Stupid Dogs
    d[587] = ("RETITLE", "Big Dog and Little Dog standing together in bewildered confusion")
    d[588] = ("RETITLE", "Little Dog jumping excitedly in front of the calm Big Dog")
    
    # 589..591: Ghosts
    d[589] = ("RETITLE", "Spooky bedsheet ghost floating through the air saying Boo")
    d[590] = ("RETITLE", "Cute smiling ghost with wavy tail floating among stars")
    d[591] = ("RETITLE", "Three playful ghosts hovering around an old haunted graveyard")
    
    # 592..619: Other land animals
    d[592] = ("RETITLE", "African elephant standing proudly with long curved tusks and trunk raised")
    d[593] = ("RETITLE", "Mother elephant walking alongside her small baby calf")
    d[594] = ("RETITLE", "Tall giraffe nibbling fresh leaves from a high acacia branch")
    d[595] = ("RETITLE", "Lion roaring fiercely with a majestic thick mane")
    d[596] = ("RETITLE", "Tiger prowling through dense jungle grass with sharp stripes")
    d[597] = ("RETITLE", "Horse galloping at full speed with flowing mane and tail")
    d[598] = ("RETITLE", "Cute pony standing in profile in a grassy meadow")
    d[599] = ("RETITLE", "Zebra grazing peacefully showing black and white striped coat")
    d[600] = ("RETITLE", "Rhinoceros standing solid with large pointed horn on snout")
    d[601] = ("RETITLE", "Hippopotamus wading in river water with yawning open jaws")
    d[602] = ("RETITLE", "Camel with two humps walking across desert sand dunes")
    d[603] = ("RETITLE", "Llama standing alert with long neck and soft wool coat")
    d[604] = ("RETITLE", "Chubby pig standing happily in a mud puddle")
    d[605] = ("RETITLE", "Fluffy sheep standing in a pasture with thick fleece wool")
    d[606] = ("RETITLE", "Mountain goat standing balanced on a steep rocky cliff ledge")
    d[607] = ("RETITLE", "Red fox sitting alert with bushy white-tipped tail")
    d[608] = ("RETITLE", "Wolf howling at the full moon on a snowy ridge")
    d[609] = ("RETITLE", "Giant panda bear sitting down munching a fresh bamboo stalk")
    d[610] = ("RETITLE", "Raccoon peeking out with bandit mask face from a hollow log")
    d[611] = ("RETITLE", "Skunk raising its bushy tail in a defensive warning stance")
    d[612] = ("RETITLE", "Hedgehog curled into a defensive spiky protective ball")
    d[613] = ("RETITLE", "Armadillo walking armored across dry desert ground")
    d[614] = ("RETITLE", "Sloth hanging lazily upside down from a tree branch")
    d[615] = ("RETITLE", "Cheetah running at blazing sprint speed with spotted coat")
    d[616] = ("RETITLE", "Hyena standing alert with spotted back and sloping shoulders")
    d[617] = ("RETITLE", "Warthog charging forward with sharp curved tusks and mane")
    d[618] = ("RETITLE", "Meerkat standing upright on its hind legs scouting the surroundings")
    d[619] = ("RETITLE", "Badger emerging from its underground burrow at twilight")
    
    # 620: Hello Kitty
    d[620] = ("RETITLE", "Hello Kitty sitting front-on with iconic bow on left ear")
    
    # 621: Bambi
    d[621] = ("RETITLE", "Bambi the young spotted fawn deer standing shyly in forest")
    
    # 622..625: Land birds
    d[622] = ("RETITLE", "Wise old owl perched on an oak branch with wide eyes")
    d[623] = ("RETITLE", "Bald eagle soaring with broad wings and sharp hooked beak")
    d[624] = ("RETITLE", "Tropical parrot perched on a ring with colorful feathers")
    d[625] = ("RETITLE", "Rooster crowing at sunrise standing on a farm fence post")
    
    # 626: Pink Panther
    d[626] = ("RETITLE", "The Pink Panther leaning nonchalantly against a wall with cigarette holder")
    
    # 627..634: Marsupials
    d[627] = ("RETITLE", "Kangaroo bounding across the Australian outback on strong hind legs")
    d[628] = ("RETITLE", "Koala bear clinging tightly to a eucalyptus tree trunk")
    d[629] = ("RETITLE", "Mother kangaroo carrying a baby joey peeking from pouch")
    d[630] = ("RETITLE", "Wombat standing stout and sturdy on all four legs")
    d[631] = ("RETITLE", "Tasmanian devil snarling aggressively with open jaws")
    d[632] = ("RETITLE", "Sugar glider gliding through the air with patagium flaps spread")
    d[633] = ("RETITLE", "Wallaby grazing quietly on dry grass in the bush")
    d[634] = ("RETITLE", "Opossum hanging by its prehensile tail from a tree branch")
    
    # 635: Mafalda
    d[635] = ("RETITLE", "Mafalda the cartoon girl questioning the world with wild hair")
    
    # 636..642: Beavers
    d[636] = ("RETITLE", "Beaver chewing on a wooden log with prominent front teeth")
    d[637] = ("RETITLE", "Beaver swimming in river water carrying a leafy branch")
    d[638] = ("RETITLE", "Beaver standing on a wooden dam with flat paddle tail")
    d[639] = ("RETITLE", "Cute cartoon beaver waving happily with broad tail behind")
    d[640] = ("RETITLE", "Beaver building a lodge from stacked logs and river mud")
    d[641] = ("RETITLE", "Beaver slapping its flat tail on the water surface in warning")
    d[642] = ("RETITLE", "Beaver sitting on a tree stump gnawing bark")
    
    # 643..659: Devils
    d[643] = ("RETITLE", "Little devil cartoon character holding a pointed pitchfork trident")
    d[644] = ("RETITLE", "Devil face grinning wickedly with curved ram horns and goatee")
    d[645] = ("RETITLE", "Imp standing with bat wings and a barbed spade tail")
    d[646] = ("RETITLE", "Devil sitting on a flaming rock throne in the underworld")
    d[647] = ("RETITLE", "Mischievous red devil winking with glowing horns")
    d[648] = ("RETITLE", "Gargoyle devil perched on a gothic cathedral ledge")
    d[649] = ("RETITLE", "Devil dancing in leaping flames with trident raised high")
    d[650] = ("RETITLE", "Demon silhouette roaring with fiery eyes and curved horns")
    d[651] = ("RETITLE", "Cartoon devil floating on a cloud of red sulfur smoke")
    d[652] = ("RETITLE", "Devil whispering evil temptation into someone ear")
    d[653] = ("RETITLE", "Demon holding an open contract scroll with a quill")
    d[654] = ("RETITLE", "Little devil playing electric guitar on a fiery stage")
    d[655] = ("RETITLE", "Devil resting chin on hand scheming an evil plot")
    d[656] = ("RETITLE", "Fiery demon emerging from a cracking volcanic fissure")
    d[657] = ("RETITLE", "Devil wearing a sharp suit and bow tie with horns")
    d[658] = ("RETITLE", "Demon with spread bat wings casting dark fiery magic")
    d[659] = ("RETITLE", "Tiny devil angel conscience pair arguing on someone shoulders")
    
    # 660: Tribal people
    d[660] = ("DELETE", "unclear")
    
    # 661..665: Pokemon
    d[661] = ("RETITLE", "Pikachu smiling cheerfully with lightning bolt tail and pointed ears")
    d[662] = ("RETITLE", "Charmander standing upright with a burning flame on its tail")
    d[663] = ("RETITLE", "Squirtle turtle shooting a stream of water from its mouth")
    d[664] = ("RETITLE", "Bulbasaur resting on all fours with plant bulb on its back")
    d[665] = ("RETITLE", "Meowth feline Pokemon with golden coin amulet on forehead")
    
    # 666..713: Dogs (48 dogs)
    d[666] = ("RETITLE", "Golden retriever sitting politely with wagging tail and happy pant")
    d[667] = ("RETITLE", "German shepherd standing alert at attention with pointed ears")
    d[668] = ("RETITLE", "Bulldog sitting stout with wrinkly snout and droopy jowls")
    d[669] = ("RETITLE", "Dachshund sausage dog walking with long body and short legs")
    d[670] = ("RETITLE", "Poodle standing proudly with styled fluffy puff pompadour coat")
    d[671] = ("RETITLE", "Beagle tracking a scent with nose to the ground and tail up")
    d[672] = ("RETITLE", "Dalmatian dog standing with classic spotted coat and collar")
    d[673] = ("RETITLE", "Husky dog howling in the snow with thick winter fur")
    d[674] = ("RETITLE", "Chihuahua standing tiny and alert with large pointed ears")
    d[675] = ("RETITLE", "Pug sitting with curled tail and funny wrinkled sad face")
    d[676] = ("RETITLE", "Great Dane standing tall and majestic with slender legs")
    d[677] = ("RETITLE", "Border collie crouching ready to herd with focused gaze")
    d[678] = ("RETITLE", "Playful puppy rolling on its back asking for belly rubs")
    d[679] = ("RETITLE", "Dog holding a tennis ball proudly in its mouth")
    d[680] = ("RETITLE", "Two dogs playing tug of war with a braided rope toy")
    d[681] = ("RETITLE", "Sleeping dog curled up peacefully on a cozy floor rug")
    d[682] = ("RETITLE", "Dog head in profile panting with tongue hanging out happily")
    d[683] = ("RETITLE", "Corgi walking showing cute fluffy rounded backside and short legs")
    d[684] = ("RETITLE", "Boxer dog standing in sturdy athletic pose with clipped ears")
    d[685] = ("RETITLE", "Rottweiler sitting calm and watchful with muscular build")
    d[686] = ("RETITLE", "Saint Bernard wearing a miniature wooden rescue barrel on collar")
    d[687] = ("RETITLE", "Dog begging upright on its hind legs with front paws together")
    d[688] = ("RETITLE", "Cute puppy chewing on a large tasty bone treat")
    d[689] = ("RETITLE", "Dog peering through a wooden fence hole at neighbors")
    d[690] = ("RETITLE", "Yorkshire terrier sitting with long silky fur and red hairbow")
    d[691] = ("RETITLE", "Shih Tzu sitting fluffily with mustache fur and friendly eyes")
    d[692] = ("RETITLE", "Dog jumping high in the air to catch a flying frisbee disk")
    d[693] = ("RETITLE", "Hound dog sitting sorrowful with very long droopy ears")
    d[694] = ("RETITLE", "Dog sticking its head out of a car window in the breeze")
    d[695] = ("RETITLE", "Puppy peeking out curiously from inside an open laundry basket")
    d[696] = ("RETITLE", "Dog digging a hole in the garden lawn with dirt flying")
    d[697] = ("RETITLE", "Scottish terrier Scottie dog silhouette standing in sharp outline")
    d[698] = ("RETITLE", "Greyhound sprinting gracefully at top racing speed")
    d[699] = ("RETITLE", "Dog sitting in front of an empty food bowl waiting for dinner")
    d[700] = ("RETITLE", "Two puppies sleeping snuggled together in a basket")
    d[701] = ("RETITLE", "Dog swimming in a lake with head above rippling water")
    d[702] = ("RETITLE", "Dog wearing a birthday party hat with confetti all around")
    d[703] = ("RETITLE", "Old wise dog resting with grey muzzle and gentle eyes")
    d[704] = ("RETITLE", "Dog wearing a pair of sunglasses looking like a cool buddy")
    d[705] = ("RETITLE", "Dog giving a high five paw to its human companion")
    d[706] = ("RETITLE", "Fluffy Chow Chow dog with thick lion-like neck ruff")
    d[707] = ("RETITLE", "Doberman pinscher standing sleek and alert with docked tail")
    d[708] = ("RETITLE", "Cocker spaniel with long wavy feathered ears sitting pretty")
    d[709] = ("RETITLE", "Dog chasing its own tail in a spinning circular whirl")
    d[710] = ("RETITLE", "Puppy tangled in a leash while exploring a park tree")
    d[711] = ("RETITLE", "Dog lying under a garden tree enjoying the afternoon shade")
    d[712] = ("RETITLE", "Dog barking happily with front paws lowered in play bow")
    d[713] = ("RETITLE", "Small dog sitting proudly inside a lady bicycle front basket")
    
    # 714..719: Guillotines
    d[714] = ("RETITLE", "French Revolution guillotine standing tall with angled blade raised")
    d[715] = ("RETITLE", "Guillotine frame with release rope and wooden head stock lunette")
    d[716] = ("RETITLE", "Historical execution guillotine rendered in sharp wooden beams")
    d[717] = ("RETITLE", "Guillotine with wicker basket below for the fallen head")
    d[718] = ("RETITLE", "Miniature desktop cigar cutter designed like a functional guillotine")
    d[719] = ("RETITLE", "Guillotine silhouette standing grim against a dark stormy sky")
    
    # 720..722: Smurfs
    d[720] = ("RETITLE", "Papa Smurf smiling with white beard and red Phrygian cap")
    d[721] = ("RETITLE", "Smurfette walking cheerfully with long blonde hair and white dress")
    d[722] = ("RETITLE", "Brainy Smurf adjusting his round glasses while lecturing others")
    
    # 723..741: Aliens
    d[723] = ("RETITLE", "Extraterrestrial alien with large oval head and slanted dark eyes")
    d[724] = ("RETITLE", "Flying saucer UFO hovering in night sky with tractor beam on")
    d[725] = ("RETITLE", "Little green alien waving three-fingered hand in peace greeting")
    d[726] = ("RETITLE", "Alien piloting a round spacecraft cockpit with radar controls")
    d[727] = ("RETITLE", "Alien stepping down from an open spacecraft landing ramp")
    d[728] = ("RETITLE", "Three-eyed alien monster with tentacles smiling friendly")
    d[729] = ("RETITLE", "Alien abduction scene with cow lifted into flying saucer beam")
    d[730] = ("RETITLE", "Slender grey alien standing front-on in atmospheric fog")
    d[731] = ("RETITLE", "Alien using a ray gun blaster weapon in cosmic battle")
    d[732] = ("RETITLE", "Martian creature with antenna eyes peering out from crater")
    d[733] = ("RETITLE", "Alien face in close-up with intricate textured cranium grooves")
    d[734] = ("RETITLE", "UFO fleet flying in formation across starry planetary space")
    d[735] = ("RETITLE", "Alien scientist analyzing a glowing cosmic crystal in laboratory")
    d[736] = ("RETITLE", "Friendly alien riding a retro rocket scooter through stars")
    d[737] = ("RETITLE", "Alien creature hatching from a glowing extraterrestrial egg")
    d[738] = ("RETITLE", "Xenomorph alien warrior crouching with elongated skull and tail")
    d[739] = ("RETITLE", "Alien wearing an interstellar spacesuit helmet on moon surface")
    d[740] = ("RETITLE", "Alien communicating through holographic light patterns")
    d[741] = ("RETITLE", "Extraterrestrial diplomat holding an intergalactic peace treaty scroll")
    
    # 742..745: Beanie Babies
    d[742] = ("RETITLE", "Beanie Baby plush bear with red heart tag on ear")
    d[743] = ("RETITLE", "Stuffed plush puppy toy sitting with beanbag pellet belly")
    d[744] = ("RETITLE", "Plush kitty Beanie Baby resting with embroidered whiskers")
    d[745] = ("RETITLE", "Collection of miniature plush collectible animal toys")
    
    # 746..749: Superman
    d[746] = ("RETITLE", "Superman flying horizontally with red cape fluttering behind")
    d[747] = ("RETITLE", "Clark Kent opening his dress shirt to reveal the Superman S shield")
    d[748] = ("RETITLE", "Superman standing heroic hands on hips in classic power pose")
    d[749] = ("RETITLE", "Superman lifting a heavy automobile above his head with strength")
    
    # 750..761: People other
    d[750] = ("RETITLE", "Silhouette of a man walking in rain with an umbrella")
    d[751] = ("RETITLE", "Detective in fedora hat and trench coat smoking a pipe")
    d[752] = ("RETITLE", "Chef wearing tall toque hat holding a hot steaming pizza pie")
    d[753] = ("RETITLE", "Scuba diver swimming with oxygen tank and flippers underwater")
    d[754] = ("RETITLE", "Astronaut in spacesuit floating on a spacewalk outside shuttle")
    d[755] = ("RETITLE", "Firefighter in helmet holding an active high-pressure water hose")
    d[756] = ("RETITLE", "Guitarist jamming on electric guitar on a concert stage")
    d[757] = ("RETITLE", "Ballet dancer leaping gracefully in a pirouette jump")
    d[758] = ("RETITLE", "Gardener pushing a wheelbarrow filled with fresh vegetables")
    d[759] = ("RETITLE", "Skier gliding down a snowy mountain slope with poles")
    d[760] = ("RETITLE", "Surfer riding a cresting ocean wave on a surfboard")
    d[761] = ("RETITLE", "Magician pulling a white rabbit out of a black top hat")
    
    # 762..763: Popeye
    d[762] = ("RETITLE", "Popeye the Sailor Man flexing his anchor-tattooed forearm muscle with pipe")
    d[763] = ("RETITLE", "Popeye squeezing an open can of spinach directly into his mouth")
    
    # 764..765: Clowns
    d[764] = ("RETITLE", "Circus clown face with round red nose, smile, and ruffled collar")
    d[765] = ("RETITLE", "Juggling clown riding a unicycle while tossing three balls")
    
    # 766..768: Buttocks
    d[766] = ("DELETE", "nsfw")
    d[767] = ("DELETE", "nsfw")
    d[768] = ("DELETE", "nsfw")
    
    # 769..771: Sexual/other -> DELETE nsfw
    d[769] = ("DELETE", "nsfw")
    d[770] = ("DELETE", "nsfw")
    d[771] = ("DELETE", "nsfw")
    
    # 772..779: Furniture / Toilets
    d[772] = ("RETITLE", "Standard ceramic flush toilet with tank and open seat lid")
    d[773] = ("RETITLE", "Toilet bowl with roll of toilet paper mounted on wall holder")
    d[774] = ("RETITLE", "Outhouse wooden privy shack with crescent moon cut into door")
    d[775] = ("RETITLE", "Modern bathroom toilet fixture with dual flush buttons on top")
    d[776] = ("RETITLE", "Toilet plunger standing upright beside a bathroom commode")
    d[777] = ("RETITLE", "Cat curiously peering inside a porcelain toilet bowl")
    d[778] = ("RETITLE", "Golden throne royal toilet seat with ornate crown trim")
    d[779] = ("RETITLE", "Plumber repairing a bathroom toilet pipe with a wrench")
    
    # 780..781: The Beatles
    d[780] = ("RETITLE", "The Beatles four band members walking across Abbey Road crossing")
    d[781] = ("RETITLE", "John, Paul, George, and Ringo performing with guitars and drums")
    
    # 782: Napoleon
    d[782] = ("RETITLE", "Napoleon Bonaparte portrait wearing bicorne hat with hand in coat")
    
    # 783..785: Kings
    d[783] = ("RETITLE", "Medieval king wearing a golden jeweled crown and royal ermine robe")
    d[784] = ("RETITLE", "King sitting on an ornate stone throne holding a royal scepter")
    d[785] = ("RETITLE", "Playing card King of Hearts holding a sword behind his head")
    
    # 786..791: Snowmen
    d[786] = ("RETITLE", "Snowman wearing a top hat, carrot nose, and warm striped scarf")
    d[787] = ("RETITLE", "Snowman waving stick arms with falling snowflakes all around")
    d[788] = ("RETITLE", "Snowman holding a wooden broomstick beside a snow-covered pine tree")
    d[789] = ("RETITLE", "Little snowman family of three standing together in a snowy yard")
    d[790] = ("RETITLE", "Snowman smiling with button eyes and coal mouth in winter breeze")
    d[791] = ("RETITLE", "Melting snowman under the warm spring sun with puddle at base")
    
    # 792..796: Santa Claus
    d[792] = ("RETITLE", "Santa Claus face smiling with fluffy white beard and pompom hat")
    d[793] = ("RETITLE", "Santa Claus carrying a heavy sack of toys over his shoulder")
    d[794] = ("RETITLE", "Santa Claus flying in a reindeer-pulled sleigh across the moon")
    d[795] = ("RETITLE", "Santa Claus climbing down a brick chimney on Christmas Eve")
    d[796] = ("RETITLE", "Santa Claus checking his long Christmas gift list with quill pen")
    
    # 797: Hair Stylists
    d[797] = ("RETITLE", "Hair stylist cutting hair with scissors and a comb in hand")
    
    # 798: Albert Einstein
    d[798] = ("RETITLE", "Albert Einstein with wild hair sticking out his tongue playfully")
    
    # 799..803: Wizards
    d[799] = ("RETITLE", "Wise wizard with long white beard wearing a starry pointed hat")
    d[800] = ("RETITLE", "Wizard holding an open spellbook while channeling magical energy")
    d[801] = ("RETITLE", "Sorcerer raising a magic wand casting glowing elemental sparks")
    d[802] = ("RETITLE", "Wizard with a pet owl perched on his wooden walking staff")
    d[803] = ("RETITLE", "Alchemist wizard brewing a bubbling magical potion in a cauldron")
    
    # 804..806: Mimes
    d[804] = ("RETITLE", "Mime artist trapped inside an invisible glass box with hands pressed")
    d[805] = ("RETITLE", "Mime in striped shirt and beret performing a silent gesture")
    d[806] = ("RETITLE", "Mime pulling on an invisible rope with exaggerated strain")
    
    # 807..808: Cowboys
    d[807] = ("RETITLE", "Cowboy in Stetson hat riding a galloping stallion across prairie")
    d[808] = ("RETITLE", "Sheriff leaning against a saloon post with silver star badge")
    
    # 809..863: Mice (55 mice!)
    d[809] = ("RETITLE", "Tiny mouse sitting on hind legs holding a piece of swiss cheese")
    d[810] = ("RETITLE", "Mouse creeping along a baseboard with long slender tail trailing")
    d[811] = ("RETITLE", "Field mouse perched on a grain stalk eating wheat seeds")
    d[812] = ("RETITLE", "Mouse peeking out from a curved mousehole in a wooden wall")
    d[813] = ("RETITLE", "Two mice whispering secrets to each other with twitching whiskers")
    d[814] = ("RETITLE", "Mouse sleeping curled up inside a hollowed-out apple")
    d[815] = ("RETITLE", "Curious mouse sniffing the air with raised pink nose")
    d[816] = ("RETITLE", "Mouse running at top speed across a kitchen floorboard")
    d[817] = ("RETITLE", "Cute mouse wearing a tiny acorn cap as a helmet")
    d[818] = ("RETITLE", "Mouse carefully inspecting a wooden spring mousetrap with cheese")
    d[819] = ("RETITLE", "Chubby dormouse napping inside a teacup with tail wrapped around")
    d[820] = ("RETITLE", "Mouse standing upright looking through a handheld magnifying glass")
    d[821] = ("RETITLE", "Mother mouse leading four little mouse pups in a single file")
    d[822] = ("RETITLE", "Mouse balancing precariously on a thin hanging clothesline rope")
    d[823] = ("RETITLE", "Little mouse reading a tiny book under a mushroom umbrella")
    d[824] = ("RETITLE", "Mouse head in profile with large round ears and long whiskers")
    d[825] = ("RETITLE", "Mouse carrying a single blackberry held firmly in both front paws")
    d[826] = ("RETITLE", "Two mice sharing a giant wedge of yellow cheddar cheese")
    d[827] = ("RETITLE", "Mouse wearing spectacles and holding a tiny wooden pencil")
    d[828] = ("RETITLE", "Field mouse standing alert among blooming buttercup flowers")
    d[829] = ("RETITLE", "Mouse paddling across water in a floating walnut shell boat")
    d[830] = ("RETITLE", "Mouse climbing up a curtain fabric with sharp little claws")
    d[831] = ("RETITLE", "Cute cartoon mouse waving happily with big round ears")
    d[832] = ("RETITLE", "Mouse hiding underneath a fallen autumn maple leaf")
    d[833] = ("RETITLE", "Mouse sitting on an old clock face near the hour hand")
    d[834] = ("RETITLE", "Tiny mouse sitting inside a thimble holding a sewing needle")
    d[835] = ("RETITLE", "Mouse nibbling on a peanut shell on the pantry shelf")
    d[836] = ("RETITLE", "Mouse standing on tiptoes reaching up for a hanging berry")
    d[837] = ("RETITLE", "Field mouse curled asleep inside a woven bird nest")
    d[838] = ("RETITLE", "Mouse wearing a tiny woolen scarf against the winter chill")
    d[839] = ("RETITLE", "Two mice dancing a waltz on their hind legs together")
    d[840] = ("RETITLE", "Mouse inspecting a shiny copper coin found on the floor")
    d[841] = ("RETITLE", "Mouse peeking out from inside an empty matchbox bed")
    d[842] = ("RETITLE", "Mouse sliding down a curved teapot spout like a playground slide")
    d[843] = ("RETITLE", "Cute mouse holding a dandelion seed puff ready to blow")
    d[844] = ("RETITLE", "Mouse sitting inside an open leather shoe by the laces")
    d[845] = ("RETITLE", "Mouse tiptoeing past a sleeping cat on the rug")
    d[846] = ("RETITLE", "Little mouse carrying a tiny candle lantern in the dark")
    d[847] = ("RETITLE", "Mouse stretching after a long nap with front paws forward")
    d[848] = ("RETITLE", "Field mouse collecting fallen sunflower seeds into a cache")
    d[849] = ("RETITLE", "Mouse sitting atop a spool of colorful sewing thread")
    d[850] = ("RETITLE", "Mouse looking at its own reflection in a puddle of water")
    d[851] = ("RETITLE", "Two mice pulling a wagon made from a tin can")
    d[852] = ("RETITLE", "Mouse wearing a tiny crown sitting on a wooden block")
    d[853] = ("RETITLE", "Mouse nibbling a cookie crumb dropped under the dining table")
    d[854] = ("RETITLE", "Field mouse perched on an ear of corn husking kernels")
    d[855] = ("RETITLE", "Mouse holding an umbrella made from a broad green leaf")
    d[856] = ("RETITLE", "Mouse wearing a little backpack heading out on an adventure")
    d[857] = ("RETITLE", "Cute mouse peeking through a keyhole in a wooden door")
    d[858] = ("RETITLE", "Mouse sitting in a wicker basket filled with dried fruit")
    d[859] = ("RETITLE", "Mouse grooming its long whiskers with tiny front paws")
    d[860] = ("RETITLE", "Field mouse running through tall grass stalks at sunset")
    d[861] = ("RETITLE", "Mouse sitting beside a tiny ceramic pitcher and cup")
    d[862] = ("RETITLE", "Mouse swinging playfully from a curved vine tendril")
    d[863] = ("RETITLE", "Tiny mouse sleeping peacefully under a fluffy cotton ball")
    
    # 864..866: Dinosaurs
    d[864] = ("RETITLE", "Tyrannosaurus Rex roaring with sharp teeth and small two-clawed arms")
    d[865] = ("RETITLE", "Brachiosaurus long-necked dinosaur browsing high treetop foliage")
    d[866] = ("RETITLE", "Triceratops standing defensive with three sharp facial horns and frill")
    
    # 867..868: Hand gestures
    d[867] = ("RETITLE", "Hand giving a thumbs up gesture of approval and encouragement")
    d[868] = ("DELETE", "nsfw") # Middle finger gesture per README rule!
    
    # 869: Famous people other
    d[869] = ("RETITLE", "William Shakespeare portrait with ruffled Elizabethan collar and goatee")
    
    # 870..874: Other rodents
    d[870] = ("RETITLE", "Chipmunk standing on hind legs with cheeks stuffed with nuts")
    d[871] = ("RETITLE", "Squirrel sitting on a tree branch holding an oak acorn")
    d[872] = ("RETITLE", "Guinea pig resting plump and fluffy on a bed of hay")
    d[873] = ("RETITLE", "Prairie dog standing sentinel on a mound outside its burrow")
    d[874] = ("RETITLE", "Chinchilla sitting with ultra-soft dense fur and bushy tail")
    
    # 875..877: Eyes
    d[875] = ("RETITLE", "Pair of wide curious cartoon eyes staring directly forward")
    d[876] = ("RETITLE", "Pair of sleepy half-closed eyes with heavy eyelids and lashes")
    d[877] = ("RETITLE", "Single detailed human eye with iris reflections and eyebrow")
    
    # 878..880: Elvis Presley
    d[878] = ("RETITLE", "Elvis Presley singing into a microphone with his famous pompadour hair")
    d[879] = ("RETITLE", "Elvis Presley wearing a jumpsuit with high collar and sunglasses")
    d[880] = ("RETITLE", "Elvis Presley striking his iconic rock and roll leg shake pose")
    
    # 881..884: Sexual/women -> DELETE nsfw
    d[881] = ("DELETE", "nsfw")
    d[882] = ("DELETE", "nsfw")
    d[883] = ("DELETE", "nsfw")
    d[884] = ("DELETE", "nsfw")
    
    # 885: Lips
    d[885] = ("RETITLE", "Pair of full human lips leaving a kiss mark impression")
    
    # 886..887: Charlie Chaplin
    d[886] = ("RETITLE", "Charlie Chaplin as the Little Tramp with bowler hat and cane")
    d[887] = ("RETITLE", "Charlie Chaplin walking away into the distance with waddling gait")
    
    return d

if __name__ == "__main__":
    b2 = get_batch2()
    print(f"Batch 2 generated {len(b2)} decisions (expected 387: 501..887)")
