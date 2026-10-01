# npexception's Valkyrie ascension (NetHack 5.0.0): how she survived the early and mid game

Source: the dumplog plus all 19 ttyrecs from 2026-09-26 16:47:07 onward, replayed through pyte. The terminal was **223x68**, not 80x24 (curses windowtype with perm_invent). The bottom status line, the 39-line message window and the perm_invent Armor section were sampled at every change of T.
Scripts and data are in `/private/tmp/claude-501/-Users-ian-dev-nethack-jev/ebda16db-8980-4812-b6ec-ca004938cd16/scratchpad/npx/`: `replay.py`, `all.jsonl`, `msgs_dd.tsv` (deduplicated messages), `acchanges.txt` and `worn.txt`.
Caveat: messages are deduplicated over a rolling window of 80 lines, so counts of repeated messages are lower bounds. Messages shown only in popup dialogs, such as shopkeeper sell offers, are not captured.

## Headline

**Low AC was *not* how she survived the early game.** AC was 0 at T2000, -3 at T5000, -3 at T10000 and -6 at T20000. It only went past -10 after T38000.
She survived the early game in three ways:
- She got levels fast in the upper Mines with the pet (XL6 by T1932).
- She then spent about 9,000 turns making Dlvl 2 a fortified base: a converted altar, a stash box and sacrifice gifts (Mjollnir T9441, Werebane T10082).
- She went deeper only at XL9-10 with AC around -4.

After T2000 her HP never fell below 40% before T20000. The one near-death was **T1230: HP 1/33, XL3, AC5, Mines Dlvl 3.** She was blind and deaf, fought an invisible biter, then a kobold lord. She did not pray.

## AC timeline

