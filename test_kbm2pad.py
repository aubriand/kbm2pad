"""Auto-test de la logique pure (tourne sur tout OS) : python test_kbm2pad.py"""
import json
import math
from pathlib import Path

from kbm2pad import dpad_dir, layer_binds, mouse_to_stick, pad_state, stick_byte, validate

profile = json.loads((Path(__file__).parent / "profiles" / "gta.json").read_text(encoding="utf-8"))
validate(profile)
base = layer_binds(profile, "base")
car = layer_binds(profile, "vehicule")

# diagonale normalisée, opposés s'annulent
_, _, _, ls, _ = pad_state({"z", "d"}, base, (0, 0), 0.5)
assert math.isclose(math.hypot(*ls), 1) and ls[0] > 0 > ls[1], ls
assert pad_state({"q", "d"}, base, (0, 0), 0.5)[3] == (0, 0)
# marche
assert math.isclose(pad_state({"z", "lctrl"}, base, (0, 0), 0.5)[3][1], -0.5)
# boutons, gâchettes, couche véhicule
b, l2, r2, _, _ = pad_state({"space", "mouse_left", "mouse_right", "m"}, base, (0, 0), 0.5)
assert b == {"square", "touchpad"} and l2 == r2 == 255
b, l2, r2, ls, _ = pad_state({"z", "space", "q"}, car, (0, 0), 0.5)
assert r2 == 255 and b == {"r1"} and ls == (-1, 0)
# souris -> stick : arrêt = centre, lent = au moins anti-deadzone, rapide = plafonné à 1
assert mouse_to_stick(0, 0, 0.02, 2500, 0.8, 0.2) == (0, 0)
x, y = mouse_to_stick(1, 0, 0.02, 2500, 0.8, 0.2)
assert 0.2 <= x < 0.3 and y == 0, x
x, y = mouse_to_stick(300, 400, 0.02, 2500, 0.8, 0.2)
assert math.isclose(math.hypot(x, y), 1) and math.isclose(x / y, 0.75)
# souris + touches sur le même stick restent dans le cercle
assert math.hypot(*pad_state({"l"}, base, (0.9, 0.9), 0.5)[4]) <= 1 + 1e-9
# conversions DS4
assert (stick_byte(-1), stick_byte(0), stick_byte(1)) == (1, 128, 255)
assert dpad_dir({"up", "right"}) == "NORTHEAST" and dpad_dir({"up", "down"}) == "NONE"
# hooks simulés (sans Windows) : avale / laisse passer
import types
from kbm2pad import Bridge


class Swallowed(Exception):
    pass


def raise_swallowed():
    raise Swallowed


br = Bridge(profile, True, True)
br.kb = br.ms = types.SimpleNamespace(suppress_event=raise_swallowed)


def key(vk, down):
    try:
        br.kb_filter(0x100 if down else 0x101, types.SimpleNamespace(vkCode=vk, flags=0))
        return "pass"
    except Swallowed:
        return "swallow"


def click(down):
    try:
        br.ms_filter(0x201 if down else 0x202, types.SimpleNamespace(pt=None, mouseData=0, flags=0))
        return "pass"
    except Swallowed:
        return "swallow"


assert click(True) == "pass"          # clic qui active Veyra : capture pas encore ON
br.capturing = True
assert click(False) == "pass"         # son relâchement doit passer, sinon clic bloqué dans Windows
assert key(0x5A, True) == "swallow" and "z" in br.held
assert key(0x7A, True) == "pass"      # F11 en passthrough
assert key(0x77, True) == "pass" and not br.enabled  # F8 jamais avalé
br.capturing = False                  # pause pendant que Z est tenu
assert key(0x5A, False) == "swallow" and "z" not in br.held  # relâchement d'un appui avalé
assert key(0x5A, False) == "pass"

# profil invalide refusé
try:
    validate({"binds": {"w": "saut"}})
    raise SystemExit("validate aurait dû refuser")
except ValueError:
    pass
print("OK")
