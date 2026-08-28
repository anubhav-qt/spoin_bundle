# -*- coding: utf-8 -*-
"""Curation generator for Batch 1: indexes 189 to 500."""
import json, re, io

entries = json.load(open(r"C:\Temp\entries.json", encoding="utf-8"))

def build_batch1():
    decisions = {}
    
    # Let's write decisions for 189..500
    # 189, 190: Fish
    # 191..206: Winnie the Pooh
    # 207: Pillsbury doughboy
    # 208..219: Fairies
    # 220..226: Preachers
    # 227..228: Toys / Slinky
    # 229..233: Native Americans / Canoes / Headdress
    # 234..235: Balloons
    # 236..237: Pacman
    # 238: Alice in wonderland
    # 239..249: Looney Tunes (Tweety, Marvin the Martian, Daffy, Bugs Bunny, Taz, Sylvester)
    # 250..255: Explosives / Bombs / Dynamite
    # 256..268: Sesame Street (Cookie Monster, Elmo, Big Bird, Bert, Ernie)
    # 269..271: Futurama (Bender, Fry)
    # 272..279: Wallace & Gromit
    # 280..306: Angels
    # 307..309: Mickey Mouse
    # 310..312: Fantasy
    # 313..315: Mona Lisa
    # 316..317: Couples
    # 318..363: Cats (46 cats)
    # 364: Spongebob
    # 365..370: Faces
    # 371..377: Babies
    # 378..381: Red Dwarf
    # 382: Garfield
    # 383..384: Video game creatures
    # 385..386: Scorpions
    # 387..389: Monsters
    # 390..400: Rabbits
    # 401: Video game other
    # 402: Tiny Toon Adventures
    # 403..418: Teddy Bears
    # 419..421: Looney tunes
    # 422: Little Mermaid
    # 423..427: Toy Story (Buzz Lightyear, Woody, Aliens)
    # 428..443: Peanuts (Snoopy, Charlie Brown, Woodstock, Linus)
    # 444..467: The Simpsons (Homer, Bart, Lisa, Marge, Maggie)
    # 468..469: Other water animals
    # 470..472: X-Files
    # 473..488: Water birds (Ducks, Swans, Flamingos, Penguins)
    # 489..490: Skeletons
    # 491..495: Babylon 5
    # 496..500: Batman
    return decisions

print("Batch 1 scaffold ready")
