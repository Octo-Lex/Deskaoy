# Wayland Input Injection Strategy

## Status

**Research/design spike.** Wayland input injection is currently **UNSUPPORTED**.
All Linux input methods return `ErrorCategory.UNSUPPORTED` on Wayland sessions.
This document defines the strategy for a future implementation.

No runtime support is claimed. No fake success paths exist or will be added.

## Problem

Wayland's security model prevents clients from injecting global input events
(mouse, keyboard) without explicit user consent. Unlike X11, where any client
can grab the server and inject events via XTest or xdotool, Wayland compositors
isolate clients and do not expose a global input injection interface.

This is by design — it prevents keyloggers, clickjacking, and other input
attacks. The trade-off is that automation tools like Deskaoy cannot inject
input without going through a consent-aware portal.

## Backend hierarchy

### 1. X11 + xdotool (currently supported)

Already implemented in Batch 10. When `XDG_SESSION_TYPE=x11`, `DISPLAY` is set,
and `xdotool` is available, Deskaoy uses xdotool for click, type_text,
key_press, scroll, and fill.

### 2. Wayland + XDG RemoteDesktop portal + libei/EIS (preferred future path)

The **XDG Desktop Portal RemoteDesktop interface** is the standard,
consent-aware way to inject input on Wayland. It requires:

1. **CreateSession** — create a remote desktop session
2. **SelectDevices** — request keyboard, pointer, and/or touchscreen access
3. **Start** — present a consent dialog to the user; they choose what to share
4. **ConnectToEIS** (portal v2) — receive a file descriptor for libei/EIS input

Once an EIS connection is established via `ConnectToEIS`, all input events are
sent through the libei sender context. The `Notify*` methods
(`NotifyPointerMotion`, `NotifyKeyboardKeycode`, etc.) become unavailable.

**Portal API methods available for input injection:**

| Method | Purpose |
|--------|---------|
| `NotifyPointerMotion` | Relative pointer movement (dx, dy) |
| `NotifyPointerMotionAbsolute` | Absolute pointer position (stream-relative) |
| `NotifyPointerButton` | Button press/release (Evdev button codes) |
| `NotifyPointerAxis` | Smooth scroll axis movement |
| `NotifyPointerAxisDiscrete` | Discrete scroll wheel steps |
| `NotifyKeyboardKeycode` | Key press/release by Evdev keycode |
| `NotifyKeyboardKeysym` | Key press/release by X11 keysym |
| `NotifyTouchDown` / `NotifyTouchMotion` / `NotifyTouchUp` | Touch events |

**Device types** (`AvailableDeviceTypes` property):
- `1` — Keyboard
- `2` — Pointer
- `4` — Touchscreen

**Session persistence** (portal v2):
- `persist_mode=0`: Do not persist (prompt every time)
- `persist_mode=1`: Persist while the application is running
- `persist_mode=2`: Persist until explicitly revoked

A `restore_token` allows re-establishing a session without re-prompting, which
is important for daemon-mode automation.

**libei/EIS** (preferred for portal v2+):
- `ConnectToEIS` returns a file descriptor
- Pass to `ei_setup_backend_fd()` in a libei sender context
- All input flows through libei — more efficient and type-safe than `Notify*`
- The EIS implementation manages device availability and event delivery

### 3. Wayland + legacy Notify* methods (fallback)

On portal implementations that support v1 but not `ConnectToEIS`, the `Notify*`
methods can be used directly after `Start`. This is a viable fallback but less
efficient (each event is a separate D-Bus call).

### 4. ydotool / uinput (not recommended as default)

`ydotool` uses the kernel's `uinput` subsystem to create a virtual input device.
It works on both X11 and Wayland but requires:
- Root access, OR
- The user to be in the `input` group, OR
- A systemd unit with appropriate capabilities

This grants **global, unconditional** input access — the opposite of the
consent-aware portal model. It should only be used as an explicit opt-in
fallback, never as the default.

### 5. Compositor-specific APIs (avoid as default)

Some compositors (wlroots, GNOME Shell, KDE KWin) expose internal protocols
for input injection. These are unstable, compositor-specific, and not portable.
They should be treated as optional future backends, not the primary path.

## Recommended implementation plan

### Phase 1: Detection (this batch)

- `deskaoy doctor` reports Wayland session type and portal availability
- Document the strategy and backend decision
- No input injection attempted

### Phase 2: Portal prototype (future, behind opt-in)

- Implement behind `DESKAOY_WAYLAND_REMOTE_DESKTOP=1`
- Use dbus-python or pydbus for portal D-Bus communication
- Implement session lifecycle: CreateSession → SelectDevices → Start
- Handle consent dialog interaction (or document that user must click "Share")
- Implement `ConnectToEIS` + libei sender if portal v2 available
- Fall back to `Notify*` methods on portal v1

### Phase 3: Production support

- Remove opt-in flag after validation on GNOME and KDE
- Add session persistence via `restore_token`
- Add timeout/reconnect handling for daemon mode
- Document compositor compatibility matrix

## Dependencies for implementation

| Dependency | Purpose | Availability |
|------------|---------|--------------|
| `python-dbus` or `dbus-next` | D-Bus communication with portal | Standard on most Linux |
| `libei` (Python bindings) | EIS input event protocol | Newer; may need libei-python |
| `xdg-desktop-portal` | Portal daemon | Installed by most desktop environments |
| `xdg-desktop-portal-gnome` / `-kde` | Backend implementation | Compositor-specific |

## Current behavior

On Wayland sessions, `deskaoy doctor` reports:

```
[WARN] Linux: input backend (xdotool)  unsupported on Wayland — ...
```

And all input methods return:

```python
ActionResult(
    ok=False,
    error=ActionError(
        ErrorCategory.UNSUPPORTED,
        "Wayland session detected — xdotool cannot inject input "
        "on Wayland without compositor-specific portals"
    )
)
```

This is the correct honest behavior. It will not change until Phase 2 is
implemented and validated.

## References

- [XDG Desktop Portal: RemoteDesktop](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html)
- [libei](https://libinput.pages.freedesktop.org/libei/)
- [EIS (Emulated Input Server)](https://whot.fedorapeople.org/libei/)


---

*Decision record: Portal/libei is the preferred path because it is consent-aware,
standardized, and works across compositors that implement the XDG portal spec.
ydotool/uinput is rejected as default because it bypasses the consent model.*