| T | Dlvl | XL | AC | HP |
|---|---|---|---|---|
| 500 | 1 | 1 | 6 | 16 |
| 1000 | 2 | 1 | 5 | 16 |
| 2000 | 6 (Minetown) | 6 | 0 | 67 |
| 3000 | 6 | 6 | 0 | 67 |
| 5000 | 5 | 8 | -3 | 85 |
| 7500 | 2 | 8 | -3 | 81 |
| 10000 | 2 | 9 | -3 | 93 |
| 12500 | 2 | 9 | -1 (nymph stole helm) | 93 |
| 15000 | 8 | 10 | -4 | 104 |
| 20000 | 10 (Mines' End) | 11 | -6 | 98/110 |
| 25000 | 3 | 11 | -8 | 110 |
| 30000 | 23 | 12 | -8 | 100/116 |
| 35000 | 20 | 13 | -10 | 122 |
| 40000 | 12 | 13 | -18 | 122 |
| 45000 | 20 | 14 | -25 | 128 |
| 50000 | 43 | 14 | -30 | 129 |
| 55000 | 30 | 15 | -34 | 135 |
| 60361 | Astral | 16 | -33 | 151 |

### Net AC changes in the first ~22k turns

Short swaps from trying items on and stripping armor are omitted; the full list is in `acchanges.txt` and `worn.txt`.

| T | AC | Cause | Source |
|---|---|---|---|
| 1 | 6 | Starting +3 small shield | start |
| 932 | 5 | Orcish helm, after an altar BUC test on Dlvl 2 | floor |
| 1107-1243 | 2-3 | Dwarvish cloak and iron shoes from a dwarf the pet killed | dwarf drop |
| 1545 | 0 | Swapped in a **+2** orcish helm that the dog brought her | floor (pet) |
| 2090-2114 | 0 | Altar BUC test in the Minetown temple. Tried on a dwarvish iron helm and several iron shoes to learn enchantments; kept the +2 orcish helm and blessed +2 iron shoes | floor, Mines dwarves |
| 4627 | -3 | Ring mail, carried to her by the dog | floor |
| 8822-8826 | -3 | Tried "combat boots" after a BUC test: they were **speed boots**. She took them off again and kept the +2 iron shoes for AC | floor |
| 11212 | -4 | Oilskin cloak | floor |
| 11379, 12897 | -3 | Mummy wrapping put on to enter shops (she was permanently invisible from ~T3850) | Mines (dwarf mummy) |
| 12267 / 13097 | 0 / -1 | Nymphs stole her helms; she got them back by killing the nymph at T13281 | — |
| 13381 | -2 | Brown pudding rotted her cloak and shield | — |
| 13812 | -4 | Elven mithril-coat, uncursed by the altar test (a cursed one found at T8503 was boxed) | floor |
| 16382 | -5 | Put on an unknown uncursed sapphire ring: it was a **+1 ring of protection** | floor |
| 16396 | -6 | +1 dwarvish cloak, replacing the oilskin | floor |
| 21703 | -8 | Read a blessed **scroll of enchant armor with only the Hawaiian shirt worn**, giving a +3 shirt, then dressed again | floor shirt, scroll from stash |

### Mid and late game: where the remaining 25 points of AC came from

| T | AC after | Cause |
|---|---|---|
| 31184 | -11 | Stripped down so that enchant armor could only hit the speed boots (a cursed scroll first, then a blessed one), giving +2 speed boots, now worn full-time |
| 38300-38472 | -13 | Shield of reflection (floor), enchanted to +3 the same way. Speed boots went to +3; ring of protection back on |
| **39014-39016** | **-18** | **Bought protection from the Minetown priest: 3 donations of about 6k gold each at XL13, -5 AC** |
| 43051-43119 | -25 | A cursed or confused genocide scroll "Sent in some gray dragons". She killed one, wore the **gray dragon scale mail**, and enchanted it (+3 by T47684) |
| **45351-45357** | **-29** | **Donated about 37k gold (from Fort Ludios/Croesus) to the Valley priestess, -4 AC** |
| 47683-47707 | -34 | Two cloaks of protection found. Stripped down, read enchant armor on the cloak: +3 cloak of protection, MC3 |
| 58258 | -33 | Wish: "blessed fixed +2 Hawaiian shirt" |

Final AC budget: GDSM +4 (13), cloak of protection +3 (6), shield of reflection +3 (5), speed boots +3 (4), +2 leather gloves (3), dwarvish iron helm (2), +2 shirt (2), ring of protection +1 (1), and divine protection +9 from 11 priest donations.

Two blessed scrolls of enchant armor were still unread in the bag at the end. **She deliberately hoarded enchant armor until she owned endgame armor worth enchanting.**

## Armor sources

| Source | Items |
|---|---|
| Floor and monster drops | Almost everything: orcish and dwarvish helms, iron shoes, dwarvish cloaks, ring mail, oilskin, elven mithril, speed boots, Hawaiian shirt, leather gloves, shield of reflection, cloaks of protection, ring of protection |
| Shop | **None.** She bought only a key (T3926, 18zm), one scroll (T14398, 80zm, base 60 = enchant weapon), a potion of water, a bag of tricks and a ring |
| Prayer or sacrifice gift | No armor. The gifts were Mjollnir (T9441), Werebane (T10082) and Snickersnee (T31217) |
| Priest donations | -9 AC in total (T39014 Minetown, T45351 Valley) |
| Wish | Hawaiian shirt (T58258) only. The first wish (T37177) was for a wand of polymorph |
| Reverse genocide | Gray dragon scale mail (T43051) |

## Early-game habits

- **Route.** She descended to Dlvl 3 at T935 and entered the Mines at T1004. She reached Minetown at T1989 at XL6, having gone XL1→XL6 in Mines levels 3-7 with the little dog. She spent about T2000-4600 around Minetown (the temple was cross-aligned to Odin), clearing gnomes and dwarves to XL7-8. She did not go below Mines Dlvl 7 until Mines' End at T20963.
- **Altar base on Dlvl 2 (T5000-14000).** Dlvl 2 had a scroll shop and a Loki altar near the Mines entrance. She sacrificed fresh corpses until the altar converted at T8466 ("altar glows white"), after 5 "power of Tyr decrease" messages. She logged 14+ sacrifices before T20000. Results: luck (clovers at T8542, 8735, 10874, 12806, 13848), Mjollnir at T9441 and Werebane at T10082. A large box next to the altar became her stash (scrolls, potions and wands, sorted after BUC tests). She returned to this base repeatedly (T16-17k, 21k, 22k, 25k, 27k).
- **BUC testing.** Before T26000, 125+ "lands on the altar" messages, at the Minetown and Dlvl 2 altars. She tested every armor piece and ring before wearing it, and tried unknown uncursed armor and rings on to learn enchantments and identities (the speed boots, the ring of protection).
- **Prayer.** Only 4 prayers in 60k turns. The three early ones (T10905, 12821, 13856) were made standing on the altar right after a sacrifice gave luck or reconciliation, while healthy, **to make holy water**. The only emergency prayer was T56225 (fainted from hunger). She did not pray at HP 1/33 on T1230.
- **Elbereth.** Rare: about 5 dust engravings before T26000 (T7250 with an Elbereth test-engrave to identify a wand, T12847, T16408). It was not a survival crutch.
- **Shops.** She stepped onto items to see prices in the Dlvl 2 bookstore (T644-690) and in all Minetown shops (T3867-4010). She bought almost nothing. To shop while invisible she put on a mummy wrapping (T3850, T11379, T12897, T22710, T25047, T33275).
- **Food.** She ate corpses whenever safe: 57 "corpse tastes" and 186 "You finish eating" messages. Rations were a backup (11 food rations eaten before T26000). She ate a floating eye early (T1632, telepathy) and later used a towel or blindfold for telepathic scans dozens of times. She got hungry only once and fainted once (T56225).
- **Resting.** She almost never stopped to rest: only 3 multi-turn waits started below 70% HP before T26000. She regenerated while doing safe work such as walking back to the altar, sorting the stash or eating.
- **Pet.** The dog did a lot of the early killing: dwarves at T1088 and T4277, a kobold lord at T1235, watchmen. It also fetched armor for her (the +2 orcish helm, ring mail). She used a magic whistle to keep it close (from T3393).
- **Sokoban** came late: T14269-18400, at XL9-10 with AC -4 and Mjollnir in hand. **The Quest** was at T40088 (XL13-14). **Medusa** fell at T35608. **The Castle** was reached at T35607.

## Strategies for the bot, ordered by early-game survival impact

1. **Be very careful in Mines levels 1-2 at XL1-3.** Her only near-death came at T1230, with XL3 and AC5, against invisible enemies and a kobold lord while blind. Rules: below 50% HP at XL<5, stop fighting new monsters. Retreat upstairs or behind the pet, and pray if HP < 1/7 and prayer is likely safe (T > ~300 at start). Do not go blind or deaf into melee.
2. **Gain levels with the pet before going deep, and keep the pet close.** Aim for XL6 by Minetown and XL9-10 before Sokoban or Dlvl 8+. She did not pass Dlvl 7 until T14350. Keep the dog adjacent and let it take dwarves and kobolds. Use a magic whistle if one is found.
3. **Wear every safe AC piece from Mines dwarves and the floor, and pick the best by trying things on.** Dwarvish iron helm, iron shoes, dwarvish cloak, ring mail or mithril get a Valkyrie to AC 0 by Minetown and about -4 by T14000. BUC-test on an altar first. Prefer the higher enchantment over the better base item (she kept a +2 orcish helm over a +0 dwarvish iron helm). Prefer AC over speed until you can enchant the boots.
4. **Use a nearby altar as a base: BUC-test everything, and sacrifice to convert it and get gifts.** A Valkyrie at a co-aligned altar gets Mjollnir quickly (first gift at T9441). Fresh corpses also raise Luck. Stash spare items next to the altar.
5. **Get protection from a priest the moment gold allows** Each donation of at least 400×XL gold (and less than 600×XL) can give -1 AC. It is certain while divine protection is below +9, and a chance after that. Cheaper at low XL. It gave her -9 AC in total. A bot should track gold against `400*XL` and visit the Minetown temple, even a cross-aligned one, because donating works for any alignment. This is the cheapest big AC gain in the game.
6. **Enchant armor with only the target piece worn.** Strip everything else, read the scroll, then dress again (T21703 shirt, T31184 boots, T38433 shield, T47690 cloak). Never let an early blessed enchant armor scroll hit a +0 throwaway piece. Save them for pieces that will stay to the end (GDSM or SDSM, cloak of protection or MR, speed boots, a shirt under body armor).
7. **Put on a shirt under body armor and enchant it.** A shirt is a free extra slot (+3 shirt = 3 AC at T21703) and is safe to enchant to +3 or more.
8. **Use test-wears for identification.** An unknown uncursed ring that changes AC is protection (T16382). Boots that make you "speed up" are speed boots (T8824).
9. **Pray rarely and on purpose.** Prayer was not her emergency button (she used it 4 times). Save it for real trouble (low HP, weak from hunger), and use spare timeouts at the altar to make holy water.
10. **Engrave-test wands with Elbereth, but do not depend on Elbereth.** She used it only a handful of times. Positioning, the pet and level advantage did the work.
