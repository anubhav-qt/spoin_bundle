# -*- coding: utf-8 -*-
"""Full decision map for Batch 1: indexes 189 to 500."""
import json, io

entries = json.load(open(r"C:\Temp\entries.json", encoding="utf-8"))

def get_batch1():
    d = {}
    
    # 189..190: Fish
    d[189] = ("RETITLE", "Angelfish swimming through rising air bubble streams")
    d[190] = ("RETITLE", "Small goldfish blowing bubble stream swimming rightward")
    
    # 191..206: Winnie the Pooh
    d[191] = ("RETITLE", "Eeyore the donkey standing in profile with a pinned tail")
    d[192] = ("RETITLE", "Piglet smiling in a striped sweater standing front-on")
    d[193] = ("RETITLE", "Winnie the Pooh bear reaching his paw into a honey pot")
    d[194] = ("RETITLE", "Winnie the Pooh sitting beside a jar labeled Hunny")
    d[195] = ("RETITLE", "Winnie the Pooh floating upward holding a round balloon")
    d[196] = ("RETITLE", "Tigger bouncing upright on his coiled spring tail")
    d[197] = ("RETITLE", "Eeyore sitting dejectedly with droopy long ears")
    d[198] = ("RETITLE", "Piglet holding a flower bouquet with both hands")
    d[199] = ("RETITLE", "Winnie the Pooh face smiling with round bear ears")
    d[200] = ("RETITLE", "Tigger leaping with striped body and outstretched paws")
    d[201] = ("RETITLE", "Owl perched on a tree stump with large round spectacles")
    d[202] = ("RETITLE", "Rabbit from Winnie the Pooh standing with crossed arms")
    d[203] = ("RETITLE", "Winnie the Pooh and Piglet walking together holding hands")
    d[204] = ("RETITLE", "Eeyore lying down with his chin resting on his hooves")
    d[205] = ("RETITLE", "Kanga the kangaroo carrying baby Roo in her front pouch")
    d[206] = ("DELETE", "unclear")
    
    # 207: Pillsbury doughboy
    d[207] = ("RETITLE", "Pillsbury Doughboy wearing a tall chef hat and neckerchief")
    
    # 208..219: Fairies
    d[208] = ("RETITLE", "Winged fairy sitting on a curved crescent moon holding a star")
    d[209] = ("RETITLE", "Small fairy with spread butterfly wings hovering in midair")
    d[210] = ("RETITLE", "Fairy kneeling on a mushroom cap holding a magic wand")
    d[211] = ("RETITLE", "Fairy silhouette flying gracefully with shimmering trailing dust")
    d[212] = ("RETITLE", "Fairy standing amidst tall grass blades and blooming wildflowers")
    d[213] = ("RETITLE", "Fairy sleeping curled inside a large open flower blossom")
    d[214] = ("RETITLE", "Tinkerbell flying with pointed slippers and sparkling wings")
    d[215] = ("RETITLE", "Fairy dancing on tiptoe with arched arms and gossamer wings")
    d[216] = ("RETITLE", "Tiny woodland fairy holding a wand with sparkling tip")
    d[217] = ("RETITLE", "Woodland fairy in profile holding a wand with starburst")
    d[218] = ("RETITLE", "Fairy with gossamer wings holding a shining magical star wand")
    d[219] = ("RETITLE", "Fairy sitting on an ornate flowering tree branch")
    
    # 220..226: Preachers
    d[220] = ("RETITLE", "Preacher standing behind a wooden pulpit with a cross")
    d[221] = ("RETITLE", "Stick preacher figure standing at an elevated podium")
    d[222] = ("RETITLE", "Minister in clerical robes at a pulpit with cross emblem")
    d[223] = ("RETITLE", "Speaker addressing a congregation from a tall lectern")
    d[224] = ("RETITLE", "Clergyman wearing a stole and clerical collar at a podium")
    d[225] = ("RETITLE", "Preacher standing behind an altar table with a communion chalice")
    d[226] = ("RETITLE", "Priest wearing vestments preaching from an ornate church pulpit")
    
    # 227..228: Toys / Slinky
    d[227] = ("DELETE", "unclear")
    d[228] = ("RETITLE", "Slinky coiled metal toy spring tumbling down stepped levels")
    
    # 229..233: Native Americans
    d[229] = ("RETITLE", "Two people paddling together in a long canoe on calm water")
    d[230] = ("RETITLE", "Indigenous chief wearing a feathered war bonnet in profile")
    d[231] = ("RETITLE", "Native American warrior portrait with braided hair and single feather")
    d[232] = ("RETITLE", "Detailed chief portrait wearing a grand eagle feather headdress")
    d[233] = ("RETITLE", "Native American chief profile with feathered headdress and necklace")
    
    # 234..235: Balloons
    d[234] = ("RETITLE", "Oval party balloon floating on a thin curved string")
    d[235] = ("RETITLE", "Cluster of three helium balloons tied together with ribbon")
    
    # 236..237: Pacman
    d[236] = ("RETITLE", "Pac-Man opening wide mouth to chomp floating power pellets")
    d[237] = ("RETITLE", "Pac-Man chasing a fleeing arcade ghost monster across a line")
    
    # 238: Alice in Wonderland
    d[238] = ("RETITLE", "Alice in Wonderland falling down the deep rabbit hole with skirt flowing")
    
    # 239..249: Looney Tunes
    d[239] = ("RETITLE", "Tweety Bird canary standing front-on with large head and eyelashes")
    d[240] = ("RETITLE", "Marvin the Martian aiming his ray gun in a Roman plume helmet")
    d[241] = ("RETITLE", "Bugs Bunny chewing a carrot with long upright ears")
    d[242] = ("RETITLE", "Daffy Duck with arms crossed and beak turned indignantly")
    d[243] = ("RETITLE", "Tasmanian Devil spinning in a ferocious whirlwind tornado")
    d[244] = ("RETITLE", "Sylvester the cat stalking forward with arched back and whiskers")
    d[245] = ("RETITLE", "Marvin the Martian standing at attention holding an alien disintegrator pistol")
    d[246] = ("RETITLE", "Wile E. Coyote holding a smoking ACME dynamite stick")
    d[247] = ("RETITLE", "Marvin the Martian wearing sneakers and a plumed helmet")
    d[248] = ("RETITLE", "Porky Pig stuttering with open vest and round curly tail")
    d[249] = ("RETITLE", "Road Runner bird sprinting with head forward and trailing dust")
    
    # 250..255: Explosives
    d[250] = ("RETITLE", "Round cannonball bomb with a sparkling lit fuse line")
    d[251] = ("RETITLE", "Spherical bomb with a burning fuse ready to detonate")
    d[252] = ("RETITLE", "Small round bomb with smoke curling from its short fuse")
    d[253] = ("RETITLE", "Bundle of dynamite sticks wired together with a digital timer")
    d[254] = ("RETITLE", "Three sticks of ACME dynamite strapped with an alarm clock")
    d[255] = ("RETITLE", "Old-fashioned spherical pirate bomb with a glowing fuse wick")
    
    # 256..268: Sesame Street
    d[256] = ("RETITLE", "Cookie Monster face with wide googly eyes and open mouth")
    d[257] = ("RETITLE", "Big Bird standing tall with feathered plumage and large beak")
    d[258] = ("RETITLE", "Cookie Monster happily munching on a chocolate chip cookie")
    d[259] = ("RETITLE", "Elmo smiling and waving with his furry hand raised")
    d[260] = ("RETITLE", "Bert and Ernie standing side by side smiling cheerfully")
    d[261] = ("RETITLE", "Oscar the Grouch popping out of his metal trash can")
    d[262] = ("RETITLE", "Count von Count laughing with his pointed fangs and monocle")
    d[263] = ("RETITLE", "Cookie Monster with cookie crumbs flying around his open mouth")
    d[264] = ("RETITLE", "Elmo standing cheerfully with arms outstretched in greeting")
    d[265] = ("RETITLE", "Elmo waving happily with a friendly wide open smile")
    d[266] = ("RETITLE", "Grover puppet standing upright in furry superhero cape pose")
    d[267] = ("RETITLE", "Elmo walking forward with a joyful cheerful expression")
    d[268] = ("RETITLE", "Kermit the Frog smiling front-on with his pointed collar")
    
    # 269..271: Futurama
    d[269] = ("RETITLE", "Bender bending robot face with antenna and visor eyes")
    d[270] = ("RETITLE", "Bender the robot standing hands on hips holding a beverage can")
    d[271] = ("RETITLE", "Philip J. Fry walking forward with signature parted red hair")
    
    # 272..279: Wallace & Gromit
    d[272] = ("RETITLE", "Wallace grinning widely wearing his knitted sweater vest and tie")
    d[273] = ("RETITLE", "Gromit the beagle dog sitting thoughtfully with floppy ears")
    d[274] = ("RETITLE", "Wallace and Gromit standing together ready for tea and crackers")
    d[275] = ("RETITLE", "Gromit reading a newspaper in a comfortable armchair")
    d[276] = ("RETITLE", "Wallace holding a wedge of Wensleydale cheese on a plate")
    d[277] = ("RETITLE", "Feathers McGraw penguin wearing a red rubber glove on his head")
    d[278] = ("RETITLE", "Wallace operating a complex mechanical contraption in his workshop")
    d[279] = ("RETITLE", "Gromit knitting a scarf with concentration and dropped ears")
    
    # 280..306: Angels
    d[280] = ("RETITLE", "Tiny angel flying horizontally with small wings and a halo")
    d[281] = ("RETITLE", "Angel praying with folded hands and outstretched feathered wings")
    d[282] = ("RETITLE", "Cherub angel holding a small harp with floating halo")
    d[283] = ("RETITLE", "Angel kneeling in prayer with downward-swept feathered wings")
    d[284] = ("RETITLE", "Little cherub angel blowing a golden celestial trumpet horn")
    d[285] = ("RETITLE", "Angel standing in flowing robes with hands clasped together")
    d[286] = ("RETITLE", "Angel hovering in air with wide spread wings and glowing halo")
    d[287] = ("RETITLE", "Seraph angel in robes with hands raised in peaceful blessing")
    d[288] = ("RETITLE", "Cherub with curly hair sitting on a cloud with tiny wings")
    d[289] = ("RETITLE", "Angel floating downwards surrounded by twinkling starry lights")
    d[290] = ("RETITLE", "Angel playing a handheld stringed harp with graceful posture")
    d[291] = ("RETITLE", "Guardian angel extending protective hands with grand feathered wings")
    d[292] = ("RETITLE", "Winged angel figure kneeling beside a glowing celestial star")
    d[293] = ("RETITLE", "Angel floating on a soft cloud holding an olive branch")
    d[294] = ("RETITLE", "Angel with ornate feathered wings praying with bowed head")
    d[295] = ("RETITLE", "Cherub holding a flaming candle in a starry night sky")
    d[296] = ("RETITLE", "Angel figure with symmetrical wings and long flowing gown")
    d[297] = ("RETITLE", "Large detailed angel with spread wings and radiant halo aura")
    d[298] = ("RETITLE", "Angel floating among cloud layers playing a curved trumpet")
    d[299] = ("RETITLE", "Angel in pleated robes with folded hands facing forward")
    d[300] = ("RETITLE", "Cherub sitting atop a crescent moon with feathered wings")
    d[301] = ("RETITLE", "Angel kneeling gracefully with sweeping wings and bowed head")
    d[302] = ("RETITLE", "Standing angel with ornate patterned wings and prayer beads")
    d[303] = ("RETITLE", "Flying cherub angel aiming a golden bow and love arrow")
    d[304] = ("RETITLE", "Angel standing atop a pillared archway overlooking clouds")
    d[305] = ("RETITLE", "Detailed angel silhouette with grand feathered wingspan")
    d[306] = ("RETITLE", "Seraphic angel holding a shining lantern aloft in prayer")
    
    # 307..309: Mickey Mouse
    d[307] = ("RETITLE", "Mickey Mouse face smiling cheerfully with iconic round ears")
    d[308] = ("RETITLE", "Mickey Mouse standing hands on hips wearing button shorts")
    d[309] = ("RETITLE", "Mickey Mouse in sorcerer robes and pointed star hat")
    
    # 310..312: Fantasy
    d[310] = ("RETITLE", "Mythical wizard casting a spell with a glowing staff")
    d[311] = ("RETITLE", "Centaur warrior drawing a recurve hunting bow on four legs")
    d[312] = ("RETITLE", "Griffin standing with eagle head and lion claws ready to pounce")
    
    # 313..315: Mona Lisa
    d[313] = ("RETITLE", "Mona Lisa portrait outline with enigmatic smile and folded hands")
    d[314] = ("RETITLE", "Mona Lisa painting rendered in shaded text blocks")
    d[315] = ("RETITLE", "Detailed portrait of Mona Lisa with delicate veil and cross-hatching")
    
    # 316..317: Couples
    d[316] = ("RETITLE", "Silhouette of romantic couple kissing beneath a starry moonlit sky")
    d[317] = ("RETITLE", "Couple holding hands walking along a path into the distance")
    
    # 318..363: Cats (46 cats)
    d[318] = ("RETITLE", "Small kitten curled up asleep on a round cushion")
    d[319] = ("RETITLE", "Cat silhouette sitting upright with an elegantly curled tail")
    d[320] = ("RETITLE", "Playful kitten batting at a swinging ball of yarn")
    d[321] = ("RETITLE", "Cat crouching low with wide pupils preparing to pounce")
    d[322] = ("RETITLE", "Curious cat peering over the edge of a wooden wall")
    d[323] = ("RETITLE", "Cat stretching its front paws forward with arched back")
    d[324] = ("RETITLE", "Fluffy longhaired Persian cat sitting front-on with flat face")
    d[325] = ("RETITLE", "Two cats sitting together with tails entwined into a heart")
    d[326] = ("RETITLE", "Cat head in profile with pointed triangular ears and whiskers")
    d[327] = ("RETITLE", "Sleeping cat resting on a windowsill under a crescent moon")
    d[328] = ("RETITLE", "Cat licking its front paw in a grooming posture")
    d[329] = ("RETITLE", "Slender black cat walking gracefully with tail held high")
    d[330] = ("RETITLE", "Cat sitting inside an empty open cardboard box")
    d[331] = ("RETITLE", "Chubby tabby cat resting on its belly with paws tucked")
    d[332] = ("RETITLE", "Cat face with long curved whiskers and almond-shaped eyes")
    d[333] = ("RETITLE", "Kitten climbing up a vertical wooden scratching post")
    d[334] = ("RETITLE", "Cat yawning widely showing tiny sharp teeth and pink tongue")
    d[335] = ("RETITLE", "Sleek cat silhouette sitting against a glowing full moon")
    d[336] = ("RETITLE", "Cat sitting on the back of an upholstered armchair")
    d[337] = ("RETITLE", "Playful cat rolling on its back with all four paws up")
    d[338] = ("RETITLE", "Cat staring intently at a small goldfish in a glass bowl")
    d[339] = ("RETITLE", "Minimalist single-line cat drawing viewed from behind with curling tail")
    d[340] = ("RETITLE", "Cat perched high on a narrow wooden fence rail")
    d[341] = ("RETITLE", "Cute kitten peeking out from inside an old leather boot")
    d[342] = ("RETITLE", "Cat stalking forward in slow stealthy hunting motion")
    d[343] = ("RETITLE", "Two kittens wrestling and tumbling together on the floor")
    d[344] = ("RETITLE", "Cat sitting beside an empty food dish looking expectant")
    d[345] = ("RETITLE", "Cheshire Cat grinning widely from high up a tree branch")
    d[346] = ("RETITLE", "Cat sleeping on an open book on a study desk")
    d[347] = ("RETITLE", "Mother cat resting with three tiny nursing kittens")
    d[348] = ("RETITLE", "Cat swatting a dangling hanging cord with front claws")
    d[349] = ("RETITLE", "Stylized geometric cat sitting in sharp angled lines")
    d[350] = ("RETITLE", "Cat sitting upright alert with one ear swiveled sideways")
    d[351] = ("RETITLE", "Kitten sitting inside a flowerpot among blooming daisy petals")
    d[352] = ("RETITLE", "Cat relaxing on its side with legs stretched out lazily")
    d[353] = ("RETITLE", "Cat peeking around the corner of an open doorway")
    d[354] = ("RETITLE", "Silhouette of cat walking along a rooftop under chimney smoke")
    d[355] = ("RETITLE", "Cat looking up curiously at a flying butterfly")
    d[356] = ("RETITLE", "Kitten tangled inside a spool of knitting wool")
    d[357] = ("RETITLE", "Cat sitting proudly with a tiny bow tie collar")
    d[358] = ("RETITLE", "Fat cat napping soundly on a soft fluffy pillow")
    d[359] = ("RETITLE", "Cat scratching a wooden table leg with extended claws")
    d[360] = ("RETITLE", "Siamese cat sitting slender with distinctive dark mask markings")
    d[361] = ("RETITLE", "Cat head poking through a round hole in a fence")
    d[362] = ("RETITLE", "Two cats sharing a bowl of milk side by side")
    d[363] = ("RETITLE", "Cat balancing nimbly on a narrow tree limb")
    
    # 364: Spongebob
    d[364] = ("RETITLE", "SpongeBob SquarePants laughing cheerfully in his square brown trousers")
    
    # 365..370: Faces
    d[365] = ("RETITLE", "Smiling cartoon face with big round eyes and rosy cheeks")
    d[366] = ("RETITLE", "Winking face sticking out its tongue in a cheeky expression")
    d[367] = ("RETITLE", "Surprised face with wide open mouth and raised eyebrows")
    d[368] = ("RETITLE", "Grumpy face with furrowed brow and down-turned mouth")
    d[369] = ("RETITLE", "Laughing face with tears of joy streaming from eyes")
    d[370] = ("RETITLE", "Shocked face with hands pressed against both cheeks")
    
    # 371..377: Babies
    d[371] = ("RETITLE", "Baby crawling on hands and knees wearing a diaper")
    d[372] = ("RETITLE", "Baby sleeping peacefully in a wicker crib under a blanket")
    d[373] = ("RETITLE", "Baby sucking on a pacifier dummy with wide round eyes")
    d[374] = ("RETITLE", "Baby sitting in a high chair holding a feeding spoon")
    d[375] = ("RETITLE", "Baby playing with colorful alphabet building blocks")
    d[376] = ("RETITLE", "Baby wrapped snugly in a swaddling blanket with bonnet")
    d[377] = ("RETITLE", "Baby laughing with arms raised holding a rattle toy")
    
    # 378..381: Red Dwarf
    d[378] = ("RETITLE", "Dave Lister from Red Dwarf wearing his dreadlocks and leather jacket")
    d[379] = ("RETITLE", "Arnold Rimmer with holographic H emblem shining on forehead")
    d[380] = ("RETITLE", "Cat character from Red Dwarf in stylish zoot suit jacket")
    d[381] = ("RETITLE", "Kryten the sanitation mechanoid robot with angular grooved head")
    
    # 382: Garfield
    d[382] = ("RETITLE", "Garfield the fat orange cat resting his chin on folded arms")
    
    # 383..384: Video game creatures
    d[383] = ("RETITLE", "Space Invader pixel alien descending in retro arcade style")
    d[384] = ("RETITLE", "Retro video game monster with horns and menacing jagged teeth")
    
    # 385..386: Scorpions
    d[385] = ("RETITLE", "Desert scorpion with curved stinger tail arched over its body")
    d[386] = ("RETITLE", "Scorpion in defensive stance with wide open front pincers")
    
    # 387..389: Monsters
    d[387] = ("RETITLE", "Friendly one-eyed cyclops monster waving with a wide smile")
    d[388] = ("RETITLE", "Furry monster peeking out from underneath a child bed")
    d[389] = ("RETITLE", "Spooky tentacled monster emerging from a dark swirling portal")
    
    # 390..400: Rabbits
    d[390] = ("RETITLE", "Fluffy bunny rabbit sitting in grass with long upright ears")
    d[391] = ("RETITLE", "Rabbit nibbling on a fresh garden carrot held in paws")
    d[392] = ("RETITLE", "Two rabbits touching noses together in a field of clover")
    d[393] = ("RETITLE", "Rabbit standing up on its hind legs looking around alertly")
    d[394] = ("RETITLE", "Cute bunny curled asleep into a fluffy round ball")
    d[395] = ("RETITLE", "Rabbit hopping mid-leap with ears laid back against its body")
    d[396] = ("RETITLE", "Bunny head in profile with long whiskers and twitching nose")
    d[397] = ("RETITLE", "Easter bunny carrying a woven basket filled with decorated eggs")
    d[398] = ("RETITLE", "Small baby rabbit sitting inside a teacup with droopy ears")
    d[399] = ("RETITLE", "Rabbit peeking out from inside an underground burrow hole")
    d[400] = ("RETITLE", "Lop-eared rabbit resting its chin on its front paws")
    
    # 401: Video game other
    d[401] = ("RETITLE", "Classic retro arcade joystick controller with round ball top and buttons")
    
    # 402: Tiny Toon Adventures
    d[402] = ("RETITLE", "Buster Bunny giving a thumbs up sign with long blue ears")
    
    # 403..418: Teddy Bears
    d[403] = ("RETITLE", "Classic teddy bear sitting upright with stitched nose and button eyes")
    d[404] = ("RETITLE", "Teddy bear holding a big plush heart in both paws")
    d[405] = ("RETITLE", "Cute teddy bear wearing a knitted winter scarf and beanie hat")
    d[406] = ("RETITLE", "Teddy bear waving one fuzzy paw with a friendly smile")
    d[407] = ("RETITLE", "Small teddy bear sitting inside an open gift box with ribbon")
    d[408] = ("RETITLE", "Teddy bear holding a cluster of party balloons on strings")
    d[409] = ("RETITLE", "Two teddy bears hugging each other warmly side by side")
    d[410] = ("RETITLE", "Teddy bear wearing a bowtie sitting with legs spread out")
    d[411] = ("RETITLE", "Teddy bear lying in bed tucked under a patchwork quilt")
    d[412] = ("RETITLE", "Teddy bear reading a small storybook held in its lap")
    d[413] = ("RETITLE", "Teddy bear sitting on a wooden rocking horse toy")
    d[414] = ("RETITLE", "Teddy bear wearing pajamas and holding a tiny stuffed doll")
    d[415] = ("RETITLE", "Teddy bear sitting under an umbrella during a gentle rain shower")
    d[416] = ("RETITLE", "Cute teddy bear peeking over a wooden fence panel")
    d[417] = ("RETITLE", "Teddy bear holding a bouquet of freshly picked wild daisies")
    d[418] = ("RETITLE", "Teddy bear sitting in a little red wooden wagon cart")
    
    # 419..421: Looney Tunes
    d[419] = ("RETITLE", "Foghorn Leghorn rooster strutting forward with chest puffed out proudly")
    d[420] = ("RETITLE", "Speedy Gonzales mouse wearing a wide sombrero running at top speed")
    d[421] = ("RETITLE", "Pepe Le Pew skunk hopping along trailing romantic heart perfume")
    
    # 422: Little Mermaid
    d[422] = ("RETITLE", "Ariel the Little Mermaid sitting on a seaside rock with flowing hair")
    
    # 423..427: Toy Story
    d[423] = ("RETITLE", "Buzz Lightyear space ranger standing in heroic stance with wings spread")
    d[424] = ("RETITLE", "Woody the cowboy sheriff tipping his wide-brimmed hat with a grin")
    d[425] = ("RETITLE", "Three-eyed green alien toy from Toy Story looking upward in awe")
    d[426] = ("RETITLE", "Rex the green dinosaur standing nervously with small trembling arms")
    d[427] = ("RETITLE", "Hamm the pink piggy bank standing stout on four stubby legs")
    
    # 428..443: Peanuts
    d[428] = ("RETITLE", "Snoopy sleeping on top of his red doghouse with paws up")
    d[429] = ("RETITLE", "Charlie Brown standing in his signature zigzag striped yellow shirt")
    d[430] = ("RETITLE", "Woodstock the little yellow bird perched happily on a twig")
    d[431] = ("RETITLE", "Linus van Pelt sucking his thumb while clutching his security blanket")
    d[432] = ("RETITLE", "Lucy van Pelt sitting at her psychiatric help counseling booth")
    d[433] = ("RETITLE", "Snoopy as the World War One Flying Ace wearing aviator goggles")
    d[434] = ("RETITLE", "Schroeder playing his miniature toy piano with intense musical focus")
    d[435] = ("RETITLE", "Snoopy doing his happy dance on two hind legs with ears floppy")
    d[436] = ("RETITLE", "Charlie Brown sighing with head bowed after missing the football kick")
    d[437] = ("RETITLE", "Snoopy typing a novel on an old-fashioned manual typewriter")
    d[438] = ("RETITLE", "Woodstock flying in an erratic looping flight pattern through the air")
    d[439] = ("RETITLE", "Peppermint Patty slouching at her school classroom desk asleep")
    d[440] = ("RETITLE", "Snoopy hugging Charlie Brown around the neck in a warm embrace")
    d[441] = ("RETITLE", "Sally Brown leaning against a wall waiting for her sweet babboo")
    d[442] = ("RETITLE", "Snoopy as Joe Cool leaning casually against a wall in sunglasses")
    d[443] = ("RETITLE", "Pig-Pen surrounded by his perpetual cloud of swirling dust particles")
    
    # 444..467: The Simpsons
    d[444] = ("RETITLE", "Homer Simpson face grinning with five o clock shadow and round eyes")
    d[445] = ("RETITLE", "Bart Simpson skateboarding with spiky hair and arms outstretched")
    d[446] = ("RETITLE", "Lisa Simpson playing her saxophone with musical notes floating up")
    d[447] = ("RETITLE", "Marge Simpson standing with her tall beehive blue hairstyle")
    d[448] = ("RETITLE", "Maggie Simpson sucking on her pacifier wearing a blue star sleepsuit")
    d[449] = ("RETITLE", "Homer Simpson drooling over a frosted doughnut with sprinkles")
    d[450] = ("RETITLE", "Bart Simpson writing repeatedly on the school chalkboard in detention")
    d[451] = ("RETITLE", "Homer Simpson strangling Bart in comedic cartoon fury")
    d[452] = ("RETITLE", "Krusty the Clown laughing with wild green hair and bowtie")
    d[453] = ("RETITLE", "Mr. Burns steepling his fingers saying excellent with sinister grin")
    d[454] = ("RETITLE", "Ned Flanders waving cheerfully over the garden fence in green sweater")
    d[455] = ("RETITLE", "Moe Szyslak wiping a beer glass behind his tavern counter")
    d[456] = ("RETITLE", "Barney Gumble burping while sitting on a tavern barstool")
    d[457] = ("RETITLE", "Chief Wiggum eating a box of donuts with police badge")
    d[458] = ("RETITLE", "Ralph Wiggum smiling innocently picking his nose with one finger")
    d[459] = ("RETITLE", "Milhouse van Houten wearing thick red glasses and blue hair")
    d[460] = ("RETITLE", "Sideshow Bob with palm tree hair stepping on a garden rake")
    d[461] = ("RETITLE", "Apu Nahasapeemapetilon standing behind the Kwik-E-Mart convenience counter")
    d[462] = ("RETITLE", "Homer Simpson relaxing on the living room couch holding a TV remote")
    d[463] = ("RETITLE", "Bart Simpson firing a slingshot with mischievous grin")
    d[464] = ("RETITLE", "Groundskeeper Willie wielding a garden rake in his kilt")
    d[465] = ("RETITLE", "Comic Book Guy holding a rare vintage comic with disdainful scowl")
    d[466] = ("RETITLE", "Santa's Little Helper the greyhound dog resting on the living room rug")
    d[467] = ("RETITLE", "Snowball II the black cat curling up in the Simpsons hallway")
    
    # 468..469: Other water
    d[468] = ("RETITLE", "Sea turtle swimming gracefully underwater with broad front flippers")
    d[469] = ("RETITLE", "Playful dolphin leaping out of the ocean waves in a high arc")
    
    # 470..472: X-Files
    d[470] = ("RETITLE", "Fox Mulder and Dana Scully standing together holding FBI agent badges")
    d[471] = ("RETITLE", "Flying saucer UFO beaming light down with text I Want to Believe")
    d[472] = ("RETITLE", "Classic grey alien face with large dark almond eyes in profile")
    
    # 473..488: Water birds
    d[473] = ("RETITLE", "Mallard duck swimming smoothly across rippling pond water")
    d[474] = ("RETITLE", "Graceful white swan gliding on water with neck curved in S-shape")
    d[475] = ("RETITLE", "Mother duck followed by four tiny ducklings swimming in a row")
    d[476] = ("RETITLE", "Flamingo standing balanced on one slender leg with head tucked")
    d[477] = ("RETITLE", "Emperor penguin standing upright on an icy Antarctic snowfield")
    d[478] = ("RETITLE", "Pelican perching on a wooden dock post with large throat pouch")
    d[479] = ("RETITLE", "Seagull flying with outstretched wings against a coastal breeze")
    d[480] = ("RETITLE", "Two swans facing each other with necks forming a heart silhouette")
    d[481] = ("RETITLE", "Duck dipping its head underwater with tail feathers tipped up")
    d[482] = ("RETITLE", "Penguin chick covered in fluffy down standing between parent feet")
    d[483] = ("RETITLE", "Heron wading slowly through shallow marsh water hunting for fish")
    d[484] = ("RETITLE", "Rubber duck toy floating in a bubbly warm bathtub")
    d[485] = ("RETITLE", "Pair of flamingos wading in shallow tropical lagoon water")
    d[486] = ("RETITLE", "Puffin bird standing on a coastal cliff with colorful striped beak")
    d[487] = ("RETITLE", "Goose stretching its wings wide while honking on the riverbank")
    d[488] = ("RETITLE", "Penguin sliding along the ice on its belly with wings out")
    
    # 489..490: Skeletons
    d[489] = ("RETITLE", "Full human skeleton standing upright with ribcage and skull")
    d[490] = ("RETITLE", "Skeleton sitting casually on a chair with skull resting on hand")
    
    # 491..495: Babylon 5
    d[491] = ("RETITLE", "Babylon 5 rotating space station cylinder in deep space")
    d[492] = ("RETITLE", "Vorlon alien encounter suit standing mysterious and towering")
    d[493] = ("RETITLE", "Shadow battlecruiser warship with spidery black tendrils in space")
    d[494] = ("RETITLE", "Starfury fighter spacecraft with four angled wing engine pods")
    d[495] = ("RETITLE", "Centauri ambassador with fan-shaped crested hairstyle and ornate coat")
    
    # 496..500: Batman
    d[496] = ("RETITLE", "Batman standing on a high Gotham rooftop with cape billowing in wind")
    d[497] = ("RETITLE", "Bat-Signal shining the iconic bat emblem into stormy night clouds")
    d[498] = ("RETITLE", "Batmobile armored supercar parked with sleek aerodynamic fins")
    d[499] = ("RETITLE", "The Joker grinning maniacally in his purple suit and bowtie")
    d[500] = ("RETITLE", "Batman and Robin leaping forward together into crime-fighting action")
    
    return d

if __name__ == "__main__":
    b1 = get_batch1()
    print(f"Batch 1 generated {len(b1)} decisions (expected 312: 189..500)")
