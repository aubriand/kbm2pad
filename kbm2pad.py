"""kbm2pad: clavier + souris -> manette DualShock 4 virtuelle (ViGEmBus).

Pensé pour jouer sur PS5 via Veyra (PS5 Remote Play), mais marche avec tout ce
qui lit une manette. Windows uniquement pour la capture ; la logique pure
(mapping, souris -> stick) est testable partout : python test_kbm2pad.py
"""
import argparse
import json
import math
import sys
import threading
import time
from collections import deque
from pathlib import Path

BUTTONS = ("cross", "circle", "square", "triangle", "l1", "r1", "l3", "r3",
           "options", "share", "ps", "touchpad", "up", "down", "left", "right")
TRIGGERS = ("l2", "r2")
STICK_DIRS = {f"{s}_{d}": (s, v) for s in ("ls", "rs") for d, v in
              (("up", (0, -1)), ("down", (0, 1)), ("left", (-1, 0)), ("right", (1, 0)))}
TARGETS = set(BUTTONS) | set(TRIGGERS) | set(STICK_DIRS) | {"walk"}


# ---------- logique pure ----------

def layer_binds(profile, layer):
    """Binds actifs : base + surcharges de la couche (key -> cible)."""
    return {**profile["binds"], **profile.get("layers", {}).get(layer, {})}


def validate(profile):
    for layer in [None, *profile.get("layers", {})]:
        binds = profile["binds"] if layer is None else profile["layers"][layer]
        for key, target in binds.items():
            if target not in TARGETS:
                raise ValueError(f"cible inconnue '{target}' pour la touche '{key}' (couche {layer or 'base'})")
            if not key.startswith(("mouse_", "wheel_")) and key not in VK_BY_NAME:
                raise ValueError(f"touche inconnue '{key}'")


def clamp_vec(x, y):
    m = math.hypot(x, y)
    return (x / m, y / m) if m > 1 else (x, y)


def mouse_to_stick(dx, dy, dt, full_speed, curve, anti_deadzone):
    """Déplacement souris (counts) sur dt secondes -> stick (-1..1), direction conservée.

    full_speed : vitesse souris (counts/s) qui donne le stick à fond.
    anti_deadzone : saute la zone morte du jeu pour que les petits gestes bougent la caméra.
    """
    if dt <= 0 or (dx == 0 and dy == 0):
        return 0.0, 0.0
    vx, vy = dx / dt, dy / dt
    speed = math.hypot(vx, vy)
    m = anti_deadzone + (1 - anti_deadzone) * min(1.0, speed / full_speed) ** curve
    return vx / speed * m, vy / speed * m


def pad_state(held, binds, mouse_rs, walk_scale):
    """Touches tenues -> état manette : (frozenset boutons, l2, r2, ls, rs)."""
    buttons, l2, r2 = set(), 0, 0
    sticks = {"ls": [0.0, 0.0], "rs": [0.0, 0.0]}
    walk = False
    for key in held:
        t = binds.get(key)
        if t is None:
            continue
        if t in STICK_DIRS:
            s, (vx, vy) = STICK_DIRS[t]
            sticks[s][0] += vx
            sticks[s][1] += vy
        elif t == "l2":
            l2 = 255
        elif t == "r2":
            r2 = 255
        elif t == "walk":
            walk = True
        else:
            buttons.add(t)
    # axes opposés tenus ensemble s'annulent ; diagonale normalisée
    ls = clamp_vec(*[max(-1, min(1, v)) for v in sticks["ls"]])
    if walk:
        ls = (ls[0] * walk_scale, ls[1] * walk_scale)
    rs = clamp_vec(sticks["rs"][0] + mouse_rs[0], sticks["rs"][1] + mouse_rs[1])
    return frozenset(buttons), l2, r2, ls, rs


def stick_byte(v):
    """-1..1 -> 0..255 (DS4 : 128 = centre, Y 0 = haut)."""
    return max(0, min(255, 128 + round(v * 127)))


