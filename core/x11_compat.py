"""
X11 authentication fix for GNOME / XWayland sessions on Linux.

PyAutoGUI and MouseInfo pull in `python3-xlib` 0.15, an old fork that only
accepts an Xauthority entry whose display number is exactly the one in
$DISPLAY. GNOME's XWayland (mutter) writes its cookie with an EMPTY display
number, which the X protocol defines as "any display". The old fork never
matches it, connects with no cookie, and the server answers "Authorization
required, but no authorization protocol specified" — so every action that
imports pyautogui was rejected at launch on a Wayland session.

The maintained `python-xlib` fixed this upstream; `apply()` gives whichever copy
is installed the same rule. It must run before anything imports pyautogui.
"""
import sys

_FAMILY_WILD = 0xFFFF


def apply() -> None:
    if not sys.platform.startswith("linux"):
        return
    try:
        from Xlib import error, xauth
    except Exception:
        return       # no Xlib installed — nothing that needs it will load either

    cls = xauth.Xauthority
    if getattr(cls.get_best_auth, "_jarvis_wildcard", False):
        return

    def get_best_auth(self, family, address, dispno,
                      types=(b"MIT-MAGIC-COOKIE-1",)):
        num = str(dispno).encode()
        if isinstance(address, str):
            address = address.encode()
        address = bytes(address)

        # Rank: exact address + exact display > exact address + any display >
        # wildcard family. The best rank seen per scheme wins.
        best: dict[bytes, tuple[int, bytes]] = {}
        for efam, eaddr, enum, ename, edata in self.entries:
            if enum not in (num, b""):
                continue
            if efam == family and eaddr == address:
                rank = 2 if enum == num else 1
            elif efam == _FAMILY_WILD:
                rank = 0
            else:
                continue
            if ename not in best or rank > best[ename][0]:
                best[ename] = (rank, edata)

        for t in types:
            if t in best:
                return t, best[t][1]
        raise error.XNoAuthError((family, address, dispno))

    get_best_auth._jarvis_wildcard = True
    cls.get_best_auth = get_best_auth
