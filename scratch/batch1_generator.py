# -*- coding: utf-8 -*-
"""Generate decisions for entries 189 to 500."""
import json, io, os, re

entries = json.load(open(r"C:\Temp\entries.json", encoding="utf-8"))

def generate():
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
    # Let's inspect cat entries to ensure every single one is uniquely described!
    return d

print("batch1 generator setup ready")