DPAD = {  # (x, y) -> nom de direction DS4 dans vgamepad
    (0, 0): "NONE", (0, -1): "NORTH", (1, -1): "NORTHEAST", (1, 0): "EAST", (1, 1): "SOUTHEAST",
    (0, 1): "SOUTH", (-1, 1): "SOUTHWEST", (-1, 0): "WEST", (-1, -1): "NORTHWEST",
}


def dpad_dir(buttons):
    x = ("right" in buttons) - ("left" in buttons)
    y = ("down" in buttons) - ("up" in buttons)
    return DPAD[(x, y)]


# ---------- noms de touches -> virtual-key Windows ----------

VK_BY_NAME = {
    **{chr(c).lower(): c for c in range(ord("A"), ord("Z") + 1)},
    **{str(d): 0x30 + d for d in range(10)},
    **{f"f{i}": 0x6F + i for i in range(1, 25)},
    "space": 0x20, "enter": 0x0D, "tab": 0x09, "esc": 0x1B, "backspace": 0x08,
    "lshift": 0xA0, "rshift": 0xA1, "lctrl": 0xA2, "rctrl": 0xA3, "lalt": 0xA4, "ralt": 0xA5,
    "lwin": 0x5B, "rwin": 0x5C, "capslock": 0x14,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    **{f"num{d}": 0x60 + d for d in range(10)},
}
NAME_BY_VK = {v: k for k, v in VK_BY_NAME.items()}
# Les codes virtuels Windows suivent la disposition : "z" = la touche marquée Z (AZERTY ou QWERTY).


# ---------- Windows ----------

