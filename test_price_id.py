"""Price-ID self-check: shk.c get_cost inversion and appearance parsing."""
from jev.bot import appearance, price_bases, quote_bases, sell_price

assert appearance('a scroll labeled KERNOD WEL (for sale, 26 zorkmids)') == ('scroll', 'KERNOD WEL')
assert appearance('2 uncursed dark green potions') == ('potion', 'dark green')
assert appearance('a potion of healing') is None
assert appearance('a black onyx ring') == ('ring', 'black onyx')
assert sell_price(20, 9, 0) == 27 and sell_price(20, 9, 1) == 36  # Ch 8-10: 4/3, unID surcharge another 4/3
assert price_bases('scroll', 27, 9) == {20}
assert price_bases('potion', 20, 12) == {20}
assert price_bases('scroll', 80, 12) == {60, 80}  # ambiguous: 60 * 4/3 == 80
assert appearance('a scroll labeled FOO BAR {buy 26 sell 10}') == ('scroll', 'FOO BAR')
assert quote_bases('scroll', 'a scroll labeled FOO BAR {buy 27-36}', 9) == {20}
assert quote_bases('scroll', 'a scroll labeled FOO BAR {sell 10}', 9) == {20}  # 20/2
assert quote_bases('scroll', 'a scroll labeled FOO BAR {sell 30}', 9) == {60, 80}  # 60/2, 80*3/8
assert quote_bases('scroll', 'a scroll labeled FOO BAR {buy 80 sell 30}', 12) == {60, 80} and quote_bases('scroll', 'a scroll labeled FOO BAR {buy 80 sell 23-30}', 12) == {60, 80}
assert quote_bases('scroll', 'a scroll labeled FOO BAR {buy 107 sell 30}', 12) == {80}
assert quote_bases('potion', 'a pink potion', 12) is None
print('ok')
