# kbm2pad

Joue à un jeu prévu pour la manette (ex. GTA sur PS5) au **clavier et à la souris**. kbm2pad
crée une **manette DualShock 4 virtuelle** et la pilote avec ton clavier et ta souris.

Il est pensé pour **[Veyra](https://github.com/Likely7/Veyra-NRVideo)** (PS5 Remote Play).
Veyra lit les manettes via SDL et les transmet à la PS5, donc la manette virtuelle passe
sans rien modifier dans Veyra. Il marche aussi avec tout autre programme qui lit une manette.

- Une **DS4** plutôt qu'une manette Xbox, pour avoir le **pavé tactile** (la carte dans GTA), PS, Share et Options.
- La capture est **active seulement quand Veyra est au premier plan**. À ce moment-là, clavier
  et souris sont "avalés" : Veyra ne reçoit plus Espace (pause), V, etc. Ailleurs, tout marche normalement.
- **F8** met en pause ou relance (cette touche n'est jamais avalée). Win et F11 passent toujours.
- **Souris → stick droit** : vitesse de la souris → inclinaison du stick, avec une courbe, une
  anti-deadzone et un lissage.
- **Couches** : **V** bascule entre à pied et véhicule (Z = accélérer, S = freiner, Espace = frein à main).

## Installation (Windows 10/11)

1. Installe **Python 3.11+** depuis python.org (coche "Add to PATH").
2. Dans ce dossier, lance :
   ```
   pip install -r requirements.txt
   ```
   `vgamepad` installe le pilote **ViGEmBus** (accepte l'installateur qui s'ouvre). Redémarre si on te le demande.
3. Dans Windows : Paramètres → Souris → Options supplémentaires → **décoche "Améliorer la
   précision du pointeur"**. Sinon l'accélération Windows fausse la visée.

## Utilisation avec Veyra

1. Lance `python kbm2pad.py` (ou `python kbm2pad.py profiles\mon_profil.json`).
2. Lance Veyra et démarre le PS5 Remote Play.
3. Clique dans la fenêtre Veyra : la console affiche `capture ON`. Joue.
4. **F8** pour reprendre la souris (ex. pour cliquer dans l'interface de Veyra), **F8** pour revenir.
   Ctrl+C dans la console pour quitter.

**Si une vraie manette est branchée :** en mode PS5 Remote Play, Veyra prend la première
manette qu'il trouve. Débranche la vraie manette, ou lance kbm2pad avant de la brancher.
En mode « contrôle PS5 + carte d'acquisition », Veyra suit la dernière manette utilisée :
appuie sur une touche et il passe sur la virtuelle.

**Tester sans jeu :** `python kbm2pad.py --dry-run --any-window` affiche l'état de la manette
dans la console, sans créer de manette (attention : la souris est capturée partout, F8 pour la libérer).
Pour voir la vraie manette virtuelle, lance `--any-window` sans `--dry-run`, puis un testeur de
manette dans le navigateur (ou `joy.cpl`).

## Profil (`profiles/gta.json`)

- `binds` : touche → cible. Cibles possibles : `cross circle square triangle l1 r1 l2 r2 l3 r3
  options share ps touchpad up down left right`, `ls_up/down/left/right`,
  `rs_up/down/left/right`, `walk` (le stick gauche passe à `walk_scale`).
- Touches : lettres, chiffres, `f1`–`f24`, `space enter tab esc backspace lshift rshift lctrl
  rctrl lalt ralt capslock up down left right insert delete home end pageup pagedown num0–num9`,
  `mouse_left mouse_right mouse_middle mouse_x1 mouse_x2 wheel_up wheel_down`.
- Les lettres sont **celles imprimées sur la touche** (Windows suit ta disposition clavier).
  Le profil fourni est en **AZERTY (ZQSD)**. En QWERTY, remplace `z q a` par `w a q`.
- `layers` : surcharges par couche, en boucle avec `layer_key`.
- `mouse` :
  - `full_speed` : vitesse de souris (counts/s) qui met le stick à fond. **Plus petit = plus sensible.**
  - `curve` : < 1 rend les petits gestes plus forts.
  - `anti_deadzone` : saute la zone morte du jeu. Monte-la si les petits gestes ne bougent pas la caméra.
  - `smooth_ms` : lissage. Plus haut = plus doux mais plus de latence.
  - `sens_x`, `sens_y`, `invert_y`.

Les contrôles GTA du profil reprennent la disposition PS habituelle de la série. Ajuste-les
selon les contrôles du jeu.

## Limites connues

- Windows uniquement (hooks clavier/souris bas niveau). La logique se teste partout : `python test_kbm2pad.py`.
- Un jeu PC avec anti-cheat peut refuser les manettes virtuelles. Sur PS5 via Remote Play, la
  console voit juste une manette.
- Pas de gyroscope, pas de macros, pas d'interface graphique (tout passe par le JSON).

Licence MIT.