class Bridge:
    def __init__(self, profile, dry_run, any_window):
        self.p = profile
        self.dry_run = dry_run
        self.any_window = any_window
        self.layers = ["base", *profile.get("layers", {})]
        self.layer = 0
        self.binds = layer_binds(profile, self.layers[0])
        self.enabled = True
        self.fg_ok = False
        self.capturing = False
        self.held = set()
        self.raw_down = set()  # anti auto-répétition du clavier
        self.swallowed = set()  # appuis avalés dont il faut aussi avaler le relâchement
        self.pulses = {}  # molette : touche -> fin de l'appui
        self.lock = threading.Lock()
        self.acc = [0, 0]
        self.anchor = (0, 0)
        self.window = deque()  # (t, dx, dy) pour le lissage souris
        self.toggle_vk = VK_BY_NAME[profile.get("toggle_key", "f8")]
        self.layer_vk = VK_BY_NAME.get(profile.get("layer_key", ""))
        self.passthrough = {VK_BY_NAME[k] for k in profile.get("passthrough", [])}
        self.targets = {e.lower() for e in profile.get("target_exe", ["veyra.exe"])}
        self.kb = self.ms = None

    # --- hooks (thread du hook : rester rapide, Windows coupe un hook lent) ---
    def kb_filter(self, msg, data):
        if data.flags & 0x10:  # LLKHF_INJECTED : ignore ce que d'autres programmes simulent
            return False
        vk, down = data.vkCode, msg in (0x100, 0x104)
        first = down and vk not in self.raw_down
        (self.raw_down.add if down else self.raw_down.discard)(vk)
        if vk == self.toggle_vk:
            if first:
                self.enabled = not self.enabled
                print("kbm2pad", "ACTIF" if self.enabled else "en pause")
            return False  # jamais avalée, sinon impossible de reprendre la main
        if vk == self.layer_vk and first and self.capturing:
            self.layer = (self.layer + 1) % len(self.layers)
            self.binds = layer_binds(self.p, self.layers[self.layer])
            print("couche :", self.layers[self.layer])
        return self.button(NAME_BY_VK.get(vk, vk), down, self.kb, vk in self.passthrough)

    def button(self, name, down, listener, passthrough=False):
        """Appui/relâche. On n'avale un relâchement que si on a avalé son appui :
        sinon Windows croit la touche encore enfoncée (ex. clic qui active Veyra)."""
        if not down:
            with self.lock:
                self.held.discard(name)
            if name in self.swallowed:
                self.swallowed.discard(name)
                listener.suppress_event()
            return False
        if not self.capturing:
            return False
        with self.lock:
            self.held.add(name)
        if not passthrough:
            self.swallowed.add(name)
            listener.suppress_event()
        return False

    MOUSE_BTN = {0x201: ("mouse_left", True), 0x202: ("mouse_left", False),
                 0x204: ("mouse_right", True), 0x205: ("mouse_right", False),
                 0x207: ("mouse_middle", True), 0x208: ("mouse_middle", False)}

    def ms_filter(self, msg, data):
        if data.flags & 0x01:  # LLMHF_INJECTED
            return False
        if msg in self.MOUSE_BTN:
            return self.button(*self.MOUSE_BTN[msg], self.ms)
        if msg in (0x20B, 0x20C):  # boutons latéraux X1/X2
            name = "mouse_x1" if (data.mouseData >> 16) == 1 else "mouse_x2"
            return self.button(name, msg == 0x20B, self.ms)
        if not self.capturing:
            return False
        if msg == 0x200:  # WM_MOUSEMOVE : le curseur reste figé, pt = ancre + delta
            with self.lock:
                self.acc[0] += data.pt.x - self.anchor[0]
                self.acc[1] += data.pt.y - self.anchor[1]
        elif msg == 0x20A:  # molette : un appui bref
            delta = (data.mouseData >> 16) & 0xFFFF
            name = "wheel_down" if delta & 0x8000 else "wheel_up"
            with self.lock:
                self.pulses[name] = time.perf_counter() + 0.08
        self.ms.suppress_event()
        return False

    # --- boucle principale ---
    def foreground_exe(self):
        import ctypes
        from ctypes import wintypes
        u, k = ctypes.windll.user32, ctypes.windll.kernel32
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(u.GetForegroundWindow(), ctypes.byref(pid))
        h = k.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ""
        buf, size = ctypes.create_unicode_buffer(520), wintypes.DWORD(520)
        ok = k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
        k.CloseHandle(h)
        return Path(buf.value).name.lower() if ok else ""

    def set_capture(self, on):
        import ctypes
        if on == self.capturing:
            return
        if on:
            u = ctypes.windll.user32
            # curseur au centre de l'écran : sinon les deltas sont coupés au bord
            self.anchor = (u.GetSystemMetrics(0) // 2, u.GetSystemMetrics(1) // 2)
            u.SetCursorPos(*self.anchor)
        with self.lock:
            self.held.clear()
            self.pulses.clear()
            self.acc = [0, 0]
        self.window.clear()
        self.capturing = on
        print("capture", "ON" if on else "OFF")

    def mouse_rs(self, now):
        m = self.p["mouse"]
        with self.lock:
            dx, dy = self.acc
            self.acc = [0, 0]
        self.window.append((now, dx, dy))
        span = m.get("smooth_ms", 20) / 1000
        while self.window and self.window[0][0] < now - span:
            self.window.popleft()
        sx = sum(w[1] for w in self.window) * m.get("sens_x", 1.0)
        sy = sum(w[2] for w in self.window) * m.get("sens_y", 1.0) * (-1 if m.get("invert_y") else 1)
        return mouse_to_stick(sx, sy, span, m["full_speed"], m.get("curve", 1.0), m.get("anti_deadzone", 0.0))

    def run(self, rate):
        import ctypes
        # Sans ça, à 125-150 % d'échelle, SetCursorPos (logique) et pt du hook (physique)
        # divergent et le stick droit reste penché.
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
        except (AttributeError, OSError):
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        from pynput import keyboard, mouse
        pad = None
        if not self.dry_run:
            import vgamepad as vg
            pad = vg.VDS4Gamepad()
            btn = {"cross": vg.DS4_BUTTONS.DS4_BUTTON_CROSS, "circle": vg.DS4_BUTTONS.DS4_BUTTON_CIRCLE,
                   "square": vg.DS4_BUTTONS.DS4_BUTTON_SQUARE, "triangle": vg.DS4_BUTTONS.DS4_BUTTON_TRIANGLE,
                   "l1": vg.DS4_BUTTONS.DS4_BUTTON_SHOULDER_LEFT, "r1": vg.DS4_BUTTONS.DS4_BUTTON_SHOULDER_RIGHT,
                   "l3": vg.DS4_BUTTONS.DS4_BUTTON_THUMB_LEFT, "r3": vg.DS4_BUTTONS.DS4_BUTTON_THUMB_RIGHT,
                   "options": vg.DS4_BUTTONS.DS4_BUTTON_OPTIONS, "share": vg.DS4_BUTTONS.DS4_BUTTON_SHARE}
            special = {"ps": vg.DS4_SPECIAL_BUTTONS.DS4_SPECIAL_BUTTON_PS,
                       "touchpad": vg.DS4_SPECIAL_BUTTONS.DS4_SPECIAL_BUTTON_TOUCHPAD}
        self.kb = keyboard.Listener(win32_event_filter=self.kb_filter)
        self.ms = mouse.Listener(win32_event_filter=self.ms_filter)
        self.kb.start()
        self.ms.start()
        print(f"kbm2pad prêt. {self.p.get('toggle_key', 'f8').upper()} = pause/reprise, Ctrl+C dans cette console = quitter.")
        last, last_exe, next_fg, dt = None, None, 0.0, 1 / rate
        try:
            while True:
                now = time.perf_counter()
                if now >= next_fg:
                    exe = self.foreground_exe()
                    if exe != last_exe:
                        print("premier plan :", exe or "?")
                        last_exe = exe
                    self.fg_ok = self.any_window or exe in self.targets
                    next_fg = now + 0.1
                self.set_capture(self.enabled and self.fg_ok)
                with self.lock:
                    held = self.held | {k for k, t in self.pulses.items() if t > now}
                rs = self.mouse_rs(now) if self.capturing else (0.0, 0.0)
                state = pad_state(held, self.binds, rs, self.p.get("walk_scale", 0.45))
                if state != last:
                    last = state
                    buttons, l2, r2, ls, rs = state
                    if pad is None:
                        print(sorted(buttons), "L2", l2, "R2", r2, "LS", [round(v, 2) for v in ls],
                              "RS", [round(v, 2) for v in rs])
                    else:
                        pad.reset()
                        for b in buttons:
                            if b in btn:
                                pad.press_button(btn[b])
                            elif b in special:
                                pad.press_special_button(special[b])
                        pad.directional_pad(getattr(vg.DS4_DPAD_DIRECTIONS, "DS4_BUTTON_DPAD_" + dpad_dir(buttons)))
                        # le vrai DS4 met aussi le bit bouton quand la gâchette est enfoncée
                        if l2:
                            pad.press_button(vg.DS4_BUTTONS.DS4_BUTTON_TRIGGER_LEFT)
                        if r2:
                            pad.press_button(vg.DS4_BUTTONS.DS4_BUTTON_TRIGGER_RIGHT)
                        pad.left_trigger(l2)
                        pad.right_trigger(r2)
                        pad.left_joystick(stick_byte(ls[0]), stick_byte(ls[1]))
                        pad.right_joystick(stick_byte(rs[0]), stick_byte(rs[1]))
                        pad.update()
                time.sleep(max(0.0, dt - (time.perf_counter() - now)))
        except KeyboardInterrupt:
            pass
        finally:
            self.capturing = False
            self.kb.stop()
            self.ms.stop()
            if pad is not None:
                pad.reset()
                pad.update()


def main():
    ap = argparse.ArgumentParser(description="Clavier + souris -> manette DS4 virtuelle")
    ap.add_argument("profile", nargs="?", default=str(Path(__file__).with_name("profiles") / "gta.json"))
    ap.add_argument("--dry-run", action="store_true", help="pas de manette : affiche l'état dans la console")
    ap.add_argument("--any-window", action="store_true", help="capture quelle que soit la fenêtre au premier plan")
    ap.add_argument("--rate", type=int, default=250, help="mises à jour manette par seconde")
    a = ap.parse_args()
    if sys.platform != "win32":
        sys.exit("kbm2pad capture le clavier/souris via les hooks Windows : Windows uniquement.")
    if sys.version_info < (3, 11):
        sys.exit("Python 3.11+ requis (timer haute résolution de time.sleep sous Windows).")
    profile = json.loads(Path(a.profile).read_text(encoding="utf-8"))
    validate(profile)
    Bridge(profile, a.dry_run, a.any_window).run(a.rate)


if __name__ == "__main__":
    main()
